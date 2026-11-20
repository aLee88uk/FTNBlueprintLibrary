"""Human-readable names for building ids used in ``.blueprint`` files.

The game stores buildings as snake_case ids (``gas_plant``, ``enclosed_belt``).
This module maps them to the names shown in the in-game UI so the library can
display "Gas Plant" instead of the raw id.

The mapping is intentionally explicit rather than derived: the in-game names
are not always a simple title-case of the id (e.g. ``enclosed_belt`` is shown
as "Enclosed Conveyor", and ``pelletizer`` as "Hay Bricketizer").  Unknown ids
fall back to a title-cased version of the id.
"""

from __future__ import annotations

__all__ = ["BUILDING_NAMES", "pretty_building_name"]

#: raw build id -> in-game display name.
BUILDING_NAMES: dict[str, str] = {
    # logistics
    "belt": "Conveyor Belt",
    "conveyor": "Conveyor Belt",
    "enclosed_belt": "Enclosed Conveyor",
    "enclosed_conveyor": "Enclosed Conveyor",
    "compact_splitter": "Compact Splitter",
    "compact_joiner": "Compact Joiner",
    "conveyor_compact_splitter": "Compact Splitter",
    "conveyor_compact_joiner": "Compact Joiner",
    # water / pipes
    "pipe": "Pipe",
    "water_main": "Water Pipe",
    "water_cross": "Water Cross",
    "water_splitter": "Water Splitter",
    # power
    "gas_plant": "Gas Plant",
    "switch_box": "Power Station",
    "power": "Power Station",
    # processing
    "pelletizer": "Hay Bricketizer",
    "hay_pelletizer": "Hay Bricketizer",
    # storage / movement
    "depot": "Depot",
    "haylift": "Hay Lift",
    "hay_lift": "Hay Lift",
    "haystairs": "Hay Stairs",
    "hay_stairs": "Hay Stairs",
    # ground works
    "deck": "Platform",
    "platform": "Platform",
}


def pretty_building_name(build_id: str) -> str:
    """Return the in-game display name for ``build_id``.

    Strips a ``build:`` prefix, looks up the explicit mapping, and falls back
    to title-casing the snake_case id (``gas_plant`` -> ``Gas Plant``).
    """
    if not build_id:
        return ""
    key = build_id.split(":", 1)[-1] if ":" in build_id else build_id
    if key in BUILDING_NAMES:
        return BUILDING_NAMES[key]
    return key.replace("_", " ").strip().title()
