"""Win32 interop via ctypes, for what Qt can't do."""

from __future__ import annotations

import ctypes
import winreg
from ctypes import wintypes

from .. import PACKAGE_ID

# --- constants ---------------------------------------------------------------
GWL_EXSTYLE = -20
GWL_STYLE = -16

WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

CURSOR_SHOWING = 0x00000001
CURSOR_SUPPRESSED = 0x00000002

WS_CAPTION = 0x00C00000  # WS_BORDER | WS_DLGFRAME
WS_THICKFRAME = 0x00040000
WS_MAXIMIZEBOX = 0x00010000

MONITOR_DEFAULTTOPRIMARY = 0x00000001
MONITOR_DEFAULTTONEAREST = 0x00000002
MDT_EFFECTIVE_DPI = 0
EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001
DISPLAY_DEVICE_ACTIVE = 0x00000001

GW_HWNDNEXT = 2  # the window below, in Z-order

DWMWA_CLOAKED = 14

ZBID_DESKTOP = 1

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

TH32CS_SNAPPROCESS = 0x00000002

MUI_LANGUAGE_NAME = 0x8

WM_MOVE = 0x0003
WM_WINDOWPOSCHANGING = 0x0046
WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_DPICHANGED = 0x02E0
SPI_GETNONCLIENTMETRICS = 0x0029
SM_CXSMICON = 49
NIM_MODIFY = 0x1
NIF_ICON = 0x2

# The desktop and the taskbars: excluded from fullscreen detection and from the app below.
_SHELL_CLASSES = frozenset(
    {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
)

HWND_TOP = 0
HWND_BOTTOM = 1
HWND_TOPMOST = -1
HWND_BROADCAST = 0xFFFF

ASFW_ANY = -1

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

ULW_ALPHA = 0x00000002
AC_SRC_ALPHA = 0x01

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1


# --- structures --------------------------------------------------------------
class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _MonitorInfoExW(_MonitorInfo):
    _fields_ = [("szDevice", ctypes.c_wchar * 32)]  # CCHDEVICENAME


class _DisplayDeviceW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),  # ULONG_PTR
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),  # MAX_PATH
    ]


class _LogFontW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", wintypes.LONG),
        ("lfWidth", wintypes.LONG),
        ("lfEscapement", wintypes.LONG),
        ("lfOrientation", wintypes.LONG),
        ("lfWeight", wintypes.LONG),
        ("lfItalic", wintypes.BYTE),
        ("lfUnderline", wintypes.BYTE),
        ("lfStrikeOut", wintypes.BYTE),
        ("lfCharSet", wintypes.BYTE),
        ("lfOutPrecision", wintypes.BYTE),
        ("lfClipPrecision", wintypes.BYTE),
        ("lfQuality", wintypes.BYTE),
        ("lfPitchAndFamily", wintypes.BYTE),
        ("lfFaceName", ctypes.c_wchar * 32),
    ]


class _NonClientMetricsW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("iBorderWidth", ctypes.c_int),
        ("iScrollWidth", ctypes.c_int),
        ("iScrollHeight", ctypes.c_int),
        ("iCaptionWidth", ctypes.c_int),
        ("iCaptionHeight", ctypes.c_int),
        ("lfCaptionFont", _LogFontW),
        ("iSmCaptionWidth", ctypes.c_int),
        ("iSmCaptionHeight", ctypes.c_int),
        ("lfSmCaptionFont", _LogFontW),
        ("iMenuWidth", ctypes.c_int),
        ("iMenuHeight", ctypes.c_int),
        ("lfMenuFont", _LogFontW),
        ("lfStatusFont", _LogFontW),
        ("lfMessageFont", _LogFontW),
        ("iPaddedBorderWidth", ctypes.c_int),
    ]


