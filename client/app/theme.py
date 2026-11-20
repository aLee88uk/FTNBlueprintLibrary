"""Theme loading: palettes from JSON + one shared QSS template.

Three named themes ship with the client (``needlework_light``, ``midnight_yard``
and ``harvest_warm``) plus a ``system`` option that follows the OS colour scheme.
A single ``base.qss`` template is rendered against the chosen palette so the
three themes can never drift apart.
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

__all__ = [
    "THEMES_DIR",
    "THEME_NAMES",
    "SYSTEM_THEME",
    "load_palettes",
    "palette_for",
    "resolve_theme",
    "build_stylesheet",
    "apply_theme",
    "preview_theme_for",
]

if getattr(sys, "frozen", False):  # pragma: no cover - PyInstaller layout
    _PACKAGE_DIR = Path(getattr(sys, "_MEIPASS", "")) / "app"
else:
    _PACKAGE_DIR = Path(__file__).resolve().parent

THEMES_DIR = _PACKAGE_DIR / "themes"
PALETTES_FILE = THEMES_DIR / "palettes.json"
BASE_QSS = THEMES_DIR / "base.qss"

SYSTEM_THEME = "system"

_THEME_NAMES = ("needlework_light", "midnight_yard", "harvest_warm")
THEME_NAMES = (SYSTEM_THEME, *_THEME_NAMES)

_TOKEN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@lru_cache(maxsize=1)
def load_palettes() -> dict[str, dict]:
    """Load and cache ``palettes.json``."""
    try:
        data = json.loads(PALETTES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def _template() -> str:
    try:
        return BASE_QSS.read_text(encoding="utf-8")
    except OSError:
        return ""


def system_theme() -> str:
    """Return the concrete theme matching the OS colour scheme."""
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt

        app = QGuiApplication.instance()
        if app is not None:
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return "midnight_yard"
            if scheme == Qt.ColorScheme.Light:
                return "needlework_light"
    except Exception:  # noqa: BLE001 - Qt may be absent in headless tests
        pass
    return "needlework_light"


def resolve_theme(name: str | None) -> str:
    """Map ``system`` (or an unknown name) to a concrete palette key."""
    if not name or name == SYSTEM_THEME:
        return system_theme()
    if name in load_palettes():
        return name
    return "needlework_light"


def palette_for(name: str | None) -> dict:
    """Return the palette dict for a (possibly ``system``) theme name."""
    palettes = load_palettes()
    resolved = resolve_theme(name)
    return palettes.get(resolved) or palettes.get("needlework_light") or {}


def preview_theme_for(name: str | None) -> str:
    """The ``render_svg`` theme (``dark``/``light``) that matches a UI theme."""
    palette = palette_for(name)
    return "dark" if palette.get("dark") else "light"


def build_stylesheet(name: str | None) -> str:
    """Render ``base.qss`` with the palette for ``name``."""
    palette = palette_for(name)
    template = _template()
    if not template or not palette:
        return template

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = palette.get(key)
        return str(value) if value is not None else match.group(0)

    return _TOKEN.sub(replace, template)


def apply_theme(app, name: str | None) -> str:
    """Apply the stylesheet to ``app``; returns the concrete theme used."""
    resolved = resolve_theme(name)
    app.setStyleSheet(build_stylesheet(resolved))
    return resolved
