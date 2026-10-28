"""The clock window: frameless, always on top."""

from __future__ import annotations

import math
from fractions import Fraction

from PyQt6.QtCore import (
    QByteArray, QDateTime, QEvent, QMargins, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTime,
    QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap, QRegion,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QVBoxLayout, QWidget,
)

from ..models.config import Config, Monitor
from ..services import haptics, monitors, win32
from ..services.paths import resource_path
from . import positioning
from .style import ARROW_IDLE, accent

#: An anchor point snaps when the card, grown by this many px, covers it. Larger than
#: EDGE_SNAP_TOLERANCE, so points win near a border.
POINT_SNAP_TOLERANCE = 40
#: A border snaps when the card's edge comes within this many px of it.
EDGE_SNAP_TOLERANCE = 30
#: Distance (px) over which a border's guide glow fades in as the clock approaches.
EDGE_GLOW_RANGE = 200
#: Glow of a border farther than EDGE_GLOW_RANGE.
EDGE_GLOW_MIN = 0.0
#: Transparent gutter (px) around the card for the edit-mode arrows, always reserved.
GUTTER = 32
#: Shortest horizontal arrow: below it the two heads overlap, so it overhangs the corners.
ARROW_MIN = 28
#: How far an arrow's outermost pixel sits past the card edge: line at GUTTER // 2, head 7.
ARROW_PROTRUSION = GUTTER // 2 + 7
#: Shortest vertical arrow: with ARROW_MIN it would overhang into the gear on a short clock.
ARROW_MIN_V = 20
#: Gear icon (px), where the two arrows cross.
GEAR_SIZE = 18
#: Ink of the × that takes the gear's place while settings is open (px).
CLOSE_SIZE = 13


def _rgba(hex_color: str, opacity: float) -> str:
    """`rgba(r, g, b, P%)` for a stylesheet, from #RRGGBB and a 0..1 opacity."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {round(opacity * 100)}%)"


def _round(value: float) -> int:
    """Half away from zero, like Qt's qRound: Python's round() takes halves to even."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


class _ClockLabel(QWidget):
    """The time, painted by hand: padding measured on the glyph ink and equal on every side
    (QLabel pads the whole line box), and each digit as wide as the widest, so the box
    doesn't change size as the time ticks."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._color = QColor("#FFFFFF")
        self._padding_pct = 55  # % of the ink height
        self._padding = 0
        self._ink_top = 0
        self._size = QSize(1, 1)

    def configure(self, font: QFont, color: QColor, padding_pct: int, text: str) -> None:
        self.setFont(font)
        self._color = color
        self._padding_pct = padding_pct
        self._text = text
        self._recompute()

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self._recompute()

    def _recompute(self) -> None:
        fm = self.fontMetrics()
        # All digits, not just the shown ones: their ink differs by a pixel, and the box
        # would jump every second.
        sample = "0123456789" + "".join(
            dict.fromkeys(ch for ch in self._text if not ch.isdigit()))
        ink = fm.tightBoundingRect(sample or " ")
        self._ink_top = ink.top()
        self._padding = int(round(self._padding_pct / 100.0 * ink.height()))
        widest = max((fm.horizontalAdvance(str(d)) for d in range(10)), default=1)
        width = sum(widest if ch.isdigit() else fm.horizontalAdvance(ch)
                    for ch in self._text)
        p = self._padding
        self._size = QSize(max(width, 1) + 2 * p, ink.height() + 2 * p)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return self._size

    def minimumSizeHint(self) -> QSize:
        return self._size

    def paintEvent(self, _event) -> None:
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self.font())
        painter.setPen(self._color)
        fm = self.fontMetrics()
        widest = max((fm.horizontalAdvance(str(d)) for d in range(10)), default=1)
        p = self._padding
        baseline = p - self._ink_top  # ink exactly `padding` below the top
        x = float(p)
        for ch in self._text:  # each digit centered in a cell as wide as the widest
            if ch.isdigit():
                cw = fm.horizontalAdvance(ch)
                painter.drawText(int(round(x + (widest - cw) / 2.0)), int(round(baseline)), ch)
                x += widest
            else:
                painter.drawText(int(round(x)), int(round(baseline)), ch)
                x += fm.horizontalAdvance(ch)


class _AlignedShadow(QGraphicsDropShadowEffect):
    """A drop shadow whose bounds fall on whole physical pixels: Qt pastes the shadowed card
    at their corner, and half a pixel off shifts the text with every blur or offset change."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._step = 1

    def set_step(self, step: int) -> None:
        """See :meth:`ClockWindow._pixel_step`."""
        if step != self._step:
            self._step = step
            self.updateBoundingRect()

    def boundingRectFor(self, rect: QRectF) -> QRectF:
        r = super().boundingRectFor(rect)
        s = self._step
        left, top = math.floor(r.left() / s) * s, math.floor(r.top() / s) * s
        right, bottom = math.ceil(r.right() / s) * s, math.ceil(r.bottom() / s) * s
        return QRectF(left, top, right - left, bottom - top)


class _ArrowLayer(QWidget):
    """The edit-mode arrows and gear, a layer over the card: painted by the window, they'd
    sit under the card's shadow."""

    def __init__(self, parent: QWidget, paint) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._paint = paint

    def paintEvent(self, _event) -> None:
        self._paint(QPainter(self))


