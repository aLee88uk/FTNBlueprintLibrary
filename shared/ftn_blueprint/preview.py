"""Pure-Python isometric (2.5D) blueprint preview renderer (SVG).

The client rasterises the returned SVG with Qt (``QSvgRenderer``) and the
server can rasterise it with ``cairosvg`` -- so the *same* generator drives both
and the visual output never diverges.

Pieces are projected from their real 3D coordinates (Godot's Y is the up axis)
through a fixed isometric basis, so a multi-level build reads as a stacked model
instead of a flat plan::

    screen_x = (x - z) * cos(30°)
    screen_y = (x + z) * sin(30°) - y

Geometry is derived from the real row shapes found in live blueprints:

======================  =====================================================
Row shape               Geometry used
======================  =====================================================
``a``/``b`` segments     a line between the two 3D endpoints
``platform``/``span``    a thin slab below the floor plane, sized by ``span``
everything else          an extruded box at ``position`` rotated by ``yaw``
======================  =====================================================

Two view options shape the output:

* ``hide_walls=True`` omits pieces identified as walls while keeping the
  geometry of other buildings unchanged.
* ``max_level=k`` renders vertical levels ``0..k`` cumulatively, so a slider can
  reveal the structure from the ground up. ``max_level=None`` renders every level.

There is no per-building footprint/height table in the game data yet, so boxes
use a small nominal size table (:data:`BUILD_SIZES`) with a sensible default.

Nothing in here trusts the input: every piece of user text is XML-escaped.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence
from xml.sax.saxutils import escape

from .blueprint import assign_levels
from .names import pretty_building_name

__all__ = ["render_svg", "build_style", "BUILD_SIZES", "PREVIEW_VERSION"]

#: Bump whenever the renderer's output changes. The server bakes this into its
#: preview cache keys, so old SVGs are transparently re-rendered instead of
#: being served (e.g. the 2D top-down -> isometric switch).
PREVIEW_VERSION = 10

# --- palette -----------------------------------------------------------------
THEMES = {
    "dark": {
        "bg": "#11161d",
        "ground": "#0c1117",
        "grid": "#1d2734",
        "grid_major": "#27354a",
        "text": "#e6edf5",
        "muted": "#93a4b8",
        "badge_bg": "#1b2430",
        "badge_br": "#2c3a4d",
        "frame": "#2c3a4d",
    },
    "light": {
        "bg": "#f6f7f9",
        "ground": "#e9ecf2",
        "grid": "#dde2ea",
        "grid_major": "#c8cfdb",
        "text": "#1d2430",
        "muted": "#5c6a7d",
        "badge_bg": "#ffffff",
        "badge_br": "#d3d8e2",
        "frame": "#d3d8e2",
    },
}

# --- building id -> (kind, colour) ------------------------------------------
# ``kind`` drives how the piece is drawn:
#   line  -> stroked segment from a/b        pipe -> thicker stroked segment
#   rect  -> thin slab from span             machine -> extruded box + glyph
BUILD_STYLES: dict[str, tuple[str, str]] = {
    # logistics
    "belt": ("line", "#e8a33d"),
    "conveyor": ("line", "#e8a33d"),
    "enclosed_belt": ("line", "#c07a2b"),
    "pipe": ("pipe", "#3d9be8"),
    "water_main": ("pipe", "#3d9be8"),
    "water_cross": ("machine", "#3d9be8"),
    "water_splitter": ("machine", "#3d9be8"),
    "compact_splitter": ("machine", "#f2c14e"),
    "compact_joiner": ("machine", "#f2c14e"),
    "conveyor_compact_splitter": ("machine", "#f2c14e"),
    "conveyor_compact_joiner": ("machine", "#f2c14e"),
    # power
    "gas_plant": ("machine", "#e2603f"),
    "switch_box": ("machine", "#e2603f"),
    "power": ("machine", "#e2603f"),
    # processing
    "pelletizer": ("machine", "#7bc86c"),
    "hay_pelletizer": ("machine", "#7bc86c"),
    # storage / movement
    "depot": ("machine", "#b07cd6"),
    "haylift": ("machine", "#b07cd6"),
    "hay_lift": ("machine", "#b07cd6"),
    "haystairs": ("machine", "#b07cd6"),
    "hay_stairs": ("machine", "#b07cd6"),
    # ground works
    "deck": ("rect", "#6d7c92"),
    "platform": ("rect", "#6d7c92"),
}

#: Fallback cycle for unknown building ids (deterministic per id).
_FALLBACK_COLOURS = (
    "#8fb8de", "#d6a5e0", "#e0c48f", "#9ad8c0", "#e0a09a", "#b6c78a",
)

#: Short glyph shown inside machine markers.
_GLYPHS: dict[str, str] = {
    "gas_plant": "G",
    "switch_box": "S",
    "pelletizer": "P",
    "hay_pelletizer": "P",
    "depot": "D",
    "haylift": "L",
    "hay_lift": "L",
    "haystairs": "H",
    "hay_stairs": "H",
    "compact_splitter": "S",
    "compact_joiner": "J",
    "conveyor_compact_splitter": "S",
    "conveyor_compact_joiner": "J",
    "water_cross": "+",
    "water_splitter": "W",
}

#: Nominal ``(width, depth, height)`` in world units for box pieces. The game
#: does not expose real footprints yet, so these are deliberately approximate.
BUILD_SIZES: dict[str, tuple[float, float, float]] = {
    "gas_plant": (3.0, 3.0, 3.5),
    "switch_box": (2.0, 2.0, 2.6),
    "power": (2.0, 2.0, 2.6),
    "pelletizer": (2.4, 2.4, 2.6),
    "hay_pelletizer": (2.4, 2.4, 2.6),
    "depot": (3.0, 3.0, 2.6),
    "haylift": (2.0, 2.0, 1.4),
    "hay_lift": (2.0, 2.0, 1.4),
    "haystairs": (2.0, 2.0, 1.4),
    "hay_stairs": (2.0, 2.0, 1.4),
    "compact_splitter": (1.6, 1.6, 1.3),
    "compact_joiner": (1.6, 1.6, 1.3),
    "conveyor_compact_splitter": (1.6, 1.6, 1.3),
    "conveyor_compact_joiner": (1.6, 1.6, 1.3),
    "water_splitter": (1.4, 1.4, 1.3),
    "water_cross": (0.8, 0.8, 0.8),
}

#: Size used for box pieces with no explicit entry.
_DEFAULT_SIZE = (1.6, 1.6, 1.4)

#: Height of a ``span`` slab (platforms / decks), extending below its position.
_SLAB_HEIGHT = 0.5

# --- isometric projection -----------------------------------------------------
_ISO_COS = math.cos(math.radians(30.0))  # 0.8660
_ISO_SIN = math.sin(math.radians(30.0))  # 0.5

#: View direction used for face culling / painter's-algorithm depth, as a unit
#: vector pointing from the model toward the camera (Godot: +x right, +y up).
_VIEW = (1.0, 1.0, 1.0)


def _hex_rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"not a hex colour: {colour!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _mix(colour_a: str, colour_b: str, amount: float) -> str:
    """Linear blend of two hex colours (``amount`` 0..1 toward ``colour_b``)."""
    try:
        a = _hex_rgb(colour_a)
        b = _hex_rgb(colour_b)
    except ValueError:
        return colour_a
    amount = max(0.0, min(1.0, amount))
    return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * amount):02x}" for i in range(3))


def _shade(colour: str, amount: float) -> str:
    """Darken ``colour`` toward near-black (used for box side faces)."""
    return _mix(colour, "#05070a", amount)


def _base_id(build_id: str) -> str:
    """Strip a ``build:`` prefix (rows use bare ids, the root ``icon`` is prefixed)."""
    return build_id.split(":", 1)[-1] if ":" in build_id else build_id


def _is_wall_piece(row: Mapping[str, Any], build_id: str) -> bool:
    """Whether the building id or row type explicitly identifies a wall."""
    for value in (build_id, str(row.get("type", ""))):
        tokens = value.lower().replace(":", "_").replace("-", "_").split("_")
        if "wall" in tokens or "walls" in tokens:
            return True
    return False


def build_style(build_id: str) -> tuple[str, str]:
    """Return ``(kind, colour)`` for a building id, with a stable fallback."""
    key = _base_id(build_id)
    if key in BUILD_STYLES:
        return BUILD_STYLES[key]
    digest = 0
    for char in key:
        digest = (digest * 131 + ord(char)) & 0xFFFFFFFF
    return "machine", _FALLBACK_COLOURS[digest % len(_FALLBACK_COLOURS)]


def _glyph(build_id: str) -> str:
    key = _base_id(build_id)
    if key in _GLYPHS:
        return _GLYPHS[key]
    for token in key.split("_"):
        if token:
            return token[0].upper()
    return "?"


def _humanise(build_id: str) -> str:
    return pretty_building_name(build_id)


def _as_vec3(value: Any) -> tuple[float, float, float] | None:
    if value is None:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, IndexError):
        return None


def _row_geometry(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return ``{"kind": "segment", "p0", "p1"}`` or ``{"kind": "point", "center"}``."""
    p0 = _as_vec3(row.get("a"))
    p1 = _as_vec3(row.get("b"))
    if p0 is not None and p1 is not None:
        return {"kind": "segment", "p0": p0, "p1": p1}
    center = _as_vec3(row.get("position"))
    if center is None:
        return None
    return {"kind": "point", "center": center}


