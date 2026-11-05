"""Secrets loader. Reads MM_SECRET_<NAME> from the environment (populated by sops or 1Password).

Values are wrapped so they never appear in reprs, logs or tracebacks by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Secret:
    _value: str

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('****')"

    __str__ = __repr__


class MissingSecretError(KeyError):
    pass


def get_secret(name: str) -> Secret:
    key = f"MM_SECRET_{name.upper()}"
    value = os.environ.get(key)
    if not value:
        raise MissingSecretError(f"{key} is not set (load secrets with sops or 1Password CLI)")
    return Secret(value)


def has_secret(name: str) -> bool:
    return bool(os.environ.get(f"MM_SECRET_{name.upper()}"))


def known_secret_values() -> list[str]:
    """Every loaded secret value, so the log redactor can scrub them."""
    return [v for k, v in os.environ.items() if k.startswith("MM_SECRET_") and len(v) >= 6]
