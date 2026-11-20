"""Cross-platform helpers for opening files and folders in the OS shell."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

__all__ = ["reveal_in_file_manager", "open_folder", "open_path"]


def _start(args: list[str]) -> None:
    try:
        if os.name == "nt":
            # ``explorer`` returns a non-zero exit code even on success, so detach.
            subprocess.Popen(args, close_fds=True)
        else:
            subprocess.Popen(args)
    except OSError:
        pass


def reveal_in_file_manager(path: str | os.PathLike[str]) -> None:
    """Open the OS file manager with ``path`` selected."""
    target = Path(path)
    if os.name == "nt":
        _start(["explorer", f"/select,{target}"])
    elif sys.platform == "darwin":
        _start(["open", "-R", str(target)])
    else:
        _start(["xdg-open", str(target.parent)])


def open_folder(path: str | os.PathLike[str]) -> None:
    """Open a folder in the OS file manager."""
    target = Path(path)
    if os.name == "nt":
        _start(["explorer", str(target)])
    elif sys.platform == "darwin":
        _start(["open", str(target)])
    else:
        _start(["xdg-open", str(target)])


def open_path(path: str | os.PathLike[str]) -> None:
    """Open a file with the OS default application."""
    target = Path(path)
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        _start(["open", str(target)])
    else:
        _start(["xdg-open", str(target)])
