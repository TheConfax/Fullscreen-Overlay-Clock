"""Config model: every from_dict accepts anything and falls back to defaults field by field."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from .. import CONFIG_VERSION

THEMES = ("auto", "light", "dark")

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


# --- validation helpers ------------------------------------------------------
def _enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if value in allowed else default


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _str(value: Any, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _color(value: Any, default: str) -> str:
    if isinstance(value, str) and _HEX_RE.fullmatch(value):
        return value.upper()
    return default


def _num(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _int(value: Any, lo: int, hi: int, default: int) -> int:
    return int(round(_num(value, lo, hi, default)))


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _str_list(value: Any) -> list[str]:
    """A de-duplicated (case-insensitive), stripped list of non-empty strings."""
    names: list[str] = []
    if isinstance(value, list):
        seen: set[str] = set()
        for item in value:
            if isinstance(item, str) and item.strip():
                name = item.strip()
                key = name.lower()
                if key not in seen:
                    seen.add(key)
                    names.append(name)
    return names


# --- clock -------------------------------------------------------------------
@dataclass
class TimeFormat:
    use_24h: bool = True
    show_ampm: bool = True  # 12-hour mode only
    leading_zero: bool = True
    show_seconds: bool = False

    @classmethod
    def from_dict(cls, d: Any) -> "TimeFormat":
        d = _as_dict(d)
        df = cls()
        return cls(
            use_24h=_bool(d.get("use_24h"), df.use_24h),
            show_ampm=_bool(d.get("show_ampm"), df.show_ampm),
            leading_zero=_bool(d.get("leading_zero"), df.leading_zero),
            show_seconds=_bool(d.get("show_seconds"), df.show_seconds),
        )

    def to_dict(self) -> dict:
        return {
            "use_24h": self.use_24h,
            "show_ampm": self.show_ampm,
            "leading_zero": self.leading_zero,
            "show_seconds": self.show_seconds,
        }

    def render(self, now) -> str:
        """*now* (a QDateTime) as the clock shows it."""
        hour = "H" if self.use_24h else "h"
        if self.leading_zero:
            hour += hour
        fmt = f"{hour}:mm"
        if self.show_seconds:
            fmt += ":ss"
        if self.use_24h:
            return now.toString(fmt)
        # Qt's h counts 1-12 only next to AP, so AP is always asked for and cut when hidden.
        text = now.toString(fmt + " AP")
        return text if self.show_ampm else text.rsplit(" ", 1)[0]


@dataclass
class Text:
    font_family: str = "Consolas"
    font_weight: str = "Bold"  # a font style name (`"Regular"`, `"Semibold"`), not a number
    font_size: int = 13
    color: str = "#FFFFFF"
    opacity: float = 1.0

    @classmethod
    def from_dict(cls, d: Any) -> "Text":
        d = _as_dict(d)
        df = cls()
        return cls(
            font_family=_str(d.get("font_family"), df.font_family),
            font_weight=_str(d.get("font_weight"), df.font_weight),
            font_size=_int(d.get("font_size"), 8, 100, df.font_size),
            color=_color(d.get("color"), df.color),
            opacity=_num(d.get("opacity"), 0.01, 1.0, df.opacity),  # never fully invisible
        )

    def to_dict(self) -> dict:
        return {
            "font_family": self.font_family,
            "font_weight": self.font_weight,
            "font_size": self.font_size,
            "color": self.color,
            "opacity": self.opacity,
        }


@dataclass
class Background:
    color: str = "#000000"
    opacity: float = 0.75
    padding: int = 50         # % of the text height, on every side
    corner_radius: int = 50   # % of the max pill radius (0 = square, 100 = full pill)
    # corner_radius applies only to the corners set True.
    round_top_left: bool = True
    round_top_right: bool = True
    round_bottom_left: bool = True
    round_bottom_right: bool = True
    auto_corners: bool = True  # corners on a flush screen edge go square

    @classmethod
    def from_dict(cls, d: Any) -> "Background":
        d = _as_dict(d)
        df = cls()
        return cls(
            color=_color(d.get("color"), df.color),
            opacity=_num(d.get("opacity"), 0.0, 1.0, df.opacity),
            padding=_int(d.get("padding"), 0, 100, df.padding),
            corner_radius=_int(d.get("corner_radius"), 0, 100, df.corner_radius),
            round_top_left=_bool(d.get("round_top_left"), df.round_top_left),
            round_top_right=_bool(d.get("round_top_right"), df.round_top_right),
            round_bottom_left=_bool(d.get("round_bottom_left"), df.round_bottom_left),
            round_bottom_right=_bool(d.get("round_bottom_right"), df.round_bottom_right),
            auto_corners=_bool(d.get("auto_corners"), df.auto_corners),
        )

    def to_dict(self) -> dict:
        return {
            "color": self.color,
            "opacity": self.opacity,
            "padding": self.padding,
            "corner_radius": self.corner_radius,
            "round_top_left": self.round_top_left,
            "round_top_right": self.round_top_right,
            "round_bottom_left": self.round_bottom_left,
            "round_bottom_right": self.round_bottom_right,
            "auto_corners": self.auto_corners,
        }


@dataclass
class Shadow:
    intensity: int = 0    # shadow opacity %, 0 = off
    color: str = "#000000"
    blur: int = 0         # 0–100; 100 = a blur of twice the clock height
    offset_x: int = 0     # ±100 = a quarter of the clock height
    offset_y: int = 0     # ±100 = a quarter of the clock height

    @classmethod
    def from_dict(cls, d: Any) -> "Shadow":
        d = _as_dict(d)
        df = cls()
        return cls(
            intensity=_int(d.get("intensity"), 0, 100, df.intensity),
            color=_color(d.get("color"), df.color),
            blur=_int(d.get("blur"), 0, 100, df.blur),
            offset_x=_int(d.get("offset_x"), -100, 100, df.offset_x),
            offset_y=_int(d.get("offset_y"), -100, 100, df.offset_y),
        )

    def to_dict(self) -> dict:
        return {
            "intensity": self.intensity,
            "color": self.color,
            "blur": self.blur,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
        }


@dataclass
class Monitor:
    # Windows' StableMonitorId, `""` = the primary. The name only labels a disconnected
    # monitor in the settings list: Windows no longer reports it then.
    id: str = ""
    name: str = ""

    @classmethod
    def from_dict(cls, d: Any) -> "Monitor":
        d = _as_dict(d)
        return cls(id=_str(d.get("id"), ""), name=_str(d.get("name"), ""))

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name}


@dataclass
class Position:
    monitor: Monitor = field(default_factory=Monitor)
    # Fractions of the free space (monitor minus clock): 0 flush left / top, 1 flush right /
    # bottom. Outside 0..1 the clock overhangs, onto the next monitor or off-screen (the wheel
    # goes there on purpose).
    x: float = 1.0
    y: float = 0.0

    @classmethod
    def from_dict(cls, d: Any) -> "Position":
        d = _as_dict(d)
        df = cls()
        return cls(
            monitor=Monitor.from_dict(d.get("monitor")),
            x=_num(d.get("x"), -1000.0, 1000.0, df.x),
            y=_num(d.get("y"), -1000.0, 1000.0, df.y),
        )

    def to_dict(self) -> dict:
        return {"monitor": self.monitor.to_dict(), "x": round(self.x, 6), "y": round(self.y, 6)}


@dataclass
class Clock:
    time_format: TimeFormat = field(default_factory=TimeFormat)
    text: Text = field(default_factory=Text)
    background: Background = field(default_factory=Background)
    shadow: Shadow = field(default_factory=Shadow)
    position: Position = field(default_factory=Position)

    @classmethod
    def from_dict(cls, d: Any) -> "Clock":
        d = _as_dict(d)
        return cls(
            time_format=TimeFormat.from_dict(d.get("time_format")),
            text=Text.from_dict(d.get("text")),
            background=Background.from_dict(d.get("background")),
            shadow=Shadow.from_dict(d.get("shadow")),
            position=Position.from_dict(d.get("position")),
        )

    def to_dict(self) -> dict:
        return {
            "time_format": self.time_format.to_dict(),
            "text": self.text.to_dict(),
            "background": self.background.to_dict(),
            "shadow": self.shadow.to_dict(),
            "position": self.position.to_dict(),
        }


# --- system ------------------------------------------------------------------
@dataclass
class Display:
    show_on_desktop: bool = False  # not only over fullscreen games

    @classmethod
    def from_dict(cls, d: Any) -> "Display":
        d = _as_dict(d)
        df = cls()
        return cls(show_on_desktop=_bool(d.get("show_on_desktop"), df.show_on_desktop))

    def to_dict(self) -> dict:
        return {"show_on_desktop": self.show_on_desktop}


@dataclass
class Interface:
    theme: str = "auto"
    # Checked only as text: a code we don't ship acts as `"auto"` (i18n.resolve) but is kept.
    language: str = "auto"

    @classmethod
    def from_dict(cls, d: Any) -> "Interface":
        d = _as_dict(d)
        df = cls()
        return cls(
            theme=_enum(d.get("theme"), THEMES, df.theme),
            language=_str(d.get("language"), df.language).casefold(),
        )

    def to_dict(self) -> dict:
        return {"theme": self.theme, "language": self.language}


@dataclass
class Tutorial:
    completed: bool = False  # last step reached; "Restart tutorial" clears it
    # The genuine first onboarding: only its end resets the style and turns autostart on.
    firstrun: bool = True

    @classmethod
    def from_dict(cls, d: Any) -> "Tutorial":
        d = _as_dict(d)
        return cls(completed=_bool(d.get("completed"), False),
                   firstrun=_bool(d.get("firstrun"), True))

    def to_dict(self) -> dict:
        return {"completed": self.completed, "firstrun": self.firstrun}


@dataclass
class System:
    display: Display = field(default_factory=Display)
    interface: Interface = field(default_factory=Interface)
    tutorial: Tutorial = field(default_factory=Tutorial)

    @classmethod
    def from_dict(cls, d: Any) -> "System":
        d = _as_dict(d)
        return cls(
            display=Display.from_dict(d.get("display")),
            interface=Interface.from_dict(d.get("interface")),
            tutorial=Tutorial.from_dict(d.get("tutorial")),
        )

    def to_dict(self) -> dict:
        return {
            "display": self.display.to_dict(),
            "interface": self.interface.to_dict(),
            "tutorial": self.tutorial.to_dict(),
        }


# --- root --------------------------------------------------------------------
# One step per format change: takes the raw dict of version N and returns that of N+1.
# Bump config-version in pyproject.toml and add the step here, in the same commit.
_MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def _migrate(d: dict, version: int) -> dict:
    while version < CONFIG_VERSION:
        d = _MIGRATIONS[version](d)
        version += 1
    return d


@dataclass
class Config:
    version: int = CONFIG_VERSION  # the format the file was written in
    clock: Clock = field(default_factory=Clock)
    exclusions: list[str] = field(default_factory=list)  # process exe names
    system: System = field(default_factory=System)

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def from_dict(cls, d: Any) -> "Config":
        d = _as_dict(d)
        version = d.get("version")
        # Missing or garbled (a bool is an int too): a hand-edited file, read as the current format.
        if type(version) is not int or version < 1:
            version = CONFIG_VERSION
        if version < CONFIG_VERSION:
            d, version = _migrate(d, version), CONFIG_VERSION
        return cls(
            version=version,
            clock=Clock.from_dict(d.get("clock")),
            exclusions=_str_list(d.get("exclusions")),
            system=System.from_dict(d.get("system")),
        )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "clock": self.clock.to_dict(),
            "exclusions": list(self.exclusions),
            "system": self.system.to_dict(),
        }

    def copy(self) -> "Config":
        return replace(
            self,
            clock=replace(
                self.clock,
                time_format=replace(self.clock.time_format),
                text=replace(self.clock.text),
                background=replace(self.clock.background),
                shadow=replace(self.clock.shadow),
                position=replace(self.clock.position,
                                 monitor=replace(self.clock.position.monitor)),
            ),
            exclusions=list(self.exclusions),
            system=replace(
                self.system,
                display=replace(self.system.display),
                interface=replace(self.system.interface),
                tutorial=replace(self.system.tutorial),
            ),
        )