def _iter_pieces(meta: Any) -> Iterable[tuple[int, Mapping[str, Any], str]]:
    rows: Sequence[Mapping[str, Any]] = getattr(meta, "rows", None) or []
    ids: Sequence[str] = getattr(meta, "build_ids", None) or []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        build_id = ids[index] if index < len(ids) and isinstance(ids[index], str) and ids[index] else str(row.get("type", "unknown"))
        yield index, row, build_id


def _piece_size(row: Mapping[str, Any], build_id: str) -> tuple[float, float, float]:
    """Nominal ``(width, depth, height)`` for a box piece."""
    span = row.get("span")
    if span is not None:
        try:
            width = abs(float(span[0]))
            depth = abs(float(span[1]))
            return (max(width, 0.4), max(depth, 0.4), _SLAB_HEIGHT)
        except (TypeError, ValueError, IndexError):
            pass
    return BUILD_SIZES.get(_base_id(build_id), _DEFAULT_SIZE)


def _yaw(row: Mapping[str, Any]) -> float:
    try:
        return float(row.get("yaw", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _box_corners(
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    yaw: float,
    *,
    top_aligned: bool = False,
) -> tuple[list, list]:
    """Return bottom/top corners; platforms can anchor their top at ``center.y``."""
    cx, cy, cz = center
    hw, hd = size[0] / 2.0, size[1] / 2.0
    bottom_y = cy - size[2] if top_aligned else cy
    top_y = cy if top_aligned else cy + size[2]
    cos_t, sin_t = math.cos(yaw), math.sin(yaw)
    base: list[tuple[float, float, float]] = []
    for lx, lz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
        wx = cx + lx * cos_t - lz * sin_t
        wz = cz + lx * sin_t + lz * cos_t
        base.append((wx, bottom_y, wz))
    top = [(x, top_y, z) for (x, _y, z) in base]
    return base, top


def _visible_wall(normal: tuple[float, float]) -> bool:
    """A vertical face is visible when its outward normal points at the camera."""
    return normal[0] * _VIEW[0] + normal[1] * _VIEW[2] > 1e-6


def _wall_normal(edge: tuple[tuple[float, float, float], tuple[float, float, float]], center_xz: tuple[float, float]) -> tuple[float, float]:
    """Outward XZ normal of a box's vertical face."""
    (x1, _y1, z1), (x2, _y2, z2) = edge
    ex, ez = x2 - x1, z2 - z1
    mid_x, mid_z = (x1 + x2) / 2.0, (z1 + z2) / 2.0
    out_x, out_z = mid_x - center_xz[0], mid_z - center_xz[1]
    n1 = (ez, -ex)
    if n1[0] * out_x + n1[1] * out_z < 0:
        n1 = (-n1[0], -n1[1])
    length = math.hypot(*n1) or 1.0
    return (n1[0] / length, n1[1] / length)


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    if number >= 1000:
        return f"{number:,.0f}"
    return f"{number:.0f}"


def render_svg(
    meta: Any,
    *,
    width: int = 800,
    height: int = 500,
    theme: str = "dark",
    title: str | None = None,
    author: str | None = None,
    show_legend: bool = True,
    max_level: int | None = None,
    hide_walls: bool = False,
) -> str:
    """Render ``meta`` (a :class:`~ftn_blueprint.blueprint.BlueprintMeta`) to an SVG string.

    The build is drawn as a fixed isometric projection of the real 3D piece
    coordinates. ``max_level`` keeps levels ``0..max_level`` (cumulative) so a
    slider can uncover the structure from the ground up; ``None`` keeps all
    levels. ``hide_walls`` omits pieces identified as walls without changing
    the shape of the remaining buildings.
    """
    palette = THEMES.get(theme, THEMES["dark"])

    rows_all = list(getattr(meta, "rows", None) or [])
    row_levels, level_ys = assign_levels(rows_all)
    level_count = max(len(level_ys), 1)
    if max_level is not None:
        max_level = max(0, min(int(max_level), level_count - 1))

    pieces: list[dict[str, Any]] = []
    for index, row, build_id in _iter_pieces(meta):
        piece_level = row_levels[index] if index < len(row_levels) else 0
        if max_level is not None and piece_level > max_level:
            continue
        if hide_walls and _is_wall_piece(row, build_id):
            continue
        geometry = _row_geometry(row)
        if geometry is None:
            continue
        kind, colour = build_style(build_id)
        pieces.append({
            "index": index,
            "row": row,
            "build_id": build_id,
            "geometry": geometry,
            "kind": kind,
            "colour": colour,
            "level": piece_level,
        })

    # -- project every vertex up front so we can fit the drawing ------------
    projected: list[list[tuple[float, float]]] = []
    world_min_x = world_min_z = math.inf
    world_max_x = world_max_z = -math.inf
    base_y = 0.0
    first_box = True
    for piece in pieces:
        geometry = piece["geometry"]
        if geometry["kind"] == "segment":
            points = [geometry["p0"], geometry["p1"]]
            screen = [_project(*p) for p in points]
            xs = [p[0] for p in points]
            zs = [p[2] for p in points]
            ys = [p[1] for p in points]
        else:
            size = _piece_size(piece["row"], piece["build_id"])
            base, top = _box_corners(
                geometry["center"],
                size,
                _yaw(piece["row"]),
                top_aligned=piece["kind"] == "rect",
            )
            points = base + top
            screen = [_project(*p) for p in points]
            xs = [p[0] for p in points]
            zs = [p[2] for p in points]
            ys = [p[1] for p in points]
        projected.append(screen)
        world_min_x, world_max_x = min(world_min_x, *xs), max(world_max_x, *xs)
        world_min_z, world_max_z = min(world_min_z, *zs), max(world_max_z, *zs)
        if first_box:
            base_y = min(ys)
            first_box = False
        else:
            base_y = min(base_y, min(ys))

    if not pieces:
        world_min_x = world_min_z = -6.0
        world_max_x = world_max_z = 6.0
        projected = []

    all_screen = [p for screen in projected for p in screen]
    if all_screen:
        min_sx = min(p[0] for p in all_screen)
        max_sx = max(p[0] for p in all_screen)
        min_sy = min(p[1] for p in all_screen)
        max_sy = max(p[1] for p in all_screen)
    else:
        min_sx = min_sy = 0.0
        max_sx = max_sy = 1.0

    counts: dict[str, int] = {}
    for piece in pieces:
        counts[piece["build_id"]] = counts.get(piece["build_id"], 0) + 1
    legend_builds = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    # Cap the legend so a blueprint with dozens of building kinds does not crowd
    # out the actual model. The most common kinds are listed first; the rest are
    # summarised as "and N more kind(s)".
    MAX_LEGEND_ITEMS = 24
    legend_displayed = legend_builds[:MAX_LEGEND_ITEMS]
    legend_overflow = len(legend_builds) - len(legend_displayed)

    # Adaptive columns: use as many as the width allows (min ~170px per column)
    # but only as many as needed to keep the list short.
    max_cols_by_width = max(1, width // 170)
    target_rows = 8
    needed_cols = math.ceil(len(legend_displayed) / target_rows) if legend_displayed else 1
    legend_columns = max(1, min(needed_cols, max_cols_by_width))
    legend_rows = math.ceil(len(legend_displayed) / legend_columns) if legend_displayed else 0

    margin = 48.0
    legend_header_h = 30.0
    legend_row_h = 18.0
    extra_overflow_row = legend_row_h if legend_overflow > 0 else 0.0
    legend_h = (
        legend_header_h + legend_rows * legend_row_h + extra_overflow_row
        if show_legend and legend_rows
        else 0.0
    )
    inner_w = max(width - margin * 2, 40)
    inner_h = max(height - margin * 2 - legend_h, 40)
    span_sx = max(max_sx - min_sx, 1e-6)
    span_sy = max(max_sy - min_sy, 1e-6)

    # The ground grid and piece strokes extend beyond the raw content bounds.
    # grid_step depends on scale, the grid's projected bounds depend on
    # grid_step, and scale depends on those bounds plus the stroke width.
    # Iterate until all three are consistent so the grid + strokes always fit
    # inside the viewBox instead of being clipped at the edges.
    def _grid_step_for_scale(s: float) -> float:
        gs = 1.0
        if s * gs < 6:
            gs = 5.0
        if s * gs < 6:
            gs = 10.0
        return gs

    def _combined_bounds(gs: float) -> tuple[float, float, float, float]:
        """Projected screen bounds of the union of content and ground grid.

        The grid is drawn as x-lines (constant x, spanning world_min_z ..
        world_max_z+gs) and z-lines (constant z, spanning world_min_x ..
        world_max_x+gs). Only the actual line endpoints are rendered, so the
        far corner (world_max_x+gs, world_max_z+gs) is *not* part of the grid;
        projecting it would overestimate the bounds and shift the drawing
        off-centre. We project the real endpoints instead.
        """
        gx0 = math.floor(world_min_x / gs) * gs
        gz0 = math.floor(world_min_z / gs) * gs
        last_x = gx0 + math.floor((world_max_x + gs - gx0) / gs) * gs
        last_z = gz0 + math.floor((world_max_z + gs - gz0) / gs) * gs

        sx_vals: list[float] = []
        sy_vals: list[float] = []
        x = gx0
        while x <= last_x + 1e-9:
            for z in (world_min_z, world_max_z + gs):
                px, py = _project(x, base_y, z)
                sx_vals.append(px)
                sy_vals.append(py)
            x += gs
        z = gz0
        while z <= last_z + 1e-9:
            for wx in (world_min_x, world_max_x + gs):
                px, py = _project(wx, base_y, z)
                sx_vals.append(px)
                sy_vals.append(py)
            z += gs

        g_min_sx = min(sx_vals)
        g_max_sx = max(sx_vals)
        g_min_sy = min(sy_vals)
        g_max_sy = max(sy_vals)
        return (
            min(min_sx, g_min_sx),
            max(max_sx, g_max_sx),
            min(min_sy, g_min_sy),
            max(max_sy, g_max_sy),
        )

    # Initial scale guess ignoring grid + stroke.
    scale = min(inner_w / span_sx, inner_h / span_sy)
    for _ in range(8):
        gs = _grid_step_for_scale(scale)
        c_min_sx, c_max_sx, c_min_sy, c_max_sy = _combined_bounds(gs)
        W = max(c_max_sx - c_min_sx, 1e-6)
        H = max(c_max_sy - c_min_sy, 1e-6)
        # Max stroke width in px across piece kinds; round linecaps extend half
        # of this beyond each endpoint, so reserve the full width as padding
        # (half on each side).
        stroke = max(scale * 0.7, 3.0)
        new_scale = min((inner_w - stroke) / W, (inner_h - stroke) / H)
        new_scale = max(new_scale, 1e-6)
        if abs(new_scale - scale) < 1e-4:
            scale = new_scale
            break
        scale = new_scale

    # Final bounds / grid step from the converged scale.
    grid_step = _grid_step_for_scale(scale)
    anchor_min_sx, c_max_sx, anchor_min_sy, c_max_sy = _combined_bounds(grid_step)
    span_sx = max(c_max_sx - anchor_min_sx, 1e-6)
    span_sy = max(c_max_sy - anchor_min_sy, 1e-6)

    offset_x = margin + (inner_w - span_sx * scale) / 2.0
    offset_y = margin + (inner_h - span_sy * scale) / 2.0

    def to_px(point: tuple[float, float]) -> tuple[float, float]:
        sx, sy = point
        return (offset_x + (sx - anchor_min_sx) * scale, offset_y + (sy - anchor_min_sy) * scale)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
    )
    parts.append(f'<rect width="{width}" height="{height}" fill="{palette["bg"]}"/>')

    # -- ground grid on the base plane --------------------------------------
    # grid_step was determined above during the bounds-fit iteration.
    grid_x0 = math.floor(world_min_x / grid_step) * grid_step
    grid_z0 = math.floor(world_min_z / grid_step) * grid_step
    x = grid_x0
    while x <= world_max_x + grid_step:
        major = abs(x / (grid_step * 5) - round(x / (grid_step * 5))) < 1e-6
        colour = palette["grid_major"] if major else palette["grid"]
        x1, y1 = to_px(_project(x, base_y, world_min_z))
        x2, y2 = to_px(_project(x, base_y, world_max_z + grid_step))
        parts.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{colour}" stroke-width="1"/>')
        x += grid_step
    z = grid_z0
    while z <= world_max_z + grid_step:
        major = abs(z / (grid_step * 5) - round(z / (grid_step * 5))) < 1e-6
        colour = palette["grid_major"] if major else palette["grid"]
        x1, y1 = to_px(_project(world_min_x, base_y, z))
        x2, y2 = to_px(_project(world_max_x + grid_step, base_y, z))
        parts.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{colour}" stroke-width="1"/>')
        z += grid_step

    # -- pieces, far to near (painter's algorithm) --------------------------
    ordered = sorted(
        range(len(pieces)),
        key=lambda i: _piece_order_key(pieces[i]),
    )
    for i in ordered:
        piece = pieces[i]
        _draw_piece(parts, piece, projected[i], scale, to_px)

    # -- badges ---------------------------------------------------------------
    piece_total = len(pieces)
    piece_label = "Piece" if piece_total == 1 else "Pieces"
    badge_items = [
        f"{piece_total} {piece_label}",
        f"Cost {_format_number(getattr(meta, 'total_cost', 0.0))}",
        f"MK {getattr(meta, 'mk', 0)}",
    ]
    if level_count > 1:
        if max_level is None:
            badge_items.insert(0, f"{level_count} Levels")
        else:
            badge_items.insert(0, f"Levels 1–{max_level + 1}/{level_count}")
    if author:
        author_text = str(author)
        if len(author_text) > 36:
            author_text = author_text[:33] + "..."
        badge_items.append(f"By {author_text}")

    parts.append(
        f'<rect x="0" y="0" width="{width}" height="30" fill="{palette["badge_bg"]}" fill-opacity="0.92"/>'
    )
    badge_x = 12.0
    for item in badge_items:
        badge_width = min(float(width) - badge_x - 8.0, max(54.0, len(item) * 7.0 + 16.0))
        if badge_width <= 0:
            break
        parts.append(
            f'<rect x="{badge_x:.1f}" y="5" width="{badge_width:.1f}" height="20" rx="7" '
            f'fill="{palette["frame"]}" fill-opacity="0.78" stroke="{palette["frame"]}" stroke-width="0.7"/>'
        )
        parts.append(
            f'<text x="{badge_x + 8.0:.1f}" y="19" font-family="Segoe UI, system-ui, sans-serif" '
            f'font-size="11.5" font-weight="600" fill="{palette["text"]}">{escape(item)}</text>'
        )
        badge_x += badge_width + 7.0

    # The blueprint title is only drawn in the full detail/zoom view. Card
    # previews (show_legend=False) already show the title below the preview,
    # so drawing it again inside the SVG would crowd and overlap the layout.
    if show_legend:
        heading = title if title is not None else getattr(meta, "name", "")
        parts.append(
            f'<text x="14" y="{height - legend_h - 12}" font-family="Segoe UI, system-ui, sans-serif" '
            f'font-size="15" font-weight="600" fill="{palette["text"]}">{escape(str(heading))}</text>'
        )

    # -- legend ---------------------------------------------------------------
    if show_legend and legend_rows:
        legend_top = height - legend_h
        parts.append(f'<line x1="0" y1="{legend_top:.0f}" x2="{width}" y2="{legend_top:.0f}" stroke="{palette["frame"]}"/>')
        parts.append(
            f'<text x="12" y="{legend_top + 18:.1f}" font-family="Segoe UI, system-ui, sans-serif" '
            f'font-size="10.5" font-weight="600" fill="{palette["text"]}">Legend</text>'
        )
        col_width = width / legend_columns
        for item_index, (build_id, count) in enumerate(legend_displayed):
            row_index, col_index = divmod(item_index, legend_columns)
            x = col_index * col_width + 12.0
            baseline = legend_top + legend_header_h + row_index * legend_row_h + 13.0
            kind, colour = build_style(build_id)
            icon_x = x
            icon_y = baseline - 5.0

            if kind in {"line", "pipe"}:
                is_enclosed = "enclosed" in _base_id(build_id)
                dash = ' stroke-dasharray="3 2"' if is_enclosed else ""
                stroke_width = 4.0 if kind == "pipe" else 2.5
                parts.append(
                    f'<line x1="{icon_x:.1f}" y1="{icon_y:.1f}" x2="{icon_x + 16:.1f}" y2="{icon_y:.1f}" '
                    f'class="legend-icon legend-{kind}" stroke="{colour}" stroke-width="{stroke_width:.1f}" '
                    f'stroke-linecap="round"{dash}/>'
                )
            elif kind == "rect":
                parts.append(
                    f'<polygon points="{icon_x + 8:.1f},{icon_y - 5:.1f} '
                    f'{icon_x + 16:.1f},{icon_y - 1:.1f} {icon_x + 8:.1f},{icon_y + 3:.1f} '
                    f'{icon_x:.1f},{icon_y - 1:.1f}" class="legend-icon legend-rect" fill="{colour}"/>'
                )
            else:
                parts.append(
                    f'<polygon points="{icon_x:.1f},{icon_y - 2:.1f} '
                    f'{icon_x + 8:.1f},{icon_y - 6:.1f} {icon_x + 16:.1f},{icon_y - 2:.1f} '
                    f'{icon_x + 8:.1f},{icon_y + 2:.1f}" class="legend-icon legend-machine" '
                    f'fill="{_mix(colour, "#ffffff", 0.10)}"/>'
                )
                parts.append(
                    f'<polygon points="{icon_x:.1f},{icon_y - 2:.1f} {icon_x + 8:.1f},{icon_y + 2:.1f} '
                    f'{icon_x + 8:.1f},{icon_y + 7:.1f} {icon_x:.1f},{icon_y + 3:.1f}" '
                    f'fill="{_shade(colour, 0.42)}"/>'
                )
                parts.append(
                    f'<polygon points="{icon_x + 8:.1f},{icon_y + 2:.1f} {icon_x + 16:.1f},{icon_y - 2:.1f} '
                    f'{icon_x + 16:.1f},{icon_y + 3:.1f} {icon_x + 8:.1f},{icon_y + 7:.1f}" '
                    f'fill="{_shade(colour, 0.20)}"/>'
                )

            label = f"{_humanise(build_id)} x{count}"
            parts.append(
                f'<text x="{icon_x + 23:.1f}" y="{baseline:.1f}" font-family="Segoe UI, system-ui, sans-serif" '
                f'font-size="11.5" fill="{palette["muted"]}">{escape(label)}</text>'
            )

        if legend_overflow > 0:
            kind_word = "kind" if legend_overflow == 1 else "kinds"
            overflow_y = legend_top + legend_header_h + legend_rows * legend_row_h + 13.0
            parts.append(
                f'<text x="12" y="{overflow_y:.1f}" font-family="Segoe UI, system-ui, sans-serif" '
                f'font-size="11" font-style="italic" fill="{palette["muted"]}">'
                f'… and {legend_overflow} more {kind_word}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _project(x: float, y: float, z: float) -> tuple[float, float]:
    """Isometric projection of a world point (``y`` is up)."""
    return ((x - z) * _ISO_COS, (x + z) * _ISO_SIN - y)


def _depth_key(piece: Mapping[str, Any]) -> float:
    """Painter's-algorithm depth along the view axis (larger = nearer)."""
    geometry = piece["geometry"]
    if geometry["kind"] == "segment":
        (x0, y0, z0), (x1, y1, z1) = geometry["p0"], geometry["p1"]
        return (x0 + x1) / 2.0 + (y0 + y1) / 2.0 + (z0 + z1) / 2.0
    cx, cy, cz = geometry["center"]
    return cx + cy + cz


def _piece_order_key(piece: Mapping[str, Any]) -> tuple[int, int, float, int]:
    """Order floors bottom-up, with each floor's platform behind its objects."""
    return (
        int(piece["level"]),
        0 if piece["kind"] == "rect" else 1,
        _depth_key(piece),
        int(piece["index"]),
    )


def _draw_piece(
    parts: list[str],
    piece: Mapping[str, Any],
    screen: list[tuple[float, float]],
    scale: float,
    to_px: Any,
) -> None:
    """Append the SVG for one projected piece (segment line or extruded box)."""
    row = piece["row"]
    build_id = piece["build_id"]
    colour: str = piece["colour"]
    geometry = piece["geometry"]

    if geometry["kind"] == "segment":
        (x1, y1), (x2, y2) = to_px(screen[0]), to_px(screen[1])
        row_kind = str(row.get("type", ""))
        if "water" in row_kind or "pipe" in row_kind or piece["kind"] == "pipe":
            stroke_w = max(scale * 0.5, 2.5)
            dash = ""
            opacity = "0.95"
        elif "enclosed" in row_kind:
            stroke_w = max(scale * 0.7, 3.0)
            dash = ' stroke-dasharray="7 4"'
            opacity = "0.9"
        else:
            stroke_w = max(scale * 0.7, 3.0)
            dash = ""
            opacity = "1"
        parts.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{colour}" stroke-width="{stroke_w:.2f}" stroke-linecap="round" '
            f'opacity="{opacity}"{dash}/>'
        )
        return

    size = _piece_size(row, build_id)
    base, top = _box_corners(
        geometry["center"],
        size,
        _yaw(row),
        top_aligned=piece["kind"] == "rect",
    )
    base_px = [to_px(_project(*p)) for p in base]
    top_px = [to_px(_project(*p)) for p in top]
    center_xz = (geometry["center"][0], geometry["center"][2])

    # Side faces are part of the building shape; hide_walls filters wall pieces.
    walls: list[tuple[float, str, str]] = []
    for i in range(4):
        j = (i + 1) % 4
        normal = _wall_normal((base[i], base[j]), center_xz)
        if not _visible_wall(normal):
            continue
        face = _shade(colour, 0.42 if abs(normal[0]) >= abs(normal[1]) else 0.20)
        depth = base[i][0] + base[i][2] + base[j][0] + base[j][2]
        points = " ".join(f"{px:.2f},{py:.2f}" for px, py in (base_px[i], base_px[j], top_px[j], top_px[i]))
        walls.append((depth, face, points))
    for _depth, face, points in sorted(walls):
        parts.append(f'<polygon points="{points}" fill="{face}" stroke="{_shade(colour, 0.55)}" stroke-width="0.6"/>')

    # Top face (always drawn, brightest).
    top_points = " ".join(f"{px:.2f},{py:.2f}" for px, py in top_px)
    top_colour = _mix(colour, "#ffffff", 0.10)
    parts.append(
        f'<polygon points="{top_points}" fill="{top_colour}" fill-opacity="0.96" '
        f'stroke="{_shade(colour, 0.5)}" stroke-width="0.8"/>'
    )

    # Glyph on the top face for machine pieces, when there is room.
    cx = sum(p[0] for p in top_px) / 4.0
    cy = sum(p[1] for p in top_px) / 4.0
    if piece["kind"] == "machine" and min(size[0], size[1]) * scale >= 12:
        parts.append(
            f'<text x="{cx:.2f}" y="{cy + 3.5:.2f}" text-anchor="middle" '
            f'font-family="Segoe UI, system-ui, sans-serif" font-size="{max(9.0, size[0] * scale * 0.5):.2f}" '
            f'font-weight="600" fill="#0b0f14" fill-opacity="0.72">{escape(_glyph(build_id))}</text>'
        )
