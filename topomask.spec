# SPDX-License-Identifier: Apache-2.0
# PyInstaller spec for the Windows desktop app: PyInstaller --noconfirm --clean topomask.spec
# ruff: noqa: F821

import sys
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH)
sys.path.insert(0, str(ROOT / "src"))
from topomask import __version__, draw_icon  # noqa: E402

BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)
ICON = BUILD / "topomask.ico"
draw_icon(256).save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

numbers = (*(int(x) for x in __version__.split(".")), 0)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=numbers,
        prodvers=numbers,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("FileDescription", "topomask"),
                        StringStruct("FileVersion", __version__),
                        StringStruct("InternalName", "topomask"),
                        StringStruct("LegalCopyright", "Apache-2.0"),
                        StringStruct("OriginalFilename", "topomask.exe"),
                        StringStruct("ProductName", "topomask"),
                        StringStruct("ProductVersion", __version__),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
VERSION_FILE = BUILD / "version_info.txt"
VERSION_FILE.write_text(str(version_info), encoding="utf-8")

a = Analysis(
    [str(ROOT / "src" / "topomask.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "topomask.html"), ".")],
    hiddenimports=["pystray._win32"],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="topomask",
    console=False,
    upx=False,
    icon=str(ICON),
    version=str(VERSION_FILE),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="topomask")
