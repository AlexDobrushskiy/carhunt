"""Cross-process file locks under $CARHUNT_HOME/locks/ (fcntl.flock: released when the process dies)."""
from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager

from carhunt.core import paths


class LockTimeout(TimeoutError):
    pass


@contextmanager
def flock(name: str, *, timeout: float | None = None, shared: bool = False) -> Iterator[None]:
    """Hold lock NAME. timeout=None waits forever, 0 = try once; raises LockTimeout."""
    f = paths.locks_dir() / f"{paths.safe_name(name, 'lock')}.lock"
    fd = os.open(f, os.O_RDWR | os.O_CREAT, 0o600)
    mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    try:
        if timeout is None:
            fcntl.flock(fd, mode)
        else:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, mode | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LockTimeout(f"lock {name} is held by another process") from None
                    time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing the fd releases the lock
