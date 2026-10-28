"""Packs the PyInstaller onedir build into an MSIX.

One mode required:
  --dev      self-signed
  --release  unsigned
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from _output import fail, fatal, fix, handoff, info, ok, run_indented, step, steps, warn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from src import (APP_NAME, APPLICATION_ID, AUTHOR, DESCRIPTION, PACKAGE_ID, PUBLISHER,
                 STARTUP_TASK_ID, __version__)

EXE_NAME = APP_NAME.replace(" ", "")
BUILD = ROOT / "dist" / "exe" / EXE_NAME
MANIFEST = ROOT / "AppxManifest.xml"
ICONS = ROOT / "icons_msix"
STAGING = ROOT / "build" / "msix" / "package"
OUT_DIR = ROOT / "dist" / "msix"
TOOLS = ROOT / "sdk"
STAMP = TOOLS / "sdk-version.txt"
SDK_FEED = "https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools"
SDK_VERSION = ""    # pin a version here to freeze it; empty = latest
MAKEAPPX = TOOLS / "makeappx.exe"
MAKEPRI = TOOLS / "makepri.exe"
SIGNTOOL = TOOLS / "signtool.exe"
CERT_STORE = "Cert:\\CurrentUser\\My"
DISPLAY_NAME = APP_NAME


def _is_dev() -> bool:
    modes = {a for a in sys.argv[1:] if a in ("--dev", "--release")}
    if len(modes) != 1:
        raise SystemExit("Usage: build_msix.py --dev | --release")
    return modes.pop() == "--dev"


if _is_dev():
    PUBLISHER = f"CN={APP_NAME} - Dev"
    DISPLAY_NAME = f"{APP_NAME} - Dev"


def _latest_sdk() -> str | None:
    try:
        with urllib.request.urlopen(f"{SDK_FEED}/index.json", timeout=15) as response:
            stable = [v for v in json.load(response)["versions"] if "-" not in v]
        return stable[-1] if stable else None
    except OSError:
        return None


def _download_sdk(version: str) -> None:
    url = f"{SDK_FEED}/{version}/microsoft.windows.sdk.buildtools.{version}.nupkg"
    info(f"downloading SDK BuildTools {version}")
    with urllib.request.urlopen(url) as response:
        blob = io.BytesIO(response.read())
    if TOOLS.exists():
        shutil.rmtree(TOOLS)
    with zipfile.ZipFile(blob) as archive:
        inside = [n for n in archive.namelist() if re.match(r"bin/[^/]+/x64/.+", n)]
        if not inside:
            fatal("no bin/<sdk>/x64 in the NuGet package - did the layout change?")
        prefix = inside[0].split("/x64/")[0] + "/x64/"
        for name in inside:
            target = TOOLS / name[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    STAMP.write_text(version, encoding="utf-8")


def _ensure_tools() -> None:
    have = STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else None
    wanted = SDK_VERSION or _latest_sdk()
    if wanted is None:
        if have and MAKEAPPX.exists():
            warn(f"nuget.org unreachable, keeping SDK BuildTools {have}")
            ok(f"SDK BuildTools {have}")
            return
        fatal("no SDK BuildTools on disk and nuget.org is unreachable",
              "connect to the internet and run it again")
    if have != wanted or not MAKEAPPX.exists():
        _download_sdk(wanted)
    ok(f"SDK BuildTools {wanted}")


def _package_version() -> str:
    parts = [p for p in __version__.split(".") if p.isdigit()]
    parts += ["0"] * (3 - len(parts))
    return ".".join(parts[:3]) + ".0"


def _identity(manifest: Path) -> str:
    match = re.search(r"<Identity\b[^>]*>", manifest.read_text(encoding="utf-8"))
    if match is None:
        fatal(f"no <Identity> element in {manifest}")
    return match.group(0)


def _sub(text: str, pattern: str, replacement: str, what: str, count: int = 1) -> str:
    out, n = re.subn(pattern, lambda _: replacement, text, flags=re.S)
    if n != count:
        fatal(f"expected {count}x {what} in the manifest, found {n}")
    return out


def _stamp_manifest(manifest: Path, version: str) -> None:
    """Write the product identity into the staged manifest.

    The checked-in manifest holds inert placeholders: pyproject.toml is where these
    are edited.
    """
    identity = _identity(manifest)
    stamped = _sub(identity, r'Version="[^"]*"', f'Version="{version}"', "Version in <Identity>")
    stamped = _sub(stamped, r'Name="[^"]*"', f"Name={quoteattr(PACKAGE_ID)}",
                   "Name in <Identity>")
    stamped = _sub(stamped, r'Publisher="[^"]*"', f"Publisher={quoteattr(PUBLISHER)}",
                   "Publisher in <Identity>")
    text = manifest.read_text(encoding="utf-8").replace(identity, stamped)
    text = _sub(text, r"<PublisherDisplayName>.*?</PublisherDisplayName>",
                f"<PublisherDisplayName>{escape(AUTHOR)}</PublisherDisplayName>",
                "PublisherDisplayName")
    text = _sub(text, r"<Description>.*?</Description>",
                f"<Description>{escape(DESCRIPTION)}</Description>", "<Description>")
    text = _sub(text, r'Description="[^"]*"',
                f"Description={quoteattr(DESCRIPTION)}", "Description attribute")
    text = _sub(text, r"<DisplayName>.*?</DisplayName>",
                f"<DisplayName>{escape(DISPLAY_NAME)}</DisplayName>", "<DisplayName>")
    text = _sub(text, r'DisplayName="[^"]*"', f"DisplayName={quoteattr(DISPLAY_NAME)}",
                "DisplayName attribute", count=2)
    text = _sub(text, r'Executable="[^"]*"', f'Executable="{EXE_NAME}.exe"',
                "Executable attribute", count=2)
    text = _sub(text, r'TaskId="[^"]*"', f"TaskId={quoteattr(STARTUP_TASK_ID)}", "TaskId")
    # \b keeps this off TaskId, which ends in the same three characters.
    text = _sub(text, r'\bId="[^"]*"', f"Id={quoteattr(APPLICATION_ID)}", "Application Id")
    manifest.write_text(text, encoding="utf-8")


def _stage() -> None:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    shutil.copytree(BUILD, STAGING)
    shutil.copy2(MANIFEST, STAGING)
    shutil.copytree(ICONS, STAGING / "icons")


def _make_pri() -> int:
    config = STAGING.parent / "priconfig.xml"
    rc = run_indented([str(MAKEPRI), "createconfig", "/cf", str(config),
                       "/dq", "en-US", "/o"], ROOT)
    if rc != 0:
        return rc
    text = config.read_text(encoding="utf-8")
    config.write_text(re.sub(r"\s*<packaging>.*?</packaging>", "", text, flags=re.S),
                      encoding="utf-8")
    return run_indented([str(MAKEPRI), "new", "/pr", str(STAGING), "/cf", str(config),
                         "/of", str(STAGING / "resources.pri"), "/o"], ROOT)


def _ensure_cert(subject: str) -> int:
    ps = (
        f'$s = "{subject}"; '
        f'Get-ChildItem {CERT_STORE} | '
        'Where-Object { $_.Subject -eq $s -and $_.NotAfter -le (Get-Date) } | '
        'ForEach-Object { if ($_.HasPrivateKey) { Remove-Item -Path $_.PSPath -DeleteKey } '
        'else { Remove-Item -Path $_.PSPath } }; '
        f'if (-not (Get-ChildItem {CERT_STORE} | Where-Object {{ $_.Subject -eq $s }})) {{ '
        'Write-Host "minting a dev certificate ($s)"; '
        'New-SelfSignedCertificate -Type Custom -Subject $s -KeyUsage DigitalSignature '
        f'-FriendlyName "{APP_NAME} - Dev" -CertStoreLocation "{CERT_STORE}" '
        '-TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}") | Out-Null }'
    )
    return run_indented(["powershell", "-NoProfile", "-Command", ps], ROOT)


def _sign(msix: Path) -> int:
    subject = PUBLISHER
    rc = _ensure_cert(subject)
    if rc != 0:
        return rc
    # signtool /n matches the CN alone, not the whole subject.
    return run_indented([str(SIGNTOOL), "sign", "/fd", "SHA256", "/n", subject.removeprefix("CN="),
                         "/s", "My", str(msix)], ROOT)


def main() -> int:
    dev = _is_dev()
    steps(6 if dev else 5, "Packing the MSIX (dev)" if dev else "Packing the MSIX (release)")
    if not dev:
        # What the Store gets must match a commit of the public repo.
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                capture_output=True, text=True)
        if status.returncode != 0:
            fatal("git status failed", status.stderr.strip())
        dirty = status.stdout.splitlines()
        if dirty:
            fail("the working tree is not clean", dirty)
            fix("commit the changes, then pack again")
            return 1
    bundled = BUILD / "_internal" / "pyproject.toml"
    if not (BUILD / f"{EXE_NAME}.exe").exists() or not bundled.exists():
        fatal(f"missing {BUILD.relative_to(ROOT)}", "build the exe first")
    built = tomllib.loads(bundled.read_text(encoding="utf-8"))["project"]["version"]
    if built != __version__:
        fatal(f"{BUILD.relative_to(ROOT)} is {built}, pyproject.toml says {__version__}",
              "build the exe first")
    # The whole folder is staged as-is, so a stale or undeclared asset would ship silently.
    rc = subprocess.run([sys.executable, str(HERE / "icons.py"), "verify"], cwd=ROOT,
                        env=handoff()).returncode
    if rc != 0:
        return rc

    step("Getting the SDK BuildTools")
    _ensure_tools()

    version = _package_version()
    step(f"Staging {version}")
    _stage()
    _stamp_manifest(STAGING / "AppxManifest.xml", version)
    ok(f"{BUILD.relative_to(ROOT)} staged with the manifest and the icons")

    step("Building the resource index (makepri)")
    rc = _make_pri()
    if rc != 0:
        fail("makepri failed")
        return rc
    ok("resources.pri written")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    msix = OUT_DIR / f"{'dev-' if dev else ''}{EXE_NAME}-{__version__}.msix"
    shown = msix.relative_to(ROOT)
    step("Packing (makeappx)")
    rc = run_indented([str(MAKEAPPX), "pack", "/d", str(STAGING), "/p", str(msix), "/o"], ROOT)
    if rc != 0:
        fail("makeappx failed")
        return rc
    ok(f"{shown} packed")
    if not dev:
        info("unsigned: the Store signs it")
        return 0

    step("Signing with the dev certificate")
    rc = _sign(msix)
    if rc != 0:
        fail("signing failed")
        return rc
    ok(f"{shown} signed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
