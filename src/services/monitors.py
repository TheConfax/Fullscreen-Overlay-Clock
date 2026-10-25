"""Which Qt screen is which monitor, by Windows' StableMonitorId."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QGuiApplication, QScreen
from winrt.windows.devices.display.core import DisplayManager, DisplayManagerOptions

from . import win32

_ids: list[tuple[QScreen, str]] = []
_screens: list[QScreen] = []  # what _ids was matched against
_stale = True


def _stable_ids() -> dict[str, str]:
    """StableMonitorId of each connected monitor, by casefolded device interface path."""
    manager = DisplayManager.create(DisplayManagerOptions.NONE)
    try:
        return {t.device_interface_path.casefold(): t.stable_monitor_id
                for t in manager.get_current_targets()
                if t.is_connected and t.stable_monitor_id}
    finally:
        manager.close()


def _match(screens: list[QScreen]) -> list[tuple[QScreen, str]]:
    try:
        ids = _stable_ids()
    except OSError:
        return []
    found = []
    for path, (x, y, w, h) in win32.monitor_rects().items():
        monitor_id = ids.get(path)
        if not monitor_id:
            continue
        for screen in screens:
            g, dpr = screen.geometry(), screen.devicePixelRatio()
            # Qt keeps each screen's top-left in physical pixels and scales only its size.
            if ((g.x(), g.y()) == (x, y) and abs(g.width() * dpr - w) <= 1
                    and abs(g.height() * dpr - h) <= 1):
                found.append((screen, monitor_id))
                break
    return found


def _invalidate(*_) -> None:
    global _stale
    _stale = True


def _current() -> list[tuple[QScreen, str]]:
    """The cached matches, redone when a screen comes, goes or changes: `_target_screen`
    asks on every reposition, too often to ask Windows each time."""
    global _stale
    screens = QGuiApplication.screens()
    if _stale or screens != _screens:
        for screen in screens:
            if screen not in _screens:
                screen.geometryChanged.connect(_invalidate)
        _screens[:] = screens
        _ids[:] = _match(screens)
        _stale = False
    return _ids


def id_of(screen: QScreen) -> str:
    """The screen's StableMonitorId, or `""` when Windows can't tell."""
    return next((monitor_id for s, monitor_id in _current() if s == screen), "")


def screen_for(monitor_id: str) -> QScreen | None:
    """The connected screen with *monitor_id*, or None."""
    if not monitor_id:
        return None
    return next((s for s, i in _current() if i == monitor_id), None)


# --- places on the desktop ---------------------------------------------------
ORDINALS = ("first", "second", "third", "fourth", "fifth")
ROWS = ("very_top", "top", "", "bottom", "very_bottom")
COLUMNS = ("left", "", "right") + ORDINALS


@dataclass(frozen=True)
class Place:
    """Where a screen sits among the others, as catalog keys: *row* from `ROWS`, *column*
    from `COLUMNS`, `""` for the middle; `"too_many"` in either past five rows or columns."""
    screen: QScreen
    row: str
    column: str


def _separated(a0: float, a1: float, b0: float, b1: float) -> bool:
    """Apart on one axis: neither center lies within the other's extent."""
    ac, bc = (a0 + a1) / 2, (b0 + b1) / 2
    return not b0 <= ac <= b1 and not a0 <= bc <= a1


def _ranks(spans: list[tuple[float, float]]) -> tuple[list[tuple[int, int]], int]:
    """Per span: the longest chain of spans apart from it before and after it on the axis,
    and how many rows (or columns) that makes."""
    n = len(spans)
    before = [[j for j in range(n) if _separated(*spans[j], *spans[i])
               and sum(spans[j]) < sum(spans[i])] for i in range(n)]
    after = [[j for j in range(n) if i in before[j]] for i in range(n)]

    def depth(i: int, links: list[list[int]], memo: dict[int, int]) -> int:
        if i not in memo:
            memo[i] = max((depth(j, links, memo) + 1 for j in links[i]), default=0)
        return memo[i]

    fwd: dict[int, int] = {}
    bwd: dict[int, int] = {}
    ranks = [(depth(i, before, fwd), depth(i, after, bwd)) for i in range(n)]
    return ranks, max((f for f, _ in ranks), default=-1) + 1


def _column(f: int, b: int, n: int) -> str:
    if n >= 4:
        return ORDINALS[f] if f < len(ORDINALS) else "too_many"
    if f == 0 and b > 0:
        return "left"
    if b == 0 and f > 0:
        return "right"
    return ""


def _row_word(r: int, n: int) -> str:
    """Row *r* of *n*, top first: counted from the nearer edge."""
    d, top = min(r, n - 1 - r), r < n - 1 - r
    if n >= 6 and d >= 2:
        return "too_many"
    if r == n - 1 - r:
        return ""
    if d == 0:
        if n >= 4:
            return "very_top" if top else "very_bottom"
        return "top" if top else "bottom"
    if d == 1 and n >= 4:
        return "top" if top else "bottom"
    return ""


def _row(f: int, b: int, n: int) -> str:
    """A screen between rows takes the plain `"top"` / `"bottom"` over the `"very_"` ones and
    over the middle; between a top row and a bottom one it is in the middle."""
    words = {_row_word(r, n) for r in range(f, n - b)}
    if words & {"top", "very_top"} and words & {"bottom", "very_bottom"}:
        return ""
    for plain in ("top", "bottom"):
        if plain in words:
            return plain
    return words.pop() if len(words) == 1 else ""


def places(screens: list[QScreen]) -> list[Place]:
    """Every screen's place, in reading order: rows top to bottom, each left to right."""
    # Physical pixels: Qt's top-left is Windows' own, only the size is scaled.
    boxes = [(g.x(), g.y(), g.width() * s.devicePixelRatio(), g.height() * s.devicePixelRatio())
             for s in screens for g in (s.geometry(),)]
    cols, n_cols = _ranks([(x, x + w) for x, _, w, _ in boxes])
    rows, n_rows = _ranks([(y, y + h) for _, y, _, h in boxes])
    order = sorted(range(len(screens)), key=lambda i: (rows[i][0], cols[i][0], boxes[i][0]))
    return [Place(screens[i], _row(*rows[i], n_rows), _column(*cols[i], n_cols)) for i in order]
