"""Small "support the project" popup opened from the nav rail.

The whole app is free and ad-free; this dialog is the only place that asks for
anything back, and it is entirely optional. It just surfaces a short thank-you
note and a button that opens the tip jar in the default browser.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import SUPPORT_URL

__all__ = ["SupportDialog"]


class SupportDialog(QDialog):
    """A short thank-you note plus an optional tip-jar button."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Support")
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        heading = QLabel("Thanks for using FTN Blueprint Library", self)
        heading.setObjectName("SectionTitle")
        heading.setWordWrap(True)
        root.addWidget(heading)

        message = QLabel(
            "I hope you enjoy it. I hate ads as much as you do, so there aren't "
            "any here. If you'd like to support the project, you can buy me a "
            "coffee below. No pressure at all.",
            self,
        )
        message.setObjectName("CardMeta")
        message.setWordWrap(True)
        root.addWidget(message)

        coffee = QPushButton("☕ Buy me a coffee", self)
        coffee.setObjectName("Primary")
        coffee.clicked.connect(self._open_support)
        root.addWidget(coffee)

        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.rejected.connect(self.reject)
        root.addWidget(close)

    def _open_support(self) -> None:
        QDesktopServices.openUrl(QUrl(SUPPORT_URL))
