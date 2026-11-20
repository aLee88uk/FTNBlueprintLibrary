"""Codec tests: byte-exact round trip against the three live blueprints."""

from __future__ import annotations

import pathlib
import struct

import pytest

from ftn_blueprint.variant import (
    ENCODE_FLAG_64,
    Float64,
    Int64,
    Reader,
    VariantError,
    Vector2,
    Vector3,
    Writer,
    decode_blob,
    read_variant,
    write_variant,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
SAMPLES = sorted(FIXTURES.glob("*.blueprint"))


def test_samples_present() -> None:
    assert len(SAMPLES) == 3, f"expected 3 live samples, found {[p.name for p in SAMPLES]}"


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_header_length_matches_payload(path: pathlib.Path) -> None:
    raw = path.read_bytes()
    declared = struct.unpack_from("<I", raw, 0)[0]
    assert declared == len(raw) - 4


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_byte_exact_round_trip(path: pathlib.Path) -> None:
    """``write_variant(decode_blob(f)) == f[4:]`` proves both codec directions."""
    raw = path.read_bytes()
    assert write_variant(decode_blob(raw)) == raw[4:]


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_root_is_dictionary_with_19_keys(path: pathlib.Path) -> None:
    root = decode_blob(path.read_bytes())
    assert isinstance(root, dict)
    assert len(root) == 19


def test_scalar_encodings_match_observed_bytes() -> None:
    # INT (i32) and FLOAT (f32) as seen in the small sample.
    assert write_variant(1) == bytes.fromhex("02000000") + bytes.fromhex("01000000")
    assert write_variant(1.5707964) == bytes.fromhex("03000000") + bytes.fromhex("db0fc93f")
    # BOOL is a u32.
    assert write_variant(True) == bytes.fromhex("01000000") + bytes.fromhex("01000000")
    # NIL is just the type id.
    assert write_variant(None) == bytes.fromhex("00000000")


def test_string_padding_to_four_bytes() -> None:
    # "format" (6 bytes) -> 2 zero pad bytes.
    assert write_variant("format") == bytes.fromhex("04000000") + struct.pack("<I", 6) + b"format\x00\x00"
    # "name" (4 bytes) -> no padding.
    assert write_variant("name") == bytes.fromhex("04000000") + struct.pack("<I", 4) + b"name"
    # "1794502162_4776" (15 bytes) -> 1 zero pad byte.
    blob = write_variant("1794502162_4776")
    assert blob.endswith(b"1794502162_4776\x00")


def test_flag64_int_and_float_round_trip() -> None:
    """``ENCODE_FLAG_64`` selects 8-byte i64/f64 payloads (seen in big blueprints)."""
    payload = write_variant({"yaw": Float64(-3.141592653589793), "big": Int64(2**40)})
    assert b"\x03\x00\x01\x00" in payload  # FLOAT | ENCODE_FLAG_64
    assert b"\x02\x00\x01\x00" in payload  # INT | ENCODE_FLAG_64
    decoded = read_variant(Reader(payload))
    assert isinstance(decoded["yaw"], Float64)
    assert isinstance(decoded["big"], Int64)
    assert decoded["yaw"] == pytest.approx(-3.141592653589793)
    assert decoded["big"] == 2**40
    assert (Int64.__mro__[1] is int) and (Float64.__mro__[1] is float)
    assert ENCODE_FLAG_64 == 1 << 16


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        -7,
        123456,
        1.5,
        -0.0,
        "",
        "unicode ✓ – 日本語",
        {"a": 1, "b": [1, 2, 3], "c": {"d": "e"}},
        [1, "two", 3.0, None, True],
        [],
        {},
        b"\x00\x01\x02",
        Vector2((1.0, 2.0)),
        Vector3((1.0, 2.0, 3.0)),
        {"rows": [{"type": "conveyor", "a": Vector3((0, 1, 2)), "b": Vector3((0, 1, 4))}]},
    ],
)
def test_round_trip_various_types(value: object) -> None:
    payload = write_variant(value)
    assert write_variant(read_variant(Reader(payload))) == payload


def test_nested_depth_guard() -> None:
    nested: object = []
    for _ in range(80):
        nested = [nested]
    payload = write_variant(nested)
    with pytest.raises(VariantError):
        read_variant(Reader(payload))


def test_unknown_type_id_rejected() -> None:
    with pytest.raises(VariantError):
        read_variant(Reader(struct.pack("<I", 4242) + b"\x00" * 8))


def test_short_read_rejected() -> None:
    with pytest.raises(VariantError):
        read_variant(Reader(struct.pack("<I", 4) + b"ab"))


def test_trailing_garbage_is_not_silently_accepted() -> None:
    raw = SAMPLES[0].read_bytes()
    with pytest.raises(VariantError):
        decode_blob(raw + b"\xff\xff")


def test_marker_fallback_for_future_headers() -> None:
    """A header that is larger than 4 bytes must still parse via the marker scan."""
    raw = SAMPLES[0].read_bytes()
    mutated = b"\x00\x00\x00\x00\x00\x00\x00\x00" + raw[4:]
    assert decode_blob(mutated) == decode_blob(raw)


def test_writer_matches_reader_alignment() -> None:
    writer = Writer()
    writer.u32(27)
    writer.string("abc")  # 3 bytes + 1 pad
    assert len(writer.getvalue()) == 12
    reader = Reader(writer.getvalue())
    assert reader.u32() == 27
    assert reader.u32() == 3  # string length prefix
    assert reader.utf8(3) == "abc"
    assert reader.pos == 11
    assert reader.align() == 1
