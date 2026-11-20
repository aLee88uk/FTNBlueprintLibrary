"""Scrollable container that shows cards in a responsive grid or a list."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .flow_layout import FlowLayout

__all__ = ["CardGrid"]


class CardGrid(QScrollArea):
    """Holds blueprint cards; switches between grid and list presentation."""

    def __init__(self, *, card_width: int = 300, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card_width = card_width
        self._cards: list[QWidget] = []
        self._is_grid = True

        self._grid_host = QWidget()
        self._grid_host.setAutoFillBackground(False)
        self._grid_layout = FlowLayout(self._grid_host, margin=0, spacing=14)
        self._list_host = QWidget()
        self._list_host.setAutoFillBackground(False)
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(12)

        self._empty = QLabel("Nothing here yet", self)
        self._empty.setObjectName("EmptyState")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)

        self._stack = QStackedWidget(self)
        self._stack.setAutoFillBackground(False)
        self._stack.addWidget(self._grid_host)
        self._stack.addWidget(self._list_host)
        self._stack.addWidget(self._empty)

        self.setWidget(self._stack)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self._show_empty()

    # -- content -----------------------------------------------------------
    def set_cards(self, cards: list[QWidget]) -> None:
        self._cards = list(cards)
        self._render()

    def add_cards(self, cards: list[QWidget]) -> None:
        self._cards.extend(cards)
        self._render()

    def clear_cards(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self._render()

    def remove_card(self, card: QWidget) -> None:
        """Remove a single card and re-render the grid."""
        if card in self._cards:
            self._cards.remove(card)
            card.setParent(None)
            card.deleteLater()
            self._render()

    def set_empty_text(self, text: str) -> None:
        self._empty.setText(text)
        if not self._cards:
            self._show_empty()

    def set_grid(self, is_grid: bool) -> None:
        if is_grid == self._is_grid:
            return
        self._is_grid = is_grid
        self._render()

    @property
    def is_grid(self) -> bool:
        return self._is_grid

    @property
    def cards(self) -> list[QWidget]:
        return list(self._cards)

    # -- internals ---------------------------------------------------------
    def _show_empty(self) -> None:
        self._stack.setCurrentWidget(self._empty)

    def _render(self) -> None:
        if not self._cards:
            self._show_empty()
            return

        # Detach every card from whichever host currently owns it.
        for card in self._cards:
            card.setParent(None)

        if self._is_grid:
            self._clear_layout(self._list_layout)
            self._clear_layout(self._grid_layout)
            for card in self._cards:
                card.setFixedWidth(self._card_width)
                card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                self._grid_layout.addWidget(card)
            self._stack.setCurrentWidget(self._grid_host)
        else:
            self._clear_layout(self._grid_layout)
            self._clear_layout(self._list_layout)
            for card in self._cards:
                card.setMinimumWidth(0)
                card.setMaximumWidth(16777215)
                card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self._list_layout.addWidget(card)
            self._list_layout.addStretch(1)
            self._stack.setCurrentWidget(self._list_host)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
