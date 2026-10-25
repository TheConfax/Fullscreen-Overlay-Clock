"""Icons of excluded apps, cached as PNG by process name."""

from __future__ import annotations

from PyQt6.QtCore import QFileInfo, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFileIconProvider

from .paths import icon_cache_dir

_PROVIDER: QFileIconProvider | None = None


def _cache_file(name: str):
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name.lower())
    return icon_cache_dir() / f"{safe}.png"


def pixmap_from_exe(exe_path: str) -> QPixmap | None:
    """An exe's icon, not cached; None if it can't be read."""
    if not exe_path:
        return None
    global _PROVIDER
    try:
        if _PROVIDER is None:
            _PROVIDER = QFileIconProvider()
        pm = _PROVIDER.icon(QFileInfo(exe_path)).pixmap(QSize(32, 32))
        return pm if not pm.isNull() else None
    except Exception:
        return None


def cache_icon(name: str, exe_path: str) -> None:
    """Save *exe_path*'s icon as the cached icon for *name*; silent on failure."""
    if not name:
        return
    pm = pixmap_from_exe(exe_path)
    if pm is not None:
        try:
            pm.save(str(_cache_file(name)), "PNG")
        except OSError:
            pass


def cached_pixmap(name: str) -> QPixmap | None:
    """The cached icon for *name*, or None if there isn't one."""
    if not name:
        return None
    f = _cache_file(name)
    if f.exists():
        pm = QPixmap(str(f))
        if not pm.isNull():
            return pm
    return None