class ClockWindow(QWidget):
    """The always-on-top clock; :meth:`apply` sets its config live."""

    #: While dragging or fine-tuning: (Monitor, x, y, snapped_edges).
    position_changed = pyqtSignal(object, float, float, object)
    drag_started = pyqtSignal()
    drag_ended = pyqtSignal()
    #: While dragging: per-border (intensity, along) for the guide, see :meth:`_edge_glow`.
    edge_glow = pyqtSignal(object)
    #: The gear was clicked.
    settings_requested = pyqtSignal()
    #: The gear, an × while settings is open, was clicked, or the clock right-clicked then.
    settings_close_requested = pyqtSignal()
    #: Clicks on the clock while the tutorial owns it, instead of their normal action.
    tutorial_left_click = pyqtSignal()
    tutorial_right_click = pyqtSignal()
    #: Press and release with no drag, while draggable.
    clock_clicked = pyqtSignal()
    #: A wheel fine-tune was applied.
    finetuned = pyqtSignal()
    #: The window moved or resized, also on its own after a scale, resolution or monitor change.
    geometry_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._config = Config.default()
        self._win_ready = False
        self._draggable = False
        self._dragging = False
        self._snap_state = "free"      # free / edge / anchor: what the snap tic compares to
        self._topmost_paused = False   # see pause_topmost
        self._fg_hook: int = 0         # WinEvent hook on foreground changes
        self._quitting = False         # see close_for_quit
        self._show_on_desktop = False
        self._drag_grab = QPoint()     # cursor-to-window offset at press
        self._shadow_reach = 0         # how far the shadow really paints past the card
        self._frozen_rect: QRect | None = None  # window rect while settings is open
        self._frozen_screen = None     # the monitor _frozen_rect belongs to
        self._frozen_grow_only = False  # tutorial goodbye: the rect only grows
        self._placed_size = QSize()    # the size reposition() last gave the window

        # Fine-tune arrows and gear (edit mode).
        self._active_axis: str | None = None
        self._scroll_axes: set[str] = set()  # lit while being scrolled
        self._v_line = None            # (x, y1, x, y2)
        self._h_line = None            # (x1, y, x2, y)
        self._v_hit = QRect()
        self._h_hit = QRect()
        self._side_v = "right"         # by quadrant, see _layout_arrows
        self._side_h = "bottom"
        self._gear_hit = QRect()
        self._gear_center = QPoint()   # exact crossing of the arrow axes
        self._gear_active = False      # hovered
        self._gear_cache: dict = {}    # (rgba, dpr) -> recolored pixmap
        self._settings_open = False    # set by the controller; gates click-away and Esc
        self._tutorial_active = False  # tutorial intro: centered, forced visible
        self._tutorial_hold = False    # tutorial move phase: forced visible, edit mode locked on
        self._tut_arrows_ok = True     # tutorial gate: arrows usable
        self._tut_gear_ok = True       # tutorial gate: gear usable
        self._grab_enabled = True      # tutorial gate: drag (the arrows stay usable)
        self._blackout = False         # tutorial goodbye: forced off while the style swaps
        self._drag_moved = False       # the current press dragged (else it's a click)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # for Esc in edit mode; show() takes none

        # Card (background) holding the label (text); both let the mouse through to the window.
        self._card = QFrame(self)
        self._card.setObjectName("clockCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label = _ClockLabel(self._card)

        self._card_layout = QVBoxLayout(self._card)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.addWidget(self._label)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        # The window's size is reposition()'s alone: by default the layout grows it to a
        # minimum built from stale margins.
        self._outer.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        # Top-left, at a fixed size: when Windows resizes the window, the card doesn't stretch.
        self._outer.addWidget(self._card, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._arrow_layer = _ArrowLayer(self, self._paint_arrows)  # created last: on top

        self._tick_timer = QTimer(self)  # on each whole second, see _tick
        self._tick_timer.setSingleShot(True)
        self._tick_timer.timeout.connect(self._tick)

        # Topmost re-assert, for what the foreground hook misses.
        self._reassert = QTimer(self)
        self._reassert.setInterval(500)
        self._reassert.timeout.connect(self._reassert_topmost)

        self._click_through: bool | None = None  # None: not applied yet
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(50)
        self._cursor_timer.timeout.connect(self._sync_click_through)

        # Edit mode: hover highlight of the arrows and gear.
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(100)
        self._hover_timer.timeout.connect(self._update_hover)

        # Arrow glow while scrolling, off shortly after the wheel stops.
        self._scroll_glow = QTimer(self)
        self._scroll_glow.setSingleShot(True)
        self._scroll_glow.setInterval(250)
        self._scroll_glow.timeout.connect(self._end_scroll_glow)

    # -- lifecycle ------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._win_ready:
            self._win_ready = True
            win32.set_tool_window(win32.get_hwnd(self))
            self._apply_window_state()
            self._fg_hook = win32.install_foreground_hook(self._on_fg_changed)
            self._update_text()
            self.reposition()
            # Next loop iteration: the first visibility check may hide us, not from here.
            QTimer.singleShot(0, self._tick)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._arrow_layer.setGeometry(self.rect())
        if self._win_ready and event.size() != self._placed_size:
            # Not ours (a scale change keeps the physical size): fix it now, not on the next tick.
            QTimer.singleShot(0, self.reposition)
        self.geometry_changed.emit()

    def closeEvent(self, event) -> None:
        # Only Quit closes the clock: any other close (Alt+F4 in edit mode) would hide it, and
        # the next show doesn't reinstall the foreground hook. Treated like Esc instead.
        if not self._quitting:
            event.ignore()
            if self._draggable and not self._settings_open and not self._tutorial_hold:
                self.set_draggable(False)
            return
        win32.uninstall_foreground_hook(self._fg_hook)
        self._fg_hook = 0
        super().closeEvent(event)

    def close_for_quit(self) -> None:
        """Close for good, on app exit: the one close :meth:`closeEvent` lets through."""
        self._quitting = True
        self.close()

    # -- configuration --------------------------------------------------------
    def apply(self, config: Config) -> None:
        """Apply a whole config live."""
        self._config = config.copy()
        self._show_on_desktop = config.system.display.show_on_desktop
        self._restyle()
        if self._win_ready:
            self.reposition()
            self._refresh_visibility()

    def _restyle(self) -> None:
        """Text, card and shadow. The text comes first: the box it makes sizes the rest."""
        txt = self._config.clock.text
        font = QFont(txt.font_family, txt.font_size)
        font.setStyleName(txt.font_weight)  # a style name of the family; Qt falls back if missing
        text_color = QColor(txt.color)
        text_color.setAlphaF(txt.opacity)
        self._label.configure(font, text_color, self._config.clock.background.padding,
                              self._config.clock.time_format.render(QDateTime.currentDateTime()))
        self._apply_card_style()

        # Both offsets and the blur scale with the clock's height, so a % throws the same
        # on either axis: ±100 offset = 0.25× the height, blur 50 = the height.
        box = self._label.sizeHint()
        sh = self._config.clock.shadow
        off_x = round(sh.offset_x / 400.0 * box.height())
        off_y = round(sh.offset_y / 400.0 * box.height())
        blur = round(sh.blur / 50.0 * box.height())
        if sh.intensity > 0:
            # Kept, not recreated: its setters skip unchanged values.
            shadow = self._card.graphicsEffect()
            if not isinstance(shadow, _AlignedShadow):
                shadow = _AlignedShadow(self._card)
                self._card.setGraphicsEffect(shadow)
            shadow.setBlurRadius(blur)
            # At exactly (0, 0) it draws nothing: a sub-pixel nudge keeps the centered glow.
            if off_x == 0 and off_y == 0:
                shadow.setOffset(0.01, 0.01)
            else:
                shadow.setOffset(off_x, off_y)
            col = QColor(sh.color)
            col.setAlphaF(sh.intensity / 100.0)  # intensity = shadow opacity
            shadow.setColor(col)
        elif self._card.graphicsEffect() is not None:
            self._card.setGraphicsEffect(None)
        # The whole radius: Qt updates that far, and UpdateLayeredWindow fails past the window.
        self._shadow_reach = blur + max(abs(off_x), abs(off_y)) if sh.intensity > 0 else 0

    def _apply_card_style(self) -> None:
        """Background and corners. `corner_radius` is a % of half the box height (100% =
        pill), capped at `box_h // 2`: past half a side Qt draws a square corner, and
        rounding an odd height goes one pixel over."""
        bg = self._config.clock.background
        box_h = self._label.sizeHint().height()
        max_pill = box_h // 2
        radius = min(int(round(bg.corner_radius / 100.0 * (box_h / 2.0))), max_pill)
        tl = radius if bg.round_top_left else 0
        tr = radius if bg.round_top_right else 0
        bl = radius if bg.round_bottom_left else 0
        br = radius if bg.round_bottom_right else 0
        sheet = (
            f"QFrame#clockCard {{"
            f" background-color: {_rgba(bg.color, bg.opacity)};"
            f" border-top-left-radius: {tl}px;"
            f" border-top-right-radius: {tr}px;"
            f" border-bottom-left-radius: {bl}px;"
            f" border-bottom-right-radius: {br}px; }}"
        )
        if sheet != self._card.styleSheet():  # setting one re-polishes the card, even unchanged
            self._card.setStyleSheet(sheet)

    @property
    def _margin(self) -> int:
        """Transparent border: room for the shadow and, in edit mode, for the arrows, which
        can sit over the shadow, so the larger of the two. The shadow gets a
        :meth:`_pixel_step` more, for _AlignedShadow's rounding."""
        shadow = self._shadow_reach + self._pixel_step() if self._shadow_reach else 0
        return max(shadow, GUTTER if self._draggable else 0)

    def _pixel_step(self) -> int:
        """The shortest logical length that is whole physical pixels on the clock's screen:
        1 at 100% and 200%, 2 at 150%, 4 at 125%."""
        return Fraction(self._target_screen().devicePixelRatio()).limit_denominator(16).denominator

    # -- clock ----------------------------------------------------------------
    def _tick(self) -> None:
        self._update_text()
        self._refresh_visibility()
        self._tick_timer.start(max(1, 1000 - QTime.currentTime().msec()))  # next whole second

    def _update_text(self) -> None:
        text = self._config.clock.time_format.render(QDateTime.currentDateTime())
        self._label.set_text(text)
        if self._win_ready and not self._dragging:
            self.reposition()

    # -- window state (win32 + opacity) --------------------------------------
    def _apply_window_state(self) -> None:
        hwnd = win32.get_hwnd(self)
        self._sync_click_through()
        self._sync_activation()
        win32.reassert_topmost(hwnd)
        self._sync_timers()
        if self._draggable:
            self._hover_timer.start()
        else:
            self._hover_timer.stop()
        self.setWindowOpacity(1.0)

    def _sync_activation(self) -> None:
        # A click must not take the foreground from a fullscreen app, whose hidden cursor can
        # sit over a corner clock: only edit mode and the tutorial activate it, and the
        # right-click into edit mode does it by hand.
        if self._win_ready:
            win32.set_no_activate(win32.get_hwnd(self), not (
                self._draggable or self._tutorial_active or self._tutorial_hold))

    def _sync_click_through(self) -> None:
        # A hidden cursor means nobody is aiming at the clock (in a game, right-click to aim
        # toggled edit mode), so clicks go through. That also keeps the app's cursor hidden
        # instead of ours popping up over the clock.
        # Over the shadow too: a layered window takes every click on a pixel that isn't fully
        # transparent.
        if not self._win_ready:
            return
        local = self.mapFromGlobal(QCursor.pos())
        over_shadow = (not self._dragging and self.rect().contains(local)
                       and not self._grab_area().contains(local))
        through = over_shadow or not (
            self._draggable or self._settings_open or self._tutorial_active
            or self._tutorial_hold) and win32.cursor_hidden()
        if through != self._click_through:
            self._click_through = through
            win32.set_click_through(win32.get_hwnd(self), through)

    def pause_topmost(self, paused: bool) -> None:
        """Stop re-claiming topmost while the tray menu or one of our modals is open: a claim
        closes the menu and climbs over the modal. Everything else keeps running."""
        self._topmost_paused = paused
        if not self._win_ready:
            return
        self._sync_timers()
        if not paused:
            self._reassert_topmost()

    def _sync_timers(self) -> None:
        # Click-through and topmost matter only while the clock is on screen; hidden, the
        # whole-second tick is enough to notice when to show it.
        on = self._win_ready and self.isVisible()
        if on:
            self._cursor_timer.start()
        else:
            self._cursor_timer.stop()
        if on and not self._topmost_paused:
            self._reassert.start()
        else:
            self._reassert.stop()

    # -- visibility (fullscreen app vs desktop) ------------------------------
    def _refresh_visibility(self) -> None:
        """Shown only while a fullscreen app has the foreground on its monitor, unless edit
        mode, settings, the tutorial or `show_on_desktop` force it on."""
        if not self._win_ready:
            return
        if self._blackout:
            want = False  # wins over everything
        elif (self._settings_open or self._draggable or self._show_on_desktop
                or self._tutorial_active or self._tutorial_hold):
            want = True
        else:
            # Qt keeps a screen's top-left in physical pixels, the point Windows wants.
            origin = self._target_screen().geometry().topLeft()
            want = win32.is_fullscreen_app(
                win32.get_hwnd(self), (origin.x(), origin.y()), self._config.exclusions)
        if want != self.isVisible():
            if want:
                self._sync_click_through()  # its timer was off while hidden
            self.setVisible(want)
            self._sync_timers()
            if want and not self._topmost_paused:
                self.bring_to_front()

    def _on_fg_changed(self, *_) -> None:
        """WinEvent callback: a window took the foreground."""
        self._reassert_topmost()

    def _reassert_topmost(self) -> None:
        # Not while paused or a Qt popup is open: restacking closes it.
        if self._win_ready and not self._topmost_paused and QApplication.activePopupWidget() is None:
            win32.reassert_topmost(win32.get_hwnd(self))

    # -- positioning ----------------------------------------------------------
    def _target_screen(self):
        screen = monitors.screen_for(self._config.clock.position.monitor.id)
        return screen or QGuiApplication.screens()[0]  # [0] is the primary

    def target_screen(self):
        """The screen the clock is configured for."""
        return self._target_screen()

    def target_geometry(self):
        """The full-screen rectangle the position is relative to."""
        return self._screen_geom(self._target_screen())

    def fraction_at(self, card_tl: QPoint) -> tuple[float, float]:
        """The (x, y) that places the card's top-left at *card_tl* on the clock's monitor."""
        geom = self._screen_geom(self._target_screen())
        return positioning.fraction_for(geom, self.card_global_rect().size(), card_tl)

    def set_position_live(self, x: float, y: float) -> None:
        """Set the position and reposition, without restyling: cheap enough for every
        frame of a glide. Changes only this window's copy of the config."""
        p = self._config.clock.position
        p.x, p.y = x, y
        self.reposition()

    def bring_to_front(self) -> None:
        """Raise and re-claim topmost, above our own windows too."""
        self.raise_()
        if self._win_ready:
            win32.reassert_topmost(win32.get_hwnd(self))

    def _screen_geom(self, screen):
        return screen.geometry()  # the full screen, taskbar included

    def _monitor_at(self, card_rect: QRect):
        """The screen under the card's center, and the Monitor that names it."""
        screen = QGuiApplication.screenAt(card_rect.center()) or self._target_screen()
        return screen, Monitor(monitors.id_of(screen), screen.name())

    @staticmethod
    def _edge_is_wall(screen, side: str, along: int) -> bool:
        """True when *side* of *screen* has no other monitor beyond it at *along* (y for
        left/right, x for top/bottom): the clock is clamped there instead of crossing."""
        g = screen.geometry()
        if side == "left":
            probe = QPoint(g.left() - 2, along)
        elif side == "right":
            probe = QPoint(g.right() + 2, along)
        elif side == "top":
            probe = QPoint(along, g.top() - 2)
        else:  # bottom
            probe = QPoint(along, g.bottom() + 2)
        other = QGuiApplication.screenAt(probe)
        return other is None or other is screen

    def reposition(self) -> None:
        """Put the card (not the window, which carries the transparent border) at its saved
        position."""
        if self._dragging:
            return
        card = self._label.sizeHint()  # the card is the label, no inner margins
        screen = self._target_screen()
        geom = self._screen_geom(screen)
        if self._tutorial_active:
            # Tutorial intro: dead center, whatever the saved position.
            card_tl = QPoint(geom.x() + (geom.width() - card.width()) // 2,
                             geom.y() + (geom.height() - card.height()) // 2)
        else:
            pos = self._config.clock.position
            card_tl = positioning.topleft_for(geom, card, pos.x, pos.y)
        rect = self._window_rect(geom, card_tl, card)
        if self._frozen_rect is not None:
            # In the goodbye (see freeze_geometry) the rect only grows, but another monitor starts
            # a new one: a union across monitors is drawn at one of their scales.
            if self._frozen_grow_only and screen is self._frozen_screen:
                rect = rect.united(self._frozen_rect)
            self._frozen_rect = rect
            self._frozen_screen = screen
        margins = QMargins(
            card_tl.x() - rect.x(),
            card_tl.y() - rect.y(),
            rect.x() + rect.width() - (card_tl.x() + card.width()),
            rect.y() + rect.height() - (card_tl.y() + card.height()))
        # Only a new size or card spot changes the image: a plain move can keep the old one.
        reshaped = rect.size() != self.size() or margins != self._outer.contentsMargins()
        self._outer.setContentsMargins(margins)
        self._card.setFixedSize(card)
        self._placed_size = rect.size()
        shadow = self._card.graphicsEffect()
        if isinstance(shadow, _AlignedShadow):
            shadow.set_step(self._pixel_step())  # here, so a scale change reaches it too
        if self.geometry() == rect:
            self._lay_out()
            return
        if reshaped and self.testAttribute(Qt.WidgetAttribute.WA_Mapped):
            # Laid out at the new size before the window has it, so the image can be drawn first.
            self._outer.setGeometry(QRect(QPoint(0, 0), rect.size()))
            self._arrow_layer.setGeometry(QRect(QPoint(0, 0), rect.size()))
            self._card_layout.activate()
            if self._draggable:
                self._layout_arrows(rect.topLeft())
            if self._show_at_once(rect):
                self.setGeometry(rect)  # already there on screen: Qt just catches up
                self._lay_out()
                return
        self.setGeometry(rect)
        self._lay_out()
        if reshaped and self.testAttribute(Qt.WidgetAttribute.WA_Mapped):
            self.repaint()  # the one-step update failed: at least shorten the stale frame

    def _window_rect(self, geom: QRect, card_tl: QPoint, card: QSize) -> QRect:
        """The card plus the margin, cornered on whole physical pixels of the screen *geom*: a
        half pixel rounds down below zero and up above, so the card would shift a pixel as the
        corner crosses the screen's edge."""
        m = self._margin
        step = self._pixel_step()
        left = geom.x() + (card_tl.x() - m - geom.x()) // step * step
        top = geom.y() + (card_tl.y() - m - geom.y()) // step * step
        return QRect(left, top, card_tl.x() + card.width() + m - left,
                     card_tl.y() + card.height() + m - top)

    def _lay_out(self) -> None:
        """Lay out now, not on the next event: a window that only moved gets no layout pass,
        and the arrows and the wheel read the card's spot."""
        self._outer.activate()
        self._card_layout.activate()
        if self._draggable:
            self._layout_arrows()

    def _show_at_once(self, rect: QRect) -> bool:
        """Draw the window as it will be at *rect*, then hand Windows position, size and image
        together (see :func:`win32.update_layered`)."""
        # Qt's mapping: scaled from the top-left of the screen under the center, the same in
        # both units.
        screen = QGuiApplication.screenAt(rect.center()) or self._target_screen()
        dpr = screen.devicePixelRatio()
        origin = screen.geometry().topLeft()
        x = _round(origin.x() + (rect.x() - origin.x()) * dpr)
        y = _round(origin.y() + (rect.y() - origin.y()) * dpr)
        w, h = _round(rect.width() * dpr), _round(rect.height() * dpr)
        image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        self.render(image, QPoint(), QRegion(0, 0, rect.width(), rect.height()))
        return win32.update_layered(win32.get_hwnd(self), x, y, w, h, int(image.constBits()))

    def freeze_geometry(self, frozen: bool, pos=None) -> None:
        """Track the window rect while settings is open.

        *pos*: the position the clock is about to glide to (the tutorial goodbye), grown
        into the rect now, at rest; from then on the rect only grows, so every frame of the
        glide is a pure repaint. Freezing twice without *pos* does nothing."""
        if not frozen:
            if self._frozen_rect is None:
                return
            self._frozen_rect = None
            self._frozen_screen = None
            self._frozen_grow_only = False
            self.reposition()  # back to the compact window
            return
        if self._frozen_rect is not None and pos is None:
            return
        fr = self._frozen_rect if self._frozen_rect is not None else self.geometry()
        if pos is not None:
            card = self._label.sizeHint()
            geom = self._screen_geom(self._target_screen())
            card_tl = positioning.topleft_for(geom, card, pos.x, pos.y)
            fr = fr.united(self._window_rect(geom, card_tl, card))
        self._frozen_grow_only = pos is not None
        self._frozen_rect = fr  # reposition() sets the margins before growing the window
        self._frozen_screen = self._target_screen()
        self.reposition()

    # -- tutorial -------------------------------------------------------------
    def set_tutorial_active(self, active: bool) -> None:
        """Tutorial intro: centered and forced visible, clicks emitted as
        :attr:`tutorial_left_click` / :attr:`tutorial_right_click`."""
        if active == self._tutorial_active:
            return
        self._tutorial_active = active
        self._sync_activation()
        if self._win_ready:
            self.reposition()
            self._refresh_visibility()

    def set_tutorial_hold(self, hold: bool) -> None:
        """Tutorial move phase: forced visible, edit mode locked on (right-click, Esc and
        click-away can't drop it), draggable; not centered, clicks are normal."""
        if hold == self._tutorial_hold:
            return
        self._tutorial_hold = hold
        self._sync_activation()
        if self._win_ready:
            self._refresh_visibility()

    def set_tutorial_controls(self, arrows: bool, gear: bool) -> None:
        """Whether the arrows and the gear work (wheel, click, hover). They're drawn either
        way, so the tutorial can show them before their step. Both on outside the tutorial."""
        self._tut_arrows_ok = arrows
        self._tut_gear_ok = gear
        self.update()

    def set_blackout(self, on: bool) -> None:
        """Force the clock off whatever else says: the tutorial goodbye, while the style swaps."""
        if on == self._blackout:
            return
        self._blackout = on
        self._refresh_visibility()

    def set_grab_enabled(self, enabled: bool) -> None:
        """Whether a drag moves the clock. When off, the arrows and gear still work and a
        click emits :attr:`clock_clicked`."""
        self._grab_enabled = enabled

    def card_global_rect(self) -> QRect:
        """The card's rect in global coordinates."""
        return QRect(self.mapToGlobal(self._card.geometry().topLeft()), self._card.size())

    # -- settings arrows ------------------------------------------------------
    def _update_hover(self) -> None:
        """In edit mode, light the arrow or gear under the cursor."""
        if self._draggable:
            local = self.mapFromGlobal(QCursor.pos())
            axis = self._axis_at(local) if self._tut_arrows_ok else None
            gear = self._gear_hit.contains(local) if self._tut_gear_ok else False
            if axis != self._active_axis or gear != self._gear_active:
                self._active_axis = axis
                self._gear_active = gear
                self.update()

    def _layout_arrows(self, origin: QPoint | None = None) -> None:
        """Arrows and gear in the gutter, on the card's sides facing the screen center.
        *origin*: where the window is about to be, when it isn't there yet."""
        if not self._draggable:
            return
        card = self._card.geometry()
        if card.width() <= 0 or card.height() <= 0:
            return
        center = (origin if origin is not None else self.geometry().topLeft()) + card.center()
        screen = QGuiApplication.screenAt(center) or self._target_screen()
        sc = self._screen_geom(screen).center()
        self._side_v = "right" if center.x() < sc.x() else "left"
        self._side_h = "bottom" if center.y() < sc.y() else "top"
        side_v, side_h = self._side_v, self._side_h
        g, apad = GUTTER, 6

        # As long as the card edge, but not below the minimum: then centered, overhanging
        # into the empty corner of the gutter.
        vcy = (card.top() + card.bottom()) // 2
        vlen = max(card.height() - 2 * apad, ARROW_MIN_V)
        vx = card.left() - g // 2 if side_v == "left" else card.right() + g // 2
        self._v_line = (vx, vcy - vlen // 2, vx, vcy + vlen // 2)
        self._v_hit = QRect(vx - g // 2, vcy - vlen // 2, g, vlen)

        hcx = (card.left() + card.right()) // 2
        hlen = max(card.width() - 2 * apad, ARROW_MIN)
        hy = card.top() - g // 2 if side_h == "top" else card.bottom() + g // 2
        self._h_line = (hcx - hlen // 2, hy, hcx + hlen // 2, hy)
        self._h_hit = QRect(hcx - hlen // 2, hy - g // 2, hlen, g)

        # On the exact crossing: QRect.center() rounds 1 px up-left.
        self._gear_center = QPoint(vx, hy)
        self._gear_hit = QRect(0, 0, g, g)
        self._gear_hit.moveCenter(self._gear_center)
        self.update()

    def _grab_area(self) -> QRect:
        """What takes clicks, in window coordinates: the card, plus the arrow gutter in edit
        mode."""
        card = self._card.geometry()
        return card.adjusted(-GUTTER, -GUTTER, GUTTER, GUTTER) if self._draggable else card

    def _axis_at(self, point: QPoint) -> str | None:
        if self._v_hit.contains(point):
            return "y"
        if self._h_hit.contains(point):
            return "x"
        return None

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        # Alpha 1: invisible, yet it takes clicks at any background opacity.
        painter.fillRect(self._grab_area(), QColor(0, 0, 0, 1))

    def _paint_arrows(self, painter: QPainter) -> None:
        """The arrows and gear, for :class:`_ArrowLayer`."""
        if not self._draggable or self._v_line is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        lit = accent()
        y_active = self._active_axis == "y" or "y" in self._scroll_axes
        x_active = self._active_axis == "x" or "x" in self._scroll_axes
        self._draw_arrow(painter, self._v_line, True, y_active, lit)
        self._draw_arrow(painter, self._h_line, False, x_active, lit)
        on = self._gear_active
        if self._settings_open:
            self._draw_close(painter, lit if on else ARROW_IDLE, on)
        else:
            size = GEAR_SIZE + 2 if on else GEAR_SIZE  # grows like a lit arrow
            pm = self._gear_pixmap(lit if on else ARROW_IDLE, size)
            painter.drawPixmap(self._gear_center - QPoint(size // 2, size // 2), pm)

    def _draw_close(self, painter: QPainter, color: QColor, active: bool) -> None:
        """The × in the gear's place, stroked like the arrows."""
        width = 3 if active else 2
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        c = QPointF(self._gear_center)
        h = (CLOSE_SIZE + (2 if active else 0) - width) / 2  # the round caps add the rest
        painter.drawLine(c + QPointF(-h, -h), c + QPointF(h, h))
        painter.drawLine(c + QPointF(-h, h), c + QPointF(h, -h))

    @staticmethod
    def _draw_arrow(painter, line, vertical, active, active_color) -> None:
        pen = QPen(active_color if active else ARROW_IDLE, 3 if active else 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        a, b, c, d = line
        length = abs(d - b) if vertical else abs(c - a)
        head = min(7 if active else 6, length // 3)
        if vertical:
            x, y1, _, y2 = a, b, c, d
            painter.drawLine(x, y1, x, y2)
            painter.drawLine(x, y1, x - head, y1 + head)
            painter.drawLine(x, y1, x + head, y1 + head)
            painter.drawLine(x, y2, x - head, y2 - head)
            painter.drawLine(x, y2, x + head, y2 - head)
        else:
            x1, y, x2, _ = a, b, c, d
            painter.drawLine(x1, y, x2, y)
            painter.drawLine(x1, y, x1 + head, y - head)
            painter.drawLine(x1, y, x1 + head, y + head)
            painter.drawLine(x2, y, x2 - head, y - head)
            painter.drawLine(x2, y, x2 - head, y + head)

    def _gear_pixmap(self, color: QColor, size: int) -> QPixmap:
        """The gear SVG recolored like the arrows, *size* px wide."""
        dpr = self.devicePixelRatioF()
        key = (color.rgba(), size, dpr)
        pm = self._gear_cache.get(key)
        if pm is not None:
            return pm
        svg = resource_path("resources", "settings.svg").read_text(encoding="latin-1")
        fill = f'fill="rgb({color.red()},{color.green()},{color.blue()})" fill-opacity="{color.alphaF():.3f}"'
        renderer = QSvgRenderer(QByteArray(svg.replace("<path ", f"<path {fill} ", 1).encode()))
        pm = QPixmap(round(size * dpr), round(size * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(p)
        p.end()
        pm.setDevicePixelRatio(dpr)
        self._gear_cache[key] = pm
        return pm

    # -- edit mode: drag / wheel / gear --------------------------------------
    @property
    def is_snapped(self) -> bool:
        """Flush to a border or on an anchor point, as of the last drag."""
        return self._snap_state in ("edge", "anchor")

    @property
    def arrow_side_h(self) -> str | None:
        """Side of the horizontal arrow ('top' / 'bottom'), None when not draggable."""
        return self._side_h if self._draggable else None

    def set_draggable(self, draggable: bool) -> None:
        if draggable == self._draggable:
            return
        was_dragging = self._dragging and self._drag_moved
        self._draggable = draggable
        self._dragging = False
        self._active_axis = None
        self._scroll_axes = set()
        if draggable:
            self._grab_enabled = True  # the tutorial revokes it per step
            # From the saved position: grabbing a clock already snapped must not tic.
            self._snap_state = self._position_snap_state()
        if self._win_ready:
            self._apply_window_state()
            self.reposition()
            self._refresh_visibility()
        if draggable:
            self._layout_arrows()
            self.setFocus()  # so Esc reaches keyPressEvent
            QTimer.singleShot(0, haptics.prewarm)
        else:
            self._gear_active = False
        self.update()  # the arrows come or go even when the window keeps its size
        if was_dragging:
            # The release won't count as a drop any more: end the drag here, or the guide stays up.
            self.drag_ended.emit()
            self._restake_topmost_soon()

    def notify_settings_open(self, open_: bool) -> None:
        """Settings opened or closed. While open, click-away and Esc keep edit mode, and the
        window is frozen: style edits are the only thing that resizes the clock."""
        self._settings_open = open_
        self.freeze_geometry(open_)
        self.update()  # gear or ×

    def event(self, e) -> bool:
        # Click-away leaves edit mode, unless settings takes over or the tutorial holds it.
        if (e.type() == QEvent.Type.WindowDeactivate and self._draggable
                and not self._settings_open and not self._tutorial_hold):
            QTimer.singleShot(0, self._exit_edit_on_deactivate)
        return super().event(e)

    def _exit_edit_on_deactivate(self) -> None:
        if self._draggable and not self._settings_open and not self._tutorial_hold:
            self.set_draggable(False)

    def keyPressEvent(self, event) -> None:
        if (event.key() == Qt.Key.Key_Escape and self._draggable
                and not self._settings_open and not self._tutorial_hold):
            self.set_draggable(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._tutorial_active:
            if event.button() == Qt.MouseButton.LeftButton:
                self.tutorial_left_click.emit()
            elif event.button() == Qt.MouseButton.RightButton:
                self.tutorial_right_click.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton and not self._dragging:
            # Toggles edit mode; leaving it with settings open closes them.
            if self._tutorial_hold:
                event.accept()  # move phase: edit mode stays on
                return
            if self._settings_open:
                self.settings_close_requested.emit()
            else:
                self.set_draggable(not self._draggable)
                if self._draggable:
                    self.activateWindow()  # for Esc and click-away (see _sync_activation)
            event.accept()
            return
        if self._tutorial_hold and not self._draggable and event.button() == Qt.MouseButton.LeftButton:
            # Move phase before the unlock: a click advances, like the bubble. Not draggable,
            # so no drag would report it.
            self.clock_clicked.emit()
            event.accept()
            return
        if self._draggable and event.button() == Qt.MouseButton.LeftButton:
            if self._tut_gear_ok and self._gear_hit.contains(event.position().toPoint()):
                if self._settings_open:
                    self.settings_close_requested.emit()
                else:
                    self.settings_requested.emit()
                event.accept()
                return
            if not self._grab_enabled:
                self.clock_clicked.emit()
                event.accept()
                return
            self._dragging = True
            self._drag_moved = False
            self._drag_grab = event.globalPosition().toPoint() - self.pos()
            # _snap_state is not reseeded: it carries the magnetization across drags and
            # fine-tunes, so re-attaching a fine-tuned clock tics.
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        if not self._drag_moved:
            self._drag_moved = True
            self.drag_started.emit()  # on the first real move
        window_tl = event.globalPosition().toPoint() - self._drag_grab
        off = self._card.geometry().topLeft()  # not the uniform margin while frozen
        card = self._card.geometry().size()
        card_x, card_y = window_tl.x() + off.x(), window_tl.y() + off.y()
        card_rect = QRect(card_x, card_y, card.width(), card.height())
        # Position relative to the monitor the clock is on now.
        screen, monitor = self._monitor_at(card_rect)
        geom = self._screen_geom(screen)
        # 1) Anchor points pull hardest: both axes snap.
        magnet = positioning.anchor_under_rect(geom, card_rect, POINT_SNAP_TOLERANCE)
        if magnet is not None:
            x, y = magnet
            tl = positioning.topleft_for(geom, card, x, y)
            self.move(tl.x() - off.x(), tl.y() - off.y())
            snap_state = "anchor"
        else:
            # 2) Outer borders are walls (one shared with another monitor can be crossed),
            #    then each axis snaps flush.
            gx, gy = geom.x(), geom.y()
            gr, gb = gx + geom.width() - card.width(), gy + geom.height() - card.height()
            cxc, cyc = card_rect.center().x(), card_rect.center().y()
            cx, cy = card_x, card_y
            if cx < gx and self._edge_is_wall(screen, "left", cyc):
                cx = gx
            elif cx > gr and self._edge_is_wall(screen, "right", cyc):
                cx = gr
            if cy < gy and self._edge_is_wall(screen, "top", cxc):
                cy = gy
            elif cy > gb and self._edge_is_wall(screen, "bottom", cxc):
                cy = gb
            edge = positioning.edge_snap(geom, card, QPoint(cx, cy), EDGE_SNAP_TOLERANCE)
            if edge is not None:
                x, y = edge
                tl = positioning.topleft_for(geom, card, x, y)
                self.move(tl.x() - off.x(), tl.y() - off.y())
                snap_state = "edge"
            else:
                # 3) Free, inside the walls.
                self.move(cx - off.x(), cy - off.y())
                x, y = positioning.fraction_for(geom, card, QPoint(cx, cy))
                snap_state = "free"
        pos = self._config.clock.position
        pos.monitor, pos.x, pos.y = monitor, x, y
        self._layout_arrows()
        self.position_changed.emit(monitor, x, y, positioning.snapped_edges(x, y))
        self.edge_glow.emit(self._edge_glow(geom, card))
        self._update_snap_haptic(snap_state)
        self._reassert_topmost()  # a move can lose topmost against the taskbar
        event.accept()

    def _position_snap_state(self) -> str:
        """Snap state of the saved position: on an anchor point, flush to a border, or free."""
        pos = self._config.clock.position
        if (pos.x, pos.y) in positioning.ANCHORS:
            return "anchor"
        return "edge" if positioning.snapped_edges(pos.x, pos.y) else "free"

    def _update_snap_haptic(self, state: str) -> None:
        """Tic on reaching an anchor point, or a border from a free state; never while
        sliding along a border already stuck to."""
        if state == "anchor" and self._snap_state != "anchor":
            haptics.snap_pulse()
        elif state == "edge" and self._snap_state == "free":
            haptics.snap_pulse()
        self._snap_state = state

    def _edge_glow(self, geom, card) -> dict:
        """Per-border `(intensity, along)` of the placed card. *intensity*: 1.0 flush, down
        to EDGE_GLOW_MIN at EDGE_GLOW_RANGE, shared monitor borders too. *along*: where the
        clock projects on that border, in the guide's coordinates (x for top/bottom, y for
        left/right)."""
        w, h = card.width(), card.height()
        tlx, tly = self.x() + self._card.x(), self.y() + self._card.y()
        gx, gy, gw, gh = geom.x(), geom.y(), geom.width(), geom.height()
        cxc, cyc = tlx + w // 2, tly + h // 2
        dist = {"top": tly - gy, "bottom": (gy + gh) - (tly + h),
                "left": tlx - gx, "right": (gx + gw) - (tlx + w)}
        along = {"top": cxc - gx, "bottom": cxc - gx, "left": cyc - gy, "right": cyc - gy}
        return {e: (max(EDGE_GLOW_MIN, 1.0 - dist[e] / EDGE_GLOW_RANGE),
                    along[e]) for e in dist}

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            if self._drag_moved:
                self.drag_ended.emit()
                self._restake_topmost_soon()
            else:
                self.clock_clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _restake_topmost_soon(self) -> None:
        """Re-claim topmost a few times over 300 ms: after a drag the taskbar repaints over
        us later, so one re-claim on release comes too early."""
        for delay in (10, 50, 100, 150, 300):
            QTimer.singleShot(delay, self._reassert_topmost)

    def wheelEvent(self, event) -> None:
        dx, dy = event.angleDelta().x(), event.angleDelta().y()
        # Qt flips the horizontal wheel sign of Windows: flip it back, so dx > 0 is the
        # thumbwheel going right, with the user's scroll inversion kept.
        dx = -dx
        # Not while dragging: the drag owns the position.
        if self._draggable and not self._dragging and self._tut_arrows_ok and (dx or dy):
            local = event.position().toPoint()
            axis = self._axis_at(local)
            if axis is None and not self._card.geometry().contains(local):
                super().wheelEvent(event)
                return
            # Over an arrow: that axis, any wheel direction. Over the card: both axes.
            # Decided each notch; the cursor follows the clock, so it stays the same.
            mode = axis or "xy"
            before = self.mapToGlobal(self._card.geometry().topLeft())
            scrolled: set[str] = set()
            # One screen px per notch: wheel up / right moves the clock up / right.
            step_x = step_y = 0
            if mode == "x":
                step_x = 1 if (dy or dx) > 0 else -1
                scrolled = {"x"}
            elif mode == "y":
                step_y = -1 if (dy or dx) > 0 else 1
                scrolled = {"y"}
            else:  # `"xy"` — free 2D over the clock body
                if dx:
                    step_x = 1 if dx > 0 else -1
                    scrolled.add("x")
                if dy:
                    step_y = -1 if dy > 0 else 1
                    scrolled.add("y")
            # No walls, off-screen on purpose; like a drag, the monitor is the one under the center.
            card = self._card.geometry().size()
            tl = before + QPoint(step_x, step_y)
            screen, monitor = self._monitor_at(QRect(tl, card))
            pos = self._config.clock.position
            if screen is not self._target_screen():
                # Only a real crossing: on the primary standing in for a disconnected
                # monitor, the saved one stays.
                pos.monitor = monitor
            pos.x, pos.y = positioning.fraction_for(self._screen_geom(screen), card, tl)
            self.reposition()
            # The cursor follows the card, so the next notch lands on the same spot.
            delta = self.mapToGlobal(self._card.geometry().topLeft()) - before
            if not delta.isNull():
                QCursor.setPos(QCursor.pos() + delta)
            self._scroll_axes = scrolled
            self._scroll_glow.start()
            self.update()
            self.position_changed.emit(pos.monitor, pos.x, pos.y,
                                       positioning.snapped_edges(pos.x, pos.y))
            self.finetuned.emit()
            # Even if still flush: dragging back onto the border tics again.
            self._snap_state = "free"
            event.accept()
            return
        super().wheelEvent(event)

    def _end_scroll_glow(self) -> None:
        self._scroll_axes = set()
        self.update()
