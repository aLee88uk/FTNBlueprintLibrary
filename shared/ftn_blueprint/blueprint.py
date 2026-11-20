"""Parsing of *Find The Needle* ``.blueprint`` files into typed metadata.

A blueprint file is ``[u32 LE payload_len][Godot binary Variant blob]`` where
the payload is a ``DICTIONARY`` with exactly :data:`ROOT_KEYS` entries::

    format, id, name, desc, icon, colour, category, sub, mk, made, rows,
    ids, costs, tags, pins, unplugged, feeds, paints, orders

``rows`` holds one dictionary per placed structure, ``ids`` the matching
building ids and ``costs`` the per-structure build cost.
"""

from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .variant import VariantError, decode_blob, write_variant

__all__ = [
    "BlueprintError",
    "UnsupportedSchemaError",
    "Piece",
    "BlueprintMeta",
    "ROOT_KEYS",
    "SUPPORTED_SCHEMA",
    "LEVEL_GAP",
    "assign_levels",
    "parse_blueprint",
    "parse_blueprint_bytes",
    "sha256_of",
    "encode_blueprint_file",
]

#: Two pieces belong to the same floor when their Y (up-axis) values are within
#: this many world units. The game stacks floors ~5 units apart, so this cleanly
#: separates levels while keeping a floor's own slab/deck offsets (~0.4) together.
LEVEL_GAP = 2.5

#: Schema version this library understands (``format`` field).
SUPPORTED_SCHEMA = 1

#: The 19 keys every root dictionary is expected to contain.
ROOT_KEYS: tuple[str, ...] = (
    "format",
    "id",
    "name",
    "desc",
    "icon",
    "colour",
    "category",
    "sub",
    "mk",
    "made",
    "rows",
    "ids",
    "costs",
    "tags",
    "pins",
    "unplugged",
    "feeds",
    "paints",
    "orders",
)

#: Keys that are nice to have but must not make parsing fail.
_OPTIONAL_KEYS = frozenset({"colour", "sub", "desc", "tags", "pins", "unplugged", "feeds", "paints", "orders"})


class BlueprintError(ValueError):
    """Raised when a file is not a readable blueprint."""


class UnsupportedSchemaError(BlueprintError):
    """Raised when the blueprint declares a schema version we cannot read."""


@dataclass(slots=True)
class Piece:
    """A single placed structure inside a blueprint."""

    type: str
    position: tuple[float, float, float] | None
    yaw: float
    index: int
    build_id: str | None
    cost: float
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    #: 0-based floor index (derived from the piece's Y / up-axis value).
    level: int = 0

    @property
    def label(self) -> str:
        """Human readable name derived from the row ``type`` (``build:x`` -> ``x``)."""
        return self.type.split(":", 1)[-1] if ":" in self.type else self.type


