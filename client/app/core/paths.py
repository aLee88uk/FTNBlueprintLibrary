"""Resolution of every directory and file the client touches.

Hard safety rule (see plan.txt): the app **only ever adds** ``.blueprint`` files
inside the game's ``blueprints/`` folder. Every other artefact we create lives
under :func:`app_data_dir` (``%LOCALAPPDATA%\\FTNBlueprintLibrary``).

Two environment variables exist purely to make the safety guarantees testable:

``FTNLIB_DATA_DIR``
    Override the app data directory (default ``%LOCALAPPDATA%\\FTNBlueprintLibrary``).
``FTNLIB_GAME_DIR``
    Override the game userdata directory (default
    ``%APPDATA%\\Godot\\app_userdata\\FindTheNeedle``).
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "APP_NAME",
    "GAME_DIR_NAME",
    "app_data_dir",
    "backups_dir",
    "blueprints_subdir",
    "default_blueprints_dir",
    "env_path",
    "game_userdata_dir",
    "index_path",
    "provenance_path",
    "resolve_blueprints_dir",
    "screenshot_cache_dir",
    "settings_path",
    "trash_subdir",
]

#: Folder shown in the game's Godot user data directory.
GAME_DIR_NAME = "FindTheNeedle"

#: Folder name used for our own application data.
APP_NAME = "FTNBlueprintLibrary"


def env_path(name: str) -> Path | None:
    """Return an environment variable as a :class:`Path`, or ``None`` if unset/empty."""
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def app_data_dir() -> Path:
    """Our private data directory (settings, cache, backups, provenance)."""
    override = env_path("FTNLIB_DATA_DIR")
    if override is not None:
        return override
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    # Non-Windows / unusual environments: follow the XDG spec.
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


def game_userdata_dir() -> Path:
    """The Godot user data directory that contains ``profile.cfg`` and ``blueprints/``."""
    override = env_path("FTNLIB_GAME_DIR")
    if override is not None:
        return override
    roaming = os.environ.get("APPDATA")
    if roaming:
        return Path(roaming) / "Godot" / "app_userdata" / GAME_DIR_NAME
    return Path.home() / ".local" / "share" / "godot" / "app_userdata" / GAME_DIR_NAME


def blueprints_subdir() -> str:
    """Name of the blueprint folder relative to the game user data directory."""
    return "blueprints"


def default_blueprints_dir() -> Path:
    """Where the game stores blueprints by default."""
    return game_userdata_dir() / blueprints_subdir()


def resolve_blueprints_dir(override: str | os.PathLike[str] | None = None) -> Path:
    """Return the effective blueprints directory.

    ``override`` (from settings) wins, then :func:`default_blueprints_dir`.
    """
    if override:
        return Path(override).expanduser()
    return default_blueprints_dir()


def trash_subdir(blueprints_dir: Path) -> Path:
    """The game's own recycle bin for deleted blueprints."""
    return Path(blueprints_dir) / ".trash"


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def index_path() -> Path:
    return app_data_dir() / "index.json"


def provenance_path() -> Path:
    return app_data_dir() / "provenance.json"


def backups_dir() -> Path:
    return app_data_dir() / "backups"


def screenshot_cache_dir() -> Path:
    """Disk cache for downloaded screenshots (see :mod:`core.screenshot_cache`)."""
    return app_data_dir() / "screenshot_cache"
