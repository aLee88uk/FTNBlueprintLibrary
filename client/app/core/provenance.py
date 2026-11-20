"""Provenance side-store.

The game only knows about ``.blueprint`` files; it has no concept of where a
file came from. We keep our own little ledger (``provenance.json`` in our app
data dir) so the UI can show "downloaded from <author> on <date>" and so we can
detect when a file we installed has since been modified by the player.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

from .paths import provenance_path

__all__ = ["ProvenanceRecord", "ProvenanceStore"]


@dataclass
class ProvenanceRecord:
    """Metadata about a blueprint file *we* placed in the game folder."""

    filename: str
    installed_at: float = field(default_factory=time.time)
    installed_sha256: str = ""
    remote_id: str | None = None
    remote_title: str | None = None
    remote_author: str | None = None
    original_sha256: str | None = None
    renamed_from: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ProvenanceStore:
    """A tiny JSON-backed mapping of ``filename -> ProvenanceRecord``."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else provenance_path()
        self._records: dict[str, ProvenanceRecord] = {}
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        self._records = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for filename, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            payload.setdefault("filename", filename)
            known = {f for f in ProvenanceRecord.__dataclass_fields__}  # type: ignore[attr-defined]
            record = ProvenanceRecord(**{k: v for k, v in payload.items() if k in known})
            self._records[filename.lower()] = record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {rec.filename: rec.to_dict() for rec in self._records.values()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    # -- access ------------------------------------------------------------
    def record(
        self,
        filename: str,
        *,
        installed_sha256: str,
        remote_id: str | None = None,
        remote_title: str | None = None,
        remote_author: str | None = None,
        original_sha256: str | None = None,
        renamed_from: str | None = None,
    ) -> ProvenanceRecord:
        rec = ProvenanceRecord(
            filename=filename,
            installed_sha256=installed_sha256,
            remote_id=remote_id,
            remote_title=remote_title,
            remote_author=remote_author,
            original_sha256=original_sha256,
            renamed_from=renamed_from,
        )
        self._records[filename.lower()] = rec
        self.save()
        return rec

    def get(self, filename: str) -> ProvenanceRecord | None:
        return self._records.get(Path(filename).name.lower())

    def remove(self, filename: str) -> None:
        if self._records.pop(Path(filename).name.lower(), None) is not None:
            self.save()

    def __iter__(self) -> Iterator[ProvenanceRecord]:
        return iter(self._records.values())

    def __len__(self) -> int:
        return len(self._records)
