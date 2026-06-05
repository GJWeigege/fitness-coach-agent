import pytest
from fastapi import HTTPException

from app.core.login_lockout import LoginLockout


def test_login_lockout_blocks_after_max_failures():
    lockout = LoginLockout()
    for _ in range(3):
        lockout.record_failure("alice", window_seconds=900)

    with pytest.raises(HTTPException) as exc:
        lockout.check_allowed("alice", max_attempts=3, window_seconds=900)

    assert exc.value.status_code == 429


def test_login_lockout_clears_on_success():
    lockout = LoginLockout()
    lockout.record_failure("bob", window_seconds=900)
    lockout.record_failure("bob", window_seconds=900)
    lockout.record_success("bob")

    lockout.check_allowed("bob", max_attempts=2, window_seconds=900)
