"""User settings persisted to ``%LOCALAPPDATA%\\FTNBlueprintLibrary\\settings.json``."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .core.paths import app_data_dir, settings_path

__all__ = ["Settings", "DEFAULT_API_BASE_URL", "DEFAULT_THEME", "SUPPORT_URL"]

#: Production server used by normal client launches.
DEFAULT_API_BASE_URL = "https://193-7-203-153.sslip.io"

#: Optional tip jar opened from the support popup. Entirely voluntary.
SUPPORT_URL = "https://buymeacoffee.com/alee88"

#: Theme applied on a fresh install, and the fallback for an invalid value.
DEFAULT_THEME = "harvest_warm"

#: Themes offered in Settings. ``system`` follows the OS palette.
THEMES: tuple[str, ...] = ("system", "needlework_light", "midnight_yard", "harvest_warm")


@dataclass
class Settings:
    """Everything the client persists between runs."""

    api_base_url: str = DEFAULT_API_BASE_URL
    blueprints_dir_override: str | None = None
    theme: str = DEFAULT_THEME
    grid_view: bool = True
    sort: str = "newest"
    #: Bearer token of the signed-in account (empty when signed out).
    auth_token: str = ""
    #: Cached username shown before the first server round-trip.
    auth_username: str = ""
    #: Remember whether we already showed the first-run hint.
    onboarded: bool = False
    window_geometry: str | None = None
    extra: dict = field(default_factory=dict)

    # -- (de)serialisation -------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """Read settings from disk, tolerating a missing or corrupt file."""
        path = path or settings_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        known = {f.name for f in fields(cls)}
        # Ignore any URL persisted by older versions. The public endpoint is
        # fixed in the app; only the env override below may change it.
        payload = {k: v for k, v in raw.items() if k in known and k != "api_base_url"}
        settings = cls(**payload)
        if settings.theme not in THEMES:
            settings.theme = DEFAULT_THEME
        # Optional env override so the client can be pointed at a different API.
        env_api = os.environ.get("FTNLIB_API_BASE_URL", "").strip()
        if env_api:
            settings.api_base_url = env_api
        return settings

    def save(self, path: Path | None = None) -> Path:
        """Write settings atomically; returns the path written."""
        path = path or settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = asdict(self)
        payload.pop("api_base_url", None)
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return path


def ensure_data_dir() -> Path:
    """Create our private data directory on first use."""
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory
