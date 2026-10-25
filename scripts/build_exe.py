"""Builds the app into a onedir exe with PyInstaller, from FullscreenOverlayClock.spec.

One mode required:
  --dev      reuses PyInstaller's cache
  --release  clean build
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _output import fail, fix, handoff, ok, run_indented, step, steps

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from src import APP_NAME

EXE_NAME = APP_NAME.replace(" ", "")
SPEC = ROOT / "FullscreenOverlayClock.spec"
DIST = ROOT / "dist" / "exe"
EXE = DIST / EXE_NAME / f"{EXE_NAME}.exe"
CHECKS = (
    ["check_i18n.py"],
    ["check_sizes.py"],
    ["icons.py", "verify"],
    ["licenses.py", "verify"],
)


def _is_dev() -> bool:
    modes = {a for a in sys.argv[1:] if a in ("--dev", "--release")}
    if len(modes) != 1:
        raise SystemExit("Usage: build_exe.py --dev | --release")
    return modes.pop() == "--dev"


def _check_dependencies() -> int:
    step("Checking that every import in src/ is a declared dependency (deptry)")
    rc = run_indented([sys.executable, "-m", "deptry", "--no-ansi", "src"], ROOT)
    if rc != 0:
        fail("dependencies do not match pyproject.toml")
        fix("fix pyproject.toml as deptry says above")
        return rc
    ok("every import is declared")
    return 0


def main() -> int:
    dev = _is_dev()
    steps(len(CHECKS) + 2, "Building the exe (dev)" if dev else "Building the exe (release)")
    rc = _check_dependencies()
    if rc != 0:
        return rc
    for script, *args in CHECKS:
        rc = subprocess.run([sys.executable, str(HERE / script), *args], cwd=ROOT,
                            env=handoff()).returncode
        if rc != 0:
            return rc
    flags = ["--noconfirm", "--log-level", "WARN", "--distpath", str(DIST),
             "--workpath", str(ROOT / "build" / "exe")] + ([] if dev else ["--clean"])
    step("Running PyInstaller (cache reused)" if dev else "Running PyInstaller (clean)")
    rc = run_indented([sys.executable, "-m", "PyInstaller", *flags, str(SPEC)], ROOT)
    if rc != 0:
        fail("PyInstaller failed")
        return rc
    ok(f"{EXE.relative_to(ROOT)} built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
