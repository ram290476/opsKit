
import pytest


@pytest.fixture(autouse=True)
def fake_aws_env(monkeypatch):
    """Guarantee tests can never hit a real account, even if a developer has creds loaded."""
    for k in ("AWS_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    yield
