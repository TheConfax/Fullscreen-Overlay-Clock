"""Console output shared by the scripts: one layout and one color scheme for all of them."""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Iterable
from pathlib import Path
from typing import NoReturn

_COLUMN = 5
_BOLD, _CYAN, _GREEN, _RED, _YELLOW, _RESET = (
    "\033[1m", "\033[36m", "\033[32m", "\033[31m", "\033[33m", "\033[0m")
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STEP_ENV = "SCRIPTS_STEP"  # "n/total", set by handoff() in the parent script

_total = 0
_count = 0
if _STEP_ENV in os.environ:
    _n, _, _t = os.environ.pop(_STEP_ENV).partition("/")
    _count, _total = int(_n) - 1, int(_t)


def _enable_color() -> bool:
    if not sys.stdout.isatty():
        return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False
    return bool(kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))


def _pick_bullet() -> str:
    try:
        "\N{BULLET}".encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return "*"
    return "\N{BULLET}"


_COLOR = _enable_color()
_BULLET = _pick_bullet()


def _paint(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}" if _COLOR else text


def _line(word: str, color: str, text: str) -> None:
    painted = _paint(word, color) if color else word
    first, *rest = _wrap(text)
    print(f"{painted}{' ' * (_COLUMN - len(word))}{first}", flush=True)
    for piece in rest:
        print(f"{' ' * _COLUMN}{piece}", flush=True)


def _items(items: Iterable[str]) -> None:
    for item in items:
        first, *rest = _wrap(item, _COLUMN + 2)
        print(f"{' ' * _COLUMN}{_BULLET} {first}", flush=True)
        for piece in rest:
            print(f"{' ' * (_COLUMN + 2)}{piece}", flush=True)


def steps(total: int, title: str) -> None:
    """Print the script's title, then number the next step() lines [n/total].

    Without it they carry no counter."""
    global _total
    _total = total
    print(_paint(f"{title}...", _BOLD + _CYAN), flush=True)


def step(text: str) -> None:
    global _count
    if _count:
        print(flush=True)
    _count += 1
    if _total > 1:
        print(_paint(f"[{_count}/{_total}] {text}...", _CYAN), flush=True)
    else:  # no title above it: this step is the heading
        print(_paint(f"{text}...", _BOLD + _CYAN), flush=True)


def handoff() -> dict[str, str]:
    """Environment for a child script whose own step() takes the next number of ours."""
    global _count
    _count += 1
    return {**os.environ, _STEP_ENV: f"{_count}/{_total}"}


def run_indented(command: list[str], cwd: Path) -> int:
    """Run an external tool with its output moved into the text column; returns its exit code."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}  # a piped Python child would print in bursts
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, errors="replace") as process:
        for line in process.stdout or ():
            for piece in _wrap(line.rstrip()):
                print(f"{' ' * _COLUMN}{piece}" if piece else "", flush=True)
    return process.returncode


def _wrap(line: str, indent: int = _COLUMN) -> list[str]:
    """line cut to the terminal's current width, so the terminal never wraps it back to column 0."""
    if not line or not sys.stdout.isatty():
        return [line]
    room = shutil.get_terminal_size().columns - indent - 1
    if room < 20:
        return [line]
    return textwrap.wrap(line, room, break_on_hyphens=False) or [line]


def ok(text: str) -> None:
    _line("OK", _GREEN, text)


def fail(text: str, items: Iterable[str] = ()) -> None:
    _line("FAIL", _RED, text)
    _items(items)


def fix(text: str) -> None:
    _line("FIX", _CYAN, text)


def warn(text: str, items: Iterable[str] = ()) -> None:
    _line("WARN", _YELLOW, text)
    _items(items)


def info(text: str) -> None:
    _line("INFO", "", text)


def pause() -> None:
    try:
        input(f"{' ' * _COLUMN}Press Enter to continue the build...")
    except EOFError:  # no console to wait on (isatty lies about NUL on Windows)
        print(flush=True)


def fatal(text: str, remedy: str = "") -> NoReturn:
    """fail() + fix(), then exit 1."""
    fail(text)
    if remedy:
        fix(remedy)
    raise SystemExit(1)
