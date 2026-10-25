"""App entry point: sets up the QApplication and hands off to AppController."""

from __future__ import annotations

import os
import sys

# Lets `python src/main.py` (the IDE Run button) resolve the relative imports below.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "src"

from .services import crashlog

# Before the other imports, so even a Qt DLL that fails to load ends up in crash.log.
crashlog.install()

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from . import APP_NAME, PACKAGE_ID
from .controller import AppController
from .services import fonts, win32
from .services.paths import resource_path
from .ui.style import AppStyle


def main() -> int:
    # A second exe launch opens the running copy's settings and exits.
    if getattr(sys, "frozen", False) and not win32.acquire_single_instance(
            f"{PACKAGE_ID}.SingleInstance"):
        win32.request_open_settings()
        return 0
    # Our taskbar icon when run from source.
    if not getattr(sys, "frozen", False):
        win32.set_app_id(f"{PACKAGE_ID}.Source")
    app = QApplication(sys.argv)
    app.setStyle(AppStyle())
    # Not a no-op: once set explicitly, Qt stops changing the font itself (AppController does).
    app.setFont(app.font())
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(resource_path("resources", "icon.ico"))))
    fonts.load_fonts()  # needs the QApplication
    # The tray icon, not the windows, owns the app lifetime.
    app.setQuitOnLastWindowClosed(False)

    controller = AppController(app)
    controller.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
