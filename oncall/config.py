"""Loads config.yaml and environment variables."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def env(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name)
    if required and not value:
        raise RuntimeError(f"Missing environment variable {name}. See .env.example.")
    return value
