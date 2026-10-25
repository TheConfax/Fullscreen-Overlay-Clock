"""App-wide look: the style, light/dark lookup, shared colors and sizes that follow "Text size"."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPalette
from PyQt6.QtWidgets import QProxyStyle, QStyle, QStyleOptionFocusRect

from ..services import win32

DEFAULT_FONT_PT = 9.0

DESTRUCTIVE_RED = "#d83a3a"
DESTRUCTIVE_RED_HOVER = "#e24a4a"
DESTRUCTIVE_TEXT = "#ffffff"  # on DESTRUCTIVE_RED
SUPPORT_PINK = "#FF99CC"  # the support button's border
_WINDOWS_BLUE = "#0078d4"  # Windows' default accent

# Dots and rings that must read on any color.
MARKER_FILL = QColor(255, 255, 255)
MARKER_EDGE = QColor(0, 0, 0)

ARROW_IDLE = QColor(190, 190, 190, 205)  # the clock's edit arrows and gear, at rest

# The settings pads: a translucent mid gray reads on both themes.
PAD_EDGE = QColor(127, 127, 127, 140)
PAD_FACE = QColor(127, 127, 127, 28)
PAD_CROSS = QColor(127, 127, 127, 80)


def px(value: float) -> int:
    """Scale a size chosen against Segoe UI 9pt to the current system font."""
    return round(value * QGuiApplication.font().pointSizeF() / DEFAULT_FONT_PT)


class AppStyle(QProxyStyle):
    """Same tooltip delay every time; layout margins and spacing go through px(); checkboxes
    keep the accent in an inactive window; a tab with keyboard focus gets a focus frame."""

    _LAYOUT_METRICS = frozenset({
        QStyle.PixelMetric.PM_LayoutLeftMargin, QStyle.PixelMetric.PM_LayoutTopMargin,
        QStyle.PixelMetric.PM_LayoutRightMargin, QStyle.PixelMetric.PM_LayoutBottomMargin,
        QStyle.PixelMetric.PM_LayoutHorizontalSpacing, QStyle.PixelMetric.PM_LayoutVerticalSpacing,
    })

    def styleHint(self, hint, option=None, widget=None, return_data=None) -> int:
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return 0  # Qt's default shows the next tooltip instantly for 2s after one closes
        return super().styleHint(hint, option, widget, return_data)

    def pixelMetric(self, metric, option=None, widget=None) -> int:
        value = super().pixelMetric(metric, option, widget)
        return px(value) if metric in self._LAYOUT_METRICS else value

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        # Windows' dark checkbox palette turns the accent near-black for an inactive window.
        if (element == QStyle.PrimitiveElement.PE_IndicatorCheckBox and option is not None
                and option.palette.currentColorGroup() == QPalette.ColorGroup.Inactive):
            option = type(option)(option)
            palette = QPalette(option.palette)
            palette.setCurrentColorGroup(QPalette.ColorGroup.Active)
            option.palette = palette
        super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None) -> None:
        super().drawControl(element, option, painter, widget)
        # Qt's windows11 style draws the focus frame on every control but a tab.
        if (element == QStyle.ControlElement.CE_TabBarTab and option is not None
                and option.state & QStyle.StateFlag.State_HasFocus
                and option.state & QStyle.StateFlag.State_KeyboardFocusChange):
            frame = QStyleOptionFocusRect()
            frame.rect = option.rect
            frame.state = option.state
            frame.palette = option.palette
            self.drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, frame, painter, widget)


def is_dark() -> bool:
    """True in dark mode. The color scheme updates before the palette on a theme
    switch, so the palette is only the fallback when the scheme is Unknown."""
    hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme() if hints else Qt.ColorScheme.Unknown
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def on_theme_change(slot: Callable[..., object]) -> None:
    """Call *slot* on every light/dark flip. Pass a bound method: a lambda outlives its widget."""
    hints = QGuiApplication.styleHints()
    if hints is not None:
        hints.colorSchemeChanged.connect(slot)


def accent() -> QColor:
    """The Windows accent color. Qt's Highlight is a darker shade, so it is only a fallback,
    and Windows' default blue the last one."""
    rgb = win32.accent_color()
    if rgb is not None:
        return QColor(*rgb)
    c = QGuiApplication.palette().color(QPalette.ColorRole.Highlight)
    return c if c.isValid() else QColor(_WINDOWS_BLUE)


def ink(dark: bool) -> str:
    """Text and glyphs at full contrast."""
    return "#ffffff" if dark else "#000000"


def muted_gray(dark: bool) -> str:
    """The gray of every hint and secondary text: Windows' placeholder gray."""
    return "#959595" if dark else "#7d7d7d"


def button_text_pressed(dark: bool) -> str:
    """A native button's label while held."""
    return "#d3d3d3" if dark else "#636363"


def page_background(dark: bool) -> str:
    """A tab page's background (Base, not Window)."""
    return "#2d2d2d" if dark else "#ffffff"


def panel_colors(dark: bool) -> tuple[str, str, str]:
    """Background, border and text of the in-theme panels."""
    if dark:
        return "#2b2b2b", "#454545", "#eeeeee"
    return "#f6f6f6", "#c4c4c4", "#222222"


def panel_button_colors(dark: bool) -> tuple[str, str, str]:
    """Background, hover and border of a panel's plain button."""
    if dark:
        return "#3a3a3a", "#454545", "#555555"
    return "#ececec", "#e0e0e0", "#c4c4c4"


def support_fill(dark: bool) -> tuple[str, str, str]:
    """The support button's background, hover and pressed: the native button's fill."""
    if dark:
        return "#393939", "#3e3e3e", "#343434"
    return "#ffffff", "#fcfcfc", "#fdfdfd"


def pad_hover(dark: bool) -> QColor:
    """A pad's hovered quadrant, and the auto-corner stripes."""
    return QColor(210, 210, 210, 60) if dark else QColor(105, 105, 105, 60)


def pad_corner_off(dark: bool) -> QColor:
    """A square corner on the corner pad."""
    return QColor(160, 160, 160) if dark else QColor(110, 110, 110)


def callout_colors(dark: bool) -> tuple[QColor, QColor]:
    """Fill and border of the tutorial's bubble, hint and skip link."""
    if dark:
        return QColor(30, 30, 30, 235), QColor(255, 255, 255, 40)
    return QColor(250, 250, 250, 240), QColor(0, 0, 0, 30)
