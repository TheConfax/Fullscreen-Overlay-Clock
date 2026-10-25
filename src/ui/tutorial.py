"""First-run tutorial: a flat list of steps, all-or-nothing (`system.tutorial.completed`)."""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt, QPoint, QRect, QObject, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..models.config import Clock, Text
from ..services.fonts import bubble_font_family
from ..i18n import S
from .dialogs import ConfirmDialog
from .clock import ARROW_PROTRUSION
from .style import DESTRUCTIVE_RED, callout_colors, is_dark

_HINT_DELAY_MS = 3000     # idle on a click step before the hint shows
_FINETUNE_IDLE_MS = 300   # no-scroll gap that ends the fine-tune step
_FINETUNE_MAX_MS = 2000   # cap on the fine-tune step
_FINETUNE_HOLD_MS = 500   # pause at the fine-tuned spot before gliding to park
# Before the skip link shows: a new user reads the first line first, a restart has seen it.
_SKIP_DELAY_FIRSTRUN_MS = 8000
_SKIP_DELAY_RESTART_MS = 0

_BUBBLE_GAP = 10  # px between the clock and the bubble
_HINT_GAP = 14    # px between the clock and the hint
_STACK_GAP = 6    # px between the bubble and a hint stacked past it
_EDGE = 8         # px kept clear of the screen's edges


def _pixel_font(size: int) -> QFont | None:
    """Pixeloid at *size*, None if it failed to load. No antialiasing: it smears the pixel edges."""
    family = bubble_font_family()
    if not family:
        return None
    font = QFont(family, size)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    return font


def _stack(clock: QRect, screen: QRect | None, bubble: QSize, hint: QSize | None,
           arrow_side: str | None) -> tuple[QPoint, QPoint | None]:
    """Where the bubble and the hint go: the bubble above the clock, below if there's no room;
    the hint on the other side, past the bubble if that side has no room either. Each clears
    the fine-tune arrow on the side it ends up on."""
    def clear(side: str) -> int:
        return ARROW_PROTRUSION if arrow_side == side else 0

    def above(height: int, gap: int) -> int:
        return clock.top() - gap - clear("top") - height

    def below(gap: int) -> int:
        return clock.bottom() + gap + clear("bottom")

    def fits(y: int, height: int) -> bool:
        return screen is None or (y >= screen.top() + _EDGE
                                  and y + height <= screen.bottom() - _EDGE)

    def x_for(width: int) -> int:
        x = clock.center().x() - width // 2
        if screen is None:
            return x
        return max(screen.left() + _EDGE, min(x, screen.right() - width - _EDGE))

    bubble_y = above(bubble.height(), _BUBBLE_GAP)
    bubble_up = fits(bubble_y, bubble.height())
    if not bubble_up:
        bubble_y = below(_BUBBLE_GAP)
    bubble_pos = QPoint(x_for(bubble.width()), bubble_y)
    if hint is None:
        return bubble_pos, None
    hint_y = below(_HINT_GAP) if bubble_up else above(hint.height(), _HINT_GAP)
    if not fits(hint_y, hint.height()):
        hint_y = (bubble_y - _STACK_GAP - hint.height() if bubble_up
                  else bubble_y + bubble.height() + _STACK_GAP)
    return bubble_pos, QPoint(x_for(hint.width()), hint_y)


