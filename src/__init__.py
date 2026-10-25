"""Product identity, read from pyproject.toml."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

if getattr(sys, "frozen", False):
    _root = Path(getattr(sys, "_MEIPASS"))
else:
    _root = Path(__file__).resolve().parent.parent

_data = tomllib.loads((_root / "pyproject.toml").read_text(encoding="utf-8"))
_tool = _data["tool"]["fullscreen-overlay-clock"]
_ids = _tool["identifiers"]
_urls = _data["project"]["urls"]

__version__: str = _data["project"]["version"]
APP_NAME: str = _tool["app-name"]
CONFIG_VERSION: int = _tool["config-version"]
DESCRIPTION: str = _data["project"]["description"]
AUTHOR: str = _data["project"]["authors"][0]["name"]
COPYRIGHT_YEAR: str = _tool["copyright-year"]
ISSUES_URL: str = _urls["Issues"]
DONATE_URL: str = _urls["Funding"]
PACKAGE_ID: str = _ids["package"]
PUBLISHER: str = _ids["publisher"]
APPLICATION_ID: str = _ids["application"]
STARTUP_TASK_ID: str = _ids["startup-task"]
APPDATA_DIR: str = _ids["appdata-dir"]
STORE_ID: str = _ids["store-id"]
