"""Godot binary ``Variant`` codec (little-endian) used by *Find The Needle*.

``.blueprint`` files are laid out as::

    [u32 LE payload_len][Godot binary Variant blob]

The payload is a Godot 4 ``DICTIONARY`` (type id ``27``).  This module provides
a decoder (:func:`read_variant`), a mirror encoder (:func:`write_variant`) that
round-trips byte-for-byte, and :func:`decode_blob` for whole ``.blueprint``
files.

Empirical notes gathered from three live samples:

* Scalars are little-endian: ``BOOL`` -> ``u32``, ``INT`` -> ``i32``,
  ``FLOAT`` -> ``f32``.
* The 4-byte type prefix is ``type_id | (flags << 16)``.  Flag bit 0 is
  Godot's ``ENCODE_FLAG_64``: when set, ``INT`` payloads are 8-byte ``i64`` and
  ``FLOAT`` payloads are 8-byte ``f64`` (a double).  Real samples contain both
  forms, e.g. ``03 00 00 00`` = ``f32`` and ``03 00 01 00`` = ``f64``.
* Strings are ``u32 len`` + UTF-8 bytes, then **zero-padded to a 4-byte
  boundary**.  The declared length excludes the padding.
* Consecutive fields are *not* otherwise padded (they are already 4-aligned).
"""

from __future__ import annotations

import struct
from typing import Any

__all__ = [
    "VariantError",
    "Reader",
    "Writer",
    "read_variant",
    "write_variant",
    "decode_blob",
    "Vector2",
    "Vector2i",
    "Vector3",
    "Vector3i",
    "Vector4",
    "Vector4i",
    "Rect2",
    "Rect2i",
    "Plane",
    "Quaternion",
    "AABB",
    "Basis",
    "Transform2D",
    "Transform3D",
    "Projection",
    "Color",
    "Float64",
    "Int64",
    "PackedByteArray",
    "PackedInt32Array",
    "PackedInt64Array",
    "PackedFloat32Array",
    "PackedFloat64Array",
    "PackedStringArray",
    "PackedVector2Array",
    "PackedVector3Array",
    "PackedColorArray",
    "PackedVector4Array",
]

#: Maximum nesting we are willing to follow.  Guards against corrupt/hostile
#: blobs that claim an absurd depth.
MAX_DEPTH = 64

# --- Godot 4 ``Variant::Type`` ids -------------------------------------------
T_NIL = 0
T_BOOL = 1
T_INT = 2
T_FLOAT = 3
T_STRING = 4
T_VECTOR2 = 5
T_VECTOR2I = 6
T_RECT2 = 7
T_RECT2I = 8
T_VECTOR3 = 9
T_VECTOR3I = 10
T_TRANSFORM2D = 11
T_VECTOR4 = 12
T_VECTOR4I = 13
T_PLANE = 14
T_QUATERNION = 15
T_AABB = 16
T_BASIS = 17
T_TRANSFORM3D = 18
T_PROJECTION = 19
T_COLOR = 20
T_STRING_NAME = 21
T_NODE_PATH = 22
T_RID = 23
T_OBJECT = 24
T_CALLABLE = 25
T_SIGNAL = 26
T_DICTIONARY = 27
T_ARRAY = 28
T_PACKED_BYTE_ARRAY = 29
T_PACKED_INT32_ARRAY = 30
T_PACKED_INT64_ARRAY = 31
T_PACKED_FLOAT32_ARRAY = 32
T_PACKED_FLOAT64_ARRAY = 33
T_PACKED_STRING_ARRAY = 34
T_PACKED_VECTOR2_ARRAY = 35
T_PACKED_VECTOR3_ARRAY = 36
T_PACKED_COLOR_ARRAY = 37
T_PACKED_VECTOR4_ARRAY = 38

#: The low 16 bits of the encoded type prefix hold the type id; the high 16
#: bits hold flags.  Flag bit 0 is ``ENCODE_FLAG_64``: 64-bit INT/FLOAT payload.
TYPE_MASK = 0xFFFF
ENCODE_FLAG_64 = 1 << 16

