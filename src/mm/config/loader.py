"""Load and validate config/ into a Settings object."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import yaml

from mm.config.models import (
    JurisdictionProfile,
    RiskConfig,
    Settings,
    VenueConfig,
)

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def config_dir() -> Path:
    return Path(os.environ.get("MM_CONFIG_DIR", DEFAULT_CONFIG_DIR))


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data: object = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return cast(dict[str, Any], data)


def load_settings(root: Path | None = None) -> Settings:
    root = root or config_dir()
    base = _read_yaml(root / "base.yaml")
    risk = RiskConfig.model_validate(_read_yaml(root / "risk.yaml"))

    jurisdictions: dict[str, JurisdictionProfile] = {}
    for path in sorted((root / "jurisdictions").glob("*.yaml")):
        profile = JurisdictionProfile.model_validate(_read_yaml(path))
        if profile.name != path.stem:
            raise ValueError(f"{path}: name '{profile.name}' must match file name '{path.stem}'")
        jurisdictions[profile.name] = profile

    venues: dict[str, VenueConfig] = {}
    for path in sorted((root / "venues").glob("*.yaml")):
        venue = VenueConfig.model_validate(_read_yaml(path))
        venues[venue.name] = venue

    return Settings.model_validate(
        {**base, "risk": risk, "jurisdictions": jurisdictions, "venues": venues}
    )
