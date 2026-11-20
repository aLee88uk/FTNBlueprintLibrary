"""The safety-critical installer.

Design rules (see plan.txt) — get these wrong and we damage a player's saves:

1. **Validate before touching disk.** The incoming bytes are parsed first; if
   they are not a supported blueprint nothing is written.
2. **Sanitise the name.** Directory components are stripped, Windows-illegal
   characters removed, and a ``.blueprint`` suffix enforced — a download can
   never escape the ``blueprints/`` folder.
3. **Never install while the game is running** (the game holds its own index).
4. **Never overwrite silently.** An identical file is a no-op; a different file
   with the same name is backed up and installed under ``Name (2)``.
5. **Atomic writes only.** We write ``<name>.ftnlib.tmp`` then ``os.replace`` —
   a crash can never leave a half-written ``.blueprint`` behind.
6. **Only ever *add* files inside ``blueprints/``.** Nothing outside
   ``blueprints/`` (and our own ``%LOCALAPPDATA%`` folder) is ever written, and
   we never delete or edit a game file.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ftn_blueprint import BlueprintError, BlueprintMeta, parse_blueprint, sha256_of

from ..core.paths import backups_dir, resolve_blueprints_dir
from .library import is_game_running
from .provenance import ProvenanceStore

__all__ = [
    "InstallResult",
    "install",
    "sanitize_filename",
    "cleanup_temp_files",
    "TEMP_SUFFIX",
]

TEMP_SUFFIX = ".ftnlib.tmp"

#: Characters Windows forbids in file names, plus control characters.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r"\s+")
_MULTI_UNDERSCORE = re.compile(r"_{2,}")
_MAX_STEM = 120

# InstallResult.status values.
STATUS_INSTALLED = "installed"
STATUS_ALREADY = "already_installed"
STATUS_BLOCKED = "blocked"
STATUS_INVALID = "invalid"


@dataclass
class InstallResult:
    """Outcome of an install attempt."""

    status: str
    message: str = ""
    final_path: Path | None = None
    renamed_from: str | None = None
    backup_path: Path | None = None
    sha256: str = ""
    game_running: bool = False
    meta: BlueprintMeta | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_INSTALLED, STATUS_ALREADY)

    @property
    def installed(self) -> bool:
        return self.status == STATUS_INSTALLED


def sanitize_filename(desired: str, *, fallback_stem: str = "blueprint") -> str:
    """Turn an arbitrary string into a safe ``*.blueprint`` file name.

    Strips any path components (including ``..`` traversal and drive letters),
    removes characters Windows rejects, and guarantees the ``.blueprint``
    suffix and a sane length.
    """
    raw = (desired or "").strip()
    # Normalise separators then keep only the final component.
    raw = raw.replace("\\", "/")
    raw = raw.split("/")[-1]
    raw = _ILLEGAL.sub("_", raw)
    raw = _MULTI_UNDERSCORE.sub("_", raw)
    raw = _MULTI_SPACE.sub(" ", raw).strip()

    stem = raw
    if stem.lower().endswith(".blueprint"):
        stem = stem[: -len(".blueprint")]
    # Windows dislikes trailing dots/spaces; leading dots hide the file.
    stem = stem.strip().strip(".").strip()
    stem = stem.strip()
    if len(stem) > _MAX_STEM:
        stem = stem[:_MAX_STEM].rstrip()
    if not stem:
        stem = fallback_stem
    # Reserved DOS device names would break Windows.
    if stem.upper() in _RESERVED_NAMES:
        stem = f"{stem}_file"
    return f"{stem}.blueprint"


_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def cleanup_temp_files(blueprints_dir: str | os.PathLike[str] | None = None) -> list[Path]:
    """Remove leftover ``*.ftnlib.tmp`` files from a previous crash.

    Only ever touches our own temp suffix; never a ``.blueprint``.
    """
    directory = Path(resolve_blueprints_dir(blueprints_dir))
    removed: list[Path] = []
    if not directory.is_dir():
        return removed
    for child in directory.iterdir():
        if child.is_file() and child.name.lower().endswith(TEMP_SUFFIX):
            try:
                child.unlink()
                removed.append(child)
            except OSError:
                pass
    return removed


def _unique_target(directory: Path, filename: str) -> Path:
    """Return a free path, appending ``(2)``, ``(3)`` … when needed."""
    target = directory / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    index = 2
    while True:
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def install(
    data: bytes,
    desired_name: str,
    *,
    source: dict | None = None,
    blueprints_dir: str | os.PathLike[str] | None = None,
    provenance: ProvenanceStore | None = None,
    backups_root: str | os.PathLike[str] | None = None,
    game_running: bool | None = None,
    allow_when_running: bool = False,
) -> InstallResult:
    """Safely install blueprint bytes into the game's ``blueprints/`` folder.

    Returns an :class:`InstallResult` describing exactly what happened; it never
    raises for expected problems (invalid data, collisions, game running).
    """
    source = source or {}
    directory = Path(resolve_blueprints_dir(blueprints_dir))

    # 1. Validate first — no disk writes if the payload is not a blueprint.
    try:
        meta = parse_blueprint(data)
    except BlueprintError as exc:
        return InstallResult(status=STATUS_INVALID, message=str(exc))
    digest = sha256_of(data)

    filename = sanitize_filename(desired_name, fallback_stem=meta.name or meta.filename_stem)

    # 2. Refuse while the game is running (player's own index is live).
    running = is_game_running() if game_running is None else game_running
    if running and not allow_when_running:
        return InstallResult(
            status=STATUS_BLOCKED,
            message="Find The Needle is running — close it before installing blueprints.",
            game_running=True,
            meta=meta,
            sha256=digest,
        )

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return InstallResult(status=STATUS_INVALID, message=f"cannot create blueprint folder: {exc}")

    cleanup_temp_files(directory)

    target = directory / filename
    renamed_from: str | None = None
    backup_path: Path | None = None

    if target.exists():
        try:
            existing_sha = sha256_of(target)
        except OSError:
            existing_sha = ""
        if existing_sha and existing_sha == digest:
            # 3. Identical file: no write, no backup.
            return InstallResult(
                status=STATUS_ALREADY,
                message=f"{filename} is already installed (identical).",
                final_path=target,
                sha256=digest,
                meta=meta,
            )
        # 4. Different content: back the old one up, then pick a free name.
        backup_path = _backup(target, backups_root)
        renamed_from = filename
        target = _unique_target(directory, filename)

    # 5. Atomic write: temp file in the same directory, then os.replace.
    temp = target.with_name(target.name + TEMP_SUFFIX)
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except OSError as exc:
        _silent_unlink(temp)
        return InstallResult(status=STATUS_INVALID, message=f"write failed: {exc}", meta=meta)

    # 6. Verify — re-read and compare the digest.
    try:
        written = sha256_of(target)
    except OSError as exc:
        return InstallResult(status=STATUS_INVALID, message=f"verification failed: {exc}", meta=meta)
    if written != digest:
        _silent_unlink(target)
        return InstallResult(status=STATUS_INVALID, message="verification failed: content mismatch", meta=meta)

    # 7. Record provenance.
    if provenance is not None:
        try:
            provenance.record(
                target.name,
                installed_sha256=digest,
                remote_id=source.get("id"),
                remote_title=source.get("title"),
                remote_author=source.get("author"),
                original_sha256=source.get("sha256"),
                renamed_from=renamed_from,
            )
        except OSError:
            pass

    message = f"Installed {target.name}."
    if renamed_from:
        message = f"“{renamed_from}” already existed — installed as “{target.name}” (old file backed up)."
    return InstallResult(
        status=STATUS_INSTALLED,
        message=message,
        final_path=target,
        renamed_from=renamed_from,
        backup_path=backup_path,
        sha256=digest,
        meta=meta,
    )


def _backup(target: Path, backups_root: str | os.PathLike[str] | None) -> Path | None:
    """Copy an existing file into our backups folder; returns the new path."""
    root = Path(backups_root) if backups_root is not None else backups_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination_dir = root / stamp
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = _unique_target(destination_dir, target.name)
        destination.write_bytes(target.read_bytes())
        return destination
    except OSError:
        return None


def _silent_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