_TYPE_NAMES = {
    0: "NIL", 1: "BOOL", 2: "INT", 3: "FLOAT", 4: "STRING", 5: "VECTOR2",
    6: "VECTOR2I", 7: "RECT2", 8: "RECT2I", 9: "VECTOR3", 10: "VECTOR3I",
    11: "TRANSFORM2D", 12: "VECTOR4", 13: "VECTOR4I", 14: "PLANE",
    15: "QUATERNION", 16: "AABB", 17: "BASIS", 18: "TRANSFORM3D",
    19: "PROJECTION", 20: "COLOR", 21: "STRING_NAME", 22: "NODE_PATH",
    23: "RID", 24: "OBJECT", 25: "CALLABLE", 26: "SIGNAL", 27: "DICTIONARY",
    28: "ARRAY", 29: "PACKED_BYTE_ARRAY", 30: "PACKED_INT32_ARRAY",
    31: "PACKED_INT64_ARRAY", 32: "PACKED_FLOAT32_ARRAY",
    33: "PACKED_FLOAT64_ARRAY", 34: "PACKED_STRING_ARRAY",
    35: "PACKED_VECTOR2_ARRAY", 36: "PACKED_VECTOR3_ARRAY",
    37: "PACKED_COLOR_ARRAY", 38: "PACKED_VECTOR4_ARRAY",
}


def type_name(type_id: int) -> str:
    """Human readable name for a Godot type id (used in error messages)."""
    return _TYPE_NAMES.get(type_id, f"<unknown {type_id}>")


class VariantError(ValueError):
    """Raised when a blob cannot be decoded as a Godot binary Variant."""


# --- tuple subclasses that remember their exact Godot type id ----------------
# Plain tuples would lose the distinction between e.g. VECTOR2 and VECTOR2I,
# which matters for byte-exact re-encoding.
def _make_vector(name: str, type_id: int) -> type:
    return type(name, (tuple,), {"type_id": type_id, "__slots__": ()})


Vector2 = _make_vector("Vector2", T_VECTOR2)
Vector2i = _make_vector("Vector2i", T_VECTOR2I)
Rect2 = _make_vector("Rect2", T_RECT2)
Rect2i = _make_vector("Rect2i", T_RECT2I)
Vector3 = _make_vector("Vector3", T_VECTOR3)
Vector3i = _make_vector("Vector3i", T_VECTOR3I)
Transform2D = _make_vector("Transform2D", T_TRANSFORM2D)
Vector4 = _make_vector("Vector4", T_VECTOR4)
Vector4i = _make_vector("Vector4i", T_VECTOR4I)
Plane = _make_vector("Plane", T_PLANE)
Quaternion = _make_vector("Quaternion", T_QUATERNION)
AABB = _make_vector("AABB", T_AABB)
Basis = _make_vector("Basis", T_BASIS)
Transform3D = _make_vector("Transform3D", T_TRANSFORM3D)
Projection = _make_vector("Projection", T_PROJECTION)
Color = _make_vector("Color", T_COLOR)
PackedByteArray = _make_vector("PackedByteArray", T_PACKED_BYTE_ARRAY)
PackedInt32Array = _make_vector("PackedInt32Array", T_PACKED_INT32_ARRAY)
PackedInt64Array = _make_vector("PackedInt64Array", T_PACKED_INT64_ARRAY)
PackedFloat32Array = _make_vector("PackedFloat32Array", T_PACKED_FLOAT32_ARRAY)
PackedFloat64Array = _make_vector("PackedFloat64Array", T_PACKED_FLOAT64_ARRAY)
PackedStringArray = _make_vector("PackedStringArray", T_PACKED_STRING_ARRAY)
PackedVector2Array = _make_vector("PackedVector2Array", T_PACKED_VECTOR2_ARRAY)
PackedVector3Array = _make_vector("PackedVector3Array", T_PACKED_VECTOR3_ARRAY)
PackedColorArray = _make_vector("PackedColorArray", T_PACKED_COLOR_ARRAY)
PackedVector4Array = _make_vector("PackedVector4Array", T_PACKED_VECTOR4_ARRAY)

#: Element width of the packed arrays that store flat floats / vectors.
PACKED_VECTOR_WIDTHS = {
    T_PACKED_VECTOR2_ARRAY: 2,
    T_PACKED_VECTOR3_ARRAY: 3,
    T_PACKED_COLOR_ARRAY: 4,
    T_PACKED_VECTOR4_ARRAY: 4,
}


class Float64(float):
    """A ``FLOAT`` that was stored with ``ENCODE_FLAG_64`` (8-byte double).

    Behaves exactly like :class:`float`; the marker only exists so the encoder
    can reproduce the original byte layout.
    """

    __slots__ = ()
    type_id = T_FLOAT
    flags = 1


class Int64(int):
    """An ``INT`` that was stored with ``ENCODE_FLAG_64`` (8-byte i64)."""

    __slots__ = ()
    type_id = T_INT
    flags = 1