class _CursorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", wintypes.POINT),
    ]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BlendFunction(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _WindowPos(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


class _NotifyIconDataW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", wintypes.UINT),  # a union with uTimeout
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


# --- prototypes --------------------------------------------------------------
_user32 = ctypes.WinDLL("user32", use_last_error=True)

_set_long = _user32.SetWindowLongPtrW
_get_long = _user32.GetWindowLongPtrW
_set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_set_long.restype = ctypes.c_ssize_t
_get_long.argtypes = [wintypes.HWND, ctypes.c_int]
_get_long.restype = ctypes.c_ssize_t

_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint,
]
_user32.SetWindowPos.restype = wintypes.BOOL

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HANDLE
_user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_user32.MonitorFromPoint.restype = wintypes.HANDLE
_user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
_user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC, ctypes.POINTER(wintypes.RECT), _MONITORENUMPROC, wintypes.LPARAM]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_DisplayDeviceW), wintypes.DWORD]
_user32.EnumDisplayDevicesW.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CursorInfo)]
_user32.GetCursorInfo.restype = wintypes.BOOL

_WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,  # hWinEventHook
    wintypes.DWORD,   # event
    wintypes.HWND,    # hwnd
    wintypes.LONG,    # idObject
    wintypes.LONG,    # idChild
    wintypes.DWORD,   # idEventThread
    wintypes.DWORD,   # dwmsEventTime
)
_user32.SetWinEventHook.argtypes = [
    wintypes.DWORD, wintypes.DWORD,
    wintypes.HMODULE, _WINEVENTPROC,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
]
_user32.SetWinEventHook.restype = wintypes.HANDLE
_user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
_user32.UnhookWinEvent.restype = wintypes.BOOL

_user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
    ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.SendMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SendMessageW.restype = wintypes.LPARAM
_user32.DestroyIcon.argtypes = [wintypes.HANDLE]
_user32.DestroyIcon.restype = wintypes.BOOL
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
_user32.RegisterWindowMessageW.restype = wintypes.UINT
_user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
_user32.GetSystemMetricsForDpi.restype = ctypes.c_int
# Broadcast when Explorer recreates the taskbar; Qt then re-adds its own tray icon.
TASKBAR_CREATED = _user32.RegisterWindowMessageW("TaskbarCreated")
OPEN_SETTINGS = _user32.RegisterWindowMessageW(f"{PACKAGE_ID}.OpenSettings")
_user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
_user32.AllowSetForegroundWindow.restype = wintypes.BOOL
_user32.GetDpiForWindow.argtypes = [wintypes.HWND]
_user32.GetDpiForWindow.restype = wintypes.UINT
_user32.SystemParametersInfoForDpi.argtypes = [
    wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT, wintypes.UINT]
_user32.SystemParametersInfoForDpi.restype = wintypes.BOOL
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.ReleaseDC.restype = ctypes.c_int
_user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
    wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
    ctypes.POINTER(_BlendFunction), wintypes.DWORD]
_user32.UpdateLayeredWindow.restype = wintypes.BOOL
# Undocumented, so it may go away: without it every window counts as ZBID_DESKTOP.
_get_window_band = getattr(_user32, "GetWindowBand", None)
if _get_window_band is not None:
    _get_window_band.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _get_window_band.restype = wintypes.BOOL

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
_kernel32.Process32NextW.restype = wintypes.BOOL
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.GetUserPreferredUILanguages.argtypes = [
    wintypes.DWORD, ctypes.POINTER(wintypes.ULONG), wintypes.LPWSTR,
    ctypes.POINTER(wintypes.ULONG)]
_kernel32.GetUserPreferredUILanguages.restype = wintypes.BOOL
_kernel32.GetCurrentProcessId.restype = wintypes.DWORD

_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(_BitmapInfoHeader), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteObject.restype = wintypes.BOOL
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_gdi32.DeleteDC.restype = wintypes.BOOL

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
_shell32.Shell_NotifyIconW.restype = wintypes.BOOL
_shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
_shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long  # HRESULT
_shcore = ctypes.WinDLL("shcore", use_last_error=True)
_shcore.GetDpiForMonitor.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
_shcore.GetDpiForMonitor.restype = ctypes.c_long  # HRESULT
_dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
_dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long  # HRESULT


# --- windows and styles ------------------------------------------------------
def _hwnd(value: int) -> ctypes.c_void_p:
    return ctypes.c_void_p(value)


