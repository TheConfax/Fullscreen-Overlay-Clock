"""AppController: owns the config and wires the clock, settings, guide, tray and tutorial."""

from __future__ import annotations

import copy
import math
import signal
import subprocess
import sys
from dataclasses import replace

from PyQt6.QtCore import (
    Qt, QAbstractNativeEventFilter, QEasingCurve, QObject, QPoint, QTimer, QVariantAnimation,
)
from PyQt6.QtGui import QGuiApplication, QIcon

from . import APP_NAME, i18n
from .i18n import S
from .models.config import Clock, Config, Monitor
from .services import startup, win32
from .services.config_store import ConfigStore
from .services.paths import resource_path
from .ui import positioning
from .ui.clock import ClockWindow
from .ui.dialogs import NoticeDialog
from .ui.position_guide import PositionGuide
from .ui.settings_window import SettingsWindow
from .ui.tray import TrayIcon
from .ui.tutorial import TutorialController, load_tutorial_clock

_SAVE_DEBOUNCE_MS = 800

# Tutorial: where the clock parks, and its animation timings.
_SLIDE_PX_PER_S = 1300         # glide to the parking spot
_NUDGE_SLIDE_PX_PER_S = 325    # …after a wheel fine-tune: short, at full speed it's a jump
_FINISH_MS = 900               # goodbye: shrink + glide to the corner
_FINISH_HOLD_MS = 1000         # rest at the corner after the goodbye
_FINISH_BLACKOUT_MS = 500      # clock off while the user's own style is swapped back in
_DISSOLVE_MS = 1000            # fade-out of the whole clock


class _NativeMessageFilter(QAbstractNativeEventFilter):
    """Calls the callback for each Win32 message in *handlers*; never swallows the message."""

    def __init__(self, handlers: dict) -> None:
        super().__init__()
        self._handlers = handlers

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            handler = self._handlers.get(win32.message_id(message))
            if handler is not None:
                handler()
        return False, 0