class Reader:
    """Little-endian cursor over a ``bytes`` buffer."""

    __slots__ = ("data", "pos", "base")

    def __init__(self, data: bytes, pos: int = 0, base: int = 0) -> None:
        self.data = data
        self.pos = pos
        #: Offset used as the origin for 4-byte alignment (see ``align``).
        self.base = base

    # -- low level ---------------------------------------------------------
    def _take(self, n: int) -> bytes:
        if n < 0:
            raise VariantError(f"negative read length {n}")
        end = self.pos + n
        if end > len(self.data):
            raise VariantError(
                f"short read: wanted {n} byte(s) at {self.pos}, "
                f"only {len(self.data) - self.pos} left"
            )
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def align(self, alignment: int = 4) -> int:
        """Advance to the next ``alignment``-byte boundary, returning pad size."""
        pad = (-(self.pos - self.base)) % alignment
        self.pos += pad
        if self.pos > len(self.data):
            raise VariantError("alignment padding ran past end of buffer")
        return pad

    def u8(self) -> int:
        return self._take(1)[0]

    def u32(self) -> int:
        return struct.unpack("<I", self._take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def i64(self) -> int:
        return struct.unpack("<q", self._take(8))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self._take(8))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self._take(4))[0]

    def f64(self) -> float:
        return struct.unpack("<d", self._take(8))[0]

    def utf8(self, n: int) -> str:
        return self._take(n).decode("utf-8", errors="replace")

    def remaining(self) -> int:
        return len(self.data) - self.pos


class Writer:
    """Mirror of :class:`Reader`; produces the exact byte layout."""

    __slots__ = ("buf",)

    def __init__(self) -> None:
        self.buf = bytearray()

    def raw(self, data: bytes) -> None:
        self.buf += data

    def align(self, alignment: int = 4) -> int:
        pad = (-len(self.buf)) % alignment
        if pad:
            self.buf += b"\x00" * pad
        return pad

    def u32(self, value: int) -> None:
        self.buf += struct.pack("<I", value & 0xFFFFFFFF)

    def i32(self, value: int) -> None:
        self.buf += struct.pack("<i", value)

    def i64(self, value: int) -> None:
        self.buf += struct.pack("<q", value)

    def u64(self, value: int) -> None:
        self.buf += struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)

    def f32(self, value: float) -> None:
        self.buf += struct.pack("<f", value)

    def f64(self, value: float) -> None:
        self.buf += struct.pack("<d", value)

    def string(self, value: str) -> None:
        encoded = value.encode("utf-8")
        self.u32(len(encoded))
        self.buf += encoded
        self.align(4)

    def getvalue(self) -> bytes:
        return bytes(self.buf)


def _read_string(r: Reader) -> str:
    length = r.u32()
    text = r.utf8(length)
    r.align(4)
    return text


def _read_floats(r: Reader, count: int) -> tuple:
    return struct.unpack(f"<{count}f", r._take(4 * count))


def _read_ints(r: Reader, count: int) -> tuple:
    return struct.unpack(f"<{count}i", r._take(4 * count))


