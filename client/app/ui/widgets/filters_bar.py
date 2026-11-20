"""Search box, category chips, sort selector and grid/list toggle."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .flow_layout import FlowLayout

__all__ = ["FiltersBar"]

DEFAULT_SORTS: tuple[tuple[str, str], ...] = (
    ("newest", "Newest"),
    ("downloads", "Most downloaded"),
    ("popularity", "Popularity"),
    ("cost", "Cost"),
    ("pieces", "Pieces"),
    ("name", "Name"),
)


class FiltersBar(QFrame):
    """Emits the current search, category, sort key and sort direction."""

    filters_changed = Signal(dict)
    view_changed = Signal(bool)
    refresh_requested = Signal()

    def __init__(
        self,
        *,
        categories: list[str] | None = None,
        sorts: tuple[tuple[str, str], ...] = DEFAULT_SORTS,
        show_view_toggle: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._category = ""
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self.search = QLineEdit(self)
        self.search.setObjectName("SearchInput")
        self.search.setPlaceholderText("Search blueprints by name, author or tag…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self.search.setMinimumWidth(170)
        controls.addWidget(self.search, 1)

        self.sort = QComboBox(self)
        for value, label in sorts:
            self.sort.addItem(label, value)
        self.sort.currentIndexChanged.connect(lambda _: self._emit())
        self.sort.setMinimumWidth(145)
        controls.addWidget(self.sort)

        self.direction = QComboBox(self)
        self.direction.addItem("Descending", "desc")
        self.direction.addItem("Ascending", "asc")
        self.direction.currentIndexChanged.connect(lambda _: self._emit())
        self.direction.setMinimumWidth(115)
        controls.addWidget(self.direction)

        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.setObjectName("Ghost")
        self.refresh_button.clicked.connect(lambda: self.refresh_requested.emit())
        controls.addWidget(self.refresh_button)

        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self._chip_row = FlowLayout(spacing=6)
        self._chips: dict[str, QPushButton] = {}
        layout.addLayout(controls)
        layout.addLayout(self._chip_row)
        self.set_categories(categories or [])

        self.grid_button: QPushButton | None = None
        self.list_button: QPushButton | None = None
        if show_view_toggle:
            self.grid_button = QPushButton("Grid", self)
            self.grid_button.setObjectName("Chip")
            self.grid_button.setCheckable(True)
            self.grid_button.setChecked(True)
            self.list_button = QPushButton("List", self)
            self.list_button.setObjectName("Chip")
            self.list_button.setCheckable(True)
            toggle = QButtonGroup(self)
            toggle.setExclusive(True)
            toggle.addButton(self.grid_button)
            toggle.addButton(self.list_button)
            self.grid_button.clicked.connect(lambda: self.view_changed.emit(True))
            self.list_button.clicked.connect(lambda: self.view_changed.emit(False))
            controls.addWidget(self.grid_button)
            controls.addWidget(self.list_button)

    # -- categories --------------------------------------------------------
    def set_categories(self, categories: list[str]) -> None:
        for button in self._chips.values():
            self._chip_group.removeButton(button)
            button.deleteLater()
        self._chips.clear()
        while self._chip_row.count():
            item = self._chip_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        self._add_chip("All", "")
        for name in categories:
            if name:
                self._add_chip(name, name)

    def _add_chip(self, label: str, value: str) -> None:
        button = QPushButton(label, self)
        button.setObjectName("Chip")
        button.setCheckable(True)
        button.setChecked(value == self._category)
        button.clicked.connect(lambda _, v=value: self._select_category(v))
        self._chip_group.addButton(button)
        self._chip_row.addWidget(button)
        self._chips[value] = button

    def _select_category(self, value: str) -> None:
        self._category = value
        self._emit()

    # -- state -------------------------------------------------------------
    def current_filters(self) -> dict:
        return {
            "q": self.search.text().strip(),
            "category": self._category,
            "sort": self.sort.currentData(),
            "direction": self.direction.currentData(),
        }

    def set_view(self, is_grid: bool) -> None:
        if self.grid_button is not None:
            self.grid_button.setChecked(is_grid)
        if self.list_button is not None:
            self.list_button.setChecked(not is_grid)
        self.view_changed.emit(is_grid)

    def focus_search(self) -> None:
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def _emit(self) -> None:
        self.filters_changed.emit(self.current_filters())