class AppController(QObject):
    def __init__(self, app) -> None:
        super().__init__()
        self._app = app

        self._store = ConfigStore()
        self._config: Config = self._store.load()
        # Before any window: the builders bake their strings in.
        i18n.set_language(self._config.system.interface.language)

        self._clock = ClockWindow()
        self._settings = SettingsWindow(QGuiApplication.screens)
        self._guide = PositionGuide()
        self._tray = TrayIcon(QIcon(str(resource_path("resources", "icon.ico"))))
        self._tutorial = TutorialController(self._clock, self)
        self._slide_anim: QVariantAnimation | None = None
        self._finish_anim: QVariantAnimation | None = None
        self._dissolve_anim: QVariantAnimation | None = None
        self._onboarding = False  # tutorial or its goodbye running: nothing may be saved
        self._first_run = False  # the genuine first onboarding, not a restart
        self._refusing = False  # the newer-config notice is up
        # Given back after a restarted tutorial.
        self._pre_tutorial_clock = Clock()

        # Debounced, so dragging a slider doesn't hammer the file.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._flush_save)

        self._wire()

    # -- startup and system events --------------------------------------------
    def start(self) -> None:
        if self._store.newer_config:
            # From inside the event loop: before exec(), quit() does nothing.
            QTimer.singleShot(0, self._refuse_newer_config)
            return
        # Ctrl+C on a source run quits like the tray, saving. Otherwise KeyboardInterrupt lands
        # in whatever slot is running and the app carries on.
        signal.signal(signal.SIGINT, lambda *_: self._quit())
        # Kept on self: Qt holds the filter by pointer only.
        self._message_filter = _NativeMessageFilter({
            # Text size and scaling changes (Qt no longer follows the font itself, see main.py).
            win32.WM_SETTINGCHANGE: self._on_setting_change,
            win32.WM_DISPLAYCHANGE: self._refresh_tray_icon,
            win32.WM_DPICHANGED: self._refresh_tray_icon,
            # Explorer rebuilt the taskbar, and Qt re-added the tray icon with its own image.
            win32.TASKBAR_CREATED: lambda: self._refresh_tray_icon(force=True),
            win32.OPEN_SETTINGS: self._on_second_launch,
        })
        self._app.installNativeEventFilter(self._message_filter)
        self._apply_theme()
        # All-or-nothing: an interrupted tutorial replays from the top (nothing is saved until it ends).
        run_tutorial = not self._config.system.tutorial.completed
        self._onboarding = run_tutorial
        if run_tutorial:
            self._first_run = self._config.system.tutorial.firstrun
            self._pre_tutorial_clock = copy.deepcopy(self._config.clock)
            self._clock.set_tutorial_active(True)  # before show: first paint is centered
            self._tray.set_settings_enabled(False)
            self._config.clock = load_tutorial_clock()
            # The tutorial runs on the clock's own monitor.
            self._config.clock.position.monitor = copy.copy(self._pre_tutorial_clock.position.monitor)
            self._clock.apply(self._config)
        else:
            self._clock.apply(self._config)
            if self._config.clock.background.auto_corners:
                pos = self._config.clock.position
                self._apply_auto_corners(positioning.snapped_edges(pos.x, pos.y))
        self._clock.show()
        self._settings.load(self._config)
        self._tray.show()
        self._refresh_tray_icon()  # Qt's own image is mis-sized above 100%
        if run_tutorial:
            self._tutorial.start(self._first_run)

    def _apply_theme(self) -> None:
        """Light/dark for the app windows; `"auto"` follows the Windows apps theme. The clock
        has its own colors."""
        scheme = {
            "light": Qt.ColorScheme.Light,
            "dark": Qt.ColorScheme.Dark,
        }.get(self._config.system.interface.theme, Qt.ColorScheme.Unknown)
        try:
            self._app.styleHints().setColorScheme(scheme)
        except (AttributeError, RuntimeError):
            pass  # Qt < 6.8 has no setColorScheme

    def _apply_language(self) -> None:
        """Swap the string catalog and rebuild what copied it.

        The settings rebuild is deferred: this runs inside the language combo's signal, and
        the rebuild deletes that combo. The clock has no text of its own."""
        i18n.set_language(self._config.system.interface.language)
        self._tray.retranslate()
        self._settings.request_rebuild()

    def _sync_system_font(self) -> bool:
        """Adopt Windows' current "Text size" if it moved; True when it did. The caller must
        then rebuild the settings window: its px() sizes are fixed at build."""
        pt = win32.system_font_pt()
        font = self._app.font()
        if pt is None or abs(font.pointSizeF() - pt) < 0.01:
            return False
        font.setPointSizeF(pt)
        self._app.setFont(font)
        return True

    def _refresh_tray_icon(self, force: bool = False) -> None:
        # Deferred, so it lands after whatever Qt does with the same message.
        QTimer.singleShot(0, lambda: win32.set_tray_icon(
            resource_path("resources", "icon.ico"), force))

    def _on_setting_change(self) -> None:
        self._refresh_tray_icon()
        # One copy of the broadcast per window of ours; only the first finds the font changed.
        if self._sync_system_font():
            self._settings.request_rebuild()

    def _on_second_launch(self) -> None:
        # One copy of the broadcast per window of ours; settings already open are just raised.
        if not self._tutorial.active:
            self._open_settings()

    def _wire(self) -> None:
        self._settings.config_changed.connect(self._on_settings_changed)
        self._settings.closed.connect(self._on_settings_closed)
        self._settings.minimized_changed.connect(self._on_settings_minimized)
        self._settings.restart_requested.connect(self._restart_app)
        self._clock.position_changed.connect(self._on_clock_dragged)
        self._clock.drag_started.connect(self._on_drag_started)
        self._clock.drag_ended.connect(self._on_drag_ended)
        self._clock.edge_glow.connect(self._guide.set_glow)
        self._clock.settings_requested.connect(lambda: self._open_settings("cog"))
        self._clock.settings_close_requested.connect(self._settings.close)
        self._tray.settings_requested.connect(lambda: self._open_settings("tray"))
        self._tray.quit_requested.connect(self._quit)
        self._tray.menu_about_to_show.connect(lambda: self._clock.pause_topmost(True))
        self._tray.menu_about_to_hide.connect(lambda: self._clock.pause_topmost(False))
        self._store.externally_changed.connect(self._on_external_change)
        self._app.aboutToQuit.connect(self._flush_pending_save)

    # -- settings live edits --------------------------------------------------
    def _on_settings_changed(self, config: Config) -> None:
        language_changed = config.system.interface.language != self._config.system.interface.language
        self._config = config
        self._apply_theme()
        if language_changed:
            self._apply_language()
        if config.clock.background.auto_corners:
            pos = config.clock.position
            self._apply_auto_corners(positioning.snapped_edges(pos.x, pos.y))
        else:
            self._clock.apply(config)
        self._schedule_save()

    def _on_clock_dragged(self, monitor: Monitor, x: float, y: float, snapped: frozenset) -> None:
        pos = self._config.clock.position
        crossed_monitor = monitor != pos.monitor
        pos.monitor, pos.x, pos.y = monitor, x, y
        self._settings.update_position(monitor, x, y)
        # Only when the corners actually change: apply() rebuilds the whole clock. Never in the
        # tutorial: re-applying its big clock makes the window jump (corners are redone when it parks).
        bg = self._config.clock.background
        current = (bg.round_top_left, bg.round_top_right, bg.round_bottom_left, bg.round_bottom_right)
        if (bg.auto_corners and not self._tutorial.active
                and self._corner_flags(snapped) != current):
            self._apply_auto_corners(snapped)
        if crossed_monitor:
            if self._guide.shown:  # a wheel nudge crosses too, with no guide up
                self._guide.show_on(self._clock.target_geometry())
            self._clock.bring_to_front()
        # The bubble follows the clock; the step itself advances on release (_on_drag_ended).
        if self._tutorial.in_move:
            self._tutorial.reposition_bubble()
        self._schedule_save()

    @staticmethod
    def _corner_flags(snapped: frozenset) -> tuple[bool, bool, bool, bool]:
        """Which corners are round (top-left, top-right, bottom-left, bottom-right): a corner
        on a flush edge is square."""
        return ("top"    not in snapped and "left"  not in snapped,
                "top"    not in snapped and "right" not in snapped,
                "bottom" not in snapped and "left"  not in snapped,
                "bottom" not in snapped and "right" not in snapped)

    def _apply_auto_corners(self, snapped: frozenset) -> None:
        bg = self._config.clock.background
        (bg.round_top_left, bg.round_top_right,
         bg.round_bottom_left, bg.round_bottom_right) = self._corner_flags(snapped)
        self._clock.apply(self._config)
        self._settings.update_auto_corners(bg.round_top_left, bg.round_top_right,
                                           bg.round_bottom_left, bg.round_bottom_right)

    # -- settings window open/close ------------------------------------------
    def _open_settings(self, source: str = "cog") -> None:
        # Every way into settings ends here; during the tutorial, the tutorial decides what it means.
        if self._tutorial.active:
            self._tutorial.on_settings_requested(source)
            return
        if self._settings.isVisible():  # minimized counts as visible
            if self._settings.isMinimized():
                self._settings.showNormal()  # show() keeps a window minimized
            self._settings.raise_()
            self._settings.activateWindow()
            self._clock.bring_to_front()
            return
        if self._sync_system_font():  # in case the WM_SETTINGCHANGE broadcast never reached us
            self._settings.retranslate()
        self._clock.notify_settings_open(True)
        self._settings.load(self._config)
        self._settings.showNormal()  # closed while minimized, show() would reopen it minimized
        # Centered on the clock's monitor, clear of the edge-anchored clock.
        frame = self._settings.frameGeometry()
        frame.moveCenter(self._clock.target_screen().availableGeometry().center())
        self._settings.move(frame.topLeft())
        self._settings.raise_()
        self._settings.activateWindow()
        # The guide shows only while dragging: over the combo dropdowns it makes them flicker.
        self._clock.set_draggable(True)
        self._clock.bring_to_front()

    def _on_drag_started(self) -> None:
        self._guide.set_glow({})  # start with just the faint frame, no edge lit
        self._guide.show_on(self._clock.target_geometry())
        self._clock.bring_to_front()  # clock stays above the guide

    def _on_drag_ended(self) -> None:
        self._guide.hide()
        if self._tutorial.active:
            self._tutorial.on_drag_ended()

    def _on_settings_closed(self) -> None:
        self._clock.notify_settings_open(False)
        # In the tutorial, edit mode belongs to the tutorial.
        if not self._tutorial.active:
            self._clock.set_draggable(False)
        self._guide.hide()
        if self._tutorial.active:
            self._tutorial.on_settings_closed()  # reveal "click to continue" now if it was armed

    def _on_settings_minimized(self, minimized: bool) -> None:
        """Minimized settings lock the clock like closed ones; restored, they unlock it."""
        if self._tutorial.active:
            return
        self._clock.notify_settings_open(not minimized)
        self._clock.set_draggable(not minimized)
        if minimized:
            self._guide.hide()
        else:
            self._clock.bring_to_front()

    # -- tutorial: actions the tutorial delegates back to the controller ------
    def park_clock(self, on_done=None, nudged: bool = False) -> None:
        """Glide the clock to the parking spot, commit it there, then run *on_done*."""
        target = self._park_position()
        speed = _NUDGE_SLIDE_PX_PER_S if nudged else _SLIDE_PX_PER_S
        self._slide_clock_to_park(target, speed, lambda: self._on_parked(target, on_done))

    def _park_position(self) -> tuple[float, float]:
        """Centers the clock between the settings panel and the screen's right edge, halfway
        down: clock and bubble stay off the panel."""
        screen = self._clock.target_screen()
        panel_right = (screen.availableGeometry().center().x()
                       + self._settings.frameGeometry().width() // 2)
        geom = self._clock.target_geometry()
        card = self._clock.card_global_rect().width()
        screen_right = geom.x() + geom.width()
        clock_left = panel_right + (screen_right - panel_right - card) // 2
        return self._clock.fraction_at(QPoint(clock_left, geom.y()))[0], 0.5

    def _on_parked(self, target: tuple[float, float], on_done) -> None:
        pos = self._config.clock.position
        pos.x, pos.y = target
        if self._config.clock.background.auto_corners:
            self._apply_auto_corners(positioning.snapped_edges(*target))  # touches nothing → all round
        else:
            self._clock.apply(self._config)
        if self._tutorial.in_move:
            self._tutorial.reposition_bubble()
        if on_done is not None:
            on_done()

    def open_settings_preview(self) -> None:
        """Settings as a tutorial preview: centered, and closed as soon as it's reached (cursor or
        Alt+Tab). No geometry freeze: the tutorial already holds the clock."""
        self._settings.load(self._config)
        self._settings.show_tutorial_preview()
        frame = self._settings.frameGeometry()
        frame.moveCenter(self._clock.target_screen().availableGeometry().center())
        self._settings.move(frame.topLeft())
        self._settings.raise_()

    def close_settings(self) -> None:
        # Called on every tutorial step: closing a hidden window would still fire `closed`
        # and drop edit mode.
        if self._settings.isVisible():
            self._settings.close()

    def enable_tray(self) -> None:
        self._tray.set_settings_enabled(True)

    def disable_tray(self) -> None:
        self._tray.set_settings_enabled(False)

    def dissolve_clock(self) -> None:
        """Fade the whole clock out, as if retreating to the tray. The style is untouched:
        restore_clock() brings it back."""
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(_DISSOLVE_MS)
        anim.valueChanged.connect(lambda v: self._clock.setWindowOpacity(float(v)))
        self._dissolve_anim = anim
        anim.start()

    def restore_clock(self) -> None:
        """Back to full opacity at once, after a dissolve."""
        if self._dissolve_anim is not None:
            self._dissolve_anim.stop()
            self._dissolve_anim = None
        self._clock.setWindowOpacity(1.0)

    def finish_tutorial(self) -> None:
        """Tutorial goodbye: shrink the clock and glide it to the default corner.

        It always lands on the default style, as a farewell pose; the user's own style goes
        back in afterwards, under a blackout (_blackout_finish)."""
        self._clock.set_draggable(False)  # no arrows/gear during the goodbye
        target = Clock()
        target.position.monitor = self._config.clock.position.monitor  # the corner of its own monitor
        start_font = self._config.clock.text.font_size
        end_font = target.text.font_size
        tp = target.position
        start = self._clock.fraction_at(self._clock.card_global_rect().topLeft())
        # Frozen, pre-grown rect: the shrink is a pure repaint (resizing a layered window flashes).
        self._clock.freeze_geometry(True, tp)
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(_FINISH_MS)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.valueChanged.connect(
            lambda t, sf=start_font, ef=end_font, s=start, p=tp:
            self._on_finish_tick(float(t), sf, ef, s, p))
        anim.finished.connect(lambda: self._land_finish(target))
        self._finish_anim = anim
        anim.start()

    def _on_finish_tick(self, t: float, start_font: int, end_font: int, start, tp) -> None:
        font = round(start_font + (end_font - start_font) * t)
        clock = replace(
            self._config.clock,
            text=replace(self._config.clock.text, font_size=font),
            position=replace(tp, x=start[0] + (tp.x - start[0]) * t,
                             y=start[1] + (tp.y - start[1]) * t))
        cfg = self._config.copy()
        cfg.clock = clock
        self._clock.apply(cfg)

    def _land_finish(self, target: Clock) -> None:
        """Settle the shown clock on the farewell pose while still frozen (a pure repaint).
        Display only: the real style comes back in _blackout_finish."""
        self._config.clock = target
        pos = self._config.clock.position
        if self._config.clock.background.auto_corners:
            self._apply_auto_corners(positioning.snapped_edges(pos.x, pos.y))
        else:
            self._clock.apply(self._config)
        QTimer.singleShot(_FINISH_HOLD_MS, self._blackout_finish)

    def _blackout_finish(self) -> None:
        """Clock off, then the lasting style goes in unseen: the default on a first run, the
        user's own after a restart."""
        self._clock.set_blackout(True)
        if self._first_run:
            monitor = self._config.clock.position.monitor
            self._config.clock = Clock()
            self._config.clock.position.monitor = monitor  # it stays where the user left it
        else:
            self._config.clock = self._pre_tutorial_clock
        self._clock.freeze_geometry(False)           # unfreeze while hidden — no resize flash
        self._clock.set_tutorial_controls(True, True)
        self._clock.set_tutorial_hold(False)
        self._clock.set_tutorial_active(False)
        pos = self._config.clock.position
        if self._config.clock.background.auto_corners:
            self._apply_auto_corners(positioning.snapped_edges(pos.x, pos.y))
        else:
            self._clock.apply(self._config)
        QTimer.singleShot(_FINISH_BLACKOUT_MS, self._commit_finish)

    def _commit_finish(self) -> None:
        """Lift the blackout, end the tutorial and save. Autostart and the firstrun flag change
        only on a first run."""
        self._finish_anim = None
        self._clock.set_blackout(False)
        self._tray.set_settings_enabled(True)
        self._settings.load(self._config)
        tut = self._config.system.tutorial
        if self._first_run:
            startup.set_enabled(True)
            tut.firstrun = False
        tut.completed = True
        self._onboarding = False
        self._store.save(self._config)  # now, not debounced

    def _slide_clock_to_park(self, target: tuple[float, float], speed: int, on_done) -> None:
        """Glide the clock to *target* at *speed* px/s, then run *on_done*."""
        card = self._clock.card_global_rect()
        start = self._clock.fraction_at(card.topLeft())
        end = positioning.topleft_for(self._clock.target_geometry(), card.size(), *target)
        distance = math.hypot(end.x() - card.x(), end.y() - card.y())
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(round(distance * 1000 / speed))
        anim.setEasingCurve(QEasingCurve.Type.Linear)
        anim.valueChanged.connect(
            lambda t, s=start, e=target: self._on_slide(float(t), s, e))
        anim.finished.connect(lambda: self._on_slide_done(on_done))
        self._slide_anim = anim
        anim.start()

    def _on_slide(self, t: float, start: tuple, end: tuple) -> None:
        self._clock.set_position_live(start[0] + (end[0] - start[0]) * t,
                                      start[1] + (end[1] - start[1]) * t)
        if self._tutorial.in_move:
            self._tutorial.reposition_bubble()

    def _on_slide_done(self, on_done) -> None:
        self._slide_anim = None
        on_done()

    # -- quit and restart -----------------------------------------------------
    def _quit(self) -> None:
        self._save_timer.stop()
        self._persist()
        self._guide.close()
        self._settings.close()
        self._clock.close_for_quit()
        self._tray.hide()
        self._app.quit()

    def _refuse_newer_config(self) -> None:
        """A newer version of the app wrote the config: say so and quit (the store saves nothing)."""
        if self._refusing:
            return  # the newer app saved again while the notice is up
        self._refusing = True
        self._apply_theme()
        NoticeDialog.tell(None, S.newer_config.title.format(app=APP_NAME), S.newer_config.body,
                          S.newer_config.close)
        self._quit()

    def _flush_pending_save(self) -> None:
        # Shutdown, logoff or a Store update end the app without going through _quit.
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._persist()

    def _restart_app(self) -> None:
        # Saved first: the new copy must read the cleared tutorial flag. Frozen, argv[0] is the
        # exe itself; from source it's the script, and dropping it would start a bare interpreter.
        self._save_timer.stop()
        self._persist()
        args = [sys.executable, *sys.argv[1:]] if getattr(sys, "frozen", False) \
            else [sys.executable, *sys.argv]
        win32.release_single_instance()  # FIRST, or the child takes us for a running copy and exits
        subprocess.Popen(args, close_fds=True)
        self._quit()

    # -- external file edits --------------------------------------------------
    def _on_external_change(self, config: Config) -> None:
        if self._store.newer_config:
            self._refuse_newer_config()
            return
        if self._onboarding:
            return  # ignored: the tutorial's end saves over it
        language_changed = config.system.interface.language != self._config.system.interface.language
        self._config = config
        self._apply_theme()
        if language_changed:
            self._apply_language()
        if config.clock.background.auto_corners:
            pos = config.clock.position
            self._apply_auto_corners(positioning.snapped_edges(pos.x, pos.y))
        else:
            self._clock.apply(config)
        self._settings.load(config)

    # -- helpers --------------------------------------------------------------
    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _persist(self) -> None:
        """The only way the config reaches disk, besides _commit_finish.

        Skipped while onboarding: `clock` then holds the enlarged tutorial style, and saving it
        would make the next launch "restore" it as the user's own."""
        if self._onboarding:
            return
        try:
            self._store.save(self._config)
        except OSError:
            pass

    def _flush_save(self) -> None:
        self._persist()
