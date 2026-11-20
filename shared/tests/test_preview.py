"""Preview renderer tests: geometry coverage, escaping and deterministic output."""

from __future__ import annotations

import pathlib
import re

import pytest

from ftn_blueprint import assign_levels, parse_blueprint
from ftn_blueprint.preview import (
    BUILD_SIZES,
    BUILD_STYLES,
    _box_corners,
    _piece_order_key,
    build_style,
    render_svg,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
SAMPLES = sorted(FIXTURES.glob("*.blueprint"))

MULTI_LEVEL = FIXTURES / "1794505172_2ff6.blueprint"


def _rendered_pieces(svg: str) -> int:
    """Read the piece count back out of the SVG's own badge."""
    match = re.search(r">(\d+) Pieces?<", svg)
    assert match is not None, "the preview is missing its piece badge"
    return int(match.group(1))


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_renders_valid_svg(path: pathlib.Path) -> None:
    svg = render_svg(parse_blueprint(path))
    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")
    assert 'viewBox="0 0 800 500"' in svg
    assert "<line" in svg or "<rect" in svg


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_badges_show_piece_count_and_cost(path: pathlib.Path) -> None:
    meta = parse_blueprint(path)
    svg = render_svg(meta)
    assert f"{meta.piece_count} Piece" in svg
    assert "Cost " in svg
    assert f"MK {meta.mk}" in svg


def test_output_is_deterministic() -> None:
    meta = parse_blueprint(SAMPLES[1])
    assert render_svg(meta) == render_svg(meta)


def test_segments_and_boxes_are_drawn() -> None:
    svg = render_svg(parse_blueprint(FIXTURES / "1794505172_2ff6.blueprint"))
    assert 'stroke-linecap="round"' in svg  # conveyors / pipes
    assert 'stroke-dasharray="7 4"' in svg  # enclosed belts
    assert "<polygon" in svg                # extruded box faces


def test_platform_slab_ends_at_its_floor_position() -> None:
    bottom, top = _box_corners((0.0, 4.0, 0.0), (10.0, 4.0, 0.5), 0.0, top_aligned=True)
    assert {point[1] for point in bottom} == {3.5}
    assert {point[1] for point in top} == {4.0}


def test_platforms_draw_before_objects_on_the_same_level() -> None:
    platform = {"level": 0, "kind": "rect", "geometry": {"kind": "point", "center": (8, 4, 0)}, "index": 20}
    splitter = {"level": 0, "kind": "machine", "geometry": {"kind": "point", "center": (0, 4, 0)}, "index": 10}
    next_floor = {"level": 1, "kind": "rect", "geometry": {"kind": "point", "center": (0, 9, 0)}, "index": 30}
    assert _piece_order_key(platform) < _piece_order_key(splitter)
    assert _piece_order_key(splitter) < _piece_order_key(next_floor)


def test_belts_and_pipes_use_the_fitted_viewport_coordinates() -> None:
    svg = render_svg(parse_blueprint(MULTI_LEVEL), width=900, height=560)
    segment_lines = re.findall(
        r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)" '
        r'stroke="#(?:e8a33d|3d9be8)"',
        svg,
    )
    assert segment_lines
    coordinates = [float(value) for line in segment_lines for value in line]
    assert min(coordinates) > 20  # raw projected endpoints previously sat near (0, 0)
    assert max(coordinates[::2]) < 900
    assert max(coordinates[1::2]) < 560


def test_legend_names_buildings_and_shows_their_shape_kinds() -> None:
    svg = render_svg(parse_blueprint(MULTI_LEVEL))
    assert ">Legend</text>" in svg
    assert "Pipe x91" in svg
    assert "Conveyor Belt x32" in svg
    assert "Gas Plant x24" in svg
    assert "Platform x8" in svg
    assert 'class="legend-icon legend-pipe"' in svg
    assert 'class="legend-icon legend-line"' in svg
    assert 'class="legend-icon legend-machine"' in svg
    assert 'class="legend-icon legend-rect"' in svg


def test_title_is_xml_escaped() -> None:
    meta = parse_blueprint(SAMPLES[0])
    meta.name = "<script>alert('xss')</script>"
    svg = render_svg(meta, author='"><script>bad()</script>')
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_unknown_building_ids_get_a_stable_fallback_colour() -> None:
    first = build_style("build:totally_new_machine")
    second = build_style("build:totally_new_machine")
    assert first == second
    assert first[1].startswith("#")


