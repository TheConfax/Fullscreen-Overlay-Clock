"""Checks that sizes are within limits for all languages.

One flag, optional:
  --verbose  print the whole table instead of the verdict alone

Measures a hidden settings window per language, so the figures are the real app's.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _output import fail, fatal, info, ok, step

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics, QGuiApplication
from PyQt6.QtWidgets import QApplication, QLabel, QLayout, QPushButton, QSizePolicy

from src import i18n
from src.models.config import Config
from src.services import monitors, startup, win32
from src.ui.style import DEFAULT_FONT_PT
from src.ui.settings_window import (
    _CLIENT_H, _CLIENT_W, _COMBO_TEXT_INSET, _EXCLUSIONS_BTN_W, _LABEL_COL_W,
    SettingsWindow, _SupportButton, _position_text)

LIMITS = {"reset_btn delta": 1, "issue_rate_btn delta": 1, "monitor_place excess": 0}
AUTO_LIMITS = {"tabs_bar": _CLIENT_W, "clock_tab": _CLIENT_W, "exclusions_tab": _CLIENT_W,
               "system_tab": _CLIENT_W, "clock_bar_text": _LABEL_COL_W,
               "exclusions_btn": _EXCLUSIONS_BTN_W, "client_height": _CLIENT_H}
MEASURED: dict[str, int] = {}
BOX: dict[str, int] = {}

BOLD, RED, GREEN, YELLOW, OFF = "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"


def limit_for(measure: str) -> tuple[int | None, bool]:
    """(limit, whether it comes from the code). Numbered rows share their family's limit."""
    family = measure.rsplit(" ", 1)[0]
    for table in (MEASURED, AUTO_LIMITS):
        if measure in table or family in table:
            return table.get(measure, table.get(family)), True
    return LIMITS.get(measure, LIMITS.get(family)), False


def expect(items: list, count: int | None, what: str) -> list:
    """Stops if the window no longer has what we look for: found by position and filter, a
    rearranged window would report OK on the wrong widgets. count=None: at least one."""
    wrong = not items if count is None else len(items) != count
    if wrong:
        wanted = "at least one" if count is None else count
        fatal(f"expected {wanted} {what}, found {len(items)}",
              "the settings window changed: update check_sizes.py to match")
    return items


def measure(probe: SettingsWindow) -> list[tuple[str, int]]:
    """Every figure for one language, in the order the table prints them."""
    tabs = probe._tabs
    tab_bar, window_layout = tabs.tabBar(), probe.layout()
    if tab_bar is None or window_layout is None:
        fatal("the probe window came up without a tab bar or a layout")
    pages = expect([page for i in range(tabs.count()) if (page := tabs.widget(i)) is not None],
                   3, "tabs (Clock, Exclusions, System)")
    # The "current app" name elides and asks for no width: measured at its whole text.
    name = probe._current_name
    name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    name.setText(name._full_text)
    for layout in pages[1].findChildren(QLayout):  # the nested row keeps its old hint otherwise
        layout.invalidate()
    margins = window_layout.contentsMargins()
    overhead = margins.left() + margins.right()
    bar = tab_bar.sizeHint().width()
    chrome = tabs.sizeHint().width() - max(
        [page.sizeHint().width() for page in pages] + [tab_bar.sizeHint().width()])

    rows = [("tabs_bar", bar + chrome + overhead)]
    rows += [(name, page.sizeHint().width() + chrome + overhead)
             for name, page in zip(("clock_tab", "exclusions_tab", "system_tab"), pages)]
    # sizeHint asks what the text needs; width() tells how the layout shared it out. Pinned
    # or stretched widgets need the first, the delta rows below need the second.
    toggles = [b.sizeHint().width() for b in (probe._fmt_24h, probe._fmt_ampm,
                                              probe._fmt_seconds, probe._fmt_leading)]
    rows += [(f"clock_setting {i}", width) for i, width in enumerate(toggles, 1)]
    fmt_box = probe._fmt_24h.parentWidget()
    box_layout = fmt_box.layout() if fmt_box is not None else None
    if fmt_box is None or box_layout is None:
        fatal("the time-format toggles are not in a laid-out box")
    # contentsRect, not width(): a native group box keeps its frame in the widget's own
    # margins, and the layout lives inside what is left.
    box_margins = box_layout.contentsMargins()
    inner = fmt_box.contentsRect().width()
    BOX.update(box=inner, left=box_margins.left(), right=box_margins.right())
    MEASURED["clock_setting sum"] = inner - box_margins.left() - box_margins.right()
    rows.append(("clock_setting sum", sum(toggles)))

    form_labels = expect([w for w in pages[0].findChildren(QLabel)
                          if w.minimumWidth() == _LABEL_COL_W],
                         None, "form labels pinned to _LABEL_COL_W")
    rows += [(f"clock_bar_text {i}",
              QFontMetrics(w.font()).horizontalAdvance(w.text()) + _COMBO_TEXT_INSET)
             for i, w in enumerate(form_labels, 1)]

    paired = {i18n.S.tabs.exclusions.add_current, i18n.S.tabs.exclusions.add_other}
    buttons = expect([b for b in pages[1].findChildren(QPushButton) if b.text() in paired],
                     2, "Exclusions buttons")
    rows.append(("exclusions_btn", max(b.sizeHint().width() for b in buttons)))
    BOX["btn_chrome"] = min(b.sizeHint().width()
                            - QFontMetrics(b.font()).horizontalAdvance(b.text())
                            for b in buttons)

    reset = [b.width() for b in probe._reset_group.findChildren(QPushButton)]
    rows += [(f"reset_btn {i}", width) for i, width in enumerate(reset, 1)]
    rows.append(("reset_btn delta", max(reset) - min(reset)))
    pair = [b.width() for b in expect([b for b in probe._about_column.findChildren(QPushButton)
                                       if not isinstance(b, _SupportButton)],
                                      2, "About buttons besides Donate")]
    rows += list(zip(("issue_btn", "rate_btn"), pair))
    rows.append(("issue_rate_btn delta", max(pair) - min(pair)))

    # Every place a monitor can have, not this PC's: the name gives way, the place must fit.
    display = i18n.S.tabs.system.display
    combo = probe._monitor_combo
    places = [_position_text(r, c) for r in monitors.ROWS for c in monitors.COLUMNS]
    places += [display.positions.too_many, display.positions.unplugged]
    fm = QFontMetrics(combo.font())
    longest = max(fm.horizontalAdvance(display.monitor_entry.format(name="", position=p))
                  for p in places)
    rows += [("monitor_place", longest), ("monitor_field", combo.text_width()),
             ("monitor_place excess", longest - combo.text_width())]

    tallest = max(page.sizeHint().height() for page in pages)
    v_chrome = tabs.sizeHint().height() - tallest
    v_overhead = margins.top() + margins.bottom()
    rows.append(("client_height", tallest + v_chrome + v_overhead))
    return rows


