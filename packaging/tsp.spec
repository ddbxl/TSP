# PyInstaller spec for TSP.
#
#     pip install pyinstaller
#     pyinstaller packaging/tsp.spec
#
# Writes dist/TSP/. Distribute the whole folder.

from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = ROOT / "assets" / "icon.ico"

a = Analysis(
    [str(ROOT / "src" / "tsp" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "assets" / "icon.png"), "assets"),
        (str(ROOT / "assets" / "icon.ico"), "assets"),
    ],
    hiddenimports=["tsp.gui", "tsp.cli", "tsp.core"],
    hookspath=[],
    runtime_hooks=[],
    # PyMuPDF imports these when they are present. TSP does not use them, so
    # excluding them keeps the build small.
    excludes=[
        "numpy",
        "pandas",
        "matplotlib",
        "PIL",
        "lxml",
        "cryptography",
        "setuptools",
        "pytest",
        "IPython",
        "sqlite3",
        "unittest",
        "pydoc_data",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TSP",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # no console window behind the GUI
    icon=str(ICON) if ICON.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TSP",
)
