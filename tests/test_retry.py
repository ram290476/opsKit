import pytest
from botocore.exceptions import ClientError

from opskit.retry import is_transient, retry


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "Op")


def test_classifies_transient_and_permanent():
    assert is_transient(_client_error("ThrottlingException"))
    assert is_transient(TimeoutError())
    assert not is_transient(_client_error("AccessDenied"))
    assert not is_transient(ValueError("bad input"))


def test_retries_transient_then_succeeds():
    calls, sleeps = [], []

    @retry(attempts=4, sleep=sleeps.append)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _client_error("Throttling")
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 3 and len(sleeps) == 2
    assert all(0 <= s <= 30 for s in sleeps)


def test_does_not_retry_permanent_errors():
    calls = []

    @retry(attempts=5, sleep=lambda _: None)
    def denied():
        calls.append(1)
        raise _client_error("AccessDenied")

    with pytest.raises(ClientError):
        denied()
    assert len(calls) == 1


def test_gives_up_after_attempts():
    calls = []

    @retry(attempts=3, sleep=lambda _: None)
    def always_throttled():
        calls.append(1)
        raise _client_error("Throttling")

    with pytest.raises(ClientError):
        always_throttled()
    assert len(calls) == 3
