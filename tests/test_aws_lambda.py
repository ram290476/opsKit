from pathlib import Path
from zipfile import ZipFile

import opskit.aws_lambda as aws_lambda
from opskit.aws_lambda import build_deployment_package, update_code, update_runtime
from opskit.safety import ChangeBudget


class FakeLambdaClient:
    def __init__(self):
        self.calls = []

    def update_function_configuration(self, **kwargs):
        self.calls.append(("configuration", kwargs))
        return kwargs

    def update_function_code(self, **kwargs):
        self.calls.append(("code", kwargs))
        return kwargs


def test_lambda_updates_are_dry_run_by_default(tmp_path):
    client = FakeLambdaClient()

    assert update_runtime(client, "worker", "python3.12") is None
    assert update_code(client, "worker", tmp_path / "function.zip") is None
    assert client.calls == []


def test_lambda_updates_run_with_approved_budget(tmp_path):
    client = FakeLambdaClient()
    package = tmp_path / "function.zip"
    package.write_bytes(b"lambda package")
    budget = ChangeBudget(apply=True, max_changes=2)

    assert update_runtime(client, "worker", "python3.12", budget)["Runtime"] == "python3.12"
    result = update_code(client, "worker", package, budget, publish=True)

    assert result["ZipFile"] == b"lambda package"
    assert result["Publish"] is True
    assert budget.executed == 2


def test_package_contains_source_files_at_zip_root(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "handler.py").write_text("def handler(event, context):\n    return event\n")
    (source / "ignored.pyc").write_bytes(b"bytecode")
    output = build_deployment_package(source, tmp_path / "dist" / "function.zip")

    with ZipFile(output) as archive:
        assert "handler.py" in archive.namelist()
        assert "ignored.pyc" not in archive.namelist()


def test_package_installs_requirements_into_zip(tmp_path, monkeypatch):
    source = tmp_path / "src"
    source.mkdir()
    (source / "handler.py").write_text("def handler(event, context):\n    return event\n")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-lib==1.0\n")

    def install_dependencies(command, check, timeout):
        target = command[command.index("--target") + 1]
        (Path(target) / "example_lib.py").write_text("value = 1\n")
        assert check is True
        assert timeout == 600

    monkeypatch.setattr(aws_lambda.subprocess, "run", install_dependencies)
    output = build_deployment_package(source, tmp_path / "function.zip", requirements)

    with ZipFile(output) as archive:
        assert "handler.py" in archive.namelist()
        assert "example_lib.py" in archive.namelist()