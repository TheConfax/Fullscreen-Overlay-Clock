"""Unhandled exceptions go to crash.log, then the app dies."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType

from .. import __version__
from .paths import app_data_dir

#: Past this the file starts over.
MAX_BYTES = 1_000_000

_previous_hook = sys.__excepthook__


def path() -> Path:
    return app_data_dir() / "crash.log"


def _language() -> str:
    """The catalog actually loaded, or `?` if we crashed before i18n was ready."""
    try:
        from ..i18n import active
        return active()
    except Exception:
        return "?"


def _entry(exc_type: type[BaseException], exc: BaseException,
           tb: TracebackType | None) -> str:
    stamp = datetime.now().isoformat(sep=" ", timespec="seconds")
    header = f"{stamp}  v{__version__}  lang={_language()}"
    body = "".join(traceback.format_exception(exc_type, exc, tb))
    return f"{'=' * 70}\n{header}\n{'=' * 70}\n{body}\n"


def _append(text: str) -> None:
    file = path()
    truncated = False
    try:
        truncated = file.stat().st_size >= MAX_BYTES
    except OSError:
        pass
    if truncated:
        text = f"[crash.log reached {MAX_BYTES} bytes and was reset]\n\n{text}"
    with file.open("w" if truncated else "a", encoding="utf-8") as handle:
        handle.write(text)


def _hook(exc_type: type[BaseException], exc: BaseException,
          tb: TracebackType | None) -> None:
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        _previous_hook(exc_type, exc, tb)  # asked to stop, not a crash
        return
    try:
        _append(_entry(exc_type, exc, tb))
    except Exception:
        pass  # a failing log must not hide the crash
    _previous_hook(exc_type, exc, tb)
    if sys.stderr:  # None without a console
        sys.stderr.flush()  # abort() does not flush Python's buffers
    # Deliberate: with our hook PyQt no longer kills the app on a slot error;
    # a vanished app gets reported.
    os.abort()


def install() -> None:
    """Route unhandled exceptions through the log, keeping the previous hook."""
    global _previous_hook
    _previous_hook = sys.excepthook
    sys.excepthook = _hook