def probe_language(code: str, config: Config) -> list[tuple[str, int]]:
    i18n.set_language(code)
    probe = SettingsWindow(QGuiApplication.screens)
    probe.load(config)
    probe.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    probe.show()
    for index in range(probe._tabs.count()):
        probe._tabs.setCurrentIndex(index)
        QGuiApplication.processEvents()
    rows = measure(probe)
    probe.close()
    return rows


def render(table: dict[str, dict[str, int]], codes: list[str], color: bool) -> str:
    def paint(text: str, code: str) -> str:
        return f"{code}{text}{OFF}" if color and code else text

    measures: list[str] = []
    for rows in table.values():
        for name in rows:
            if name not in measures:
                measures.append(name)

    pad = max(len(name) for name in measures) + 2
    lines = [" " * pad + "".join(f"{c.upper():>6}" for c in codes) + f"  {'LIMIT':>6}"]
    for name in measures:
        if name in ("clock_setting 1", "clock_bar_text 1", "exclusions_btn",
                    "reset_btn 1", "issue_btn", "client_height"):
            lines.append("")
        limit, automatic = limit_for(name)
        values = [table[c].get(name) for c in codes]
        worst = max((v for v in values if v is not None), default=None)
        cells = ""
        for value in values:
            if value is None:
                cells += " " * 6
                continue
            if limit is None:
                cells += f"{value:>6}"
                continue
            over = value > limit
            ink = (RED if over else GREEN) if value == worst else (YELLOW if over else "")
            cells += " " * (6 - len(str(value))) + paint(str(value), ink)
        shown = str(limit) if limit else ""
        lines.append(f"{name:<{pad}}" + cells + "  " + " " * (6 - len(shown))
                     + (paint(shown, BOLD) if automatic else shown))
    return "\n".join(lines)


def over_limit(table: dict[str, dict[str, int]], codes: list[str]) -> list[str]:
    """Every cell over its limit, as "measure [lang] value > limit"."""
    broken = []
    for code in codes:
        for name, value in table[code].items():
            limit, _ = limit_for(name)
            if limit is not None and value > limit:
                broken.append(f"{name} [{code}] {value} > {limit}")
    return broken


def main() -> int:
    step("Checking that every language fits the settings window")
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    app = QApplication(sys.argv)
    # The limits are written for the default text size: measure at it, whatever Windows'
    # "Text size" is on this machine.
    font = app.font()
    font.setPointSizeF(DEFAULT_FONT_PT)
    app.setFont(font)
    # The widest content, not whatever this PC happens to show: the "current app" preview's
    # "no app" message, and autostart's blocked row (text and button) instead of its checkbox.
    win32.app_below = lambda _hwnd: ("", "")
    startup.is_blocked = lambda: True
    config = Config.default()
    codes = [c for c, _ in i18n.available()]
    codes = [c for c in ("en", "it") if c in codes] + sorted(
        c for c in codes if c not in ("en", "it"))
    table = {code: dict(probe_language(code, config)) for code in codes}
    if verbose:
        print(f"fixed window: {_CLIENT_W} px   |   time format box: {BOX['box']} px "
              f"- margins {BOX['left']}+{BOX['right']} = {MEASURED['clock_setting sum']} px "
              f"of room\n"
              f"exclusions buttons: {_EXCLUSIONS_BTN_W} px wide, of which {BOX['btn_chrome']} is "
              f"chrome -> {_EXCLUSIONS_BTN_W - BOX['btn_chrome']} px for the label\n")
        print(render(table, codes, color=sys.stdout.isatty()) + "\n", flush=True)
    broken = over_limit(table, codes)
    if broken:
        fail("some languages do not fit the settings window", broken)
        if not verbose:
            info("run with --verbose for the full table")
        app.quit()
        return 1
    ok(f"{len(codes)} languages fit {_CLIENT_W}x{_CLIENT_H}")
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
