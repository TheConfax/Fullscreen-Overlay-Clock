"""Filesystem locations: the app's data dir and bundled resources."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import APPDATA_DIR


def app_data_dir() -> Path:
    """The app's dir under %APPDATA%, created if missing."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    directory = Path(base) / APPDATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_path() -> Path:
    return app_data_dir() / "config.json"


def icon_cache_dir() -> Path:
    """The app-icon cache dir, created if missing."""
    directory = app_data_dir() / "icons"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def root_file(*parts: str) -> Path:
    """A path from the repo root; a build mirrors that layout under `_MEIPASS`."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        base = Path(__file__).resolve().parents[2]
    return base.joinpath(*parts)


def resource_path(*parts: str) -> Path:
    """A bundled resource under `src`."""
    return root_file("src", *parts)
