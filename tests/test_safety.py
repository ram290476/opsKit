import pytest

from opskit.safety import BlastRadiusExceeded, ChangeBudget, is_protected


def test_dry_run_never_approves():
    b = ChangeBudget()
    assert not any(b.approve("delete", f"r{i}") for i in range(100))
    assert b.summary() == {"planned": 100, "executed": 0, "apply": False}


def test_blast_radius_cap():
    b = ChangeBudget(apply=True, max_changes=2)
    assert b.approve("delete", "a") and b.approve("delete", "b")
    with pytest.raises(BlastRadiusExceeded):
        b.approve("delete", "c")


@pytest.mark.parametrize("tags,expected", [
    ({"do-not-delete": "true"}, True), ({"Protected": "YES"}, True),
    ({"retain": "false"}, False), ({}, False), (None, False),
])
def test_is_protected(tags, expected):
    assert is_protected(tags) is expected
