"""Identity resolution: the game ``install_key`` (no synthetic fallback)."""

from __future__ import annotations

from pathlib import Path

from app.core.identity import game_dir_for, read_install_key, resolve_identity

PROFILE = """[identity]

install_key="2464a4cf69ee835de5127a53c007fe234d635552c699a0be7d4a9ac6d05836c8"
board_name="aLee"
"""

#: A real-world ``profile.cfg``: the game dumps multi-line JSON blobs (career
#: stats, daily records) whose continuation lines are *not* indented. Python's
#: ``configparser`` rejects those, so the key reader must not rely on it.
PROFILE_WITH_MULTILINE_JSON = """[career]

money_peak=2003412.6858260245
size_bests={
"best_dug": {
"small": 2396.9250848637894,
"standard": 45382.0
}
}
epoch=2

[days]

2026-11-12={
"belt_peak": 1848.0,
"best_dug": 45382.0,
"complete": {
"standard": 69536.49144534483
}
}

[identity]

refresh_token=""
access_token=""
board_name="aLee"
install_key="2464a4cf69ee835de5127a53c007fe234d635552c699a0be7d4a9ac6d05836c8"
"""


def write_profile(blueprints: Path, text: str) -> None:
    game_dir = blueprints.parent
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "profile.cfg").write_text(text, encoding="utf-8")


def test_reads_install_key(isolated_dirs):
    write_profile(isolated_dirs["blueprints"], PROFILE)
    key = read_install_key(isolated_dirs["blueprints"])
    assert key == "2464a4cf69ee835de5127a53c007fe234d635552c699a0be7d4a9ac6d05836c8"
    assert game_dir_for(isolated_dirs["blueprints"]) == isolated_dirs["game"]


def test_reads_install_key_when_profile_has_multiline_json(isolated_dirs):
    """The game writes unindented multi-line JSON; configparser rejects it,
    so the key reader must scan line-by-line instead."""
    write_profile(isolated_dirs["blueprints"], PROFILE_WITH_MULTILINE_JSON)
    key = read_install_key(isolated_dirs["blueprints"])
    assert key == "2464a4cf69ee835de5127a53c007fe234d635552c699a0be7d4a9ac6d05836c8"


def test_missing_profile_returns_none(isolated_dirs):
    assert read_install_key(isolated_dirs["blueprints"]) is None


def test_resolve_identity_returns_the_install_key(isolated_dirs):
    write_profile(isolated_dirs["blueprints"], PROFILE)
    identity = resolve_identity(isolated_dirs["blueprints"])
    assert identity == "2464a4cf69ee835de5127a53c007fe234d635552c699a0be7d4a9ac6d05836c8"


def test_resolve_identity_is_empty_without_a_game_key(isolated_dirs):
    # No profile.cfg -> no real key. We must NOT invent one, so the server
    # refuses registration/upload (retail-only) instead of trusting a made-up key.
    assert resolve_identity(isolated_dirs["blueprints"]) == ""


def test_game_dir_for_default(isolated_dirs):
    assert game_dir_for(None) == isolated_dirs["game"]