def get_hwnd(widget) -> int:
    return int(widget.winId())


def message_id(message) -> int:
    """The message number in the MSG* a native event filter receives."""
    return wintypes.MSG.from_address(int(message)).message


def keep_off_bottom(message, hwnd: int) -> None:
    """Drop a move of *hwnd* to the bottom of the z-order from *message*, a native filter's MSG*."""
    msg = wintypes.MSG.from_address(int(message))
    if msg.message != WM_WINDOWPOSCHANGING or msg.hWnd != hwnd:
        return
    pos = _WindowPos.from_address(msg.lParam)
    if not pos.flags & SWP_NOZORDER and pos.hwndInsertAfter == HWND_BOTTOM:
        pos.flags |= SWP_NOZORDER


def _get_exstyle(hwnd: int) -> int:
    return int(_get_long(_hwnd(hwnd), GWL_EXSTYLE))


def _apply_exstyle(hwnd: int, style: int) -> None:
    if style == _get_exstyle(hwnd):
        return  # a FRAMECHANGED with nothing changed still recalculates the frame
    _set_long(_hwnd(hwnd), GWL_EXSTYLE, style)
    _flush_frame(hwnd)


def _flush_frame(hwnd: int) -> None:
    """Apply a style change without moving, resizing or restacking the window."""
    _user32.SetWindowPos(
        _hwnd(hwnd), _hwnd(HWND_TOP), 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def set_tool_window(hwnd: int) -> None:
    """Keep the window out of the taskbar and Alt-Tab."""
    style = _get_exstyle(hwnd)
    _apply_exstyle(hwnd, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)


def drop_sizing_border(hwnd: int) -> None:
    """Remove the sizing border and maximize box: `setFixedSize` leaves the resize cursors."""
    style = int(_get_long(_hwnd(hwnd), GWL_STYLE))
    _set_long(_hwnd(hwnd), GWL_STYLE, style & ~(WS_THICKFRAME | WS_MAXIMIZEBOX))
    _flush_frame(hwnd)


def set_click_through(hwnd: int, enabled: bool) -> None:
    """Toggle WS_EX_TRANSPARENT; WS_EX_LAYERED is kept on, click-through needs it."""
    style = _get_exstyle(hwnd) | WS_EX_LAYERED
    if enabled:
        style |= WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    _apply_exstyle(hwnd, style)


def set_no_activate(hwnd: int, enabled: bool) -> None:
    """Toggle WS_EX_NOACTIVATE: a click neither activates the window nor takes the
    foreground (MA_NOACTIVATE alone still takes it)."""
    style = _get_exstyle(hwnd)
    _apply_exstyle(hwnd, style | WS_EX_NOACTIVATE if enabled else style & ~WS_EX_NOACTIVATE)


def reassert_topmost(hwnd: int) -> None:
    """Move the window back to the top of the topmost windows."""
    _user32.SetWindowPos(
        _hwnd(hwnd), _hwnd(HWND_TOPMOST), 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def update_layered(hwnd: int, x: int, y: int, width: int, height: int, bits: int) -> bool:
    """Move, resize and repaint a layered window in one call, in physical pixels: moved on
    its own, it shows its old image at the new spot until the next paint. *bits*: top-down,
    premultiplied BGRA rows of `width * 4` bytes. Then a WM_MOVE, which UpdateLayeredWindow
    doesn't send: without it Qt keeps the old rect and its next flush moves the window back."""
    screen_dc = _user32.GetDC(None)
    mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
    header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height, 1, 32)
    dib_bits = ctypes.c_void_p()
    bitmap = _gdi32.CreateDIBSection(screen_dc, ctypes.byref(header), 0,
                                     ctypes.byref(dib_bits), None, 0)
    ok = False
    if bitmap and dib_bits.value:
        ctypes.memmove(dib_bits, bits, width * height * 4)
        previous = _gdi32.SelectObject(mem_dc, bitmap)
        ok = bool(_user32.UpdateLayeredWindow(
            _hwnd(hwnd), screen_dc, ctypes.byref(wintypes.POINT(x, y)),
            ctypes.byref(wintypes.SIZE(width, height)), mem_dc,
            ctypes.byref(wintypes.POINT(0, 0)), 0,
            ctypes.byref(_BlendFunction(0, 0, 255, AC_SRC_ALPHA)), ULW_ALPHA))
        _gdi32.SelectObject(mem_dc, previous)
        _gdi32.DeleteObject(bitmap)
    _gdi32.DeleteDC(mem_dc)
    _user32.ReleaseDC(None, screen_dc)
    if ok:
        _user32.SendMessageW(_hwnd(hwnd), WM_MOVE, 0, ((y & 0xFFFF) << 16) | (x & 0xFFFF))
    return ok


# --- single instance ---------------------------------------------------------
_ERROR_ALREADY_EXISTS = 183
_single_instance_handle = None


def acquire_single_instance(name: str) -> bool:
    """Take the named mutex for the process lifetime. False if another instance holds it,
    True otherwise (also when the mutex can't be created)."""
    global _single_instance_handle
    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    _single_instance_handle = handle
    return True


def release_single_instance() -> None:
    """Drop the mutex so a relaunched copy can take it."""
    global _single_instance_handle
    if _single_instance_handle:
        _kernel32.CloseHandle(_single_instance_handle)
        _single_instance_handle = None


def request_open_settings() -> None:
    """Ask the running instance to open its settings."""
    # We were just launched, so the foreground is ours to hand over.
    _user32.AllowSetForegroundWindow(ASFW_ANY)
    _user32.PostMessageW(_hwnd(HWND_BROADCAST), OPEN_SETTINGS, 0, 0)


# --- icons -------------------------------------------------------------------
_window_icons: dict[tuple[int, int], int] = {}  # icons we loaded, per (hwnd, ICON_BIG/ICON_SMALL)
_tray_icon = 0  # our current tray icon
_tray_slot = 0  # the slot size it was picked for


def set_app_id(app_id: str) -> None:
    """Group this process's windows under *app_id* in the taskbar. Before any window opens."""
    _shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def _ico_frame_sizes(path: str) -> list[int]:
    """Square widths of the frames in an .ico, from its header."""
    try:
        with open(path, "rb") as f:
            count = int.from_bytes(f.read(6)[4:6], "little")
            sizes = []
            for _ in range(count):
                entry = f.read(16)
                if len(entry) < 16:
                    break
                sizes.append(entry[0] or 256)  # bWidth, 0 means 256
            return sorted(set(sizes))
    except OSError:
        return []


def _frame_for(frames: list[int], target: int) -> int:
    """The smallest frame that covers *target*: Windows must only ever scale down."""
    return next((s for s in frames if s >= target), frames[-1] if frames else target)


def set_window_icon_native(hwnd: int, ico_path) -> None:
    """Give the window taskbar and caption icons from *ico_path*, sized for its DPI.

    Qt only supplies 16 and 32 px, which the 24 px taskbar slot blurs. The taskbar reads
    WM_SETICON only, not the class icon.
    """
    dpi = _user32.GetDpiForWindow(_hwnd(hwnd)) or 96
    path = str(ico_path)
    frames = _ico_frame_sizes(path)
    for which, base in ((ICON_BIG, 24), (ICON_SMALL, 16)):
        target = round(base * dpi / 96)
        load = _frame_for(frames, target)
        handle = _user32.LoadImageW(None, path, IMAGE_ICON, load, load, LR_LOADFROMFILE)
        if handle:
            _user32.SendMessageW(_hwnd(hwnd), WM_SETICON, which, handle)
            # Free our previous icon, never Qt's.
            old = _window_icons.pop((hwnd, which), None)
            if old:
                _user32.DestroyIcon(old)
            _window_icons[(hwnd, which)] = handle


def _own_tray_windows() -> list[int]:
    """Qt's hidden tray windows in THIS process (other Qt apps use the same class)."""
    pid = _kernel32.GetCurrentProcessId()
    found = []

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            name = ctypes.create_unicode_buffer(128)
            _user32.GetClassNameW(hwnd, name, 128)
            if "TrayIconMessageWindowClass" in name.value:
                found.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(visit), 0)
    return found


