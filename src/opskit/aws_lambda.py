"""Build and deploy Python AWS Lambda packages."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .safety import ChangeBudget


def build_deployment_package(
    source_dir: str | Path,
    output_zip: str | Path,
    requirements_file: str | Path | None = None,
    python_executable: str = sys.executable,
) -> Path:
    """Package handler code and optional pip requirements at the ZIP root."""
    source = Path(source_dir)
    if not source.is_dir():
        raise NotADirectoryError(source)

    output = Path(output_zip)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary_dir:
        staging = Path(temporary_dir) / "package"
        shutil.copytree(
            source,
            staging,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        if requirements_file is not None:
            subprocess.run(
                [
                    python_executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(requirements_file),
                    "--target",
                    str(staging),
                ],
                check=True,
                timeout=600,
            )

        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for path in staging.rglob("*"):
                if path.is_file() and path.suffix != ".pyc":
                    archive.write(path, path.relative_to(staging).as_posix())
    return output


def update_runtime(
    lambda_client,
    function_name: str,
    runtime: str,
    budget: ChangeBudget | None = None,
) -> dict | None:
    """Update a function's Python runtime; dry-run unless budget.apply is true."""
    budget = budget or ChangeBudget()
    if not budget.approve("update_lambda_runtime", function_name):
        return None
    return lambda_client.update_function_configuration(
        FunctionName=function_name,
        Runtime=runtime,
    )


def update_code(
    lambda_client,
    function_name: str,
    package_zip: str | Path,
    budget: ChangeBudget | None = None,
    publish: bool = False,
) -> dict | None:
    """Upload a deployment ZIP; dry-run unless budget.apply is true."""
    budget = budget or ChangeBudget()
    if not budget.approve("update_lambda_code", function_name):
        return None
    with Path(package_zip).open("rb") as package:
        return lambda_client.update_function_code(
            FunctionName=function_name,
            ZipFile=package.read(),
            Publish=publish,
        )