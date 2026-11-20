"""A single blueprint tile: preview, title, badges and actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .flow_layout import FlowLayout
from .preview_canvas import PreviewCanvas

__all__ = ["BlueprintCard"]


class BlueprintCard(QFrame):
    """Reusable card. ``payload`` holds whatever the caller needs on click."""

    primary = Signal(object)
    secondary = Signal(object)
    activated = Signal(object)

    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        badges: list[str] | None = None,
        author: str = "",
        preview_height: int = 150,
        primary_text: str | None = "Download",
        secondary_text: str | None = "Details",
        payload: object = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.payload = payload

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.preview = PreviewCanvas(self, placeholder="Loading preview…")
        self.preview.setFixedHeight(preview_height)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.preview.clicked.connect(lambda: self.activated.emit(self.payload))
        outer.addWidget(self.preview)

        # Divider between the preview image and the text content.
        outer.addSpacing(6)
        outer.addWidget(self._make_divider())
        outer.addSpacing(6)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("CardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        outer.addWidget(self.title_label)

        if subtitle:
            self.subtitle_label = QLabel(subtitle, self)
            self.subtitle_label.setObjectName("CardMeta")
            self.subtitle_label.setWordWrap(True)
            outer.addWidget(self.subtitle_label)

        badge_row = FlowLayout(spacing=6)
        self._badge_layout = badge_row
        for text in badges or []:
            badge_row.addWidget(self._make_badge(text))
        outer.addLayout(badge_row)

        # Divider between the content (title/badges) and the action footer.
        outer.addSpacing(6)
        outer.addWidget(self._make_divider())
        outer.addSpacing(6)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.author_label = QLabel(author, self)
        self.author_label.setObjectName("CardMeta")
        footer.addWidget(self.author_label, 1)

        self.secondary_button: QPushButton | None = None
        if secondary_text:
            self.secondary_button = QPushButton(secondary_text, self)
            self.secondary_button.setObjectName("Ghost")
            self.secondary_button.clicked.connect(lambda: self.secondary.emit(self.payload))
            footer.addWidget(self.secondary_button)

        self.primary_button: QPushButton | None = None
        if primary_text:
            self.primary_button = QPushButton(primary_text, self)
            self.primary_button.setObjectName("Primary")
            self.primary_button.clicked.connect(lambda: self.primary.emit(self.payload))
            footer.addWidget(self.primary_button)

        outer.addLayout(footer)

    # -- helpers -----------------------------------------------------------
    def _make_divider(self) -> QWidget:
        """A thin horizontal separator line using the themed border color."""
        line = QWidget(self)
        line.setObjectName("Separator")
        line.setAttribute(Qt.WA_StyledBackground, True)
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return line

    def _make_badge(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setObjectName("Badge")
        label.setWordWrap(True)
        return label

    def add_badge(self, text: str) -> None:
        self._badge_layout.addWidget(self._make_badge(text))

    def update_badge(self, old_text: str, new_text: str) -> None:
        for index in range(self._badge_layout.count()):
            item = self._badge_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QLabel) and widget.text() == old_text:
                widget.setText(new_text)
                return

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_author(self, text: str) -> None:
        self.author_label.setText(text)

    def set_preview_svg(self, svg: str | None) -> None:
        self.preview.set_svg(svg)
        if svg is None:
            self.preview.set_placeholder("Preview unavailable")

    def set_preview_text(self, text: str) -> None:
        self.preview.set_placeholder(text)

    def set_primary_enabled(self, enabled: bool, text: str | None = None) -> None:
        if self.primary_button is None:
            return
        self.primary_button.setEnabled(enabled)
        if text is not None:
            self.primary_button.setText(text)