def _taskbar_dpi() -> int:
    """DPI of the taskbar's monitor. Not the taskbar window's own DPI: that one lags
    behind a scaling change."""
    taskbar = _user32.FindWindowW("Shell_TrayWnd", None)
    monitor = _user32.MonitorFromWindow(taskbar, MONITOR_DEFAULTTOPRIMARY)
    dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
    if monitor and _shcore.GetDpiForMonitor(
            monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
        return dpi_x.value
    return 96


def set_tray_icon(ico_path, force: bool = False) -> None:
    """Put the .ico frame that fits the tray slot on Qt's tray icon; a no-op while the slot
    size is unchanged, unless *force* (Qt just re-added its own). Qt 6.11 picks a frame
    too big above 100% scaling and never updates it on a scaling change."""
    global _tray_icon, _tray_slot
    dpi = _taskbar_dpi()
    slot = _user32.GetSystemMetricsForDpi(SM_CXSMICON, dpi)
    if slot == _tray_slot and not force:
        return
    path = str(ico_path)
    load = _frame_for(_ico_frame_sizes(path), slot)
    handle = _user32.LoadImageW(None, path, IMAGE_ICON, load, load, LR_LOADFROMFILE)
    if not handle:
        return
    applied = False
    # Where Qt adds its icon (qwindowssystemtrayicon.cpp): its tray window, uID 0.
    for hwnd in _own_tray_windows():
        nid = _NotifyIconDataW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = hwnd
        nid.uID = 0
        nid.uFlags = NIF_ICON
        nid.hIcon = handle
        applied = bool(_shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))) or applied
    if not applied:
        _user32.DestroyIcon(handle)
        return
    if _tray_icon:
        _user32.DestroyIcon(_tray_icon)
    _tray_icon, _tray_slot = handle, slot


