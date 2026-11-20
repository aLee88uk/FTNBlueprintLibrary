"""Install identity.

The game writes an ``install_key`` (a 64-char hex digest) into
``profile.cfg`` under ``[identity]``. That key is the *only* thing that ties a
user to their account and uploads — there is no signup. When the file is missing
(the game has never been launched, or it is a non-retail copy) there is no
identity at all: we deliberately do **not** invent one, so the server refuses
account creation and uploads rather than attributing them to a made-up key.
"""

from __future__ import annotations

import re
from pathlib import Path

from .paths import game_userdata_dir

__all__ = ["read_install_key", "resolve_identity", "game_dir_for"]


def game_dir_for(blueprints_dir: str | Path | None = None) -> Path:
    """Return the game user data directory for a given blueprints folder.

    A user override points at ``.../blueprints``; its parent holds ``profile.cfg``.
    """
    if blueprints_dir is not None:
        return Path(blueprints_dir).expanduser().parent
    return game_userdata_dir()


_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_KEY_LINE_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")


def read_install_key(blueprints_dir: str | Path | None = None) -> str | None:
    """Read ``[identity] install_key`` from the game's ``profile.cfg``.

    Returns ``None`` when the file is missing, unreadable, or has no key.

    The game stores large multi-line JSON blobs (career stats, daily records)
    in the same file. Those continuation lines are *not* indented, which breaks
    :mod:`configparser`'s strict INI rules. We only need the single-line
    ``install_key`` entry, so we scan the file section-by-section ourselves
    instead of parsing the whole thing.
    """
    profile = game_dir_for(blueprints_dir) / "profile.cfg"
    try:
        text = profile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    current_section = ""
    for raw in text.splitlines():
        section = _SECTION_RE.match(raw)
        if section:
            current_section = section.group("name").strip().lower()
            continue
        if current_section != "identity":
            continue
        match = _KEY_LINE_RE.match(raw)
        if not match:
            continue
        key = match.group("key").lower()
        if key not in ("install_key", "installkey", "key"):
            continue
        value = match.group("value").strip().strip('"').strip("'").strip()
        if value:
            return value
    return None


def resolve_identity(blueprints_dir: str | Path | None = None) -> str:
    """Return the game's ``install_key``, or ``""`` when this install has none.

    There is intentionally no synthetic fallback: without a real key the client
    sends no ``X-Install-Key`` and the server rejects registration and uploads,
    so a non-retail copy can browse and download but cannot post.
    """
    return read_install_key(blueprints_dir) or ""
