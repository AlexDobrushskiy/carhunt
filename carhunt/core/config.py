"""Load and validate $CARHUNT_HOME/config.yaml.

`secret:NAME` values stay as SecretRef objects until a caller asks for them (`cfg.secret("notify.telegram.bot_token")`),
so printing or logging a Config never shows a secret value.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from carhunt.core import paths

_SECRET = re.compile(r"^secret:([A-Za-z0-9][A-Za-z0-9_.-]{0,63})$")
_MISSING = object()


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class SecretRef:
    name: str

    def __str__(self) -> str:
        return f"secret:{self.name}"

    def resolve(self) -> str:
        from carhunt.core import secrets

        return secrets.get(self.name)


def schema() -> dict:
    return json.loads(resources.files("carhunt.core").joinpath("config.schema.json").read_text())


def validate(data: Any) -> list[str]:
    """Error strings (`path: message`); empty list = valid."""
    import jsonschema

    v = jsonschema.Draft202012Validator(schema())
    errors = [f"{'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
              for e in sorted(v.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))]
    tz = (data.get("owner") or {}).get("tz") if isinstance(data, dict) else None
    if isinstance(tz, str):
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            errors.append(f"owner.tz: unknown time zone {tz!r}")
    return errors


def _wrap(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _wrap(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_wrap(v) for v in node]
    if isinstance(node, str) and (m := _SECRET.match(node)):
        return SecretRef(m.group(1))
    return node


def _unwrap(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _unwrap(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_unwrap(v) for v in node]
    if isinstance(node, SecretRef):
        return str(node)
    return node


class Config:
    def __init__(self, data: dict, source: Path | None = None):
        self._data = _wrap(data)
        self.source = source

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict:
        return copy.deepcopy(self._data.get(name) or {})

    def secret(self, dotted: str) -> str:
        """Resolve a `secret:NAME` value (raises secrets.SecretNotFound); a plain value is returned as-is."""
        v = self.get(dotted, _MISSING)
        if v is _MISSING or v is None:
            raise ConfigError(f"{dotted} is not set in {self.source or 'config'}")
        return v.resolve() if isinstance(v, SecretRef) else str(v)

    def as_dict(self) -> dict:
        """Plain data with secret references as `secret:NAME` strings (safe to print)."""
        return _unwrap(self._data)

    def __repr__(self) -> str:
        return f"Config(source={self.source})"


def home() -> Path:
    return paths.home()


def path(*parts: str) -> Path:
    return paths.path(*parts)


def read(file: Path) -> dict:
    try:
        data = yaml.safe_load(file.read_text()) or {}
    except FileNotFoundError:
        raise ConfigError(f"no config at {file} (run scripts/bootstrap, or copy config.example.yaml there)") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"{file}: YAML error: {e}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{file}: top level must be a mapping")
    return data


def load(file: str | Path | None = None, *, check: bool = True) -> Config:
    """Read $CARHUNT_CONFIG or $CARHUNT_HOME/config.yaml; raise ConfigError if missing or invalid."""
    f = Path(file).expanduser() if file else paths.config_file()
    data = read(f)
    if check and (errors := validate(data)):
        raise ConfigError(f"{f}: invalid config\n  " + "\n  ".join(errors))
    return Config(data, f)


def load_or_none() -> Config | None:
    """The config if one exists; None if there is none yet. An invalid config still raises."""
    f = paths.config_file()
    return load(f) if f.exists() else None
