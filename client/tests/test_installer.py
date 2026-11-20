"""Installer tests — the safety-critical path (see plan.txt Verification)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.core.installer import (
    STATUS_ALREADY,
    STATUS_BLOCKED,
    STATUS_INSTALLED,
    STATUS_INVALID,
    TEMP_SUFFIX,
    cleanup_temp_files,
    install,
    sanitize_filename,
)
from app.core.provenance import ProvenanceStore
from ftn_blueprint import decode_blob, encode_blueprint_file, parse_blueprint, sha256_of

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "tests" / "fixtures"
SAMPLE_A = (FIXTURES / "1794502162_4776.blueprint").read_bytes()
SAMPLE_B = (FIXTURES / "1794505172_2ff6.blueprint").read_bytes()
SAMPLE_C = (FIXTURES / "1794508763_43c3.blueprint").read_bytes()


def make_env(tmp_path):
    blueprints = tmp_path / "FindTheNeedle" / "blueprints"
    backups = tmp_path / "appdata" / "backups"
    provenance = ProvenanceStore(tmp_path / "appdata" / "provenance.json")
    return blueprints, backups, provenance


def snapshot(root: Path) -> set[str]:
    out = set()
    for p in root.rglob("*"):
        if p.is_file():
            out.add(p.relative_to(root).as_posix())
    return out


# -- happy path ------------------------------------------------------------
def test_install_happy_path(tmp_path):
    blueprints, backups, prov = make_env(tmp_path)
    result = install(
        SAMPLE_A, "My First.blueprint",
        blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False,
    )
    assert result.status == STATUS_INSTALLED
    assert result.final_path is not None and result.final_path.exists()
    assert result.final_path.name == "My First.blueprint"
    assert result.sha256 == sha256_of(SAMPLE_A)
    assert sha256_of(result.final_path) == sha256_of(SAMPLE_A)
    # re-parseable
    meta = parse_blueprint(result.final_path)
    assert meta.name == "New Blueprint"
    # no temp files left behind
    assert not [p for p in blueprints.iterdir() if p.name.endswith(TEMP_SUFFIX)]
    # provenance recorded
    assert prov.get("My First.blueprint") is not None


# -- identical -------------------------------------------------------------
def test_install_identical_is_noop(tmp_path):
    blueprints, backups, prov = make_env(tmp_path)
    install(SAMPLE_A, "Same.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    before = snapshot(tmp_path)
    result = install(SAMPLE_A, "Same.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    assert result.status == STATUS_ALREADY
    assert snapshot(tmp_path) == before  # no backup, no write
    assert not backups.exists()


# -- conflict --------------------------------------------------------------
def test_install_conflict_backs_up_and_renames(tmp_path):
    blueprints, backups, prov = make_env(tmp_path)
    install(SAMPLE_A, "Dup.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    result = install(SAMPLE_B, "Dup.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    assert result.status == STATUS_INSTALLED
    assert result.renamed_from == "Dup.blueprint"
    assert result.final_path.name == "Dup (2).blueprint"
    assert result.backup_path is not None and result.backup_path.exists()
    assert sha256_of(result.final_path) == sha256_of(SAMPLE_B)
    # original untouched
    assert sha256_of(blueprints / "Dup.blueprint") == sha256_of(SAMPLE_A)
    # backup matches the original
    assert sha256_of(result.backup_path) == sha256_of(SAMPLE_A)


def test_install_conflict_twice_uses_index_three(tmp_path):
    blueprints, backups, prov = make_env(tmp_path)
    install(SAMPLE_A, "X.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    install(SAMPLE_B, "X.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    third = install(SAMPLE_C, "X.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    assert third.status == STATUS_INSTALLED
    assert third.final_path.name == "X (3).blueprint"
    assert sha256_of(third.final_path) == sha256_of(SAMPLE_C)


# -- game running ----------------------------------------------------------
def test_install_blocked_while_game_running(tmp_path):
    blueprints, backups, prov = make_env(tmp_path)
    result = install(SAMPLE_A, "Blocked.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=True)
    assert result.status == STATUS_BLOCKED
    assert result.game_running is True
    assert not blueprints.exists() or not list(blueprints.glob("*.blueprint"))


# -- invalid data ----------------------------------------------------------
@pytest.mark.parametrize("payload", [b"", b"not a blueprint", os.urandom(64)])
def test_install_rejects_invalid(tmp_path, payload):
    blueprints, backups, prov = make_env(tmp_path)
    result = install(payload, "bad.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    assert result.status == STATUS_INVALID
    assert not blueprints.exists() or not list(blueprints.glob("*.blueprint"))


def test_install_rejects_unsupported_schema(tmp_path):
    blueprints, backups, prov = make_env(tmp_path)
    root = decode_blob(SAMPLE_A)
    root["format"] = 2
    blob = encode_blueprint_file(root)
    result = install(blob, "v2.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)
    assert result.status == STATUS_INVALID
    assert "schema" in result.message.lower()


# -- name sanitisation -----------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("plain", "plain.blueprint"),
        ("with space.blueprint", "with space.blueprint"),
        ("..\\..\\evil.blueprint", "evil.blueprint"),
        ("../../evil.blueprint", "evil.blueprint"),
        ("C:\\Windows\\evil.blueprint", "evil.blueprint"),
        ('bad<>:"|?*name.blueprint', "bad_name.blueprint"),
        ("trailing dots...", "trailing dots.blueprint"),
        ("   ", "blueprint.blueprint"),
        ("CON", "CON_file.blueprint"),
        ("a" * 400, "a" * 120 + ".blueprint"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_install_neutralises_path_traversal(tmp_path):
    blueprints, backups, prov = make_env(tmp_path)
    result = install(
        SAMPLE_A, "..\\..\\escape.blueprint",
        blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False,
    )
    assert result.status == STATUS_INSTALLED
    assert result.final_path.parent == blueprints
    assert result.final_path.name == "escape.blueprint"


# -- no side effects -------------------------------------------------------
def test_no_writes_outside_allowed_roots(tmp_path):
    root = tmp_path / "sandbox"
    blueprints, backups, prov = make_env(root)
    before = snapshot(root) if root.exists() else set()

    install(SAMPLE_A, "Safe.blueprint", blueprints_dir=blueprints, backups_root=backups, provenance=prov, game_running=False)

    after = snapshot(root)
    new_files = after - before
    for rel in new_files:
        assert rel.startswith("FindTheNeedle/blueprints/") or rel.startswith("appdata/"), rel
    assert Path("FindTheNeedle/blueprints/Safe.blueprint").as_posix() in new_files


# -- temp cleanup ----------------------------------------------------------
def test_cleanup_temp_files(tmp_path):
    blueprints, backups, prov = make_env(tmp_path)
    blueprints.mkdir(parents=True)
    leftover = blueprints / ("Some.blueprint" + TEMP_SUFFIX)
    leftover.write_bytes(b"partial")
    keep = blueprints / "Real.blueprint"
    keep.write_bytes(SAMPLE_A)
    removed = cleanup_temp_files(blueprints)
    assert leftover in removed
    assert not leftover.exists()
    assert keep.exists()
