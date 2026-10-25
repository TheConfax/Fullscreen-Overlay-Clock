"""The settings window: divided into tabs, every change applied and saved as you make it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6 import sip
from PyQt6.QtCore import (
    Qt, QAbstractAnimation, QAbstractNativeEventFilter, QByteArray, QEasingCurve, QEvent,
    QItemSelectionModel, QObject, QPointF, QRect, QRectF, QSize, QTimer, QUrl, QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QDesktopServices, QFont, QFontDatabase, QFontMetrics,
    QGuiApplication, QIcon, QImage, QMouseEvent, QPainter, QPainterPath, QPalette, QPen, QPixmap,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFontComboBox, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QStyle,
    QStyledItemDelegate, QStyleOptionComboBox, QStyleOptionFrame, QStyleOptionSpinBox,
    QStyleOptionViewItem, QTabWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, AUTHOR, COPYRIGHT_YEAR, DONATE_URL, ISSUES_URL, STORE_ID, __version__
from ..models.config import Clock, Config, Monitor, THEMES
from ..services import app_icons, monitors, startup, win32
from ..services.paths import resource_path
from .. import i18n
from ..i18n import S
from .color_picker import ColorPicker
from .dialogs import ConfirmDialog, LicensesDialog
from .style import (
    DESTRUCTIVE_RED, PAD_CROSS, PAD_EDGE, PAD_FACE, SUPPORT_PINK,
    button_text_pressed, ink, is_dark, muted_gray, on_theme_change, pad_corner_off, pad_hover,
    page_background, px, support_fill,
)

# QComboBox to the type checker only: at runtime the mixins stay plain.
if TYPE_CHECKING:
    _ComboBase = QComboBox
else:
    _ComboBase = object

_BRIDGE_REFRESHES = 5


class _SinkBlocker(QAbstractNativeEventFilter):
    def __init__(self, bridge: _RollBridge) -> None:
        super().__init__()
        self._bridge = bridge

    def nativeEventFilter(self, event_type, message):
        hwnd = self._bridge.hwnd
        if hwnd and bytes(event_type) == b"windows_generic_MSG":
            win32.keep_off_bottom(message, hwnd)
        return False, 0


class _RollBridge(QObject):
    """Keeps Qt 6.11's animation stand-in under the dropdown for `_BRIDGE_REFRESHES` after Qt
    sinks and deletes it: the translucent dropdown reaches the screen only a few refreshes
    later, and in between the window behind shows through."""

    def __init__(self) -> None:
        super().__init__()
        self.hwnd = 0
        self._roll: QWidget | None = None
        self._ours = False  # Qt has let go of it: ours to delete
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.release)
        self._blocker = _SinkBlocker(self)
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._blocker)

    def watch(self) -> None:
        """Call right after `QComboBox.showPopup`."""
        self.release()
        roll = None
        for w in QApplication.topLevelWidgets():
            meta = w.metaObject()
            if meta is not None and meta.className() == "QRollEffect":
                roll = w
        if roll is None:  # animations off in Windows
            return
        self._roll, self.hwnd = roll, win32.get_hwnd(roll)
        roll.installEventFilter(self)
        roll.destroyed.connect(self._forget)

    def eventFilter(self, obj, event) -> bool:
        roll = self._roll
        if roll is not None and obj is roll and event.type() == QEvent.Type.DeferredDelete:
            self._ours = True
            screen = roll.screen()
            hz = (screen.refreshRate() if screen is not None else 0.0) or 60.0
            self._timer.start(round(_BRIDGE_REFRESHES * 1000 / hz))
            return True
        return super().eventFilter(obj, event)

    def release(self) -> None:
        """Delete the stand-in once Qt has handed it over; before that it is Qt's."""
        self._timer.stop()
        roll, ours = self._roll, self._ours
        self._forget()
        if roll is not None:
            roll.removeEventFilter(self)
            if ours:
                roll.hide()
                sip.delete(roll)

    def _forget(self) -> None:
        self._roll, self.hwnd, self._ours = None, 0, False


_roll_bridge: _RollBridge | None = None


class _SteadyPopupMixin(_ComboBase):
    """A combo box that pins the Clock page while its dropdown is open, so a relayout
    can't disturb the popup."""

    def showPopup(self) -> None:
        freeze = getattr(self.window(), "_freeze_for_popup", None)
        if freeze is not None:
            freeze(True)
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        freeze = getattr(self.window(), "_freeze_for_popup", None)
        if freeze is not None:
            freeze(False)


class _SyncedPopupMixin(_ComboBase):
    """Patches three holes in Qt 6.11's dropdown.

    1. A quick click on an item is lost: Qt ignores a release on the list within the
       double-click interval of the click that opened it (meant for press on the box, drag,
       release), and that second click arrives as a double-click. So a release on an item
       counts whenever the press was on the list; a press on the box still goes to Qt.
    2. A stray row looks selected: hovering moves the list's current row, and nothing resets
       it when the dropdown closes without a choice. So it is realigned on every open.
    3. The opening animation jumps at the end: Qt photographs the list for it before
       scrolling to the current row. So the list is scrolled first: before Qt's call, and
       again when Qt resizes it."""

    def showPopup(self) -> None:
        global _roll_bridge
        view, model = self.view(), self.model()
        viewport = view.viewport() if view is not None else None
        if viewport is not None and not getattr(self, "_list_click_filter", False):
            viewport.installEventFilter(self)
            self._list_click_filter = True
        self._pressed_on_list = False
        if view is not None and model is not None and self.currentIndex() >= 0:
            index = model.index(self.currentIndex(), self.modelColumn())
            view.setCurrentIndex(index)
            view.scrollTo(index)
        if _roll_bridge is None:
            _roll_bridge = _RollBridge()
        self._opening = True
        try:
            super().showPopup()
        finally:
            self._opening = False
        _roll_bridge.watch()

    def hidePopup(self) -> None:
        super().hidePopup()
        if _roll_bridge is not None:
            _roll_bridge.release()

    def eventFilter(self, obj, event) -> bool:
        view = self.view()
        if view is not None and obj is view.viewport():
            kind = event.type()
            if kind == QEvent.Type.Resize and getattr(self, "_opening", False):
                view.scrollTo(view.currentIndex())
            if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                self._pressed_on_list = True
                return True
            if kind == QEvent.Type.MouseButtonRelease and self._pressed_on_list:
                self._pressed_on_list = False
                index = view.indexAt(event.position().toPoint())
                flags = index.flags()
                if (index.isValid() and flags & Qt.ItemFlag.ItemIsEnabled
                        and flags & Qt.ItemFlag.ItemIsSelectable):
                    row = index.row()
                    self.hidePopup()  # same order as Qt: close, select, then `activated`
                    self.setCurrentIndex(row)
                    self.activated.emit(row)
                    self.textActivated.emit(self.itemText(row))
                    return True
        return super().eventFilter(obj, event)


class _ComboBox(_SyncedPopupMixin, QComboBox):
    pass


class _SteadyComboBox(_SteadyPopupMixin, _SyncedPopupMixin, QComboBox):
    pass


def _position_text(row: str, column: str) -> str:
    """A monitor's place in words; *row* and *column* are `monitors.Place` keys."""
    words = S.tabs.system.display.positions
    if "too_many" in (row, column):
        return words.too_many
    r = getattr(words, row) if row else ""
    c = getattr(words, column) if column else ""
    if r and c:
        template = words.corner if column in ("left", "right") else words.ordinal_row
        return template.format(row=r, column=c, ordinal=c)
    return r or c or words.center


class _MonitorCombo(_ComboBox):
    """The monitor picker. Each entry is name and place, with a too-long name cut by "…" so
    the place always shows whole; the chosen monitor, while disconnected, is the
    placeholder, not an entry. Sized by the layout, not by its entries, so a long name
    can't widen the window."""

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[tuple[str, str]] = []  # (name, place), place `""` = name only
        self._unplugged: str | None = None  # name of the chosen monitor while disconnected
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(1)

    def set_entries(self, entries: list[tuple[str, str]]) -> None:
        self.clear()
        self._entries = list(entries)
        for _ in self._entries:
            self.addItem("")
        self._relabel()

    def show_row(self, row: int) -> None:
        self._unplugged = None
        self.setPlaceholderText("")
        self.setCurrentIndex(row)

    def show_unplugged(self, name: str) -> None:
        self._unplugged = name
        self.setCurrentIndex(-1)
        self._relabel()

    def text_width(self) -> int:
        """Room for the text. The style starts it `_COMBO_TEXT_INSET` in, past its edit field's
        left edge, so the whole field would run it into the arrow: that same padding is kept
        before the field's right edge too."""
        style = self.style()
        if style is None:
            return self.width()
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        field = style.subControlRect(QStyle.ComplexControl.CC_ComboBox, opt,
                                     QStyle.SubControl.SC_ComboBoxEditField, self)
        padding = _COMBO_TEXT_INSET - field.left()
        return field.right() + 1 - _COMBO_TEXT_INSET - padding

    def entry_text(self, name: str, place: str) -> str:
        fm, room = self.fontMetrics(), self.text_width()
        if not place:
            return fm.elidedText(name, Qt.TextElideMode.ElideRight, room)
        template = S.tabs.system.display.monitor_entry
        room -= fm.horizontalAdvance(template.format(name="", position=place))
        return template.format(name=fm.elidedText(name, Qt.TextElideMode.ElideRight, max(room, 0)),
                               position=place)

    def _relabel(self) -> None:
        for row, (name, place) in enumerate(self._entries):
            self.setItemText(row, self.entry_text(name, place))
        if self._unplugged is not None:
            unplugged = S.tabs.system.display.positions.unplugged
            self.setPlaceholderText(
                self.entry_text(self._unplugged, unplugged) if self._unplugged else unplugged)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relabel()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event is not None and event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._relabel()


class _ElidingLineEdit(QLineEdit):
    """A line edit that, while unfocused, shows the head of a too-long text with "…"
    instead of scrolling to the cursor and showing the tail. Only the painting changes."""

    def paintEvent(self, event) -> None:
        # Painted by hand even when the text fits: Qt's own painting keeps a stale scroll
        # offset that clips the first letters.
        style = self.style()
        if self.hasFocus() or not self.text() or style is None:
            super().paintEvent(event)
            return
        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        contents = style.subElementRect(
            QStyle.SubElement.SE_LineEditContents, opt, self)
        margins = self.textMargins()
        text_rect = contents.adjusted(
            margins.left() + 2, margins.top(), -margins.right(), -margins.bottom())
        elided = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, text_rect.width())
        painter = QPainter(self)
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelLineEdit, opt, painter, self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided)


