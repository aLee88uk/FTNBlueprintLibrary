"""Application bootstrap.

Run with ``python client/run.py`` (or ``python -m app.main`` from ``client/``).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the shared codec importable when the client is started directly.
try:  # pragma: no cover - import guard
    import ftn_blueprint  # noqa: F401
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from .config import Settings  # noqa: E402
from .context import AppContext  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402

__all__ = ["main"]

if getattr(sys, "frozen", False):  # pragma: no cover - PyInstaller layout
    _ASSETS = Path(getattr(sys, "_MEIPASS", "")) / "app" / "assets"
else:
    _ASSETS = Path(__file__).resolve().parent / "assets"


def main(argv: list[str] | None = None) -> int:
    """Create the application, show the window and enter the event loop."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("FTN Blueprint Library")
    app.setApplicationDisplayName("FTN Blueprint Library")
    app.setOrganizationName("FTNBlueprintLibrary")

    icon_file = _ASSETS / "app.ico"
    if icon_file.is_file():
        icon = QIcon(str(icon_file))
        if not icon.isNull():
            app.setWindowIcon(icon)

    settings = Settings.load()
    ctx = AppContext(settings)
    window = MainWindow(ctx)
    window.show()

    if ctx.library is None or not ctx.library.exists():
        window._select(3)  # Settings
        window.notify_status("Blueprint folder not found — set it in Settings.")

    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
