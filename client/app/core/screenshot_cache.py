"""On-disk cache for downloaded blueprint screenshots.

The server serves screenshots from a content-addressed URL
(``.../screenshot?v=<sha>``), so a replaced screenshot arrives under a new
version token. Cache files are named after that token: a changed screenshot is
simply a cache miss, and stale entries are pruned by age.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

__all__ = ["ScreenshotCache", "screenshot_version"]


def screenshot_version(url: str) -> str:
    """Extract the ``?v=`` content token from a screenshot URL (``""`` if absent)."""
    return parse_qs(urlsplit(url or "").query).get("v", [""])[0]


def _sanitise(value: str) -> str:
    """Keep only filename-safe characters (defends against unexpected server values)."""
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "-_")
    return cleaned or "unknown"


class ScreenshotCache:
    """Persist downloaded screenshots under ``directory``, keyed by content version."""

    def __init__(self, directory: Path, *, max_entries: int = 200) -> None:
        self.directory = Path(directory)
        self.max_entries = max(int(max_entries), 1)

    def key_for(self, blueprint_id: str, url: str) -> str:
        """Cache key for a blueprint: its content version, or the id as a fallback."""
        return _sanitise(screenshot_version(url) or blueprint_id)

    def get(self, key: str) -> bytes | None:
        """Return cached bytes for ``key``, or ``None`` when it is not cached."""
        try:
            return (self.directory / f"{key}.img").read_bytes()
        except OSError:
            return None

    def put(self, key: str, data: bytes) -> None:
        """Store ``data`` for ``key``. Failures are swallowed — the cache is optional."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = self.directory / f".{key}.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, self.directory / f"{key}.img")
        except OSError:
            return
        self._prune()

    def _prune(self) -> None:
        """Trim the cache to ``max_entries``, removing the least recently used files."""
        try:
            files = sorted(
                self.directory.glob("*.img"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for stale in files[self.max_entries :]:
            try:
                stale.unlink()
            except OSError:
                pass