class _ElidingLabel(QLabel):
    """A one-line label that cuts a too-long text with "…" instead of widening the layout."""

    def __init__(self) -> None:
        super().__init__()
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.contentsRect().width()))


class _FlashingLineEdit(QLineEdit):
    """A line edit whose border pulses red once, to refuse what was typed. Painted over the
    native frame."""

    _PULSE_MS = 1000
    _FRAME_RADIUS = 4.0  # the native frame's, one pixel in from the edge (measured)
    _HALO_PX = 3  # inside the border, at _HALO_ALPHA of its strength
    _HALO_ALPHA = 0.35

    def __init__(self) -> None:
        super().__init__()
        self._ease = QEasingCurve(QEasingCurve.Type.BezierSpline)  # CSS ease-out
        self._ease.addCubicBezierSegment(QPointF(0.0, 0.0), QPointF(0.58, 1.0), QPointF(1.0, 1.0))
        self._pulse = QVariantAnimation(self)
        self._pulse.setDuration(self._PULSE_MS)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(2.0)
        self._pulse.valueChanged.connect(self.update)

    def flash(self) -> None:
        self._pulse.stop()
        self._pulse.start()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pulse.state() != QAbstractAnimation.State.Running:
            return
        # Up in the first half, down in the second, each half eased on its own.
        t = self._pulse.currentValue()
        level = self._ease.valueForProgress(t) if t < 1 else 1 - self._ease.valueForProgress(t - 1)
        if level <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        red = QColor(DESTRUCTIVE_RED)
        r = self._FRAME_RADIUS
        inside = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        g = self._HALO_PX
        halo = QPainterPath()
        halo.addRoundedRect(inside, r - 0.5, r - 0.5)
        halo.addRoundedRect(inside.adjusted(g, g, -g, -g), max(r - 0.5 - g, 0), max(r - 0.5 - g, 0))
        red.setAlphaF(self._HALO_ALPHA * level)
        painter.fillPath(halo, red)
        red.setAlphaF(level)
        painter.setPen(QPen(red, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5), r, r)
        if self.hasFocus():
            # The native focus line is 2px, on the frame's bottom row and the one above it.
            frame = QPainterPath()
            frame.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), r + 0.5, r + 0.5)
            painter.setClipPath(frame)
            painter.fillRect(QRectF(0, self.height() - 3, self.width(), 2), red)


class _SteadyFontComboBox(_SteadyPopupMixin, _SyncedPopupMixin, QFontComboBox):
    pass


class _WheelNotches:
    """Wheel deltas as whole notches. A touchpad sends fractions of one: they add up instead of
    rounding away, and turning back drops what was left over the other way."""

    def __init__(self) -> None:
        self._rest = 0

    def take(self, delta: int) -> int:
        if delta * self._rest < 0:
            self._rest = 0
        self._rest += delta
        notches = int(self._rest / 120)
        self._rest -= notches * 120
        return notches


class _StepSlider(QSlider):
    """Horizontal slider whose wheel moves one `singleStep` per notch, not Qt's three."""

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._notches = _WheelNotches()

    def sizeHint(self) -> QSize:
        sh = super().sizeHint()
        sh.setWidth(px(108))
        return sh

    def wheelEvent(self, event) -> None:
        self.setValue(self.value() + self._notches.take(event.angleDelta().y()) * self.singleStep())
        event.accept()


def _theme_labels() -> dict[str, str]:
    # A function, not a constant: S changes in place with the language.
    return {
        "auto": S.tabs.system.interface.theme_auto, "light": S.tabs.system.interface.theme_light,
        "dark": S.tabs.system.interface.theme_dark,
    }


def _path_tail(text: str) -> str:
    """The last part of a pasted path, or the text itself."""
    return text.replace("/", "\\").rsplit("\\", 1)[-1].strip()


def _is_file_name(name: str) -> bool:
    """Whether Windows allows *name* for a file. Device names like CON.exe pass: Windows 11
    allows them with an extension."""
    return not any(c in ':*?"<>|' or ord(c) < 32 for c in name)


_PAD_COLUMN_WIDTH = 90  # the Shadow and Background pads, identical and never stretched

_OFF_FONT_PX = 13  # the "OFF" marker, on every swatch and on the corner pad

# A ceiling as well: a longer label is clipped, and scripts/check_sizes.py checks every
# language against it. The color bars are half of it.
_LABEL_COL_W = 62

_EXCLUSIONS_BTN_W = 130  # both Exclude buttons, so the rows line up; a ceiling too

_COMBO_TEXT_INSET = 8  # a combo's text inset, given to labels so the two line up
_LINEEDIT_TEXT_INSET = 2  # a line edit's text inset, given to the "current app" icon

_SIZE_SPIN_AIR = 13  # room around the widest value in the font size box

# Written by hand, and not through px(): native control chrome doesn't grow with the text.
# Every language must fit at the default text size (scripts/check_sizes.py); above it the
# window follows the content up to the screen, then scrolls.
_CLIENT_W = 450
_CLIENT_H = 502

_ABOUT_LOGO_GAP = 5  # logo → identity column
_ABOUT_ICON_PX = 14  # button icons, a shade over the font's ascent
_ABOUT_ICON_GAP = 3  # blank column right of the art, on top of the gap the style already leaves
_ABOUT_ICON_DROP = 0  # nudge below center: 1 for an odd icon size, 0 for an even one
_ABOUT_DONATE_SCALE = 1.2  # the support button, relative to a normal button's height
_ABOUT_ACCENT_IDLE = 0.5  # the support button's border, at half strength until the pointer arrives


