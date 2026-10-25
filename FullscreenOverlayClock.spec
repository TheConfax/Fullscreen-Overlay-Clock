import sys
from fnmatch import fnmatch
from pathlib import Path, PurePath

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)  # pyright: ignore[reportUndefinedVariable]
sys.path.insert(0, str(ROOT))
from src import APP_NAME, AUTHOR, COPYRIGHT_YEAR, __version__

EXE_NAME = APP_NAME.replace(" ", "")

# Bundled by the PyQt6 hook but never loaded by the app.
DROP = [
    "PyQt6/Qt6/bin/opengl32sw.dll",                     # software OpenGL: everything is QPainter
    "PyQt6/Qt6/translations/*",                         # Qt's own .qm: only qtbase is loaded
    "PyQt6/Qt6/plugins/imageformats/*",                 # only .ico loads; PNG is built into QtGui
    "PyQt6/Qt6/bin/Qt6Pdf.dll",                         # only the qpdf image plugin needs it
    "PyQt6/Qt6/bin/Qt6Network.dll",                     # only Qt6Pdf and the TUIO plugin need it
    "PyQt6/Qt6/plugins/generic/qtuiotouchplugin.dll",   # TUIO network multitouch
    "PyQt6/Qt6/plugins/platforms/qminimal.dll",         # windowless: only qwindows runs
    "PyQt6/Qt6/plugins/platforms/qoffscreen.dll",       # windowless: only qwindows runs
]
KEEP = {
    "PyQt6/Qt6/plugins/imageformats/qico.dll",
    # Qt's own strings in each of our languages
    *(f"PyQt6/Qt6/translations/qtbase_{p.stem}.qm"
      for p in (ROOT / "src" / "i18n").glob("*.json") if p.stem != "en"),
}


def _dropped(entry) -> bool:
    dest = PurePath(entry[0]).as_posix()
    return dest not in KEEP and any(fnmatch(dest, p) for p in DROP)


def _version_file() -> str:
    v = [int(p) for p in __version__.split(".") if p.isdigit()]
    v = tuple((v + [0] * 4)[:4])
    copyright = f"© {COPYRIGHT_YEAR} {AUTHOR}"
    path = Path(workpath) / "version.txt"  # pyright: ignore[reportUndefinedVariable]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('000004B0', [
      StringStruct('CompanyName', '{AUTHOR}'),
      StringStruct('LegalCopyright', '{copyright}'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', '{EXE_NAME}'),
      StringStruct('OriginalFilename', '{EXE_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [0, 1200])])
  ]
)
""", encoding="utf-8")
    return str(path)


a = Analysis(
    [str(ROOT / "src" / "main.py")],
    pathex=[str(ROOT)],
    hiddenimports=collect_submodules("src"),
    datas=[
        (str(ROOT / "src" / "resources"), "src/resources"),
        (str(ROOT / "src" / "i18n" / "*.json"), "src/i18n"),
        (str(ROOT / "pyproject.toml"), "."),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "THIRD_PARTY_LICENSES"), "."),
    ],
    # Re-including one means restoring its credit in licenses/python-*-thirdparty.txt.
    excludes=["ssl", "_ssl", "_hashlib", "multiprocessing", "bz2", "lzma", "compression.zstd",
              "decimal"],
)
a.binaries = [b for b in a.binaries if not _dropped(b)]
a.datas = [d for d in a.datas if not _dropped(d)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=EXE_NAME,
    icon=str(ROOT / "src" / "resources" / "icon.ico"),
    version=_version_file(),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=EXE_NAME)
