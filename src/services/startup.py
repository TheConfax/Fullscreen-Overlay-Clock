"""Start with Windows via the MSIX StartupTask; always off when run from source."""

from __future__ import annotations

import asyncio

from winrt.windows.applicationmodel import StartupTask, StartupTaskState

from .. import STARTUP_TASK_ID

_ON = (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY)

#: No deep link to our own row: `ms-settings:appsfeatures-app?<PackageFamilyName>` falls
#: back to "Installed apps" on Windows 11.
SETTINGS_URI = "ms-settings:startupapps"


def _task() -> StartupTask:
    return asyncio.run(StartupTask.get_async(STARTUP_TASK_ID))


def is_enabled() -> bool:
    try:
        return _task().state in _ON
    except OSError:
        return False


def is_blocked() -> bool:
    """True when autostart was turned off in Windows settings: only Windows can turn it back on."""
    try:
        return _task().state in (StartupTaskState.DISABLED_BY_USER,
                                 StartupTaskState.DISABLED_BY_POLICY)
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """Return the state that actually resulted, which differs when Windows refuses. Never raises."""
    try:
        task = _task()
        if enabled:
            return asyncio.run(task.request_enable_async()) in _ON
        task.disable()
        return False
    except OSError:
        return False