def test_known_ids_are_in_the_style_table() -> None:
    for build_id in ("belt", "pipe", "gas_plant", "deck", "compact_splitter", "pelletizer", "depot"):
        assert build_id in BUILD_STYLES


def test_light_and_dark_themes_differ() -> None:
    meta = parse_blueprint(SAMPLES[0])
    assert render_svg(meta, theme="dark") != render_svg(meta, theme="light")


def test_empty_blueprint_does_not_crash() -> None:
    class _Empty:
        rows: list = []
        build_ids: list = []
        piece_count = 0
        total_cost = 0.0
        mk = 0
        name = "Empty"

    svg = render_svg(_Empty())
    assert svg.startswith("<svg ") and svg.endswith("</svg>")
    assert re.search(r"<svg [^>]*>", svg)


def test_author_is_escaped_and_shown() -> None:
    meta = parse_blueprint(SAMPLES[0])
    svg = render_svg(meta, author="aLee")
    assert "By aLee" in svg


# --- multi-level --------------------------------------------------------------


def test_assign_levels_clusters_by_gap() -> None:
    rows = [
        {"position": [0.0, 0.0, 0.0]},
        {"position": [0.0, 0.4, 0.0]},   # same floor (within LEVEL_GAP)
        {"position": [0.0, 4.0, 0.0]},
        {"position": [0.0, 10.0, 0.0]},
        {"a": [1.0, 15.0, 0.0], "b": [2.0, 15.0, 0.0]},  # segments anchor on ``a``
    ]
    levels, ys = assign_levels(rows)
    assert levels == [0, 0, 1, 2, 3]
    assert ys == [0.0, 4.0, 10.0, 15.0]


def test_rows_without_geometry_land_on_floor_zero() -> None:
    levels, ys = assign_levels([{"type": "mystery"}])
    assert levels == [0]
    assert ys == []


def test_floor_count_is_derived_from_the_up_axis() -> None:
    counts = {path.stem: parse_blueprint(path).level_count for path in SAMPLES}
    assert counts == {
        "1794502162_4776": 1,
        "1794505172_2ff6": 4,
        "1794508763_43c3": 2,
    }


def test_all_levels_badge_reports_the_level_count() -> None:
    svg = render_svg(parse_blueprint(MULTI_LEVEL))
    assert "4 Levels" in svg


def test_cumulative_badge_shows_the_slider_range() -> None:
    svg = render_svg(parse_blueprint(MULTI_LEVEL), max_level=1)
    assert "Levels 1–2/4" in svg
    assert "4 Levels" not in svg


def test_max_level_is_clamped_to_the_level_count() -> None:
    meta = parse_blueprint(MULTI_LEVEL)
    assert render_svg(meta, max_level=99) == render_svg(meta, max_level=3)


def test_levels_render_cumulatively() -> None:
    meta = parse_blueprint(MULTI_LEVEL)
    counts = [_rendered_pieces(render_svg(meta, max_level=k)) for k in range(meta.level_count)]
    assert counts == sorted(counts)          # raising the slider only ever adds pieces
    assert counts[-1] == _rendered_pieces(render_svg(meta))
    assert 0 < counts[0] < counts[-1]        # ground alone shows less than the whole build


def test_wall_free_blueprint_is_unchanged_when_hiding_walls() -> None:
    meta = parse_blueprint(MULTI_LEVEL)
    assert render_svg(meta, hide_walls=True) == render_svg(meta)


def test_hide_walls_omits_only_explicit_wall_pieces() -> None:
    meta = parse_blueprint(MULTI_LEVEL)
    meta.rows.append({"type": "stone_wall", "position": [0.0, 0.0, 0.0]})
    meta.build_ids.append("stone_wall")

    with_walls = render_svg(meta)
    without_walls = render_svg(meta, hide_walls=True)
    assert _rendered_pieces(with_walls) == _rendered_pieces(without_walls) + 1


def test_water_pipe_intersections_use_a_compact_footprint() -> None:
    assert BUILD_SIZES["water_cross"] == (0.8, 0.8, 0.8)
    assert BUILD_SIZES["water_cross"][0] < BUILD_SIZES.get("water_splitter", (1.4,))[0]


def test_flat_blueprint_has_no_level_badge() -> None:
    meta = parse_blueprint(FIXTURES / "1794502162_4776.blueprint")
    assert meta.level_count == 1
    svg = render_svg(meta)
    assert "levels" not in svg and "floors" not in svg
