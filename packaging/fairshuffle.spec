# PyInstaller recipe for FairShuffle (D25: PyInstaller, one folder). A .spec file is Python that
# PyInstaller runs with Analysis, PYZ, EXE and COLLECT already defined. Build through
# scripts/build_exe.py, which also adds the license and .env.example and can zip the result:
#
#     uv run --group build python scripts/build_exe.py
#
# One folder (not one file) because it starts faster, unpacks nothing to a temp folder at each
# start (a pattern antivirus scanners distrust) and keeps the Qt DLLs as separate files, as
# PySide6's LGPL license expects. UPX compression is off: it is a common antivirus trigger.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821  # SPECPATH is set by PyInstaller
sys.path.insert(0, str(ROOT / "src"))

from fairshuffle import __version__  # noqa: E402

NAME = "FairShuffle"

a = Analysis(  # noqa: F821
    [str(ROOT / "src" / "fairshuffle" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    excludes=["tkinter", "unittest", "pydoc"],  # not used; keeps the folder smaller
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

version_info = None
if sys.platform == "win32":
    # The Details tab of the .exe's Properties shows these. Only Windows has the parts to write it.
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(int(part) for part in __version__.split(".")[:3]) + (0,)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",  # US English, Unicode
                        [
                            StringStruct("FileDescription", NAME),
                            StringStruct("FileVersion", __version__),
                            StringStruct("InternalName", NAME),
                            StringStruct("LegalCopyright", "MIT License"),
                            StringStruct("OriginalFilename", f"{NAME}.exe"),
                            StringStruct("ProductName", NAME),
                            StringStruct("ProductVersion", __version__),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,  # a tray app: no console window
    upx=False,
    version=version_info,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name=NAME,
    upx=False,
)
