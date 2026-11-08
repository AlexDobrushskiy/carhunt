import pytest

from carhunt.core import lock


def test_second_holder_times_out(carhunt_env):
    with lock.flock("sends"):
        with pytest.raises(lock.LockTimeout):
            with lock.flock("sends", timeout=0.1):
                pass
    with lock.flock("sends", timeout=0):  # released
        pass
    assert (carhunt_env / "locks" / "sends.lock").exists()


def test_shared_locks_coexist():
    with lock.flock("ledger", shared=True), lock.flock("ledger", shared=True, timeout=0):
        pass


def test_lock_name_cannot_escape():
    with pytest.raises(ValueError):
        with lock.flock("../x"):
            pass
