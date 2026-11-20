"""Dialog to edit a blueprint's title, description, category and tags."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

__all__ = ["EditBlueprintDialog", "EditResult"]


@dataclass
class EditResult:
    """Values returned by :class:`EditBlueprintDialog`."""

    title: str
    description: str
    category: str
    tags: list[str]


class EditBlueprintDialog(QDialog):
    """Edit the public metadata of an owned blueprint."""

    def __init__(
        self,
        *,
        title: str,
        description: str,
        category: str,
        tags: list[str],
        categories: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit blueprint")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        hint = QLabel(
            "Update the name and description shown in the library. "
            "Only you can change these fields.",
            self,
        )
        hint.setObjectName("CardMeta")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)

        self.title_edit = QLineEdit(title, self)
        self.title_edit.setPlaceholderText("Blueprint name shown in the library")
        form.addRow("Title", self.title_edit)

        self.description_edit = QPlainTextEdit(description, self)
        self.description_edit.setPlaceholderText("What does it do? Tips, inputs/outputs, notes…")
        self.description_edit.setFixedHeight(90)
        form.addRow("Description", self.description_edit)

        self.category_combo = QComboBox(self)
        self.category_combo.setEditable(False)
        for name in categories or []:
            self.category_combo.addItem(name)
        index = self.category_combo.findText(category)
        if index < 0:
            self.category_combo.addItem(category)
            index = self.category_combo.count() - 1
        self.category_combo.setCurrentIndex(index)
        form.addRow("Category", self.category_combo)

        self.tags_edit = QLineEdit(", ".join(tags), self)
        self.tags_edit.setPlaceholderText("comma, separated, tags")
        form.addRow("Tags", self.tags_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_values(self) -> EditResult:
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        return EditResult(
            title=self.title_edit.text().strip(),
            description=self.description_edit.toPlainText().strip(),
            category=self.category_combo.currentText().strip(),
            tags=tags,
        )