# --- monitors ----------------------------------------------------------------
def monitor_rects() -> dict[str, tuple[int, int, int, int]]:
    """Each active monitor's device interface path, casefolded, and its (x, y, width, height)
    in physical pixels: the process is per-monitor DPI aware, Qt sets it."""
    by_device: dict[str, tuple[int, int, int, int]] = {}

    def visit(hmonitor, _hdc, _rect, _lparam):
        info = _MonitorInfoExW()
        info.cbSize = ctypes.sizeof(_MonitorInfoExW)
        if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            by_device[info.szDevice] = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        return True

    _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(visit), 0)
    rects: dict[str, tuple[int, int, int, int]] = {}
    adapter = 0
    while True:
        device = _DisplayDeviceW(cb=ctypes.sizeof(_DisplayDeviceW))
        if not _user32.EnumDisplayDevicesW(None, adapter, ctypes.byref(device), 0):
            break
        rect = by_device.get(device.DeviceName)
        index = 0
        while rect is not None:
            monitor = _DisplayDeviceW(cb=ctypes.sizeof(_DisplayDeviceW))
            if not _user32.EnumDisplayDevicesW(device.DeviceName, index, ctypes.byref(monitor),
                                               EDD_GET_DEVICE_INTERFACE_NAME):
                break
            if monitor.StateFlags & DISPLAY_DEVICE_ACTIVE:
                rects[monitor.DeviceID.casefold()] = rect
            index += 1
        adapter += 1
    return rects


# --- system settings ---------------------------------------------------------
def system_font_pt() -> float | None:
    """The system UI font size in points, read as Qt reads it at startup (the message
    font at 96 DPI), or None."""
    ncm = _NonClientMetricsW()
    ncm.cbSize = ctypes.sizeof(ncm)
    if not _user32.SystemParametersInfoForDpi(
            SPI_GETNONCLIENTMETRICS, ncm.cbSize, ctypes.byref(ncm), 0, 96):
        return None
    return abs(ncm.lfMessageFont.lfHeight) * 72 / 96


