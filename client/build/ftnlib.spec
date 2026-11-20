# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the FTN Blueprint Library desktop client.

Build from the repository root::

    pyinstaller client/build/ftnlib.spec

Produces ``client/dist/FTNBlueprintLibrary/FTNBlueprintLibrary.exe`` (one-dir,
windowed). The shared ``ftn_blueprint`` codec is vendored in so the frozen app
never needs the source tree.
"""

import os

SPEC_DIR = os.path.abspath(SPECPATH)
CLIENT_DIR = os.path.abspath(os.path.join(SPEC_DIR, ".."))
ROOT_DIR = os.path.abspath(os.path.join(CLIENT_DIR, ".."))
SHARED_DIR = os.path.join(ROOT_DIR, "shared")

APP_NAME = "FTNBlueprintLibrary"
ICON = os.path.join(CLIENT_DIR, "app", "assets", "app.ico")

# PyInstaller loads the version resource itself when given a path. ``version_info.txt``
# is a bare ``VSVersionInfo(...)`` expression, so it must not be exec'd here.
_VERSION_FILE = os.path.join(SPEC_DIR, "version_info.txt")
version_info = _VERSION_FILE if os.path.isfile(_VERSION_FILE) else None

a = Analysis(
    [os.path.join(CLIENT_DIR, "run.py")],
    pathex=[CLIENT_DIR, SHARED_DIR],
    binaries=[],
    datas=[
        (os.path.join(CLIENT_DIR, "app", "themes"), "app/themes"),
        (os.path.join(CLIENT_DIR, "app", "assets"), "app/assets"),
    ],
    hiddenimports=[
        "ftn_blueprint",
        "ftn_blueprint.variant",
        "ftn_blueprint.blueprint",
        "ftn_blueprint.preview",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON if os.path.isfile(ICON) else None,
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
