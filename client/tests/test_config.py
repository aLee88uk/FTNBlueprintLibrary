"""Settings persistence and path overrides."""

from __future__ import annotations

import json

from app.config import DEFAULT_API_BASE_URL, THEMES, Settings
from app.core import paths


def test_settings_roundtrip_ignores_saved_server_url(isolated_dirs, monkeypatch):
    monkeypatch.delenv("FTNLIB_API_BASE_URL", raising=False)
    settings = Settings()
    settings.theme = "midnight_yard"
    settings.api_base_url = "http://example.test"
    settings.grid_view = False
    path = settings.save(isolated_dirs["data"] / "settings.json")
    assert path.exists()
    loaded = Settings.load(path)
    assert loaded.theme == "midnight_yard"
    assert loaded.api_base_url == DEFAULT_API_BASE_URL
    assert loaded.grid_view is False
    assert "api_base_url" not in json.loads(path.read_text(encoding="utf-8"))


def test_local_launcher_can_override_fixed_server_url(isolated_dirs, monkeypatch):
    monkeypatch.setenv("FTNLIB_API_BASE_URL", "http://127.0.0.1:8123")
    assert Settings.load(isolated_dirs["data"] / "missing.json").api_base_url == "http://127.0.0.1:8123"


def test_settings_ignores_invalid_theme(isolated_dirs):
    path = isolated_dirs["data"] / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"theme": "neon-vaporwave"}', encoding="utf-8")
    assert Settings.load(path).theme == "harvest_warm"
    assert "harvest_warm" in THEMES


def test_settings_missing_and_corrupt(isolated_dirs, monkeypatch):
    monkeypatch.delenv("FTNLIB_API_BASE_URL", raising=False)
    assert Settings.load(isolated_dirs["data"] / "missing.json").api_base_url == DEFAULT_API_BASE_URL
    corrupt = isolated_dirs["data"] / "corrupt.json"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text("not json", encoding="utf-8")
    assert Settings.load(corrupt).theme == "harvest_warm"


def test_app_data_dir_uses_env(isolated_dirs):
    assert paths.app_data_dir() == isolated_dirs["data"]


def test_game_and_blueprint_dirs_use_env(isolated_dirs):
    assert paths.game_userdata_dir() == isolated_dirs["game"]
    assert paths.default_blueprints_dir() == isolated_dirs["blueprints"]
    assert paths.resolve_blueprints_dir(None) == isolated_dirs["blueprints"]


def test_resolve_blueprints_dir_override():
    assert str(paths.resolve_blueprints_dir(r"D:\Steam\FindTheNeedle\blueprints")).endswith("blueprints")


def test_trash_and_backups_paths(isolated_dirs):
    assert paths.trash_subdir(isolated_dirs["blueprints"]).name == ".trash"
    assert paths.backups_dir().parent == isolated_dirs["data"]
