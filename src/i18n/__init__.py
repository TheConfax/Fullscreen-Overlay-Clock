"""Every user-facing string, from one JSON catalog per language in this folder."""

from __future__ import annotations

import json
from functools import lru_cache
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QTranslator

from ..services.paths import resource_path
from ..services.win32 import preferred_ui_languages

AUTO = "auto"       # follow the Windows display language
FALLBACK = "en"     # the complete catalog every other one is merged over
_NAME = "_language"  # the endonym shown in the language picker; never reaches S

#: The active catalog, e.g. `S.tray.quit`. Rewritten in place, never rebound: an imported
#: `S` stays live, but a widget that copied a string has to be rebuilt.
S = SimpleNamespace()

_active = FALLBACK
_qt = QTranslator()  # Qt's own strings, such as the right-click menus


def _clean(node: dict) -> dict:
    """Drop anything that is neither a string nor a section, at any depth."""
    return {k: (_clean(v) if isinstance(v, dict) else v)
            for k, v in node.items() if isinstance(v, (str, dict))}


def _read(code: str) -> dict:
    """One catalog as a nested dict, or empty if it is missing or malformed."""
    try:
        data = json.loads(resource_path("i18n", f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return _clean(data) if isinstance(data, dict) else {}


def _merge(base: dict, over: dict) -> dict:
    """`over` on top of `base`, section by section: a half-translated section keeps
    the rest of `base`."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _namespace(node: dict) -> SimpleNamespace:
    return SimpleNamespace(**{k: (_namespace(v) if isinstance(v, dict) else v)
                              for k, v in node.items()})


@lru_cache(maxsize=1)
def available() -> tuple[tuple[str, str], ...]:
    """`(code, name)` per shipped catalog — English first, then by name."""
    found = [(p.stem, c.get(_NAME) or p.stem)
             for p in sorted(resource_path("i18n").glob("*.json"))
             if (c := _read(p.stem))]
    found.sort(key=lambda pair: (pair[0] != FALLBACK, pair[1].casefold()))
    return tuple(found)


def detect() -> str:
    """The best shipped match for the user's Windows display language."""
    codes = {code for code, _ in available()}
    for tag in preferred_ui_languages():
        base = tag.replace("_", "-").split("-")[0].casefold()
        if base in codes:
            return base
    return FALLBACK


def resolve(code: str) -> str:
    """A stored `"auto"` or code, as a code we ship; one we don't ship counts as `"auto"`."""
    code = (code or AUTO).casefold()
    return code if code in {c for c, _ in available()} else detect()


def active() -> str:
    """The code currently loaded into `S` (never `"auto"`)."""
    return _active


def set_language(code: str) -> str:
    """Swap the live catalog, returning the code actually applied."""
    global _active
    _active = resolve(code)
    values = _read(FALLBACK)
    if _active != FALLBACK:
        values = _merge(values, _read(_active))
    values.pop(_NAME, None)
    S.__dict__.clear()
    S.__dict__.update(_namespace(values).__dict__)
    _translate_qt()
    return _active


def _translate_qt() -> None:
    """Qt's strings in the active language, English when Qt has no file for it. Skipped while
    there is no app yet."""
    app = QCoreApplication.instance()
    if app is None:
        return
    app.removeTranslator(_qt)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if _active != FALLBACK and _qt.load(f"qtbase_{_active}", folder):
        app.installTranslator(_qt)


set_language(AUTO)  # S must be readable before the config is loaded
