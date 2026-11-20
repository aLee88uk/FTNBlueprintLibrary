"""Transient notification banner shown at the bottom of the window."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

__all__ = ["Toast"]

_LEVELS = ("info", "success", "warning", "error")
_DEFAULT_TIMEOUT = {"info": 4200, "success": 4200, "warning": 6500, "error": 8000}


class Toast(QFrame):
    """A small self-dismissing banner."""

    _active: list["Toast"] = []

    def __init__(self, parent: QWidget, text: str, *, level: str = "info", action: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("level", level if level in _LEVELS else "info")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(12)

        self._label = QLabel(text, self)
        self._label.setObjectName("ToastText")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._label, 1)

        self.action_button: QPushButton | None = None
        if action:
            self.action_button = QPushButton(action, self)
            self.action_button.setObjectName("Ghost")
            layout.addWidget(self.action_button)

        close = QPushButton("✕", self)
        close.setObjectName("Ghost")
        close.setFixedWidth(28)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close)

        timeout = _DEFAULT_TIMEOUT.get(level, 4200)
        QTimer.singleShot(timeout, self.dismiss)

    # -- lifecycle ---------------------------------------------------------
    def dismiss(self) -> None:
        if self in Toast._active:
            Toast._active.remove(self)
        self.hide()
        self.deleteLater()
        for toast in list(Toast._active):
            toast.reposition()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.reposition()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        parent_bounds = QRect(parent.mapToGlobal(QPoint(0, 0)), parent.size())
        screen = parent.screen() or QGuiApplication.primaryScreen()
        screen_bounds = screen.availableGeometry() if screen is not None else parent_bounds
        visible_bounds = parent_bounds.intersected(screen_bounds)
        if visible_bounds.isEmpty():
            visible_bounds = parent_bounds

        max_width = max(1, visible_bounds.width() - 48)
        width = min(max(self.sizeHint().width(), 320), max_width)
        self.setFixedWidth(width)
        self.adjustSize()

        # Stack toasts from the bottom up, using each toast's *actual* height so
        # toasts with different wrapped-text heights never overlap.
        gap = 10
        bottom = visible_bounds.bottom() - 24
        x = visible_bounds.center().x() - width // 2
        # Walk from the lowest (oldest, index 0) to the highest, accumulating
        # the real heights of everything below this one.
        offset = 0
        for other in Toast._active:
            if other is self:
                break
            offset += other.height() + gap
        y = bottom - self.height() - offset
        local_position = parent.mapFromGlobal(QPoint(x, y))
        self.move(local_position)


def show_toast(parent: QWidget, text: str, *, level: str = "info", action: str | None = None) -> Toast:
    """Create, stack and show a toast on ``parent``."""
    toast = Toast(parent, text, level=level, action=action)
    Toast._active.append(toast)
    toast.show()
    toast.raise_()
    # Reposition every active toast so the new one stacks above the rest and
    # shorter toasts shift to their correct slot.
    for existing in list(Toast._active):
        existing.reposition()
    return toast
