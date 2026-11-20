"""Test bootstrap for the desktop client.

Puts both ``client/`` and ``shared/`` on ``sys.path`` and points every writable
location at a temporary directory so no test can ever touch the real game
folder or the real ``%LOCALAPPDATA%``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Qt must run headless in CI / this sandbox.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client"
SHARED = ROOT / "shared"
for _path in (CLIENT, SHARED):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

FIXTURES = SHARED / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect app data + game dirs into ``tmp_path`` for every test."""
    data_dir = tmp_path / "appdata"
    game_dir = tmp_path / "game" / "FindTheNeedle"
    monkeypatch.setenv("FTNLIB_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FTNLIB_GAME_DIR", str(game_dir))
    return {"data": data_dir, "game": game_dir, "blueprints": game_dir / "blueprints"}


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def sample_bytes() -> bytes:
    return (FIXTURES / "1794502162_4776.blueprint").read_bytes()


@pytest.fixture(scope="session")
def qapp():
    """A single ``QApplication`` for the whole test session."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()