def preferred_ui_languages() -> tuple[str, ...]:
    """Windows display languages as tags like `"it-IT"`, best first; empty on failure."""
    count, size = wintypes.ULONG(), wintypes.ULONG()
    # The first call only reports the buffer size.
    if not _kernel32.GetUserPreferredUILanguages(
            MUI_LANGUAGE_NAME, ctypes.byref(count), None, ctypes.byref(size)):
        return ()
    buffer = ctypes.create_unicode_buffer(size.value)
    if not _kernel32.GetUserPreferredUILanguages(
            MUI_LANGUAGE_NAME, ctypes.byref(count), buffer, ctypes.byref(size)):
        return ()
    # Null-separated, double-null terminated.
    return tuple(tag for tag in ctypes.wstring_at(buffer, size.value).split("\0") if tag)


def accent_color() -> tuple[int, int, int] | None:
    """The Windows accent color as `(r, g, b)`, or None. Qt's palette only has its
    darker selection shade."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\DWM") as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
        value = int(value) & 0xFFFFFFFF  # 0xAABBGGRR
        return value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
    except (OSError, ValueError):
        return None


def cursor_hidden() -> bool:
    """True when an app hid the cursor; False when Windows hid it for touch or pen."""
    info = _CursorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not _user32.GetCursorInfo(ctypes.byref(info)):
        return False
    if info.flags & CURSOR_SUPPRESSED:
        return False
    return not (info.flags & CURSOR_SHOWING) or not info.hCursor


# --- foreground and apps -----------------------------------------------------
_fg_hook_proc = None  # keeps the ctypes callback alive


def install_foreground_hook(callback) -> int:
    """Call *callback* with the 7 WinEvent args on every foreground change, on the main
    thread. Returns the handle for :func:`uninstall_foreground_hook`."""
    global _fg_hook_proc
    _fg_hook_proc = _WINEVENTPROC(callback)
    hook = _user32.SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
        None, _fg_hook_proc, 0, 0, WINEVENT_OUTOFCONTEXT,
    )
    return int(hook) if hook else 0


def uninstall_foreground_hook(hook: int) -> None:
    global _fg_hook_proc
    if not hook:
        return
    _user32.UnhookWinEvent(ctypes.c_void_p(hook))
    _fg_hook_proc = None


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(64)
    _user32.GetClassNameW(_hwnd(hwnd), buf, len(buf))
    return buf.value


def _window_rect(hwnd: int):
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(_hwnd(hwnd), ctypes.byref(rect)):
        return None
    return rect


def _overlaps(a, b) -> bool:
    return a.left < b.right and b.left < a.right and a.top < b.bottom and b.top < a.bottom


def _cloaked(hwnd: int) -> bool:
    value = wintypes.DWORD()
    if _dwmapi.DwmGetWindowAttribute(
            _hwnd(hwnd), DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)) != 0:
        return False
    return bool(value.value)


def _window_band(hwnd: int) -> int:
    band = wintypes.DWORD()
    if _get_window_band is None or not _get_window_band(_hwnd(hwnd), ctypes.byref(band)):
        return ZBID_DESKTOP
    return band.value


def _monitor_rect(hmonitor: int):
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not _user32.GetMonitorInfoW(_hwnd(hmonitor), ctypes.byref(info)):
        return None
    return info.rcMonitor


def _pid_path(pid: int) -> str:
    """Full executable path of process *pid*, or `""`."""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value
    finally:
        _kernel32.CloseHandle(handle)


def _process_path(hwnd: int) -> str:
    """Full executable path of the process owning *hwnd*, or `""`."""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(_hwnd(hwnd), ctypes.byref(pid))
    return _pid_path(pid.value) if pid.value else ""


def _process_name(hwnd: int) -> str:
    """Executable file name of the process owning *hwnd*, or `""`."""
    path = _process_path(hwnd)
    return path.rsplit("\\", 1)[-1] if path else ""


def _norm_exe(name: str) -> str:
    """Lower-case, without a trailing `.exe`: the form exe names are compared in."""
    n = name.strip().lower()
    return n[:-4] if n.endswith(".exe") else n


def _window_below(hwnd: int) -> int:
    """The first real top-level window beneath *hwnd* in Z-order, or 0.
    Skips our own windows, the shell, tool windows, always-on-top windows not under *hwnd*,
    and invisible, cloaked or empty windows."""
    try:
        start = _hwnd(hwnd)
        ours = _window_rect(hwnd)
        our_pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(start, ctypes.byref(our_pid))
        cur = _user32.GetWindow(start, GW_HWNDNEXT)
        guard = 0
        while cur and guard < 500:
            guard += 1
            if _user32.IsWindowVisible(cur):
                exstyle = int(_get_long(cur, GWL_EXSTYLE))
                pid = wintypes.DWORD()
                _user32.GetWindowThreadProcessId(cur, ctypes.byref(pid))
                rect = _window_rect(cur)
                if (not (exstyle & WS_EX_TOOLWINDOW)
                        and pid.value != our_pid.value
                        and _class_name(cur) not in _SHELL_CLASSES
                        and rect is not None
                        and rect.right > rect.left and rect.bottom > rect.top
                        and not (exstyle & WS_EX_TOPMOST and ours is not None
                                 and not _overlaps(rect, ours))
                        and not _cloaked(cur)):
                    return cur
            cur = _user32.GetWindow(cur, GW_HWNDNEXT)
        return 0
    except OSError:
        return 0


def app_below(hwnd: int) -> tuple[str, str]:
    """(exe name, full path) of the app under our window, or ("", "") if none or a UWP app."""
    h = _window_below(hwnd)
    if not h:
        return "", ""
    path = _process_path(h)
    name = path.rsplit("\\", 1)[-1]
    if name.lower() == "applicationframehost.exe":  # the frame every UWP app runs in
        return "", ""
    return name, path


def exe_paths_for(names) -> dict[str, str]:
    """For each of *names* that is running, the full path of its process (compared as
    :func:`_norm_exe`)."""
    out: dict[str, str] = {}
    wanted: dict[str, list[str]] = {}
    for n in names:
        wanted.setdefault(_norm_exe(n), []).append(n)
    if not wanted:
        return out
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap:
        return out
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok and wanted:
            key = _norm_exe(entry.szExeFile)
            if key in wanted:
                path = _pid_path(entry.th32ProcessID)
                if path:
                    for orig in wanted.pop(key):
                        out[orig] = path
            ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
        return out
    except OSError:
        return out
    finally:
        _kernel32.CloseHandle(snap)


def is_fullscreen_app(clock_hwnd: int, monitor_point: tuple[int, int],
                      excluded_processes=()) -> bool:
    """True when a borderless-fullscreen app has the foreground on the monitor containing
    *monitor_point* (physical pixels): no title bar, covers the monitor, not the shell, not
    excluded, in our window band. The clock's monitor comes as a point because its window
    carries a transparent border, which can lie mostly on a neighbor.
    Not detected: exclusive fullscreen, and fullscreen UWP apps (they sit above our band)."""
    try:
        fg = _user32.GetForegroundWindow()
        if not fg or int(fg) == int(clock_hwnd):
            return False
        if _class_name(fg) in _SHELL_CLASSES:
            return False
        style = int(_get_long(_hwnd(fg), GWL_STYLE))
        # Don't also reject IsZoomed(): a video fullscreened from a maximized browser
        # keeps the maximize style.
        if (style & WS_CAPTION) == WS_CAPTION:
            return False
        mon_fg = _user32.MonitorFromWindow(_hwnd(fg), MONITOR_DEFAULTTONEAREST)
        mon_clock = _user32.MonitorFromPoint(wintypes.POINT(*monitor_point),
                                             MONITOR_DEFAULTTONEAREST)
        if not mon_fg or int(mon_fg) != int(mon_clock):
            return False
        mon = _monitor_rect(mon_fg)
        win = _window_rect(fg)
        if mon is None or win is None:
            return False
        covers = (win.left <= mon.left and win.top <= mon.top
                  and win.right >= mon.right and win.bottom >= mon.bottom)
        if not covers:
            return False
        if _window_band(fg) != ZBID_DESKTOP:
            return False
        if excluded_processes:
            excluded = {_norm_exe(name) for name in excluded_processes}
            if _norm_exe(_process_name(fg)) in excluded:
                return False
        return True
    except OSError:
        return False
