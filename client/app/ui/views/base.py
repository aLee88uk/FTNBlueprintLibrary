"""Common scaffolding shared by every page."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..widgets import show_toast

__all__ = ["View"]


class View(QWidget):
    """Base page: a title header plus an area subclasses fill in."""

    page_title = "View"
    page_subtitle = ""

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 18, 22, 18)
        self.root.setSpacing(14)

        header = QWidget(self)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel(self.page_title, header)
        self.title_label.setObjectName("PageTitle")
        titles.addWidget(self.title_label)
        self.subtitle_label = QLabel(self.page_subtitle, header)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setWordWrap(True)
        titles.addWidget(self.subtitle_label)
        header_row.addLayout(titles, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        header_row.addLayout(self.actions, 0)

        self.root.addWidget(header)

    # -- helpers -----------------------------------------------------------
    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)

    def notify(self, text: str, *, level: str = "info", action: str | None = None):
        """Show a toast anchored to the main window."""
        window = self.window()
        return show_toast(window if window is not None else self, text, level=level, action=action)

    # -- lifecycle ---------------------------------------------------------
    def refresh(self) -> None:
        """Reload the page's data. Overridden by subclasses."""

    def on_shown(self) -> None:
        """Called each time the page becomes visible."""
        self.refresh()