class _SupportButton(QPushButton):
    """A button whose colored border strengthens under the pointer. A stylesheet border drops
    native painting, so the native look is rebuilt by hand, inner margin included.

    State is tracked by hand, as natively: hovered while the pointer is inside or the button
    is held, pressed when both. `:hover` goes idle when a pressed button is dragged off.
    """

    # Events after which the visual state can differ from the one on screen.
    _WATCHED = frozenset({
        QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseMove, QEvent.Type.Enter, QEvent.Type.Leave,
        QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.FocusOut,
    })

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._inside = False  # pointer within the button
        self._holding = False  # mouse button down on it, wherever the pointer has wandered
        on_theme_change(self.restyle)
        self.restyle()

    def event(self, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Enter:
            self._inside = True
        elif kind == QEvent.Type.Leave:
            self._inside = False
        elif kind == QEvent.Type.MouseButtonPress:
            self._holding = True
        elif kind == QEvent.Type.MouseButtonRelease:
            self._holding = False
            # A release outside still reaches us, and no Leave follows it.
            self._inside = self.rect().contains(event.position().toPoint())
        # After the base class: isDown() is only right once Qt has handled the event. Paint
        # is not watched: restyling from a repaint schedules another one.
        handled = super().event(event)
        if kind in self._WATCHED:
            self._sync_state()
        return handled

    def _sync_state(self) -> None:
        if self.isDown():
            state = "down"
        elif self._inside or self._holding:
            state = "hover"
        else:
            state = "idle"
        if self.property("state") != state:
            self.setProperty("state", state)
            # A property the stylesheet selects on takes effect only after a re-polish.
            style = self.style()
            if style is not None:
                style.unpolish(self)
                style.polish(self)

    def restyle(self) -> None:
        dark = is_dark()
        background, hover, pressed = support_fill(dark)
        # Stated, not inherited: a stylesheet applied during colorSchemeChanged pins the palette
        # of the outgoing theme. Stating it loses the native fade while held, hence the second.
        text = _button_icon_color()
        text_pressed = _button_icon_color(pressed=True)
        r, g, b, _ = QColor(SUPPORT_PINK).getRgb()
        self.setStyleSheet(
            f"QPushButton {{ border: 1px solid rgba({r}, {g}, {b}, {_ABOUT_ACCENT_IDLE});"
            f" border-radius: 4px; margin: 2px; background: {background}; color: {text}; }}"
            f'QPushButton[state="hover"] {{ border-color: {SUPPORT_PINK};'
            f" background: {hover}; }}"
            f'QPushButton[state="down"] {{ border-color: {SUPPORT_PINK};'
            f" background: {pressed}; color: {text_pressed}; }}")
        self._sync_state()


def _blank_pixmap(width: float, height: float, dpr: float) -> QPixmap:
    """A transparent canvas at *dpr*, the density of the screen it will show on."""
    pm = QPixmap(round(width * dpr), round(height * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _ink_bounds(pm: QPixmap) -> QRectF:
    """Where the art actually is inside its canvas, in logical pixels."""
    img = pm.toImage().convertToFormat(QImage.Format.Format_Alpha8)
    dpr = pm.devicePixelRatio()
    w, h, stride = img.width(), img.height(), img.bytesPerLine()
    alpha = img.constBits().asstring(img.sizeInBytes())
    ys = [y for y in range(h) if max(alpha[y * stride:y * stride + w]) > 8]
    xs = [x for x in range(w) if max(alpha[x::stride]) > 8]
    if not xs or not ys:
        return QRectF(0, 0, w / dpr, h / dpr)
    return QRectF(xs[0] / dpr, ys[0] / dpr,
                  (xs[-1] - xs[0] + 1) / dpr, (ys[-1] - ys[0] + 1) / dpr)


def _padded_icon(art: QPixmap, size: int) -> QPixmap:
    """Re-cut the art onto a canvas that places it by its ink, not by its box: centered
    vertically, with a blank column on the right for the gap to the text.

    The padding lives in the pixmap because styling a QPushButton drops its native painting.
    """
    ink = _ink_bounds(art)
    height = size + 2 * _ABOUT_ICON_DROP
    pm = _blank_pixmap(ink.width() + px(_ABOUT_ICON_GAP), height, art.devicePixelRatio())
    painter = QPainter(pm)
    painter.drawPixmap(QPointF(-ink.x(), (height - ink.height()) / 2 + _ABOUT_ICON_DROP - ink.y()),
                       art)
    painter.end()
    return pm


def _sized(font: QFont, pixel_size: int) -> QFont:
    probe = QFont(font)
    probe.setPixelSize(pixel_size)
    return probe


def _button_icon_color(pressed: bool = False) -> str:
    """The color a native button paints its label in, faded while held."""
    dark = is_dark()
    return button_text_pressed(dark) if pressed else ink(dark)


def _draw_glyph(glyph: str, font: QFont, size: int, color: str, dpr: float) -> QPixmap:
    """One glyph on a canvas with room to spare — the caller crops to the ink."""
    ink = QFontMetrics(font).tightBoundingRect(glyph)
    art = _blank_pixmap(size * 3, size * 3, dpr)
    painter = QPainter(art)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(QPointF(size - ink.x(), size - ink.y()), glyph)
    painter.end()
    return art


def _svg_icons(filename: str, colors: tuple[str, ...], dpr: float) -> list[QPixmap]:
    """A bundled monochrome SVG drawn with `fill="black"`, one icon per color."""
    size = px(_ABOUT_ICON_PX)
    source = resource_path("resources", filename).read_text(encoding="utf-8")
    icons = []
    for color in colors:
        svg = source.replace('fill="black"', f'fill="{color}"')
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)  # the GitHub mark isn't square
        art = _blank_pixmap(size, size, dpr)
        painter = QPainter(art)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icons.append(_padded_icon(art, size))
    return icons


def _glyph_icons(glyph: str, colors: tuple[str, ...], dpr: float) -> list[QPixmap]:
    """A character drawn as icons whose ink is as tall as an SVG icon's, one per color."""
    size = px(_ABOUT_ICON_PX)
    font = QFont("Segoe UI Symbol")  # by name: left to itself the star can come from Segoe UI Emoji
    font.setPixelSize(size)
    # Searched for by measuring what is drawn: the font renders only whole pixel sizes, and
    # its metrics miss the drawn height. Once: the color doesn't change it.
    estimate = max(1, round(size * size / QFontMetrics(font).tightBoundingRect(glyph).height()))
    best = min(range(max(1, estimate - 4), estimate + 6),
               key=lambda pixel_size: abs(_ink_bounds(_draw_glyph(
                   glyph, _sized(font, pixel_size), size, colors[0], dpr)).height() - size))
    return [_padded_icon(_draw_glyph(glyph, _sized(font, best), size, color, dpr), size)
            for color in colors]


def _draw_off_label(painter: QPainter, w: int, h: int, color: QColor) -> None:
    """A bold "OFF" centered on its outline, which is exact where font metrics are not."""
    font = QFont()
    font.setBold(True)
    font.setPixelSize(px(_OFF_FONT_PX))
    path = QPainterPath()
    path.addText(0.0, 0.0, font, "OFF")
    br = path.boundingRect()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.translate(w / 2.0 - br.center().x(), h / 2.0 - br.center().y())
    painter.drawPath(path)
    painter.restore()


class _RectPad(QWidget):
    """The rounded surface of the Shadow and Background pads: fixed width, as tall as the
    grid rows it spans."""

    _SIZE = 56  # minimum side
    _PAD = 10   # inner margin
    _RADIUS = 10  # surface corner radius

    def __init__(self) -> None:
        super().__init__()
        self._pad = px(self._PAD)
        self._radius = px(self._RADIUS)
        self.setMinimumSize(px(self._SIZE), px(self._SIZE))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(px(_PAD_COLUMN_WIDTH), px(self._SIZE))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        face = QRectF(0.5, 0.5, w - 1, h - 1)
        painter.setPen(QPen(PAD_EDGE, 1))
        painter.setBrush(PAD_FACE)
        painter.drawRoundedRect(face, self._radius, self._radius)
        self._paint_content(painter, w, h)

    def _paint_content(self, painter: QPainter, w: int, h: int) -> None:
        """Subclasses paint their controls on top of the shared surface."""


class _ShadowOffsetPad(_RectPad):
    """A dot dragged inside the pad sets the shadow's offset X and Y, each in [-100, 100]
    with 0 at the center; double-click recenters it."""

    offsetChanged = pyqtSignal(int, int)  # x, y in [-100, 100]

    _DOT_R = 6

    def __init__(self) -> None:
        super().__init__()
        self._x = 0
        self._y = 0
        self._dot_color = QColor("#000000")
        self._dragging = False
        self.setToolTip(S.tabs.clock.shadow.offset_pad)

    def set_offset(self, x: int, y: int) -> None:
        """Position the dot without emitting."""
        self._x = max(-100, min(100, int(x)))
        self._y = max(-100, min(100, int(y)))
        self.update()

    def set_dot_color(self, hex_color: str) -> None:
        self._dot_color = QColor(hex_color)
        self.update()

    def _span_x(self) -> float:
        return (self.width() - 2 * self._pad) / 2.0

    def _span_y(self) -> float:
        return (self.height() - 2 * self._pad) / 2.0

    def _dot_xy(self) -> QPointF:
        return QPointF(self.width() / 2.0 + self._x / 100.0 * self._span_x(),
                       self.height() / 2.0 + self._y / 100.0 * self._span_y())

    def _to_offset(self, pos: QPointF) -> tuple[int, int]:
        x = round((pos.x() - self.width() / 2.0) / self._span_x() * 100)
        y = round((pos.y() - self.height() / 2.0) / self._span_y() * 100)
        return (max(-100, min(100, x)), max(-100, min(100, y)))

    def mousePressEvent(self, event) -> None:
        self._dragging = True
        self._drag_to(event.position())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._drag_to(event.position())

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False

    def mouseDoubleClickEvent(self, event) -> None:
        self._dragging = False
        if (self._x, self._y) != (0, 0):
            self._x, self._y = 0, 0
            self.offsetChanged.emit(0, 0)
        self.update()

    def _drag_to(self, pos: QPointF) -> None:
        x, y = self._to_offset(pos)
        if (x, y) != (self._x, self._y):
            self._x, self._y = x, y
            self.offsetChanged.emit(x, y)
        self.update()

    def _paint_content(self, painter: QPainter, w: int, h: int) -> None:
        cx, cy = w / 2.0, h / 2.0
        painter.setPen(QPen(PAD_CROSS, 1))
        painter.drawLine(QPointF(self._pad, cy), QPointF(w - self._pad, cy))
        painter.drawLine(QPointF(cx, self._pad), QPointF(cx, h - self._pad))
        dc = self._dot_color
        dark = is_dark()
        painter.setBrush(dc)
        painter.setPen(QPen(QColor(muted_gray(dark)), 1.5))
        r = float(px(self._DOT_R))
        painter.drawEllipse(self._dot_xy(), r, r)


class _CornerPad(_RectPad):
    """A pad whose four corners toggle, by click or by arrows + Space, which corners of the
    background are rounded."""

    # top-left, top-right, bottom-left, bottom-right
    cornersChanged = pyqtSignal(bool, bool, bool, bool)

    _INSET = 15   # corner bracket distance from the pad edges
    _ARM = 13     # length of each bracket arm
    _R = 9        # arc radius for a rounded corner (≤ _ARM)

    def __init__(self) -> None:
        super().__init__()
        self._corners = [True, True, True, True]
        self._hover = -1  # quadrant under the cursor, -1 = none
        self._key_corner = 0  # quadrant the arrow keys are on, lit while focused
        self._corner_radius_zero = False
        self.set_interactive(True)
        self.setMouseTracking(True)

    def set_corners(self, tl: bool, tr: bool, bl: bool, br: bool) -> None:
        """Set the four flags without emitting."""
        self._corners = [bool(tl), bool(tr), bool(bl), bool(br)]
        self.update()

    def set_interactive(self, on: bool) -> None:
        """When False the pad only displays: no hover, no clicks, no Tab stop, no tooltip."""
        self._interactive = on
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ArrowCursor)
        # Tab only: a click doesn't light the keyboard's quadrant.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus if on else Qt.FocusPolicy.NoFocus)
        if not on and self.hasFocus():
            self.clearFocus()
        self.setToolTip(S.tabs.clock.background.corner_pad if on else "")
        if not on:
            self._hover = -1
        self.update()  # the stripes come or go

    def set_corner_radius_zero(self, on: bool) -> None:
        """Write "OFF" across the pad: at corner_radius 0 no corner is rounded."""
        on = bool(on)
        if on != self._corner_radius_zero:
            self._corner_radius_zero = on
            self.update()

    def _corner_at(self, pos: QPointF) -> int:
        top = pos.y() < self.height() / 2.0
        left = pos.x() < self.width() / 2.0
        return (0 if top else 2) + (0 if left else 1)

    def _quadrant_rect(self, idx: int, w: int, h: int) -> QRectF:
        left = idx in (0, 2)
        top = idx in (0, 1)
        return QRectF(0 if left else w / 2.0, 0 if top else h / 2.0, w / 2.0, h / 2.0)

    def mouseMoveEvent(self, event) -> None:
        if not self._interactive:
            return
        idx = self._corner_at(event.position())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hover != -1:
            self._hover = -1
            self.update()

    def _geom(self, idx: int, w: int, h: int) -> tuple[float, float, int, int]:
        """Corner point (cx, cy) and the arm directions (dx, dy) for corner `idx`."""
        left = idx in (0, 2)
        top = idx in (0, 1)
        inset = px(self._INSET)
        cx = inset if left else w - inset
        cy = inset if top else h - inset
        return cx, cy, (1 if left else -1), (1 if top else -1)

    def mousePressEvent(self, event) -> None:
        if not self._interactive:
            return
        self._key_corner = self._corner_at(event.position())
        self._toggle(self._key_corner)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        row, col = divmod(self._key_corner, 2)
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            col = int(key == Qt.Key.Key_Right)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            row = int(key == Qt.Key.Key_Down)
        elif key == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self._toggle(self._key_corner)
            return
        else:
            super().keyPressEvent(event)
            return
        self._key_corner = row * 2 + col
        self.update()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()

    def _toggle(self, idx: int) -> None:
        self._corners[idx] = not self._corners[idx]
        self.cornersChanged.emit(*self._corners)
        self.update()

    def _paint_content(self, painter: QPainter, w: int, h: int) -> None:
        dark = is_dark()
        hover_color = pad_hover(dark)
        lit = {self._hover} - {-1}
        if self.hasFocus():
            lit.add(self._key_corner)
        if not self._interactive:  # auto corners: diagonal stripes
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), self._radius, self._radius)
            painter.setClipPath(clip)
            painter.setPen(QPen(hover_color, 3))
            step = px(12)
            for x in range(-h, w + h, step):
                painter.drawLine(QPointF(x, h), QPointF(x + h, 0))
            painter.restore()
        if lit:
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), self._radius, self._radius)
            painter.setClipPath(clip)
            for idx in lit:
                painter.fillRect(self._quadrant_rect(idx, w, h), hover_color)
            painter.restore()
        on_pen = QPen(self.palette().color(QPalette.ColorRole.Accent), 2.2)
        off_pen = QPen(pad_corner_off(dark), 2.0)
        arm, r = px(self._ARM), px(self._R)
        for idx in range(4):
            cx, cy, dx, dy = self._geom(idx, w, h)
            rounded = self._corners[idx]
            path = QPainterPath()
            path.moveTo(cx, cy + dy * arm)
            if rounded:
                path.lineTo(cx, cy + dy * r)
                path.quadTo(cx, cy, cx + dx * r, cy)
            else:
                path.lineTo(cx, cy)
            path.lineTo(cx + dx * arm, cy)
            painter.strokePath(path, on_pen if rounded else off_pen)
        if self._corner_radius_zero:
            _draw_off_label(painter, w, h, QColor(ink(dark)))


