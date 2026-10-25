"""Produces every icon the project ships, from the masters in media/icons/prod.

Two commands:
  build    rewrite icons_msix/ + src/resources/icon.ico from the masters
  verify   redo the work in memory and fail if what is on disk differs

Without media/ verify still checks that every file the lists call for is there and that
nothing else is, byte comparisons against the artwork are skipped.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from _output import fail, fatal, fix, info, ok, step

ROOT = Path(__file__).resolve().parent.parent
MASTERS = ROOT / "media" / "icons" / "prod"
ICONS = ROOT / "icons_msix"
ICO = ROOT / "src" / "resources" / "icon.ico"

TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256)
ALTFORMS = ("", "_altform-unplated", "_altform-lightunplated")
SCALES = (100, 125, 150, 200, 400)
FAMILIES = {
    "Square44x44Logo": {100: 44, 125: 55, 150: 66, 200: 88, 400: 176},
    "Square150x150Logo": {100: 150, 125: 188, 150: 225, 200: 300, 400: 600},
    "StoreLogo": {100: 50, 125: 63, 150: 75, 200: 100, 400: 200},
}
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 256)

_bytes: dict[Path, bytes] = {}


def _master(px: int) -> Path:
    path = MASTERS / f"icon_{px}.png"
    if not path.exists():
        fatal(f"missing master: {path}")
    return path


def _master_bytes(px: int) -> bytes:
    path = _master(px)
    if path not in _bytes:
        _bytes[path] = path.read_bytes()
    return _bytes[path]


def _plan() -> dict[str, int]:
    """Every file icons_msix/ must hold -> the master size it is copied from."""
    plan = {}
    for px in TARGET_SIZES:
        for altform in ALTFORMS:
            plan[f"Square44x44Logo.targetsize-{px}{altform}.png"] = px
    for name, sizes in FAMILIES.items():
        for scale in SCALES:
            plan[f"{name}.scale-{scale}.png"] = sizes[scale]
        plan[f"{name}.png"] = sizes[100]
    return plan


def _dib(path: Path, size: int) -> bytes:
    """32-bit .ico frame: height doubled for the AND mask, rows bottom-up."""
    from PyQt6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull():
        fatal(f"cannot read {path}")
    if image.width() != size or image.height() != size:
        fatal(f"{path} is {image.width()}x{image.height()}, expected {size}")
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    stride = image.bytesPerLine()
    raw = image.bits().asstring(image.sizeInBytes())

    out = bytearray(struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                                size * size * 4, 0, 0, 0, 0))
    for y in range(size - 1, -1, -1):
        out += raw[y * stride:y * stride + size * 4]
    mask_row = ((size + 31) // 32) * 4
    out += bytes(mask_row * size)
    return bytes(out)


def _ico() -> bytes:
    frames = [(px, _master_bytes(px) if px >= 256 else _dib(_master(px), px))
              for px in ICO_SIZES]
    out = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    offset = 6 + 16 * len(frames)
    for px, data in frames:
        dim = 0 if px >= 256 else px
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in frames:
        out += data
    return bytes(out)


def build() -> int:
    step("Building the icons from the masters")
    if not MASTERS.is_dir():
        fatal(f"missing masters: {MASTERS}", "restore them from a backup, they live outside the repo")
    plan = _plan()
    ICONS.mkdir(parents=True, exist_ok=True)

    for name, px in plan.items():
        (ICONS / name).write_bytes(_master_bytes(px))

    data = _ico()
    ICO.write_bytes(data)

    stale = sorted(p for p in ICONS.glob("*.png") if p.name not in plan)
    for path in stale:
        path.unlink()
        info(f"removed stale {path.name}")

    ok(f"{len(plan)} assets -> {ICONS.name}/, {len(ICO_SIZES)} frames -> "
       f"{ICO.name} ({len(data) / 1024:.1f} KB)")
    return 0


def verify() -> int:
    step("Checking the icons against the masters")
    plan = _plan()
    problems = []
    absent = sorted({px for px in (*plan.values(), *ICO_SIZES)
                     if not (MASTERS / f"icon_{px}.png").exists()}) if MASTERS.is_dir() else []
    problems += [f"missing master: icon_{px}.png" for px in absent]
    compare = MASTERS.is_dir() and not absent

    for name, px in sorted(plan.items()):
        path = ICONS / name
        if not path.exists():
            problems.append(f"missing: {ICONS.name}/{name}")
        elif compare and path.read_bytes() != _master_bytes(px):
            problems.append(f"does not match icon_{px}.png: {ICONS.name}/{name}")

    for path in sorted(ICONS.glob("*.png")):
        if path.name not in plan:
            problems.append(f"not one of ours, would ship anyway: {path.name}")

    rel = ICO.relative_to(ROOT).as_posix()
    if not ICO.exists():
        problems.append(f"missing: {rel}")
    elif compare and ICO.read_bytes() != _ico():
        problems.append(f"does not match the masters: {rel}")

    if problems:
        fail("icons out of date", problems)
        if absent:
            fix("restore the missing masters from a backup, they live outside the repo")
        elif compare:
            fix("python scripts/icons.py build")
        return 1
    if compare:
        ok(f"{len(plan) + 1} icons checked")
    else:
        ok(f"{len(plan) + 1} icons present")
        info("no masters here, so the artwork itself was not compared")
    return 0


def main() -> int:
    commands = {a for a in sys.argv[1:] if a in ("build", "verify")}
    if len(commands) != 1:
        raise SystemExit("Usage: icons.py build | verify")
    return build() if commands.pop() == "build" else verify()


if __name__ == "__main__":
    sys.exit(main())
