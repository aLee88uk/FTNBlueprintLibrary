"""Shared Godot ``Variant`` codec, blueprint parser and preview renderer.

This package is imported by **both** the desktop client and the FastAPI
backend, so it must stay dependency-free (standard library only) and
cross-platform.

Typical use::

    from ftn_blueprint import parse_blueprint, render_svg

    meta = parse_blueprint(r"C:\\...\\blueprints\\1794502162_4776.blueprint")
    print(meta.name, meta.piece_count, meta.total_cost)
    svg = render_svg(meta)
"""

from .blueprint import (
    ROOT_KEYS,
    SUPPORTED_SCHEMA,
    LEVEL_GAP,
    BlueprintError,
    BlueprintMeta,
    Piece,
    UnsupportedSchemaError,
    assign_levels,
    encode_blueprint_file,
    parse_blueprint,
    parse_blueprint_bytes,
    sha256_of,
    build_meta,
)
from .names import BUILDING_NAMES, pretty_building_name
from .variant import (
    VariantError,
    decode_blob,
    read_variant,
    write_variant,
    Reader,
    Writer,
)

__all__ = [
    "ROOT_KEYS",
    "SUPPORTED_SCHEMA",
    "LEVEL_GAP",
    "BlueprintError",
    "BlueprintMeta",
    "Piece",
    "UnsupportedSchemaError",
    "VariantError",
    "assign_levels",
    "build_meta",
    "decode_blob",
    "encode_blueprint_file",
    "parse_blueprint",
    "parse_blueprint_bytes",
    "read_variant",
    "sha256_of",
    "write_variant",
    "Reader",
    "Writer",
    "BUILDING_NAMES",
    "pretty_building_name",
    "render_svg",
    "PREVIEW_VERSION",
]

__version__ = "0.1.0"


def __getattr__(name: str):  # pragma: no cover - lazy import to keep optional deps optional
    if name in {"render_svg", "PREVIEW_VERSION"}:
        from . import preview

        return getattr(preview, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
