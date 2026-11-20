"""Local folder scanning, caching and game-process detection."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.core.library import LocalLibrary, is_game_running

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "tests" / "fixtures"
NAMES = ["1794502162_4776.blueprint", "1794505172_2ff6.blueprint", "1794508763_43c3.blueprint"]


def build_folder(blueprints: Path) -> None:
    blueprints.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        shutil.copy2(FIXTURES / name, blueprints / name)


def test_scan_reads_all_blueprints(isolated_dirs):
    blueprints = isolated_dirs["blueprints"]
    build_folder(blueprints)
    lib = LocalLibrary(blueprints, index_file=isolated_dirs["data"] / "index.json")
    entries = lib.scan()
    assert len(entries) == 3
    assert all(e.is_readable for e in entries)
    names = {e.meta.name for e in entries}
    assert names == {"New Blueprint", "Power Station", "Brick Factory"}
    power = next(e for e in entries if e.meta.name == "Power Station")
    assert power.piece_count == 201
    assert power.meta.icon == "build:switch_box"


def test_scan_ignores_trash_and_other_files(isolated_dirs):
    blueprints = isolated_dirs["blueprints"]
    build_folder(blueprints)
    trash = blueprints / ".trash"
    trash.mkdir()
    shutil.copy2(FIXTURES / NAMES[0], trash / NAMES[0])
    (blueprints / "notes.txt").write_text("hello", encoding="utf-8")
    lib = LocalLibrary(blueprints, index_file=isolated_dirs["data"] / "index.json")
    entries = lib.scan()
    assert len(entries) == 3
    assert all(e.path.parent == blueprints for e in entries)


def test_scan_flags_unreadable_but_keeps_going(isolated_dirs):
    blueprints = isolated_dirs["blueprints"]
    build_folder(blueprints)
    broken = blueprints / "9999999999_dead.blueprint"
    broken.write_bytes(b"\x00\x01\x02 not a blueprint")
    lib = LocalLibrary(blueprints, index_file=isolated_dirs["data"] / "index.json")
    entries = lib.scan()
    assert len(entries) == 4
    bad = next(e for e in entries if e.filename == broken.name)
    assert bad.status == "unreadable"
    assert bad.error
    assert sum(1 for e in entries if e.is_readable) == 3


def test_scan_cache_reuses_until_changed(isolated_dirs):
    blueprints = isolated_dirs["blueprints"]
    build_folder(blueprints)
    index = isolated_dirs["data"] / "index.json"
    lib = LocalLibrary(blueprints, index_file=index)
    first = lib.scan()
    second = lib.scan()
    # cached: same meta object identity
    a = {e.filename: e.meta for e in first}
    b = {e.filename: e.meta for e in second}
    assert a[NAMES[0]] is b[NAMES[0]]

    target = blueprints / NAMES[0]
    time.sleep(0.01)
    shutil.copy2(FIXTURES / NAMES[2], target)  # replace contents + mtime
    third = lib.scan()
    changed = next(e for e in third if e.filename == NAMES[0])
    assert changed.meta.name == "Brick Factory"


def test_index_persisted(isolated_dirs):
    blueprints = isolated_dirs["blueprints"]
    build_folder(blueprints)
    index = isolated_dirs["data"] / "index.json"
    LocalLibrary(blueprints, index_file=index).scan()
    assert index.exists()
    # a fresh library re-uses the persisted index without re-parsing
    lib2 = LocalLibrary(blueprints, index_file=index)
    assert str(blueprints / NAMES[0]) in lib2._cache


def test_missing_folder_is_empty(isolated_dirs):
    lib = LocalLibrary(isolated_dirs["game"] / "does_not_exist", index_file=isolated_dirs["data"] / "index.json")
    assert lib.exists() is False
    assert lib.scan() == []


def test_summarise(isolated_dirs):
    blueprints = isolated_dirs["blueprints"]
    build_folder(blueprints)
    lib = LocalLibrary(blueprints, index_file=isolated_dirs["data"] / "index.json")
    summary = lib.summarise()
    assert summary["total"] == 3
    assert summary["readable"] == 3
    assert summary["unreadable"] == 0
    assert summary["pieces"] == 1 + 201 + 59


def test_is_game_running_returns_bool():
    assert isinstance(is_game_running(), bool)