def read_variant(r: Reader, depth: int = 0) -> Any:
    """Decode one Godot ``Variant`` from ``r`` and advance the cursor."""
    if depth > MAX_DEPTH:
        raise VariantError(f"variant nesting deeper than {MAX_DEPTH}")

    type_prefix = r.u32()
    type_id = type_prefix & TYPE_MASK
    is_64 = bool((type_prefix >> 16) & 1)

    if type_id == T_NIL:
        return None
    if type_id == T_BOOL:
        return bool(r.u32())
    if type_id == T_INT:
        return Int64(r.i64()) if is_64 else r.i32()
    if type_id == T_FLOAT:
        return Float64(r.f64()) if is_64 else r.f32()
    if type_id in (T_STRING, T_STRING_NAME, T_NODE_PATH):
        return _read_string(r)
    if type_id == T_VECTOR2:
        return Vector2(_read_floats(r, 2))
    if type_id == T_VECTOR2I:
        return Vector2i(_read_ints(r, 2))
    if type_id == T_RECT2:
        return Rect2(_read_floats(r, 4))
    if type_id == T_RECT2I:
        return Rect2i(_read_ints(r, 4))
    if type_id == T_VECTOR3:
        return Vector3(_read_floats(r, 3))
    if type_id == T_VECTOR3I:
        return Vector3i(_read_ints(r, 3))
    if type_id == T_TRANSFORM2D:
        return Transform2D(_read_floats(r, 6))
    if type_id == T_VECTOR4:
        return Vector4(_read_floats(r, 4))
    if type_id == T_VECTOR4I:
        return Vector4i(_read_ints(r, 4))
    if type_id == T_PLANE:
        return Plane(_read_floats(r, 4))
    if type_id == T_QUATERNION:
        return Quaternion(_read_floats(r, 4))
    if type_id == T_AABB:
        return AABB(_read_floats(r, 6))
    if type_id == T_BASIS:
        return Basis(_read_floats(r, 9))
    if type_id == T_TRANSFORM3D:
        return Transform3D(_read_floats(r, 12))
    if type_id == T_PROJECTION:
        return Projection(_read_floats(r, 16))
    if type_id == T_COLOR:
        return Color(_read_floats(r, 4))
    if type_id == T_RID:
        return r.u64()
    if type_id == T_DICTIONARY:
        count = r.u32()
        result: dict[Any, Any] = {}
        for _ in range(count):
            key = read_variant(r, depth + 1)
            result[key] = read_variant(r, depth + 1)
        return result
    if type_id == T_ARRAY:
        count = r.u32()
        return [read_variant(r, depth + 1) for _ in range(count)]
    if type_id == T_PACKED_BYTE_ARRAY:
        count = r.u32()
        values = PackedByteArray(r._take(count))
        r.align(4)
        return values
    if type_id == T_PACKED_INT32_ARRAY:
        count = r.u32()
        return PackedInt32Array(_read_ints(r, count))
    if type_id == T_PACKED_INT64_ARRAY:
        count = r.u32()
        return PackedInt64Array(struct.unpack(f"<{count}q", r._take(8 * count)))
    if type_id == T_PACKED_FLOAT32_ARRAY:
        count = r.u32()
        return PackedFloat32Array(_read_floats(r, count))
    if type_id == T_PACKED_FLOAT64_ARRAY:
        count = r.u32()
        return PackedFloat64Array(struct.unpack(f"<{count}d", r._take(8 * count)))
    if type_id == T_PACKED_STRING_ARRAY:
        count = r.u32()
        return PackedStringArray(read_variant(r, depth + 1) for _ in range(count))
    if type_id in PACKED_VECTOR_WIDTHS:
        count = r.u32()
        width = PACKED_VECTOR_WIDTHS[type_id]
        flat = _read_floats(r, count * width)
        element = {2: Vector2, 3: Vector3, 4: Vector4}[width]
        cls = {
            T_PACKED_VECTOR2_ARRAY: PackedVector2Array,
            T_PACKED_VECTOR3_ARRAY: PackedVector3Array,
            T_PACKED_COLOR_ARRAY: PackedColorArray,
            T_PACKED_VECTOR4_ARRAY: PackedVector4Array,
        }[type_id]
        return cls(element(flat[i : i + width]) for i in range(0, len(flat), width))
    if type_id in (T_OBJECT, T_CALLABLE, T_SIGNAL):
        raise VariantError(f"unsupported variant type {type_name(type_id)} in blueprint data")

    raise VariantError(f"unknown variant type id {type_id} at {r.pos - 4}")


def _write_variant(w: Writer, value: Any) -> None:
    """Encode ``value`` mirroring :func:`read_variant`."""
    # NOTE: bool must be tested before int (bool is an int subclass), and the
    # 64-bit markers before their plain counterparts.
    if value is None:
        w.u32(T_NIL)
        return
    if isinstance(value, bool):
        w.u32(T_BOOL)
        w.u32(1 if value else 0)
        return
    if isinstance(value, Int64):
        w.u32(T_INT | ENCODE_FLAG_64)
        w.i64(value)
        return
    if isinstance(value, int):
        w.u32(T_INT)
        w.i32(value)
        return
    if isinstance(value, Float64):
        w.u32(T_FLOAT | ENCODE_FLAG_64)
        w.f64(value)
        return
    if isinstance(value, float):
        w.u32(T_FLOAT)
        w.f32(value)
        return
    if isinstance(value, str):
        w.u32(T_STRING)
        w.string(value)
        return
    if isinstance(value, (bytes, bytearray)):
        w.u32(T_PACKED_BYTE_ARRAY)
        w.u32(len(value))
        w.raw(bytes(value))
        w.align(4)
        return
    if isinstance(value, dict):
        w.u32(T_DICTIONARY)
        w.u32(len(value))
        for key, item in value.items():
            _write_variant(w, key)
            _write_variant(w, item)
        return
    if isinstance(value, list):
        w.u32(T_ARRAY)
        w.u32(len(value))
        for item in value:
            _write_variant(w, item)
        return
    if isinstance(value, tuple):
        type_id = getattr(value, "type_id", None)
        if type_id is None:
            # Plain tuple fallback: infer from arity (floats).
            type_id = {2: T_VECTOR2, 3: T_VECTOR3, 4: T_VECTOR4}.get(len(value))
            if type_id is None:
                raise VariantError(f"cannot encode plain tuple of length {len(value)}")
        w.u32(type_id)
        _write_vector_payload(w, type_id, value)
        return

    raise VariantError(f"cannot encode object of type {type(value).__name__!r}")