class _RemoveButton(QLabel):
    """The exclusion row's "×". A QLabel because a borderless QPushButton kept a stray focus
    dot; the glyph is centered on its outline, since the font's line box leaves it low."""

    clicked = pyqtSignal()

    _GLYPH = "×"

    def __init__(self) -> None:
        super().__init__()
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(px(28), px(28))  # the tallest thing in a row: it sets the row height
        self.setToolTip(S.tabs.exclusions.remove)
        font = self.font()
        font.setPixelSize(px(23))
        self.setFont(font)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()  # or the release goes to the parent
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        # Like a native button: left only, and only if released over it.
        if (event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addText(0.0, 0.0, self.font(), self._GLYPH)
        br = path.boundingRect()
        painter.translate(self.width() / 2.0 - br.center().x(),
                          self.height() / 2.0 - br.center().y())
        color = DESTRUCTIVE_RED if self._hover else muted_gray(is_dark())
        painter.fillPath(path, QBrush(QColor(color)))


class _RowNameLabel(QWidget):
    """The exclusion row's app name, centered on the font's cap height so every row lines up
    whatever its letters. Drawn as text, not as an outline like the ×, to keep ClearType."""

    _FONT_PX = 12  # the window's standard size (Segoe UI 9pt)

    def __init__(self, text: str, color: QColor) -> None:
        super().__init__()
        self._text = text
        self._color = color
        font = self.font()
        font.setPixelSize(px(self._FONT_PX))
        font.setWeight(QFont.Weight.Normal)
        self.setFont(font)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._text), fm.height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self._color)
        fm = self.fontMetrics()
        baseline = (self.height() + fm.capHeight()) / 2.0
        painter.drawText(QPointF(0.0, baseline),
                         fm.elidedText(self._text, Qt.TextElideMode.ElideRight, self.width()))


class _KeyboardRowDelegate(QStyledItemDelegate):
    """The row with keyboard focus is painted as the row under the pointer."""

    def paint(self, painter, option, index) -> None:
        if option.state & QStyle.StateFlag.State_HasFocus:
            option = QStyleOptionViewItem(option)
            option.state = ((option.state & ~QStyle.StateFlag.State_HasFocus)
                            | QStyle.StateFlag.State_MouseOver)
        super().paint(painter, option, index)