def _paint_callout(widget: QWidget, radius: int) -> None:
    """The translucent rounded background of the bubble, the hint and the skip link."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    fill, border = callout_colors(is_dark())
    painter.setBrush(fill)
    painter.setPen(QPen(border, 1))
    painter.drawRoundedRect(widget.rect().adjusted(0, 0, -1, -1), radius, radius)


def load_tutorial_clock() -> Clock:
    """The clock style during the tutorial: the default, bigger."""
    default = Clock()
    return replace(default, text=replace(default.text, font_size=Text().font_size + 17))


class TutorialBubble(QWidget):
    """Rounded callout above the clock with the step's line; a left-click emits `clicked`."""

    clicked = pyqtSignal()

    _PAD = 16
    _RADIUS = 12
    _MAX_W = 300

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(self._MAX_W)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        font = _pixel_font(10)
        if font:
            self._label.setFont(font)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(self._PAD, self._PAD, self._PAD, self._PAD)
        lay.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)  # set_text sizes the window
        lay.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
        # Width from the widest line: sizeHint() still carries the previous step's fixed width.
        fm = self._label.fontMetrics()
        longest = max((fm.horizontalAdvance(line) for line in text.split("\n")), default=0)
        width = min(longest + 1, self._MAX_W)
        self._label.setFixedWidth(width)
        # Height at the real width, in one go. sizeHint() guesses a wrapped label's height at
        # another width, so the window grew twice and Qt warned "Unable to set geometry".
        self.setFixedSize(width + 2 * self._PAD, self._label.heightForWidth(width) + 2 * self._PAD)

    def refit(self) -> None:
        """Measure the text again: after a scale change the old size clips it."""
        self.set_text(self._label.text())

    def paintEvent(self, event) -> None:
        _paint_callout(self, self._RADIUS)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class TutorialHint(QWidget):
    """Caption under the clock ("Click to continue…"). Clicks pass through to the clock."""

    _PAD_X = 12
    _PAD_Y = 6
    _RADIUS = 10

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._label = QLabel(self)
        font = _pixel_font(9)
        if font:
            self._label.setFont(font)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(self._PAD_X, self._PAD_Y, self._PAD_X, self._PAD_Y)
        lay.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
        self.adjustSize()

    def paintEvent(self, event) -> None:
        _paint_callout(self, self._RADIUS)


class TutorialSkip(TutorialHint):
    """The "Skip tutorial" link on the bubble's top-right corner, first line only. Unlike the
    hint it takes clicks; red like the Reset group."""

    clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label.setStyleSheet(f"color: {DESTRUCTIVE_RED};")
        self.set_text(S.tutorial.skip)

    def place_on_bubble(self, bubble_rect: QRect) -> None:
        """Flush on the bubble's top-right corner; on the bottom-right when there's no room above."""
        self.adjustSize()
        x = bubble_rect.right() - self.width() + 1  # right() is the last pixel, hence +1
        y = bubble_rect.top() - self.height()
        screen = QGuiApplication.screenAt(bubble_rect.center())
        if screen is not None:
            g = screen.geometry()
            x = max(g.left() + 8, min(x, g.right() - self.width() - 8))
            if y < g.top() + 8:
                y = bubble_rect.bottom() + 1
        self.move(x, y)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class _Step:
    """One line of the tutorial and what advances it. `advance` tags: `"click"` (clock or
    bubble), `"unlock"` (right-click), `"snap"` (drop flush to a border), `"tray"` (settings
    from the tray)."""

    def __init__(self, text: str, advance: set[str], on_enter=None,
                 late=None, arm_on=None, finetune=False, close_exits_edit=False) -> None:
        self.text = text
        self.advance = advance
        self.on_enter = on_enter
        # (delay_ms, hint_text): after delay_ms idle the hint shows, and only then a click advances.
        self.late = late
        # `"cog"` or `"tray"`: opening settings from there arms the click and its hint.
        self.arm_on = arm_on
        # Scrolling never advances; the step ends when scrolling stops or at the cap.
        self.finetune = finetune
        # Closing the preview also leaves edit mode.
        self.close_exits_edit = close_exits_edit


