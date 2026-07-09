"""Configuration loader for the distressed property scanner."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
COMPILED_PATH = PROJECT_ROOT / "v2_compiled.json"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
LEGACY_RAW_GLOB = "v2-*.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or CONFIG_PATH
    with open(config_path) as f:
        return yaml.safe_load(f)


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "audit").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "history").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "distressed-properties").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "dashboard").mkdir(parents=True, exist_ok=True)