class _ExclusionsList(QListWidget):
    """The excluded apps, one row per wheel notch: the rows are tall, three would overshoot.
    From the keyboard: arrows pick a row, Delete removes it."""

    remove_requested = pyqtSignal(QListWidgetItem)

    def __init__(self) -> None:
        super().__init__()
        self._notches = _WheelNotches()
        self.setItemDelegate(_KeyboardRowDelegate(self))

    def focusInEvent(self, event) -> None:
        if self.currentRow() < 0 and self.count():
            self._set_current(0)
        super().focusInEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            row, item = self.currentRow(), self.currentItem()
            if item is not None:
                self.remove_requested.emit(item)
                if self.count():
                    self._set_current(min(row, self.count() - 1))
            return
        super().keyPressEvent(event)
        self.scrollTo(self.currentIndex())  # autoScroll is off, for clicks

    def _set_current(self, row: int) -> None:
        # NoUpdate: setting the current row would select it, past NoSelection.
        self.setCurrentRow(row, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.scrollTo(self.currentIndex())

    def wheelEvent(self, event) -> None:
        bar = self.verticalScrollBar()
        if bar is None:
            return
        bar.setValue(bar.value() - self._notches.take(event.angleDelta().y()))
        event.accept()

    def refresh_hover(self) -> None:
        """Light up the row that slid under a still pointer: Qt updates hover and cursor
        only when the pointer moves, so a move on the spot is sent."""
        self.executeDelayedItemsLayout()
        top, viewport = self.window(), self.viewport()
        window = top.windowHandle() if top is not None else None
        pos = QCursor.pos()
        if (window is None or viewport is None
                or not viewport.rect().contains(viewport.mapFromGlobal(pos))):
            return
        QApplication.sendEvent(window, QMouseEvent(
            QEvent.Type.MouseMove, QPointF(window.mapFromGlobal(pos)), QPointF(pos),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


class _ColorButton(QPushButton):
    """A button that previews a color and opens a picker; emits the new hex."""

    colorChanged = pyqtSignal(str)

    def __init__(self, tooltip: str, *, width: int) -> None:
        super().__init__()
        self._color = "#000000"
        self._zero = False  # opacity 0: "OFF" across the swatch
        self.setObjectName("colorSwatch")
        self.setFixedWidth(width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._radius = px(5)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.clicked.connect(self._pick)
        on_theme_change(self._retint)

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color
        # By id: a bare background-color would cascade into the children.
        ring = muted_gray(is_dark())
        self.setStyleSheet(
            f"#colorSwatch {{"
            f" background-color: {hex_color};"
            f" border: 1px solid {ring};"
            f" border-radius: {self._radius}px; }}")

    def _retint(self) -> None:
        self.set_color(self._color)

    def color(self) -> str:
        return self._color

    def set_zero(self, on: bool) -> None:
        on = bool(on)
        if on != self._zero:
            self._zero = on
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._zero:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        hex_c = self._color.lstrip('#')
        r, g, b = int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        _draw_off_label(painter, w, h, QColor(ink(lum < 128)))

    def _pick(self) -> None:
        picker = ColorPicker(self._color, self)
        picker.colorChanged.connect(self._on_picked)
        picker.show()
        picker.activateWindow()

    def _on_picked(self, hex_color: str) -> None:
        self.set_color(hex_color)
        self.colorChanged.emit(self._color)


class SettingsWindow(QWidget):
    """The settings panel. Its controls never write while `_loading`."""

    config_changed = pyqtSignal(object)  # Config
    closed = pyqtSignal()
    restart_requested = pyqtSignal()  # Restart tutorial

    def __init__(self, screens_provider) -> None:
        super().__init__()
        self._config = Config.default()
        self._loading = False
        self._autoclose_armed = False  # tutorial preview: close on mouse-enter
        self._native_ready = False  # the Win32 fixes that need a live window are done
        self._pad_driving = False  # the shadow pad is writing the offset boxes
        self._screens_provider = screens_provider  # callable -> list[QScreen]
        self._monitors: list[Monitor] = []  # one per monitor combo row
        self._primary_row = 0
        self._monitors_pending = False
        self._preview_name: str | None = None  # last app shown in the "current app" preview
        self._muted_labels: list[QLabel] = []  # hint texts, re-tinted on theme flip
        self._icon_states: dict = {}  # button -> (normal icon, pressed icon)
        self._rebuild_pending = False
        for restyle in (self._restyle_muted_labels, self._restyle_exclusion_rows,
                        self._restyle_current_name, self._restyle_reset_group,
                        self._restyle_legal_line, self._restyle_about_icons):
            on_theme_change(restyle)

        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        # Here, before the native window exists: a flag changed later recreates the window.
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        # The panel answers clicks while inactive, so its tooltips must show then too.
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)

        tabs = self._tabs = QTabWidget(self)
        tabs.addTab(self._build_clock_tab(), S.tabs.clock.title)
        tabs.addTab(self._build_exclusions_tab(), S.tabs.exclusions.title)
        tabs.addTab(self._build_system_tab(), S.tabs.system.title)

        # Scrolls only when the screen can't hold the content.
        scroll = QScrollArea()
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # an invisible Tab stop otherwise
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(tabs)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

        # The "current app" preview, only while visible.
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(1000)
        self._preview_timer.timeout.connect(self._update_current_preview)

        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._schedule_monitor_rebuild)
        for screen in QGuiApplication.screens():
            screen.geometryChanged.connect(self._schedule_monitor_rebuild)

        # Before the first show: fixing the size of a live window can leave the grip and
        # Maximize behind.
        self._size_to_content()

    # -- tab builders ---------------------------------------------------------
    def _build_clock_tab(self) -> QWidget:
        tab = self._clock_tab = QWidget()
        form = QFormLayout(tab)

        form.addRow(self._build_time_format_group())

        self._text_color = _ColorButton(S.tabs.clock.text.color,
                                        width=px(_LABEL_COL_W) // 2)
        self._text_color.colorChanged.connect(
            lambda c: self._set("clock.text", "color", c))
        self._text_opacity = self._slider(self._on_text_opacity, lo=1)
        form.addRow(self._build_text_group())

        self._bg_color = _ColorButton(S.tabs.clock.background.color,
                                      width=px(_LABEL_COL_W) // 2)
        self._bg_color.colorChanged.connect(
            lambda c: self._set("clock.background", "color", c))
        self._bg_opacity = self._slider(self._on_bg_opacity)
        self._padding = self._pct_slider(0, 100, lambda v: self._set("clock.background", "padding", v))
        self._corner_radius = self._pct_slider(0, 100, self._on_corner_radius)
        form.addRow(self._build_background_group())

        form.addRow(self._build_shadow_group())
        return tab

    def _muted_css(self) -> str:
        return f"color: {muted_gray(is_dark())}; font-size: {px(11)}px;"

    def _register_muted(self, label) -> None:
        label.setStyleSheet(self._muted_css())
        self._muted_labels.append(label)

    def _restyle_muted_labels(self) -> None:
        css = self._muted_css()
        for label in self._muted_labels:
            label.setStyleSheet(css)

    def _reset_group_css(self) -> str:
        """Red frame and title for the Reset group. A QSS border drops the native margins: these
        are the native ones, put back by hand. The title's background, the tab page's, punches
        the gap in the top line."""
        behind = page_background(is_dark())
        return (
            f"QGroupBox {{ color: {DESTRUCTIVE_RED};"
            f" border: 1px solid {DESTRUCTIVE_RED}; border-radius: 4px;"
            f" margin: {px(9)}px 1px 1px 1px; padding: {px(8)}px 0 0 0; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0;"
            f" background: {behind}; color: {DESTRUCTIVE_RED}; }}")

    def _restyle_reset_group(self) -> None:
        if hasattr(self, "_reset_group"):
            self._reset_group.setStyleSheet(self._reset_group_css())

    def _legal_html(self) -> str:
        # In the markup: links take the palette's Link color, which the stylesheet doesn't set.
        color = muted_gray(is_dark())
        return (f"© {COPYRIGHT_YEAR} {AUTHOR} · "
                f'<a href="licenses" style="color: {color};">{S.tabs.system.about.licenses}</a>')

    def _open_licenses(self, _href: str) -> None:
        LicensesDialog(self).exec()

    def _open_external(self, url: str) -> None:
        # Out of the way: the panel stays on top of what it opens.
        QDesktopServices.openUrl(QUrl(url))
        self.showMinimized()

    def _restyle_about_icons(self) -> None:
        # A second, faded icon for the held button: QIcon has no "pressed" mode. The size is
        # read off each pixmap, since a fixed one would rescale away its padding.
        dpr = self.devicePixelRatioF()
        colors = (_button_icon_color(), _button_icon_color(pressed=True))
        for button, make_icons in getattr(self, "_about_icons", ()):
            normal, pressed = make_icons(colors, dpr)
            self._icon_states[button] = (QIcon(normal), QIcon(pressed))
            button.setIcon(self._icon_states[button][0])
            button.setIconSize(normal.deviceIndependentSize().toSize())

    def _wire_icon_press(self, button) -> None:
        button.pressed.connect(lambda: button.setIcon(self._icon_states[button][1]))
        button.released.connect(lambda: button.setIcon(self._icon_states[button][0]))

    def _restyle_legal_line(self) -> None:
        if hasattr(self, "_legal_line"):
            self._legal_line.setText(self._legal_html())

    def _restyle_exclusion_rows(self) -> None:
        if not hasattr(self, "_exclusions_list"):
            return
        for i in range(self._exclusions_list.count()):
            item = self._exclusions_list.item(i)
            self._exclusions_list.setItemWidget(item, self._exclusion_row(self._item_name(item)))

    def _build_display_group(self) -> QGroupBox:
        """The "show on desktop" toggle and the monitor picker, in one box."""
        group = QGroupBox(S.tabs.system.display.title)
        form = QFormLayout(group)
        self._show_on_desktop = QCheckBox(S.tabs.system.display.show_on_desktop)
        self._show_on_desktop.toggled.connect(
            lambda v: self._set("system.display", "show_on_desktop", v))
        form.addRow(self._show_on_desktop)
        self._monitor_combo = _MonitorCombo()
        self._monitor_combo.setMinimumWidth(0)
        self._monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)
        form.addRow(S.tabs.system.display.monitor, self._monitor_combo)
        return group

    def _build_time_format_group(self) -> QGroupBox:
        group = QGroupBox(S.tabs.clock.time_format.title)
        row = QHBoxLayout(group)
        self._fmt_24h = QCheckBox(S.tabs.clock.time_format.use_24h)
        self._fmt_24h.toggled.connect(self._on_24h_toggled)
        self._fmt_ampm = QCheckBox(S.tabs.clock.time_format.show_ampm)
        self._fmt_ampm.toggled.connect(lambda v: self._set("clock.time_format", "show_ampm", v))
        self._fmt_seconds = QCheckBox(S.tabs.clock.time_format.show_seconds)
        self._fmt_seconds.toggled.connect(lambda v: self._set("clock.time_format", "show_seconds", v))
        self._fmt_leading = QCheckBox(S.tabs.clock.time_format.leading_zero)
        self._fmt_leading.toggled.connect(lambda v: self._set("clock.time_format", "leading_zero", v))
        row.addStretch(1)
        for w in (self._fmt_24h, self._fmt_ampm, self._fmt_seconds, self._fmt_leading):
            row.addWidget(w)
            row.addStretch(1)
        return group

    def _on_24h_toggled(self, on: bool) -> None:
        self._set("clock.time_format", "use_24h", on)
        self._fmt_ampm.setEnabled(not on)

    def _build_text_group(self) -> QGroupBox:
        group = QGroupBox(S.tabs.clock.text.title)
        grid = QGridLayout(group)
        grid.addWidget(self._text_color, 0, 0, 2, 1)
        grid.addLayout(self._font_row(), 0, 1)
        opacity = QHBoxLayout()
        opacity.setContentsMargins(0, 0, 0, 0)
        opacity.addWidget(self._form_label(S.tabs.clock.text.opacity))
        opacity.addWidget(self._text_opacity[0])
        grid.addLayout(opacity, 1, 1)
        grid.setColumnStretch(1, 1)
        return group

    def _font_row(self) -> QHBoxLayout:
        """Family, weight and size; only the family stretches or shrinks."""
        self._font_combo = _SteadyFontComboBox()
        # Ignored: setMinimumWidth(0) alone can't go under the combo's minimumSizeHint.
        self._font_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._font_combo.setLineEdit(_ElidingLineEdit())
        self._font_combo.currentFontChanged.connect(self._on_font_family_changed)
        # Unfocused again after a pick, so the name is elided. On the next tick: the closing
        # popup gives the focus back first.
        self._font_combo.activated.connect(
            lambda _: QTimer.singleShot(0, self._font_combo.clearFocus))

        self._weight_combo = _SteadyComboBox()
        self._weight_combo.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self._weight_combo.currentIndexChanged.connect(
            lambda: self._set("clock.text", "font_weight", self._weight_combo.currentData()))
        self._refresh_weight_options(self._config.clock.text.font_family,
                                     select=self._config.clock.text.font_weight)

        self._size_spin = self._spin(8, 100, lambda v: self._set("clock.text", "font_size", v))
        self._size_spin.setFixedWidth(self._size_spin_width())

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._font_combo, 3)
        row.addWidget(self._weight_combo)
        row.addWidget(self._size_spin)
        return row

    def _size_spin_width(self) -> int:
        """sizeHint, widened by whatever the arrows take from the widest value's room."""
        spin = self._size_spin
        hint = spin.sizeHint()
        opt = QStyleOptionSpinBox()
        spin.initStyleOption(opt)
        opt.rect = QRect(0, 0, hint.width(), hint.height())
        style = spin.style()
        if style is None:
            return hint.width()
        edit = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox, opt, QStyle.SubControl.SC_SpinBoxEditField, spin)
        need = spin.fontMetrics().horizontalAdvance(str(spin.maximum())) + px(_SIZE_SPIN_AIR)
        return hint.width() + max(0, need - edit.width())

    def _on_font_family_changed(self, font: QFont) -> None:
        if self._loading:
            return
        family = font.family()
        # Written together, so the clock never shows the new family with the old weight.
        self._refresh_weight_options(family)
        text = self._config.clock.text
        text.font_family = family
        text.font_weight = self._weight_combo.currentData()
        self.config_changed.emit(self._config.copy())

    def _refresh_weight_options(self, family: str, select: str | None = None) -> None:
        """Fill the weight combo with *family*'s upright styles, light to heavy, without
        emitting. Picks *select*, else the current one, else Regular, else the first."""
        styles = [s for s in QFontDatabase.styles(family)
                  if "italic" not in s.lower() and "oblique" not in s.lower()]
        if not styles:
            styles = ["Regular"]
        # Fonts list their styles in their own order, not by weight.
        def _weight_of(style: str) -> int:
            w = QFontDatabase.font(family, style, 10).weight()
            return getattr(w, "value", int(w))
        styles.sort(key=lambda s: (_weight_of(s), s))
        want = select if select is not None else self._weight_combo.currentData()
        self._weight_combo.blockSignals(True)
        self._weight_combo.clear()
        for style in styles:
            self._weight_combo.addItem(style, style)
        idx = self._weight_combo.findData(want)
        if idx < 0:
            idx = self._weight_combo.findData("Regular")
        if idx < 0:
            idx = 0
        self._weight_combo.setCurrentIndex(idx)
        self._weight_combo.blockSignals(False)

    @staticmethod
    def _form_label(text: str) -> QLabel:
        """A label at the shared column width, its text in line with the combo above it."""
        w = QLabel(text)
        w.setFixedWidth(px(_LABEL_COL_W))
        w.setContentsMargins(_COMBO_TEXT_INSET, 0, 0, 0)
        return w

    def _build_background_group(self) -> QGroupBox:
        group = QGroupBox(S.tabs.clock.background.title)
        grid = QGridLayout(group)

        # Columns: color bar | label | field | separator | pad. Same in the Shadow box.
        grid.addWidget(self._bg_color, 0, 0, 3, 1)
        grid.addWidget(self._form_label(S.tabs.clock.background.opacity), 0, 1)
        grid.addWidget(self._bg_opacity[0], 0, 2)
        grid.addWidget(self._form_label(S.tabs.clock.background.padding), 1, 1)
        grid.addWidget(self._padding[0], 1, 2)
        grid.addWidget(self._form_label(S.tabs.clock.background.corner_radius), 2, 1)
        grid.addWidget(self._corner_radius[0], 2, 2)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        grid.addWidget(sep, 0, 3, 3, 1)

        self._corner_pad = _CornerPad()
        self._corner_pad.cornersChanged.connect(self._on_corners_changed)
        grid.addWidget(self._corner_pad, 0, 4, 2, 1)

        self._auto_corners_cb = QCheckBox(S.tabs.clock.background.auto_corners)
        self._auto_corners_cb.toggled.connect(self._on_auto_corners_changed)
        grid.addWidget(self._auto_corners_cb, 2, 4, Qt.AlignmentFlag.AlignCenter)

        grid.setColumnStretch(2, 3)
        grid.setColumnStretch(4, 0)
        grid.setColumnMinimumWidth(4, px(_PAD_COLUMN_WIDTH))
        return group

    def _on_corners_changed(self, tl: bool, tr: bool, bl: bool, br: bool) -> None:
        if self._loading:
            return
        bg = self._config.clock.background
        bg.round_top_left, bg.round_top_right = tl, tr
        bg.round_bottom_left, bg.round_bottom_right = bl, br
        self.config_changed.emit(self._config.copy())

    def _on_auto_corners_changed(self, checked: bool) -> None:
        if self._loading:
            return
        self._corner_pad.set_interactive(not checked)
        self._config.clock.background.auto_corners = checked
        self.config_changed.emit(self._config.copy())

    def _build_shadow_group(self) -> QGroupBox:
        group = QGroupBox(S.tabs.clock.shadow.title)
        grid = QGridLayout(group)

        self._shadow_color = _ColorButton(S.tabs.clock.shadow.color,
                                          width=px(_LABEL_COL_W) // 2)
        self._shadow_color.colorChanged.connect(
            lambda c: self._set("clock.shadow", "color", c))
        self._shadow_color.colorChanged.connect(
            lambda c: self._shadow_pad.set_dot_color(c))
        grid.addWidget(self._shadow_color, 0, 0, 3, 1)

        self._shadow_intensity = self._pct_slider(0, 100, self._on_shadow_intensity)
        grid.addWidget(self._form_label(S.tabs.clock.shadow.intensity), 0, 1)
        grid.addWidget(self._shadow_intensity[0], 0, 2)

        self._shadow_blur = self._pct_slider(
            0, 100, lambda v: self._set("clock.shadow", "blur", v))
        grid.addWidget(self._form_label(S.tabs.clock.shadow.blur), 1, 1)
        grid.addWidget(self._shadow_blur[0], 1, 2)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        grid.addWidget(sep, 0, 3, 3, 1)

        self._shadow_pad = _ShadowOffsetPad()
        self._shadow_pad.offsetChanged.connect(self._on_pad_offset)
        self._shadow_off_x = self._readout_spin(-100, 100)
        self._shadow_off_x.setFixedWidth(px(50))  # room for the minus sign
        self._shadow_off_x.valueChanged.connect(
            lambda v: self._on_shadow_offset("offset_x", v))
        self._shadow_off_y = self._readout_spin(-100, 100)
        self._shadow_off_y.setFixedWidth(px(50))
        self._shadow_off_y.valueChanged.connect(
            lambda v: self._on_shadow_offset("offset_y", v))

        grid.addWidget(self._shadow_pad, 0, 4, 3, 1)

        labels = QHBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        # The inset of _form_label, without its fixed width.
        _x_label = QLabel(S.tabs.clock.shadow.offset_x)
        _x_label.setContentsMargins(_COMBO_TEXT_INSET, 0, 0, 0)
        labels.addWidget(_x_label)
        labels.addWidget(self._shadow_off_x)
        labels.addStretch(1)
        labels.addWidget(QLabel(S.tabs.clock.shadow.offset_y))
        labels.addWidget(self._shadow_off_y)
        grid.addLayout(labels, 2, 1, 1, 2)

        grid.setColumnStretch(2, 3)
        grid.setColumnStretch(4, 0)
        grid.setColumnMinimumWidth(4, px(_PAD_COLUMN_WIDTH))
        return group

    def _on_text_opacity(self, value: float) -> None:
        self._set("clock.text", "opacity", value)
        self._text_color.set_zero(value == 0)

    def _on_bg_opacity(self, value: float) -> None:
        self._set("clock.background", "opacity", value)
        self._bg_color.set_zero(value == 0)

    def _on_corner_radius(self, value: int) -> None:
        self._set("clock.background", "corner_radius", value)
        self._corner_pad.set_corner_radius_zero(value == 0)

    def _on_shadow_intensity(self, value: int) -> None:
        self._set("clock.shadow", "intensity", value)
        self._shadow_color.set_zero(value == 0)

    def _on_shadow_offset(self, field: str, value: int) -> None:
        if self._pad_driving:
            return  # _on_pad_offset writes both at once
        self._set("clock.shadow", field, value)
        self._shadow_pad.set_offset(self._config.clock.shadow.offset_x,
                                    self._config.clock.shadow.offset_y)

    def _on_pad_offset(self, x: int, y: int) -> None:
        # One emit per move: through the boxes, a diagonal step would emit twice.
        self._pad_driving = True
        try:
            self._shadow_off_x.setValue(x)
            self._shadow_off_y.setValue(y)
        finally:
            self._pad_driving = False
        shadow = self._config.clock.shadow
        shadow.offset_x, shadow.offset_y = x, y
        self.config_changed.emit(self._config.copy())

    def _build_system_tab(self) -> QWidget:
        tab = self._system_tab = QWidget()
        layout = QVBoxLayout(tab)

        reset_group = self._reset_group = QGroupBox(S.tabs.system.reset.title)
        reset_group.setStyleSheet(self._reset_group_css())
        reset_layout = QHBoxLayout(reset_group)
        reset_clock_btn = QPushButton(S.tabs.system.reset.clock)
        reset_clock_btn.clicked.connect(self._on_reset_clock)
        clear_exclusions_btn = QPushButton(S.tabs.system.reset.exclusions)
        clear_exclusions_btn.clicked.connect(self._on_clear_exclusions)
        restart_tutorial_btn = QPushButton(S.tabs.system.reset.tutorial)
        restart_tutorial_btn.clicked.connect(self._on_restart_tutorial)
        for btn in (reset_clock_btn, clear_exclusions_btn, restart_tutorial_btn):
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            reset_layout.addWidget(btn, 1)

        layout.addWidget(self._build_display_group())
        layout.addWidget(self._build_startup_group())
        layout.addWidget(self._build_interface_group())
        layout.addWidget(reset_group)
        layout.addSpacing(px(8))  # the air a group box gets from its title band
        layout.addLayout(self._build_about_row())

        layout.addStretch(1)
        return tab

    def _build_startup_group(self) -> QGroupBox:
        group = QGroupBox(S.tabs.system.startup.title)
        layout = QVBoxLayout(group)
        # Not in the config: Windows holds it (services.startup).
        self._start_with_windows = QCheckBox(S.tabs.system.startup.enable)
        self._start_with_windows.toggled.connect(self._on_start_with_windows)
        layout.addWidget(self._start_with_windows)

        # Replaces the checkbox when the user turned the task off in Windows: it could only
        # spring back.
        self._startup_blocked = QWidget()
        blocked_row = QHBoxLayout(self._startup_blocked)
        blocked_row.setContentsMargins(0, 0, 0, 0)
        blocked_label = QLabel(S.tabs.system.startup.blocked_hint)
        self._register_muted(blocked_label)
        settings_btn = QPushButton(S.tabs.system.startup.open_windows_settings)
        settings_btn.clicked.connect(lambda: self._open_external(startup.SETTINGS_URI))
        blocked_row.addWidget(blocked_label)
        blocked_row.addStretch(1)
        blocked_row.addWidget(settings_btn)
        layout.addWidget(self._startup_blocked)

        self._sync_startup_blocked()
        return group

    def _refresh_startup(self) -> None:
        """Read autostart back from Windows, where it can change while the panel waits."""
        self._start_with_windows.blockSignals(True)
        self._start_with_windows.setChecked(startup.is_enabled())
        self._start_with_windows.blockSignals(False)
        self._sync_startup_blocked()

    def _sync_startup_blocked(self) -> None:
        blocked = startup.is_blocked()
        changed = blocked == self._startup_blocked.isHidden()
        self._start_with_windows.setVisible(not blocked)
        self._startup_blocked.setVisible(blocked)
        # The blocked row is taller than the checkbox: the logo takes or gives back the difference.
        if changed and self.isVisible():
            self._size_to_content()

    def _on_start_with_windows(self, checked: bool) -> None:
        if self._loading:
            return
        # Windows can refuse.
        actual = startup.set_enabled(checked)
        if actual != checked:
            self._loading = True
            self._start_with_windows.setChecked(actual)
            self._loading = False
        self._sync_startup_blocked()

    def _build_exclusions_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        current_row = QHBoxLayout()
        self._add_current_btn = QPushButton(S.tabs.exclusions.add_current)
        self._add_current_btn.clicked.connect(self._on_add_current)
        current_row.addWidget(self._add_current_btn)
        self._current_icon = QLabel()
        self._current_icon.setFixedHeight(px(20))
        self._current_icon.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._current_icon.setContentsMargins(_LINEEDIT_TEXT_INSET, 0, 0, 0)
        current_row.addWidget(self._current_icon)
        self._current_name = _ElidingLabel()
        current_row.addWidget(self._current_name, 1)
        layout.addLayout(current_row)

        other_row = QHBoxLayout()
        add_btn = QPushButton(S.tabs.exclusions.add_other)
        add_btn.clicked.connect(self._on_exclusion_add)
        other_row.addWidget(add_btn)
        self._exclusion_input = _FlashingLineEdit()
        self._exclusion_input.setPlaceholderText(S.tabs.exclusions.placeholder)
        self._exclusion_input.returnPressed.connect(self._on_exclusion_add)
        other_row.addWidget(self._exclusion_input, 1)
        layout.addLayout(other_row)

        # The icon starts where the input below it does.
        for r in (current_row, other_row):
            r.setSpacing(px(12))
        for btn in (self._add_current_btn, add_btn):
            btn.setFixedWidth(px(_EXCLUSIONS_BTN_W))

        hint = QLabel(S.tabs.exclusions.hint)
        hint.setWordWrap(True)
        self._register_muted(hint)
        layout.addWidget(hint)

        # No selection: the selection rectangle bled a corner behind the ×. Tab only: a click
        # doesn't light the keyboard's row.
        self._exclusions_list = _ExclusionsList()
        self._exclusions_list.remove_requested.connect(
            lambda item: self._remove_exclusion_name(self._item_name(item)))
        self._exclusions_list.setSpacing(1)
        # What the box leaves over a whole number of rows, so it never ends mid-row.
        self._exclusions_list.setViewportMargins(0, px(3), 0, px(3))
        self._exclusions_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._exclusions_list.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        # A click still makes a row current, and autoScroll would scroll it fully into view.
        self._exclusions_list.setAutoScroll(False)
        # Rows are as wide as the list (their size hints carry only a height); a long name elides.
        self._exclusions_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._exclusions_list, 1)
        return tab

    def _build_interface_group(self) -> QGroupBox:
        group = QGroupBox(S.tabs.system.interface.title)
        row = QHBoxLayout(group)
        self._theme = _ComboBox()
        labels = _theme_labels()
        for value in THEMES:
            self._theme.addItem(labels[value], value)
        self._theme.currentIndexChanged.connect(
            lambda: self._set("system.interface", "theme", self._theme.currentData()))
        self._language = _ComboBox()
        self._language.addItem(S.tabs.system.interface.language_auto, i18n.AUTO)
        for code, name in i18n.available():
            self._language.addItem(name, code)
        self._language.currentIndexChanged.connect(
            lambda: self._set("system.interface", "language", self._language.currentData()))

        lbl_theme = QLabel(S.tabs.system.interface.theme)
        lbl_language = QLabel(S.tabs.system.interface.language)
        for lbl in (lbl_theme, lbl_language):
            lbl.setContentsMargins(_COMBO_TEXT_INSET, 0, 0, 0)
        for pair in ((lbl_theme, lbl_language), (self._theme, self._language)):
            common = max(w.sizeHint().width() for w in pair)
            for w in pair:
                w.setFixedWidth(common)

        row.addWidget(lbl_theme)
        row.addWidget(self._theme)
        row.addStretch(1)
        row.addWidget(lbl_language)
        row.addWidget(self._language)
        return group

    def _build_about_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(self._build_logo(), 0, Qt.AlignmentFlag.AlignTop)
        # Not AlignTop: the column takes the row's full height, its buttons level with the
        # logo's foot.
        row.addWidget(self._build_about_column(), 1)
        return row

    def _build_logo(self) -> QLabel:
        self._logo_icon = QIcon(str(resource_path("resources", "icon.ico")))
        self._logo = QLabel()
        self._logo.setAlignment(Qt.AlignmentFlag.AlignLeft)
        return self._logo  # empty: _fit_logo fills it

    def _fit_logo(self, page_height: int) -> None:
        """Grow the logo into the System tab's leftover room, so that tab never sets the
        window height. *page_height* is the room for a page inside the window's margins.

        Measured with the logo cleared; the column beside it stays in the row either way,
        hence its height added back.
        """
        self._logo.clear()
        system_layout = self._system_tab.layout()
        if system_layout is not None:
            system_layout.activate()
        pages = [p for i in range(self._tabs.count()) if (p := self._tabs.widget(i)) is not None]
        # The tab bar and frame: the tabs' sizeHint is the tallest page plus them.
        chrome = self._tabs.sizeHint().height() - max(p.sizeHint().height() for p in pages)
        size = max(0, page_height - chrome - self._system_tab.sizeHint().height()
                   + self._about_column.sizeHint().height())
        self._logo.setPixmap(self._logo_icon.pixmap(QSize(size, size), self.devicePixelRatioF()))

    def _build_about_column(self) -> QWidget:
        """Name and legal line on top, buttons at the bottom: Donate alone, then a pair."""
        column = self._about_column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(px(_ABOUT_LOGO_GAP), 0, 0, 0)  # on top of the row's own spacing

        name = QLabel(f"{APP_NAME} v{__version__}")
        legal = self._legal_line = QLabel(self._legal_html())
        legal.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        legal.linkActivated.connect(self._open_licenses)
        self._register_muted(legal)
        for label in (name, legal):
            label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(label)

        layout.addStretch(1)
        donate = _SupportButton(S.tabs.system.about.donate)
        pair = [QPushButton(S.tabs.system.about.report_issue), QPushButton(S.tabs.system.about.rate)]
        donate.clicked.connect(lambda: self._open_external(DONATE_URL))
        pair[0].clicked.connect(lambda: self._open_external(ISSUES_URL))
        pair[1].clicked.connect(
            lambda: self._open_external(f"ms-windows-store://review/?ProductId={STORE_ID}"))
        # Off a plain button: the stylesheet skews this one's own sizeHint. Even, or the icon
        # and the label round their centering in opposite directions, a pixel apart.
        tall = round(pair[0].sizeHint().height() * _ABOUT_DONATE_SCALE)
        donate.setFixedHeight(tall + tall % 2)
        # Recipes, not pixmaps: a theme flip or a press redraws them in another color.
        self._about_icons = [
            (donate, lambda colors, dpr: _glyph_icons("♥", colors, dpr)),
            (pair[0], lambda colors, dpr: _svg_icons("GitHub_Invertocat_Black.svg", colors, dpr)),
            (pair[1], lambda colors, dpr: _glyph_icons("★", colors, dpr)),
        ]
        row = QHBoxLayout()
        for button, _ in self._about_icons:
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._wire_icon_press(button)
        for button in pair:
            row.addWidget(button, 1)
        self._restyle_about_icons()  # sets both the icon and its size
        layout.addWidget(donate)
        layout.addLayout(row)
        return column

    def _size_to_content(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        # A widget just hidden leaves its layout stale until the next loop: settle it first.
        QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        # The logo only fills the room left over, so it must not claim any while measuring.
        self._logo.clear()
        system_layout = self._system_tab.layout()
        if system_layout is not None:
            system_layout.activate()
        self._tabs.setMinimumSize(0, 0)
        layout.activate()
        m = layout.contentsMargins()
        # Off the tabs, not the layout: a scroll area caps its own size hint.
        content = self._tabs.sizeHint() + QSize(m.left() + m.right(), m.top() + m.bottom())
        size = content.expandedTo(QSize(_CLIENT_W, _CLIENT_H))
        screen, style = self.screen(), self.style()
        if screen is not None:
            room = (screen.availableGeometry().size()
                    - (self.frameGeometry().size() - self.geometry().size()))
            # The vertical scroll bar will take its width.
            if size.height() > room.height() and style is not None:
                size.setWidth(size.width()
                              + style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
            size = size.boundedTo(room)
        if size.width() < content.width() or size.height() < content.height():
            self._tabs.setMinimumSize(self._tabs.sizeHint())  # whole, and the scroll area scrolls
        self._fit_logo(max(size.height(), content.height()) - m.top() - m.bottom())
        layout.activate()
        self.setFixedSize(size)
        # Again: an unchanged fixed size does nothing, and a scaling change leaves the window
        # at the size Windows picked for the new DPI.
        self.resize(size)

    # -- small widget factories ----------------------------------------------
    def _spin(self, lo: int, hi: int, on_change) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.valueChanged.connect(on_change)
        return spin

    def _readout_spin(self, lo: int, hi: int) -> QSpinBox:
        """An editable "%" box without arrows, at the width shared by every % box."""
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSuffix("%")
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        spin.setFixedWidth(px(45))
        return spin

    def _slider(self, on_change, lo: int = 0):
        """A lo..100 slider mapped to a 0..1 float, with an editable % box beside it."""
        return self._pct_slider(lo, 100, lambda v: on_change(v / 100.0))

    def _pct_slider(self, lo: int, hi: int, on_change):
        """A lo..hi slider emitting its int value, with a % box: (container, slider, box)."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        slider = _StepSlider()
        slider.setMinimumWidth(0)
        slider.setRange(lo, hi)
        spin = self._readout_spin(lo, hi)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(on_change)
        row.addWidget(slider)
        row.addWidget(spin)
        return container, slider, spin

    # -- change plumbing ------------------------------------------------------
    def _set(self, section_path: str, field: str, value) -> None:
        """Write *field* of the section at the dotted *section_path*, then emit."""
        if self._loading:
            return
        obj = self._config
        for part in section_path.split("."):
            obj = getattr(obj, part)
        setattr(obj, field, value)
        self.config_changed.emit(self._config.copy())

    def _on_monitor_changed(self) -> None:
        row = self._monitor_combo.currentIndex()
        if 0 <= row < len(self._monitors):
            self._set("clock.position", "monitor", self._monitors[row])

    def _confirm(self, modal) -> bool:
        """Ask the confirmation whose four strings are in the catalog section *modal*."""
        return ConfirmDialog.ask(self, modal.title, modal.body, modal.ok, modal.cancel)

    def _on_reset_clock(self) -> None:
        # The whole clock section, position included.
        if not self._confirm(S.tabs.system.reset.modals.clock):
            return
        self._config.clock = Clock()
        self.load(self._config)
        self.config_changed.emit(self._config.copy())

    def _on_restart_tutorial(self) -> None:
        # Not `firstrun`: that would redo the first-run reset and autostart.
        if not self._confirm(S.tabs.system.reset.modals.tutorial):
            return
        self._config.system.tutorial.completed = False
        self.config_changed.emit(self._config.copy())
        self.restart_requested.emit()

    def _on_clear_exclusions(self) -> None:
        if not self._confirm(S.tabs.system.reset.modals.exclusions):
            return
        self._exclusions_list.clear()
        self._commit_exclusions()

    @staticmethod
    def _item_name(item) -> str:
        # Data, not text: the item's text would show through the row widget.
        return item.data(Qt.ItemDataRole.UserRole) or ""

    def _app_icon(self, pm: QPixmap) -> QPixmap:
        """An app's icon 18 logical px tall, at this window's pixel density."""
        dpr = self.devicePixelRatioF()
        icon = pm.scaledToHeight(round(px(18) * dpr), Qt.TransformationMode.SmoothTransformation)
        icon.setDevicePixelRatio(dpr)
        return icon

    def _exclusion_row(self, name: str) -> QWidget:
        """An excluded app's row: icon if cached, name, ×."""
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(px(10), px(6), px(8), px(6))
        row.setSpacing(px(10))  # the same as the left margin
        vcenter = Qt.AlignmentFlag.AlignVCenter
        pm = app_icons.cached_pixmap(name)
        if pm is not None:
            ic = QLabel()
            ic.setPixmap(self._app_icon(pm))
            row.addWidget(ic, 0, vcenter)
        label = _RowNameLabel(name, QColor(ink(is_dark())))
        row.addWidget(label, 1)
        x = _RemoveButton()
        x.clicked.connect(lambda n=name: self._remove_exclusion_name(n))
        row.addWidget(x)
        return w

    def _add_exclusion_name(self, name: str) -> None:
        """Add *name* as a program file name: a pasted path keeps its last part, and `.exe`
        is added when missing (not swapped in: Battle.net.exe is a real one)."""
        name = _path_tail(name)
        if not name:
            return
        if not name.lower().endswith(".exe"):
            name += ".exe"
        existing = {self._item_name(self._exclusions_list.item(i)).lower()
                    for i in range(self._exclusions_list.count())}
        if name.lower() in existing:
            return
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, name)
        self._exclusions_list.addItem(item)
        row = self._exclusion_row(name)
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self._exclusions_list.setItemWidget(item, row)
        self._commit_exclusions()

    def _remove_exclusion_name(self, name: str) -> None:
        for i in range(self._exclusions_list.count()):
            if self._item_name(self._exclusions_list.item(i)) == name:
                self._exclusions_list.takeItem(i)
                break
        # The cached icon stays, for when the app is added back while not running.
        self._commit_exclusions()
        QTimer.singleShot(0, self._exclusions_list.refresh_hover)  # once the removal has settled

    def _on_exclusion_add(self) -> None:
        if not _is_file_name(_path_tail(self._exclusion_input.text())):
            self._exclusion_input.flash()
            return
        self._add_exclusion_name(self._exclusion_input.text())
        self._exclusion_input.clear()
        self._refresh_icons()

    def _on_add_current(self) -> None:
        # Its path is known only now, so its icon is cached now.
        name, path = win32.app_below(win32.get_hwnd(self))
        if name and path:
            app_icons.cache_icon(name, path)
        self._add_exclusion_name(name)
        self._refresh_icons()

    def _update_current_preview(self) -> None:
        """Show the app under this window beside "Exclude current app", extracting its icon
        only when the app changes; with none, say how to get one."""
        name, path = win32.app_below(win32.get_hwnd(self))
        self._add_current_btn.setEnabled(bool(name))
        if name == self._preview_name:
            return
        self._preview_name = name
        pm = app_icons.pixmap_from_exe(path) if (name and path) else None
        if pm is not None:
            self._current_icon.setPixmap(self._app_icon(pm))
        else:
            self._current_icon.clear()
        # Without an icon the text takes its place, lined up with the input's text below.
        self._current_icon.setVisible(pm is not None)
        inset = 0 if pm is not None else _LINEEDIT_TEXT_INSET
        self._current_name.setContentsMargins(inset, 0, 0, 0)
        self._current_name.set_full_text(name or S.tabs.exclusions.no_app)
        self._restyle_current_name()

    def _restyle_current_name(self) -> None:
        """The "no app" message in the hint gray, at the size of a name."""
        if hasattr(self, "_current_name"):
            gray = self._preview_name == ""
            self._current_name.setStyleSheet(f"color: {muted_gray(is_dark())};" if gray else "")

    def _refresh_icons(self) -> None:
        """Re-cache the icon of every excluded app running now and redraw the rows; the
        others keep what they had."""
        names = [n for n in (self._item_name(self._exclusions_list.item(i))
                             for i in range(self._exclusions_list.count())) if n]
        if not names:
            return
        paths = win32.exe_paths_for(names)
        if not paths:
            return
        for name in names:
            path = paths.get(name)
            if path:
                app_icons.cache_icon(name, path)
        for i in range(self._exclusions_list.count()):
            item = self._exclusions_list.item(i)
            if item is None:
                continue
            roww = self._exclusion_row(self._item_name(item))
            item.setSizeHint(QSize(0, roww.sizeHint().height()))
            self._exclusions_list.setItemWidget(item, roww)

    def _commit_exclusions(self) -> None:
        if self._loading:
            return
        names = [self._item_name(self._exclusions_list.item(i))
                 for i in range(self._exclusions_list.count())]
        self._config.exclusions = names
        self.config_changed.emit(self._config.copy())

    def _freeze_for_popup(self, freeze: bool) -> None:
        """Pin the Clock page while a _Steady* combo is open."""
        if freeze:
            self._clock_tab.setFixedSize(self._clock_tab.size())
        else:
            self._clock_tab.setMinimumSize(0, 0)
            self._clock_tab.setMaximumSize(16777215, 16777215)

    # -- population -------------------------------------------------------------
    def _load_clock_controls(self, clock) -> None:
        """Show *clock* on the Clock tab. Call it under `_loading`."""
        tf, txt, bg, sh = (clock.time_format, clock.text,
                           clock.background, clock.shadow)
        self._fmt_24h.setChecked(tf.use_24h)
        self._fmt_ampm.setChecked(tf.show_ampm)
        self._fmt_ampm.setEnabled(not tf.use_24h)
        self._fmt_seconds.setChecked(tf.show_seconds)
        self._fmt_leading.setChecked(tf.leading_zero)
        self._font_combo.setCurrentFont(QFont(txt.font_family))
        self._size_spin.setValue(txt.font_size)
        self._refresh_weight_options(txt.font_family, select=txt.font_weight)
        self._text_color.set_color(txt.color)
        self._set_slider(self._text_opacity, txt.opacity)
        self._text_color.set_zero(txt.opacity == 0)
        self._bg_color.set_color(bg.color)
        self._set_slider(self._bg_opacity, bg.opacity)
        self._bg_color.set_zero(bg.opacity == 0)
        self._set_pct_slider(self._padding, bg.padding)
        self._set_pct_slider(self._corner_radius, bg.corner_radius)
        self._corner_pad.set_corners(bg.round_top_left, bg.round_top_right,
                                     bg.round_bottom_left, bg.round_bottom_right)
        self._corner_pad.set_corner_radius_zero(bg.corner_radius == 0)
        self._auto_corners_cb.setChecked(bg.auto_corners)
        self._corner_pad.set_interactive(not bg.auto_corners)
        self._set_pct_slider(self._shadow_intensity, sh.intensity)
        self._shadow_color.set_color(sh.color)
        self._shadow_color.set_zero(sh.intensity == 0)
        self._shadow_pad.set_dot_color(sh.color)
        self._set_pct_slider(self._shadow_blur, sh.blur)
        self._shadow_off_x.setValue(sh.offset_x)
        self._shadow_off_y.setValue(sh.offset_y)
        self._shadow_pad.set_offset(sh.offset_x, sh.offset_y)

    def retranslate(self) -> None:
        """Rebuild every tab, for a new catalog or a new system text size. The window itself
        survives. Call it deferred, never from a control's signal: it deletes that tab."""
        current = self._tabs.currentIndex()
        # They hold widgets about to die, and the theme-flip handlers walk them.
        self._muted_labels.clear()
        self._icon_states.clear()
        self._about_icons = []
        self._preview_name = None
        # Filling a fresh combo emits, and would write its first item to the config.
        self._loading = True
        try:
            while self._tabs.count():
                page = self._tabs.widget(0)
                self._tabs.removeTab(0)
                if page is not None:
                    page.deleteLater()
            self._tabs.addTab(self._build_clock_tab(), S.tabs.clock.title)
            self._tabs.addTab(self._build_exclusions_tab(), S.tabs.exclusions.title)
            self._tabs.addTab(self._build_system_tab(), S.tabs.system.title)
            self._tabs.setCurrentIndex(current)
        finally:
            self._loading = False
        self.load(self._config)
        self._size_to_content()

    def request_rebuild(self) -> None:
        """retranslate() on the next tick, once for all the requests before it (a scaling change
        sends DevicePixelRatioChange twice)."""
        if not self._rebuild_pending:
            self._rebuild_pending = True
            QTimer.singleShot(0, self._rebuild)

    def _rebuild(self) -> None:
        self._rebuild_pending = False
        self.retranslate()

    def load(self, config: Config) -> None:
        self._config = config.copy()
        self._loading = True
        try:
            disp, interface = config.system.display, config.system.interface
            self._load_clock_controls(config.clock)

            self._populate_monitors()
            self._select_monitor(config.clock.position.monitor)

            self._show_on_desktop.setChecked(disp.show_on_desktop)

            self._refresh_startup()

            self._theme.setCurrentIndex(self._index_of(self._theme, interface.theme))
            self._language.setCurrentIndex(self._index_of(self._language, interface.language))

            self._exclusions_list.clear()
            for name in config.exclusions:
                self._add_exclusion_name(name)
        finally:
            self._loading = False
        self._refresh_icons()

    def update_auto_corners(self, tl: bool, tr: bool, bl: bool, br: bool) -> None:
        """Take the corners auto corners computed, without emitting."""
        bg = self._config.clock.background
        bg.round_top_left = tl
        bg.round_top_right = tr
        bg.round_bottom_left = bl
        bg.round_bottom_right = br
        self._corner_pad.set_corners(tl, tr, bl, br)

    def update_position(self, monitor: Monitor, x: float, y: float) -> None:
        """Take the position the clock was moved to, without emitting."""
        pos = self._config.clock.position
        pos.monitor, pos.x, pos.y = monitor, x, y
        self._monitor_combo.blockSignals(True)  # a pick from the combo moves the clock
        self._select_monitor(monitor)
        self._monitor_combo.blockSignals(False)

    # -- population helpers ---------------------------------------------------
    @staticmethod
    def _index_of(combo: QComboBox, data) -> int:
        idx = combo.findData(data)
        return idx if idx >= 0 else 0

    @staticmethod
    def _set_slider(slider_tuple, value: float) -> None:
        slider_tuple[1].setValue(int(round(value * 100)))

    @staticmethod
    def _set_pct_slider(slider_tuple, value: int) -> None:
        slider_tuple[1].setValue(int(value))

    def _populate_monitors(self) -> None:
        screens = self._screens_provider()
        places = monitors.places(screens)
        self._monitors = [Monitor(monitors.id_of(p.screen), p.screen.name()) for p in places]
        self._primary_row = next(
            (row for row, p in enumerate(places) if screens and p.screen == screens[0]), 0)
        alone = len(places) == 1  # one monitor: its name says it all
        self._monitor_combo.set_entries(
            [(p.screen.name() or S.tabs.system.display.monitor,
              "" if alone else _position_text(p.row, p.column)) for p in places])

    def _select_monitor(self, monitor: Monitor) -> None:
        ids = [m.id for m in self._monitors]
        if monitor.id and monitor.id in ids:
            self._monitor_combo.show_row(ids.index(monitor.id))
        elif monitor.id:
            self._monitor_combo.show_unplugged(monitor.name)
        else:  # never chosen: the primary, where the clock is
            self._monitor_combo.show_row(self._primary_row)

    def _on_screen_added(self, screen) -> None:
        screen.geometryChanged.connect(self._schedule_monitor_rebuild)
        self._schedule_monitor_rebuild()

    def _schedule_monitor_rebuild(self, *_) -> None:
        """Screens came, went or moved: rebuild the monitor list once, when Qt has settled."""
        if not self._monitors_pending:
            self._monitors_pending = True
            QTimer.singleShot(0, self._rebuild_monitors)

    def _rebuild_monitors(self) -> None:
        self._monitors_pending = False
        self._monitor_combo.blockSignals(True)  # only the list changes: the saved choice stays
        self._populate_monitors()
        self._select_monitor(self._config.clock.position.monitor)
        self._monitor_combo.blockSignals(False)

    # -- window events --------------------------------------------------------
    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowActivate:
            if self._autoclose_armed:
                self.close()  # the preview reached by keyboard closes like on hover
                return True
            self._refresh_startup()
        # The icons are drawn at one density; Qt would stretch them blurry.
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self.request_rebuild()
            if self._native_ready:
                win32.set_window_icon_native(win32.get_hwnd(self),
                                             resource_path("resources", "icon.ico"))
        return super().event(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._native_ready:
            self._native_ready = True
            hwnd = win32.get_hwnd(self)
            win32.set_window_icon_native(hwnd, resource_path("resources", "icon.ico"))
            # Qt keeps WS_THICKFRAME on a fixed-size window: resize cursors with no resize.
            win32.drop_sizing_border(hwnd)
        self._size_to_content()
        self._update_current_preview()
        self._preview_timer.start()
        # The tabs would hold an unseen focus, and the first Tab would leave them.
        self.setFocus()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._preview_timer.stop()
        # It reopens on the first tab, switched while unseen. A spontaneous hide is a minimize,
        # which keeps its tab.
        if not event.spontaneous():
            self._tabs.setCurrentIndex(0)

    def show_tutorial_preview(self) -> None:
        """Show the panel without activating it, closing as soon as the cursor or the keyboard
        reaches it. The tutorial closes it otherwise."""
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.show()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self._autoclose_armed = True

    def enterEvent(self, event) -> None:
        if self._autoclose_armed:
            self.close()
        super().enterEvent(event)

    def closeEvent(self, event) -> None:
        self._autoclose_armed = False
        self._preview_timer.stop()
        self.closed.emit()
        super().closeEvent(event)
