"""Bundled fonts: registers them and exposes their family names."""

from __future__ import annotations

from PyQt6.QtGui import QFontDatabase

from .paths import resource_path

_bubble_family: str | None = None


def load_fonts() -> None:
    """Register the bundled fonts; call once, after the QApplication exists."""
    global _bubble_family
    fid = QFontDatabase.addApplicationFont(
        str(resource_path("resources", "pixeloid.sans-bold.ttf")))
    families = QFontDatabase.applicationFontFamilies(fid)
    _bubble_family = families[0] if families else None


def bubble_font_family() -> str | None:
    """The tutorial bubble's pixel font family, or None if it failed to load."""
    return _bubble_family