_FLOAT_WIDTHS = {
    T_VECTOR2: 2, T_RECT2: 4, T_VECTOR3: 3, T_TRANSFORM2D: 6, T_VECTOR4: 4,
    T_PLANE: 4, T_QUATERNION: 4, T_AABB: 6, T_BASIS: 9, T_TRANSFORM3D: 12,
    T_PROJECTION: 16, T_COLOR: 4,
}
_INT_WIDTHS = {T_VECTOR2I: 2, T_RECT2I: 4, T_VECTOR3I: 3, T_VECTOR4I: 4}


def _write_vector_payload(w: Writer, type_id: int, value: tuple) -> None:
    if type_id in _FLOAT_WIDTHS:
        w.raw(struct.pack(f"<{_FLOAT_WIDTHS[type_id]}f", *value))
        return
    if type_id in _INT_WIDTHS:
        w.raw(struct.pack(f"<{_INT_WIDTHS[type_id]}i", *value))
        return
    if type_id == T_PACKED_BYTE_ARRAY:
        w.u32(len(value))
        w.raw(bytes(value))
        w.align(4)
        return
    if type_id == T_PACKED_INT32_ARRAY:
        w.u32(len(value))
        w.raw(struct.pack(f"<{len(value)}i", *value))
        return
    if type_id == T_PACKED_INT64_ARRAY:
        w.u32(len(value))
        w.raw(struct.pack(f"<{len(value)}q", *value))
        return
    if type_id in (T_PACKED_FLOAT32_ARRAY, T_PACKED_FLOAT64_ARRAY):
        code = "f" if type_id == T_PACKED_FLOAT32_ARRAY else "d"
        w.u32(len(value))
        w.raw(struct.pack(f"<{len(value)}{code}", *value))
        return
    if type_id == T_PACKED_STRING_ARRAY:
        w.u32(len(value))
        for text in value:
            w.u32(T_STRING)
            w.string(text)
        return
    if type_id in PACKED_VECTOR_WIDTHS:
        width = PACKED_VECTOR_WIDTHS[type_id]
        flat: list[float] = []
        for element in value:
            if len(element) != width:
                raise VariantError(
                    f"packed array element has {len(element)} components, expected {width}"
                )
            flat.extend(element)
        w.u32(len(value))
        w.raw(struct.pack(f"<{len(flat)}f", *flat))
        return
    raise VariantError(f"cannot encode vector payload for type id {type_id}")


def write_variant(value: Any) -> bytes:
    """Encode ``value`` back into a Godot binary Variant payload."""
    w = Writer()
    _write_variant(w, value)
    return w.getvalue()


def decode_blob(data: bytes, *, strict: bool = False) -> Any:
    """Decode a whole ``.blueprint`` file (``len`` prefix + Variant payload).

    The 4-byte little-endian length prefix is skipped.  As a robustness measure
    we also look for the ``DICTIONARY`` marker inside the first few bytes, so a
    future game build that changes the header size still parses.
    """
    if len(data) < 8:
        raise VariantError(f"blob too small: {len(data)} byte(s)")

    declared = struct.unpack_from("<I", data, 0)[0]

    starts = [4]
    marker = data.find(b"\x1b\x00\x00\x00", 0, 12)
    if marker > 4:
        starts.append(marker)

    last_error: VariantError | None = None
    for start in starts:
        payload = data[start:]
        try:
            r = Reader(payload, 0, 0)
            value = read_variant(r)
        except VariantError as exc:
            last_error = exc
            continue

        if isinstance(value, dict) and r.pos == len(payload):
            if start == 4 and not strict and declared != len(payload):
                raise VariantError(
                    f"header length {declared} does not match payload {len(payload)}"
                )
            return value

    if last_error is not None:
        raise VariantError(f"could not decode blueprint blob: {last_error}")
    raise VariantError("could not decode blueprint blob: no Variant payload found")
