"""Config, paths, clock and the cardb client for discover — thin wrappers over carhunt.core."""
from __future__ import annotations

import os
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from carhunt.core import clock, lock, paths
from carhunt.core import config as core_config
from carhunt.core import db as core_db

DATA = Path(__file__).resolve().parent / "data"


def config() -> dict:
    """The whole config as a plain dict (secret refs stay `secret:NAME` strings); {} when there is none yet."""
    cfg = core_config.load_or_none()
    return cfg.as_dict() if cfg else {}


def home() -> Path:
    return paths.home()


def path(*parts: str) -> Path:
    """$CARHUNT_HOME/<parts>, parent dirs created."""
    p = paths.home().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def now() -> datetime:
    return clock.now()


def flock(name: str):
    return lock.flock(name)


def pause_file() -> Path:
    return paths.pause_file()


def db_client() -> core_db.Client:
    """core's cardb client; author = $CARDB_AUTHOR (set by `carhunt agent launch`) or `discover`."""
    cfg = core_config.load_or_none() or core_config.Config({})
    return core_db.Client.from_config(cfg, author=os.environ.get("CARDB_AUTHOR") or "discover")


@cache
def data(name: str) -> Any:
    return yaml.safe_load((DATA / f"{name}.yaml").read_text(encoding="utf-8"))
