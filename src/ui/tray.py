"""System-tray icon and its menu: Settings and Quit."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_NAME
from ..i18n import S


class TrayIcon(QSystemTrayIcon):
    """Tray icon whose menu and double-click only emit signals."""

    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    menu_about_to_show = pyqtSignal()
    menu_about_to_hide = pyqtSignal()

    def __init__(self, icon: QIcon, parent=None) -> None:
        super().__init__(icon, parent)
        self.setToolTip(APP_NAME)
        self._settings_enabled = True

        menu = QMenu()
        self._settings_action = QAction(S.tray.settings, menu)
        self._settings_action.triggered.connect(self.settings_requested)
        menu.addAction(self._settings_action)
        menu.addSeparator()
        self._quit_action = QAction(S.tray.quit, menu)
        self._quit_action.triggered.connect(self.quit_requested)
        menu.addAction(self._quit_action)
        # The clock's topmost re-assert would close the menu: the controller pauses it meanwhile.
        menu.aboutToShow.connect(self.menu_about_to_show)
        menu.aboutToHide.connect(self.menu_about_to_hide)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick and self._settings_enabled:
            self.settings_requested.emit()

    def retranslate(self) -> None:
        """Re-label the menu after a language change; the tooltip is the app name."""
        self._settings_action.setText(S.tray.settings)
        self._quit_action.setText(S.tray.quit)

    def set_settings_enabled(self, enabled: bool) -> None:
        """Turn the Settings entry (menu item and double-click) on or off. Quit is never
        turned off, so the app can always be closed."""
        self._settings_enabled = enabled
        self._settings_action.setEnabled(enabled)
