"""Provenance side-store round-trip and persistence."""

from __future__ import annotations

from app.core.provenance import ProvenanceRecord, ProvenanceStore


def test_record_and_get(tmp_path):
    store = ProvenanceStore(tmp_path / "provenance.json")
    store.record(
        "Cool Machine.blueprint",
        installed_sha256="a" * 64,
        remote_id="abc123",
        remote_title="Cool Machine",
        remote_author="aLee",
        original_sha256="b" * 64,
        renamed_from="Cool Machine (2).blueprint",
    )
    rec = store.get("Cool Machine.blueprint")
    assert isinstance(rec, ProvenanceRecord)
    assert rec.remote_author == "aLee"
    assert rec.installed_sha256 == "a" * 64
    # case-insensitive lookup by name
    assert store.get("cool machine.blueprint") is not None


def test_persistence(tmp_path):
    path = tmp_path / "provenance.json"
    store = ProvenanceStore(path)
    store.record("A.blueprint", installed_sha256="c" * 64, remote_id="1")
    reloaded = ProvenanceStore(path)
    assert len(reloaded) == 1
    assert reloaded.get("A.blueprint").remote_id == "1"


def test_remove(tmp_path):
    store = ProvenanceStore(tmp_path / "provenance.json")
    store.record("A.blueprint", installed_sha256="c" * 64)
    store.remove("A.blueprint")
    assert store.get("A.blueprint") is None
    assert len(store) == 0


def test_missing_file_is_empty(tmp_path):
    store = ProvenanceStore(tmp_path / "nope.json")
    assert len(store) == 0
    assert store.get("anything.blueprint") is None


def test_corrupt_file_tolerated(tmp_path):
    path = tmp_path / "provenance.json"
    path.write_text("{not json", encoding="utf-8")
    store = ProvenanceStore(path)
    assert len(store) == 0
