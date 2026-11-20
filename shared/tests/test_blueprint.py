"""Parser tests pinned to the three live blueprints found in the game folder."""

from __future__ import annotations

import pathlib
import random

import pytest

from ftn_blueprint import (
    BlueprintError,
    UnsupportedSchemaError,
    decode_blob,
    encode_blueprint_file,
    parse_blueprint,
    parse_blueprint_bytes,
    sha256_of,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

#: name, icon, mk, made, pieces, distinct build counts -- captured from the game.
GROUND_TRUTH = {
    "1794502162_4776.blueprint": {
        "name": "New Blueprint",
        "icon": "build:compact_joiner",
        "mk": 3,
        "made": 1794502162,
        "piece_count": 1,
        "distinct_builds": {"compact_joiner": 1},
    },
    "1794505172_2ff6.blueprint": {
        "name": "Power Station",
        "icon": "build:switch_box",
        "mk": 3,
        "made": 1794505172,
        "piece_count": 201,
        "distinct_builds": {
            "pipe": 91,
            "belt": 32,
            "gas_plant": 24,
            "compact_splitter": 20,
            "water_cross": 19,
            "deck": 8,
            "enclosed_belt": 4,
            "haylift": 3,
        },
    },
    "1794508763_43c3.blueprint": {
        "name": "Brick Factory",
        "icon": "build:pelletizer",
        "mk": 3,
        "made": 1794508780,
        "piece_count": 59,
        "distinct_builds": {
            "enclosed_belt": 23,
            "pelletizer": 8,
            "deck": 8,
            "belt": 7,
            "compact_splitter": 7,
            "haystairs": 2,
            "haylift": 2,
            "depot": 1,
            "compact_joiner": 1,
        },
    },
}


@pytest.mark.parametrize("filename, expected", GROUND_TRUTH.items())
def test_fixture_ground_truth(filename: str, expected: dict) -> None:
    meta = parse_blueprint(FIXTURES / filename)
    assert meta.schema == 1
    assert meta.name == expected["name"]
    assert meta.icon == expected["icon"]
    assert meta.mk == expected["mk"]
    assert meta.made == expected["made"]
    assert meta.piece_count == expected["piece_count"]
    assert meta.distinct_builds == expected["distinct_builds"]
    assert sum(meta.distinct_builds.values()) == meta.piece_count


@pytest.mark.parametrize("filename", GROUND_TRUTH)
def test_costs_and_ids_lengths_match_rows(filename: str) -> None:
    meta = parse_blueprint(FIXTURES / filename)
    assert len(meta.rows) == meta.piece_count
    assert len(meta.build_ids) == meta.piece_count
    assert len(meta.costs) == meta.piece_count
    assert meta.total_cost == pytest.approx(sum(meta.costs))
    assert len(meta.pieces) == meta.piece_count


@pytest.mark.parametrize("filename", GROUND_TRUTH)
def test_pieces_expose_geometry(filename: str) -> None:
    meta = parse_blueprint(FIXTURES / filename)
    for piece in meta.pieces:
        assert piece.type
        assert piece.build_id
        assert hasattr(piece, "position")
    placed = [p for p in meta.pieces if p.position is not None]
    assert placed, "expected at least one row with a position"


def test_parse_from_bytes_and_path_agree() -> None:
    path = FIXTURES / "1794505172_2ff6.blueprint"
    assert parse_blueprint(path).to_index_dict() == parse_blueprint(path.read_bytes()).to_index_dict()


def test_sha256_of_bytes_matches_file() -> None:
    path = FIXTURES / "1794502162_4776.blueprint"
    assert sha256_of(path) == sha256_of(path.read_bytes())
    assert len(sha256_of(path)) == 64


def test_unsupported_schema_is_rejected() -> None:
    root = dict(decode_blob((FIXTURES / "1794502162_4776.blueprint").read_bytes()))
    root["format"] = 2
    with pytest.raises(UnsupportedSchemaError):
        parse_blueprint_bytes(encode_blueprint_file(root))


def test_missing_required_key_is_rejected() -> None:
    root = dict(decode_blob((FIXTURES / "1794502162_4776.blueprint").read_bytes()))
    del root["rows"]
    with pytest.raises(BlueprintError):
        parse_blueprint_bytes(encode_blueprint_file(root))


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x01", b"\x00\x00\x00\x00", b"not a blueprint at all", bytes(range(64))],
    ids=["empty", "one-byte", "zero-len-header", "ascii", "binary"],
)
def test_corrupt_inputs_are_rejected(payload: bytes) -> None:
    with pytest.raises(BlueprintError):
        parse_blueprint_bytes(payload)


def test_truncated_fixture_is_rejected() -> None:
    raw = (FIXTURES / "1794505172_2ff6.blueprint").read_bytes()
    with pytest.raises(BlueprintError):
        parse_blueprint_bytes(raw[: len(raw) // 2])


def test_random_bytes_are_rejected() -> None:
    rng = random.Random(1234)
    for _ in range(25):
        blob = bytes(rng.randrange(256) for _ in range(256))
        with pytest.raises(BlueprintError):
            parse_blueprint_bytes(blob)


def test_oversized_blob_is_rejected_by_parser_limits() -> None:
    """A 10 MB blob must not crash us; it simply is not a blueprint."""
    with pytest.raises(BlueprintError):
        parse_blueprint_bytes(b"\x00" * (10 * 1024 * 1024))