@dataclass(slots=True)
class BlueprintMeta:
    """Everything we know about a blueprint after decoding it."""

    schema: int
    id: str
    name: str
    desc: str
    icon: str
    colour: str
    category: str
    sub: str
    mk: int
    made: int
    piece_count: int
    build_ids: list[str]
    distinct_builds: dict[str, int]
    total_cost: float
    tags: list[str]
    rows: list[dict[str, Any]]
    costs: list[float] = field(default_factory=list)
    pieces: list[Piece] = field(default_factory=list)
    #: Number of distinct floors (Y levels) the blueprint spans; ``1`` for a flat build.
    level_count: int = 1
    #: Representative Y (up-axis) of each floor, ascending (index == level).
    levels: list[float] = field(default_factory=list)
    size_bytes: int = 0
    sha256: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def filename_stem(self) -> str:
        """The ``<unix_ts>_<4hex>`` identifier the game uses as a file name."""
        return self.id or f"{self.made}"

    def to_index_dict(self) -> dict[str, Any]:
        """Compact, JSON-serialisable summary (used for caches and API payloads)."""
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "icon": self.icon,
            "colour": self.colour,
            "category": self.category,
            "sub": self.sub,
            "schema": self.schema,
            "mk": self.mk,
            "made": self.made,
            "piece_count": self.piece_count,
            "level_count": self.level_count,
            "distinct_builds": self.distinct_builds,
            "total_cost": self.total_cost,
            "tags": self.tags,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_int(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _extract_position(row: Mapping[str, Any]) -> tuple[float, float, float] | None:
    position = row.get("position")
    if position is None:
        return None
    try:
        x, y, z = (float(position[0]), float(position[1]), float(position[2]))
    except (TypeError, ValueError, IndexError):
        return None
    return (x, y, z)


def _piece_anchor_y(row: Mapping[str, Any]) -> float | None:
    """The piece's Y (Godot up-axis) value, used to assign it to a floor.

    Segments (conveyors/pipes) carry their ends in ``a``/``b`` and are anchored
    at their start; point pieces use the middle component of ``position``.
    """
    upper = row.get("a")
    if isinstance(upper, (list, tuple)) and len(upper) >= 2:
        try:
            return float(upper[1])
        except (TypeError, ValueError):
            return None
    position = row.get("position")
    if isinstance(position, (list, tuple)) and len(position) >= 2:
        try:
            return float(position[1])
        except (TypeError, ValueError):
            return None
    return None


def assign_levels(rows: Iterable[Mapping[str, Any]], *, gap: float = LEVEL_GAP) -> tuple[list[int], list[float]]:
    """Group rows into floors by clustering their Y (up-axis) values.

    Returns ``(level_of_row, level_ys)`` where ``level_of_row[i]`` is the 0-based
    floor index of ``rows[i]`` (ascending Y) and ``level_ys[k]`` is the lowest Y
    seen on floor ``k``. Rows without usable geometry land on floor ``0``.

    The clustering is gap-based rather than a fixed floor height, so it adapts to
    whatever vertical spacing a future game build uses.
    """
    anchors = [_piece_anchor_y(row) if isinstance(row, Mapping) else None for row in rows]
    known = sorted({y for y in anchors if y is not None})

    clusters: list[list[float]] = []
    for value in known:
        if clusters and value - clusters[-1][-1] <= gap:
            clusters[-1].append(value)
        else:
            clusters.append([value])

    level_of: dict[float, int] = {value: index for index, cluster in enumerate(clusters) for value in cluster}
    levels = [level_of[y] if y is not None else 0 for y in anchors]
    return levels, [cluster[0] for cluster in clusters]


def build_meta(root: Mapping[str, Any], *, size_bytes: int = 0, sha256: str = "") -> BlueprintMeta:
    """Turn a decoded root dictionary into a :class:`BlueprintMeta`."""
    if not isinstance(root, Mapping):
        raise BlueprintError(f"root payload is {type(root).__name__}, expected a dictionary")

    missing = [key for key in ROOT_KEYS if key not in root and key not in _OPTIONAL_KEYS]
    if missing:
        raise BlueprintError(f"blueprint is missing required key(s): {', '.join(missing)}")

    schema = _as_int(root.get("format"), -1)
    if schema != SUPPORTED_SCHEMA:
        raise UnsupportedSchemaError(
            f"unsupported blueprint schema version {schema!r} (this build supports {SUPPORTED_SCHEMA})"
        )

    rows_raw = root.get("rows") or []
    if not isinstance(rows_raw, list):
        raise BlueprintError("'rows' is not an array")
    rows: list[dict[str, Any]] = [r for r in rows_raw if isinstance(r, dict)]

    ids_raw = root.get("ids") or []
    build_ids: list[str] = [i for i in ids_raw if isinstance(i, str)] if isinstance(ids_raw, list) else []

    costs_raw = root.get("costs") or []
    costs: list[float] = [_as_float(c) for c in costs_raw] if isinstance(costs_raw, list) else []

    tags_raw = root.get("tags") or []
    tags: list[str] = [t for t in tags_raw if isinstance(t, str)] if isinstance(tags_raw, list) else []

    row_levels, level_ys = assign_levels(rows)

    pieces: list[Piece] = []
    for index, row in enumerate(rows):
        pieces.append(
            Piece(
                type=_as_str(row.get("type"), "unknown"),
                position=_extract_position(row),
                yaw=_as_float(row.get("yaw")),
                index=index,
                build_id=build_ids[index] if index < len(build_ids) else None,
                cost=costs[index] if index < len(costs) else 0.0,
                raw=dict(row),
                level=row_levels[index] if index < len(row_levels) else 0,
            )
        )

    id_value = _as_str(root.get("id"))
    made = _as_int(root.get("made"))
    return BlueprintMeta(
        schema=schema,
        id=id_value,
        name=_as_str(root.get("name")) or "Untitled Blueprint",
        desc=_as_str(root.get("desc")),
        icon=_as_str(root.get("icon")),
        colour=_as_str(root.get("colour")),
        category=_as_str(root.get("category")),
        sub=_as_str(root.get("sub")),
        mk=_as_int(root.get("mk")),
        made=made,
        piece_count=len(rows),
        build_ids=build_ids,
        distinct_builds=dict(Counter(build_ids).most_common()),
        total_cost=sum(costs),
        tags=tags,
        rows=rows,
        costs=costs,
        pieces=pieces,
        level_count=max(len(level_ys), 1),
        levels=level_ys,
        size_bytes=size_bytes,
        sha256=sha256,
        raw=dict(root),
    )


def parse_blueprint_bytes(data: bytes, *, with_hash: bool = True) -> BlueprintMeta:
    """Parse raw ``.blueprint`` file bytes."""
    try:
        root = decode_blob(data)
    except VariantError as exc:
        raise BlueprintError(f"not a valid blueprint blob: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest() if with_hash else ""
    return build_meta(root, size_bytes=len(data), sha256=digest)


def parse_blueprint(source: str | os.PathLike[str] | bytes | bytearray, *, with_hash: bool = True) -> BlueprintMeta:
    """Parse a blueprint from a path or from raw bytes."""
    if isinstance(source, (bytes, bytearray)):
        return parse_blueprint_bytes(bytes(source), with_hash=with_hash)
    path = Path(source)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BlueprintError(f"cannot read {path}: {exc}") from exc
    meta = parse_blueprint_bytes(data, with_hash=with_hash)
    if not meta.id:
        meta.id = path.stem
    return meta


def sha256_of(source: str | os.PathLike[str] | bytes | bytearray) -> str:
    """SHA-256 hex digest of a file path or of raw bytes."""
    if isinstance(source, (bytes, bytearray)):
        return hashlib.sha256(bytes(source)).hexdigest()
    path = Path(source)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def encode_blueprint_file(root: Mapping[str, Any]) -> bytes:
    """Wrap a root dictionary back into a ``.blueprint`` file (used for tests)."""
    payload = write_variant(dict(root))
    return len(payload).to_bytes(4, "little") + payload
