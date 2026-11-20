"""Scanning of the player's local blueprint folder.

* reads every ``*.blueprint`` in the folder (the ``.trash`` sub-folder is the
  game's recycle bin and is ignored),
* parses each into a :class:`~ftn_blueprint.BlueprintMeta`, tolerating and
  flagging unreadable files instead of crashing,
* caches results in ``index.json`` keyed by ``(path, mtime, size)`` so repeated
  scans only re-parse files that actually changed,
* can tell whether the game is currently running (installs must be refused
  while it is).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ftn_blueprint import BlueprintError, BlueprintMeta, parse_blueprint

from ..core.paths import index_path, resolve_blueprints_dir, trash_subdir
from .provenance import ProvenanceRecord, ProvenanceStore

__all__ = ["LocalBlueprint", "LocalLibrary", "is_game_running", "GAME_PROCESS_NAMES"]

#: Substrings (lower-cased) that identify the game executable.
GAME_PROCESS_NAMES: tuple[str, ...] = ("findtheneedle", "find the needle", "find_the_needle")

BLUEPRINT_SUFFIX = ".blueprint"
_TEMP_SUFFIX = ".ftnlib.tmp"


@dataclass
class LocalBlueprint:
    """One file in the local folder, parsed (or flagged unreadable)."""

    path: Path
    status: str = "ok"  # "ok" | "unreadable"
    error: str | None = None
    meta: BlueprintMeta | None = None
    provenance: ProvenanceRecord | None = None
    mtime: float = 0.0
    size: int = 0
    _extra: dict = field(default_factory=dict, repr=False)

    # -- convenience accessors --------------------------------------------
    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def name(self) -> str:
        if self.meta is not None and self.meta.name:
            return self.meta.name
        return self.path.stem

    @property
    def sha256(self) -> str:
        return self.meta.sha256 if self.meta is not None else ""

    @property
    def piece_count(self) -> int:
        return self.meta.piece_count if self.meta is not None else 0

    @property
    def total_cost(self) -> float:
        return self.meta.total_cost if self.meta is not None else 0.0

    @property
    def category(self) -> str:
        return self.meta.category if self.meta is not None else ""

    @property
    def is_readable(self) -> bool:
        return self.status == "ok" and self.meta is not None

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"<LocalBlueprint {self.filename} status={self.status}>"


def is_game_running() -> bool:
    """Return ``True`` when a Find The Needle process is present.

    Only the executable's *base name* is inspected (never its full path), so
    launching this tool from a folder such as ``...\\find the needle\\...`` does
    not make it mistake itself for the game.
    """
    try:
        import psutil
    except ImportError:  # pragma: no cover - optional dependency
        return False
    own_pid = os.getpid()
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            if proc.pid == own_pid:
                continue
            info = proc.info
        except Exception:  # noqa: BLE001 - psutil can raise many things
            continue
        haystack = " ".join(
            Path(str(info.get(key) or "")).name for key in ("name", "exe")
        ).lower()
        if not haystack:
            continue
        if any(token in haystack for token in GAME_PROCESS_NAMES):
            return True
    return False


class LocalLibrary:
    """The player's ``blueprints/`` folder, with an on-disk parse cache."""

    def __init__(
        self,
        blueprints_dir: str | os.PathLike[str] | None = None,
        *,
        index_file: str | os.PathLike[str] | None = None,
        provenance: ProvenanceStore | None = None,
    ) -> None:
        self.blueprints_dir = Path(resolve_blueprints_dir(blueprints_dir))
        self.index_file = Path(index_file) if index_file is not None else index_path()
        self.provenance = provenance if provenance is not None else ProvenanceStore()
        # path(str) -> {"mtime": float, "size": int, "index": dict}
        self._cache: dict[str, dict] = {}
        self._meta_cache: dict[str, BlueprintMeta] = {}
        self._load_index()

    # -- public API --------------------------------------------------------
    def exists(self) -> bool:
        return self.blueprints_dir.is_dir()

    def list_files(self) -> list[Path]:
        """Every real ``.blueprint`` file in the folder (never ``.trash``)."""
        if not self.exists():
            return []
        trash = trash_subdir(self.blueprints_dir)
        files: list[Path] = []
        for child in self.blueprints_dir.iterdir():
            if not child.is_file():
                continue
            if child.name.lower().endswith(_TEMP_SUFFIX):
                continue
            if child.suffix.lower() != BLUEPRINT_SUFFIX:
                continue
            if child.parent == trash:
                continue
            files.append(child)
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def scan(self, *, force: bool = False) -> list[LocalBlueprint]:
        """Parse the folder, re-using cached results unless files changed."""
        entries: list[LocalBlueprint] = []
        seen: set[str] = set()
        for path in self.list_files():
            key = str(path)
            seen.add(key)
            try:
                stat = path.stat()
            except OSError:
                continue
            cached = self._cache.get(key)
            if (
                not force
                and cached is not None
                and cached.get("mtime") == stat.st_mtime
                and cached.get("size") == stat.st_size
                and key in self._meta_cache
            ):
                meta = self._meta_cache[key]
            else:
                meta, error = self._parse(path)
                if meta is not None:
                    self._meta_cache[key] = meta
                    self._cache[key] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                        "index": meta.to_index_dict(),
                    }
                else:
                    self._cache.pop(key, None)
                    self._meta_cache.pop(key, None)
            entry = LocalBlueprint(
                path=path,
                mtime=stat.st_mtime,
                size=stat.st_size,
                provenance=self.provenance.get(path.name),
            )
            if meta is not None:
                entry.meta = meta
                entry.status = "ok"
            else:
                entry.status = "unreadable"
                entry.error = self._last_error
            entries.append(entry)

        # forget entries for files that vanished
        for stale in [k for k in self._cache if k not in seen]:
            self._cache.pop(stale, None)
            self._meta_cache.pop(stale, None)
        self._save_index()
        return entries

    def refresh(self) -> list[LocalBlueprint]:
        return self.scan(force=True)

    # -- internals ---------------------------------------------------------
    def _parse(self, path: Path) -> tuple[BlueprintMeta | None, str | None]:
        try:
            return parse_blueprint(path), None
        except BlueprintError as exc:
            self._last_error = str(exc)
            return None, self._last_error
        except Exception as exc:  # noqa: BLE001 - never let a bad file crash a scan
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None, self._last_error

    _last_error: str = ""

    def _load_index(self) -> None:
        try:
            raw = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for key, value in raw.items():
            if isinstance(value, dict):
                self._cache[key] = value

    def _save_index(self) -> None:
        try:
            self.index_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.index_file.with_suffix(self.index_file.suffix + ".tmp")
            tmp.write_text(json.dumps(self._cache, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.index_file)
        except OSError:
            pass

    # -- helpers -----------------------------------------------------------
    def summarise(self, entries: Iterable[LocalBlueprint] | None = None) -> dict:
        """Aggregate counts used by the UI header."""
        entries = list(entries) if entries is not None else self.scan()
        readable = [e for e in entries if e.is_readable]
        return {
            "total": len(entries),
            "readable": len(readable),
            "unreadable": len(entries) - len(readable),
            "pieces": sum(e.piece_count for e in readable),
            "last_modified": max((e.mtime for e in entries), default=0.0),
            "directory": str(self.blueprints_dir),
            "exists": self.exists(),
            "scanned_at": time.time(),
        }
