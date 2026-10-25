"""Generates THIRD_PARTY_LICENSES from the build environment.

Two commands:
  build    regenerate the file
  verify   redo the work in memory and fail if what is on disk differs

Versions and license texts come from what PyInstaller bundles.
The texts no package carries live in licenses/.
"""
from __future__ import annotations

import difflib
import platform
import struct
import sys
import tomllib
from importlib import metadata
from pathlib import Path

from _output import fail, fatal, fix, ok, step

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "THIRD_PARTY_LICENSES"
TEXTS = ROOT / "licenses"
FONT = ROOT / "src" / "resources" / "pixeloid.sans-bold.ttf"
OPENTYPE_WINDOWS_PLATFORM = 3
OPENTYPE_VERSION_NAME = 5
SEP = "=" * 80


def _clean(text: str) -> str:
    # Trailing spaces dropped so an editor that trims them on save can't fail the check.
    text = text.lstrip("\N{BYTE ORDER MARK}").replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")


def _file(path: Path) -> str:
    return _clean(path.read_text(encoding="utf-8"))


def _text(name: str) -> str:
    return _file(TEXTS / name)


def _package_file(dist: str, name: str) -> str:
    text = metadata.distribution(dist).read_text(name)
    if text is None:
        fatal(f"{dist}: {name} not found in its metadata")
    return _clean(text)


def _section(title: str, body: str) -> str:
    return "\n".join([SEP, title, SEP, "", body])


def _v(dist: str) -> str:
    return metadata.version(dist)


def _versioned(name: str, version: str, kind: str) -> str:
    # Files are named name-version-kind: after an upgrade the build stops until the text is
    # checked against the new version and the file renamed.
    path = TEXTS / f"{name}-{version}-{kind}.txt"
    if not path.exists():
        fatal(f"{path.name} not found",
              f"check the {kind} text for {name} {version} and rename the file")
    return _file(path)


def _font_version(path: Path) -> str:
    data = path.read_bytes()
    for i in range(struct.unpack(">H", data[4:6])[0]):
        tag, _, offset, _ = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        if tag != b"name":
            continue
        _, count, strings = struct.unpack(">3H", data[offset:offset + 6])
        for j in range(count):
            platform_id, _, _, name_id, length, start = struct.unpack(
                ">6H", data[offset + 6 + 12 * j:offset + 18 + 12 * j])
            if platform_id == OPENTYPE_WINDOWS_PLATFORM and name_id == OPENTYPE_VERSION_NAME:
                at = offset + strings + start
                return data[at:at + length].decode("utf-16-be").removeprefix("Version ")
    fatal(f"{path.name}: no version in its name table")


def _components() -> list[tuple[str, list[str]]]:
    gpl = _package_file("PyQt6", "licenses/LICENSE")
    qt, hidapi, winrt = _v("PyQt6-Qt6"), _v("hidapi"), _v("winrt-runtime")
    python, font = platform.python_version(), _font_version(FONT)
    return [
        (f"PyQt6 {_v('PyQt6')}", [gpl]),
        (f"Qt {qt}", [_package_file("PyQt6-Qt6", "LICENSE"), gpl]),
        (f"Qt {qt} third-party components", [_versioned("qt", qt, "thirdparty")]),
        (f"PyQt6-sip {_v('PyQt6-sip')}", [_package_file("PyQt6-sip", "licenses/LICENSE")]),
        (f"hidapi {hidapi}", [_package_file("hidapi", "licenses/LICENSE-bsd.txt"),
                              _versioned("hidapi-c", hidapi, "BSD")]),
        (f"PyWinRT {winrt}", [_versioned("pywinrt", winrt, "MIT")]),
        (f"Python {python}", [_file(Path(sys.base_prefix) / "LICENSE.txt")]),
        (f"Python {python} third-party components", [_versioned("python", python, "thirdparty")]),
        (f"Pixeloid Sans {font}", [_versioned("pixeloid", font, "OFL")]),
    ]


def _header() -> str:
    qt = _v("PyQt6-Qt6")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return _text("header.txt").format(
        repo=project["urls"]["Repository"],
        qt=qt, qt_minor=".".join(qt.split(".")[:2]), pyqt=_v("PyQt6"))


def render() -> str:
    components = sorted(_components(), key=lambda c: c[0].casefold())
    sections = [_section(title, "\n\n\n".join(texts)) for title, texts in components]
    return "\n\n\n".join([_header(), *sections]) + "\n"


def build() -> int:
    step("Building the third-party licenses")
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    ok(f"{OUT.name} written")
    return 0


def verify() -> int:
    step("Checking the third-party licenses against the installed packages")
    expected = render()
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if current == expected:
        ok(f"{len(_components())} components checked")
        return 0
    diff = difflib.unified_diff(current.splitlines(), expected.splitlines(),
                                "current", "expected", lineterm="", n=0)
    fail(f"{OUT.name} is out of date", list(diff)[:12])
    fix("python scripts/licenses.py build")
    return 1


def main() -> int:
    commands = {a for a in sys.argv[1:] if a in ("build", "verify")}
    if len(commands) != 1:
        raise SystemExit("Usage: licenses.py build | verify")
    return build() if commands.pop() == "build" else verify()


if __name__ == "__main__":
    sys.exit(main())