class TutorialController(QObject):
    """Runs the steps. The clock starts centered and forced visible; from the unlock step on it
    is draggable. Config, settings, tray and autostart belong to *host*, the controller."""

    STEP_INTRO = "intro"  # clock centered, before the unlock
    STEP_MOVE = "move"    # clock unlocked and draggable

    def __init__(self, clock, host) -> None:
        super().__init__()
        self._clock = clock
        self._host = host
        self._phase: str | None = None
        self._steps: list[_Step] = []
        self._index = 0
        self._bubble: TutorialBubble | None = None
        self._hint: TutorialHint | None = None
        self._skip: TutorialSkip | None = None
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(_HINT_DELAY_MS)
        self._hint_timer.timeout.connect(self._reveal_hint)
        self._skip_delay = _SKIP_DELAY_FIRSTRUN_MS
        self._skip_timer = QTimer(self)
        self._skip_timer.setSingleShot(True)
        self._skip_timer.timeout.connect(self._reveal_skip)
        # Fine-tune step: ends when scrolling stops or at the cap; _ft_settling guards the
        # hold → park → advance.
        self._ft_idle = QTimer(self)
        self._ft_idle.setSingleShot(True)
        self._ft_idle.setInterval(_FINETUNE_IDLE_MS)
        self._ft_idle.timeout.connect(self._finetune_done)
        self._ft_max = QTimer(self)
        self._ft_max.setSingleShot(True)
        self._ft_max.setInterval(_FINETUNE_MAX_MS)
        self._ft_max.timeout.connect(self._finetune_done)
        self._ft_settling = False
        # The arrows' side after a `close_exits_edit` step hid them: the bubble keeps clear of
        # it until the next step, instead of dropping toward the clock.
        self._kept_arrow_side: str | None = None
        clock.tutorial_left_click.connect(self._on_click)
        clock.tutorial_right_click.connect(self._on_right_click)
        clock.clock_clicked.connect(self._on_click)
        clock.finetuned.connect(self.on_finetuned)
        clock.geometry_changed.connect(self.reposition_bubble)

    # --- state the controller reads ------------------------------------------
    @property
    def active(self) -> bool:
        return self._phase is not None

    @property
    def in_move(self) -> bool:
        return self._phase == self.STEP_MOVE

    # --- lifecycle -----------------------------------------------------------
    def start(self, first_run: bool = True) -> None:
        """From the first line, every gated control off. *first_run* (not a restart) only
        delays the skip link."""
        self._skip_delay = _SKIP_DELAY_FIRSTRUN_MS if first_run else _SKIP_DELAY_RESTART_MS
        self._phase = self.STEP_INTRO
        self._clock.set_tutorial_controls(False, False)  # arrows + gear hidden until their steps
        self._steps = [
            _Step(S.tutorial.step1, {"click"}),
            _Step(S.tutorial.step2, {"unlock"}),
            _Step(S.tutorial.step3, {"snap"}),
            _Step(S.tutorial.step4, set(), self._enter_nice),
            _Step(S.tutorial.step5, set(), self._enter_arrows, finetune=True,
                  late=(10000, S.tutorial.no_scroll_hint)),  # no wheel: a click after 10s
            _Step(S.tutorial.step6, set(), self._enter_gear, arm_on="cog"),
            _Step(S.tutorial.step7, {"tray"}, self._enter_tray),
            _Step(S.tutorial.step8, {"click"}, self._enter_settings_preview, close_exits_edit=True),
            _Step(S.tutorial.step9, {"click"}),
        ]
        self._bubble = TutorialBubble()
        self._bubble.clicked.connect(self._on_click)
        self._hint = TutorialHint()
        self._skip = TutorialSkip()
        self._skip.clicked.connect(self._on_skip)
        self._goto(0)

    # --- step transitions ----------------------------------------------------
    def _goto(self, index: int) -> None:
        self._ft_idle.stop()
        self._ft_max.stop()
        self._ft_settling = False
        self._kept_arrow_side = None
        self._index = index
        self._show_current()
        step = self._steps[index]
        if step.on_enter is not None:
            step.on_enter()
        self.reposition_bubble()  # on_enter may have toggled the arrows
        self._arm_hint()

    def _arm_hint(self) -> None:
        """Restart the idle timers: the skip on the first line, the hint on click steps (a
        `late` step uses its own delay)."""
        if self._hint is not None:
            self._hint.hide()
        if self._skip is not None:
            self._skip.hide()
        self._hint_timer.stop()
        self._skip_timer.stop()
        if not self._steps:
            return
        if self._index == 0:
            self._skip_timer.start(self._skip_delay)
        step = self._steps[self._index]
        if step.late is not None:
            self._hint_timer.start(step.late[0])
        elif "click" in step.advance:
            self._hint_timer.start(_HINT_DELAY_MS)

    def _reveal_hint(self) -> None:
        if self._hint is None or not self._steps:
            return
        step = self._steps[self._index]
        if step.late is not None:
            step.advance.add("click")  # only now does a click advance
            text = step.late[1]
        elif "click" in step.advance:
            text = S.tutorial.click_hint
        else:
            return
        self._show_hint(text)

    def _reveal_skip(self) -> None:
        if self._skip is None or self._bubble is None:
            return
        self._skip.place_on_bubble(self._bubble.geometry())
        self._skip.show()
        self._skip.raise_()

    def _show_current(self) -> None:
        if self._bubble is None:
            return
        self._bubble.set_text(self._steps[self._index].text)
        self.reposition_bubble()
        self._bubble.show()
        self._bubble.raise_()

    def _advance(self, keep_settings: bool = False) -> None:
        if not keep_settings:
            self._host.close_settings()
        if self._index + 1 < len(self._steps):
            self._goto(self._index + 1)
        else:
            self._finish()

    def _finish(self) -> None:
        self._phase = None
        self._steps = []
        self._hint_timer.stop()
        self._skip_timer.stop()
        for w in (self._bubble, self._hint, self._skip):
            if w is not None:
                w.hide()
                w.deleteLater()
        self._bubble = self._hint = self._skip = None
        self._host.finish_tutorial()

    # --- per-step enter actions ---------------------------------------------
    def _enter_arrows(self) -> None:
        self._clock.set_tutorial_controls(True, False)
        self._clock.set_grab_enabled(False)  # teach scroll, not drag

    def _enter_gear(self) -> None:
        self._clock.set_tutorial_controls(False, True)

    def _enter_tray(self) -> None:
        # The clock fades out "into the tray", now the only way in.
        self._clock.set_draggable(False)
        self._clock.set_tutorial_controls(False, False)
        self._host.enable_tray()
        self._host.dissolve_clock()

    def _enter_settings_preview(self) -> None:
        # Settings from the tray are still open: the clock comes back, draggable; the cog and
        # the tray's Settings item stay off.
        self._host.restore_clock()
        self._host.disable_tray()
        self._clock.set_draggable(True)
        self._clock.set_tutorial_controls(True, False)

    def _enter_nice(self) -> None:
        # 0.8s at the border, slide to park, 0.8s more; no input.
        QTimer.singleShot(800, self._nice_park)

    def _nice_park(self) -> None:
        self._host.park_clock(lambda: QTimer.singleShot(800, self._advance))

    def _pin_where_shown(self) -> None:
        """Lift the intro's center-lock where the clock is drawn now, so a drag or the goodbye
        glide starts from there and not from the saved position."""
        clock = self._clock
        clock.set_position_live(*clock.fraction_at(clock.card_global_rect().topLeft()))
        clock.set_tutorial_hold(True)  # still forced visible once the lock goes
        clock.set_tutorial_active(False)

    def _enter_move_mode(self) -> None:
        """The unlock gesture: free the clock from the center-lock, then make it draggable."""
        self._pin_where_shown()
        self._clock.set_tutorial_controls(False, False)
        self._clock.set_draggable(True)
        self._phase = self.STEP_MOVE

    # --- input the controller / clock routes here ----------------------------
    def _on_click(self) -> None:
        if self._ft_settling:  # the glide to park advances on its own
            return
        if self._steps and "click" in self._steps[self._index].advance:
            self._advance()

    def _on_skip(self) -> None:
        """Confirmed, it exits like the last step does: goodbye, style, autostart, `completed`."""
        if not self._steps or self._bubble is None:
            return
        # The clock reclaims topmost on every foreground change, the modal's included.
        self._clock.pause_topmost(True)
        try:
            ok = ConfirmDialog.ask(self._bubble, S.tutorial.modals.skip.title,
                                   S.tutorial.modals.skip.body, S.tutorial.modals.skip.ok,
                                   S.tutorial.modals.skip.cancel, topmost=True)
        finally:
            self._clock.pause_topmost(False)
        if not ok:
            return
        self._pin_where_shown()  # the goodbye can't glide under the center-lock
        self._finish()

    def _on_right_click(self) -> None:
        if self._steps and "unlock" in self._steps[self._index].advance:
            self._enter_move_mode()
            self._advance()

    def on_drag_ended(self) -> None:
        """On the snap step, a drop flush to a border advances; leaving the step makes a second
        drop a no-op."""
        if not self._steps or "snap" not in self._steps[self._index].advance:
            return
        if not self._clock.is_snapped:
            return
        self._advance()

    def on_finetuned(self) -> None:
        """A scroll on the fine-tune step never advances: the first starts the cap, each one
        restarts the idle timer."""
        if not self._steps:
            return
        step = self._steps[self._index]
        if not step.finetune or self._ft_settling:
            return
        # There is a wheel: the no-wheel hint and its click go.
        self._hint_timer.stop()
        step.advance.discard("click")
        if self._hint is not None:
            self._hint.hide()
        if not self._ft_max.isActive():
            self._ft_max.start()
        self._ft_idle.start()

    def _finetune_done(self) -> None:
        """Freeze the arrows, hold a beat, glide to park and advance."""
        if self._ft_settling:
            return
        self._ft_settling = True
        self._ft_idle.stop()
        self._ft_max.stop()
        self._clock.set_tutorial_controls(False, False)
        QTimer.singleShot(_FINETUNE_HOLD_MS,
                          lambda: self._host.park_clock(self._advance, nudged=True))

    def on_settings_requested(self, source: str) -> None:
        """Settings asked from the cog or the tray. A source in `advance` opens the preview
        and moves on with it open; the step's `arm_on` source opens it and arms the click,
        its hint after the usual delay."""
        if not self._steps:
            return
        step = self._steps[self._index]
        if source in step.advance:
            self._host.open_settings_preview()
            self._advance(keep_settings=True)
            return
        if step.arm_on == source:
            self._host.open_settings_preview()
            if "click" not in step.advance:
                step.advance.add("click")
                self._hint_timer.start(_HINT_DELAY_MS)

    def on_settings_closed(self) -> None:
        """The preview closed. On a `close_exits_edit` step that leaves edit mode; an armed
        click shows its hint now instead of after the delay."""
        if not self._steps:
            return
        step = self._steps[self._index]
        if step.close_exits_edit:
            self._kept_arrow_side = self._clock.arrow_side_h
            self._clock.set_draggable(False)
            self._clock.set_tutorial_controls(False, False)
        if "click" in step.advance and self._hint_timer.isActive():
            self._hint_timer.stop()
            self._show_hint(S.tutorial.click_hint)

    def _show_hint(self, text: str) -> None:
        if self._hint is None:
            return
        self._hint.set_text(text)
        self._layout(with_hint=True)
        self._hint.show()
        self._hint.raise_()

    def reposition_bubble(self) -> None:
        if self._bubble is None or self._hint is None:
            return
        self._bubble.refit()
        self._hint.adjustSize()  # the skip link re-measures in place_on_bubble
        self._layout(with_hint=self._hint.isVisible())

    def _layout(self, with_hint: bool) -> None:
        """Bubble, hint and skip link around the clock, placed together so they never overlap."""
        if self._bubble is None:
            return
        clock = self._clock.card_global_rect()
        screen = QGuiApplication.screenAt(clock.center())
        hint = self._hint if with_hint else None
        bubble_pos, hint_pos = _stack(clock, screen.geometry() if screen is not None else None,
                                      self._bubble.size(), hint.size() if hint is not None else None,
                                      self._clock.arrow_side_h or self._kept_arrow_side)
        self._bubble.move(bubble_pos)
        if hint is not None and hint_pos is not None:
            hint.move(hint_pos)
        if self._skip is not None and self._skip.isVisible():
            self._skip.place_on_bubble(self._bubble.geometry())
