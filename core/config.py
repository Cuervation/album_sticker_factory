"""Configuration loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.paths import CONFIG_PATH


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load YAML config from disk."""
    target = path or CONFIG_PATH
    with target.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data

