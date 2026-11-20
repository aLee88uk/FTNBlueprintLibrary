"""Launch script for the FTN Blueprint Library desktop client.

Usage::

    python client/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _path in (HERE, ROOT / "shared"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
