"""Maximised dialog that lets the user zoom/pan a blueprint SVG in detail.

Opened from the detail drawer when the user clicks the small preview. The same
:class:`PreviewCanvas` drives both, so rendering is consistent, but here it is
given the whole screen plus explicit zoom controls.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .preview_canvas import PreviewCanvas

__all__ = ["ZoomablePreviewDialog"]


class ZoomablePreviewDialog(QDialog):
    """Full-screen zoomable viewer for a blueprint map or a screenshot."""

    view_changed = Signal(object)

    def __init__(
        self,
        *,
        svg: str = "",
        pixmap: QPixmap | None = None,
        title: str = "Blueprint map",
        level_count: int = 1,
        max_level: int | None = None,
        hide_walls: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowState(Qt.WindowMaximized)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.level_count = max(int(level_count or 1), 1)
        self.max_level = self.level_count - 1 if max_level is None else min(
            max(int(max_level), 0), self.level_count - 1
        )
        self.hide_walls = bool(hide_walls)
        # A raster image (screenshot) has no levels or walls to toggle.
        image_mode = pixmap is not None and not pixmap.isNull()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # -- toolbar -------------------------------------------------------
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("CardTitle")
        toolbar.addWidget(self.title_label, 1)

        zoom_out = QPushButton("−", self)
        zoom_out.setObjectName("Ghost")
        zoom_out.setFixedWidth(36)
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(self._zoom_out)
        toolbar.addWidget(zoom_out)

        self.zoom_label = QLabel("100%", self)
        self.zoom_label.setObjectName("CardMeta")
        self.zoom_label.setMinimumWidth(56)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        toolbar.addWidget(self.zoom_label)

        zoom_in = QPushButton("+", self)
        zoom_in.setObjectName("Ghost")
        zoom_in.setFixedWidth(36)
        zoom_in.setToolTip("Zoom in")
        zoom_in.clicked.connect(self._zoom_in)
        toolbar.addWidget(zoom_in)

        reset = QPushButton("Reset view", self)
        reset.setObjectName("Ghost")
        reset.clicked.connect(self._reset)
        toolbar.addWidget(reset)

        close_btn = QPushButton("Close", self)
        close_btn.setObjectName("Primary")
        close_btn.clicked.connect(self.accept)
        toolbar.addWidget(close_btn)

        outer.addLayout(toolbar)

        level_row = QHBoxLayout()
        level_row.setSpacing(8)
        level_label = QLabel("Levels", self)
        level_label.setObjectName("CardMeta")
        level_row.addWidget(level_label)

        self.level_slider = QSlider(Qt.Horizontal, self)
        self.level_slider.setRange(0, self.level_count - 1)
        self.level_slider.setSingleStep(1)
        self.level_slider.setPageStep(1)
        self.level_slider.setValue(self.max_level)
        self.level_slider.valueChanged.connect(self._on_level_changed)
        level_row.addWidget(self.level_slider, 1)

        self.level_value_label = QLabel(self)
        self.level_value_label.setObjectName("CardMeta")
        self.level_value_label.setMinimumWidth(56)
        self.level_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        level_row.addWidget(self.level_value_label)
        show_levels = self.level_count > 1 and not image_mode
        self.level_slider.setVisible(show_levels)
        level_label.setVisible(show_levels)
        outer.addLayout(level_row)
        self._update_level_label()

        self.walls_check = QCheckBox("Hide walls", self)
        self.walls_check.setToolTip("Drop the vertical side faces to see inside a stack")
        self.walls_check.setChecked(self.hide_walls)
        self.walls_check.toggled.connect(self._on_walls_changed)
        self.walls_check.setVisible(not image_mode)
        outer.addWidget(self.walls_check)

        # -- canvas --------------------------------------------------------
        self.canvas = PreviewCanvas(self, interactive=True, placeholder="No preview available")
        outer.addWidget(self.canvas, 1)

        hint = QLabel("Scroll to zoom · drag to pan · double-click to reset", self)
        hint.setObjectName("CardMeta")
        hint.setAlignment(Qt.AlignCenter)
        outer.addWidget(hint)

        self._svg = svg
        if image_mode:
            self.canvas.set_pixmap(pixmap)
        else:
            self.canvas.set_svg(svg)

    def set_svg(self, svg: str | None) -> None:
        """Replace the current variant after the asynchronous request completes."""
        self._svg = svg or ""
        self.canvas.set_svg(self._svg)

    def _on_level_changed(self, value: int) -> None:
        self.max_level = int(value)
        self._update_level_label()
        self.view_changed.emit((self.max_level, self.hide_walls))

    def _on_walls_changed(self, checked: bool) -> None:
        self.hide_walls = bool(checked)
        self.view_changed.emit((self.max_level, self.hide_walls))

    def _update_level_label(self) -> None:
        self.level_value_label.setText(f"{self.max_level + 1}/{self.level_count}")

    # -- zoom helpers ------------------------------------------------------
    def _zoom_in(self) -> None:
        self.canvas._zoom = min(self.canvas._zoom * 1.25, 8.0)
        self.canvas.update()
        self._update_zoom_label()

    def _zoom_out(self) -> None:
        self.canvas._zoom = max(self.canvas._zoom / 1.25, 0.2)
        self.canvas.update()
        self._update_zoom_label()

    def _reset(self) -> None:
        self.canvas.reset_view()
        self._update_zoom_label()

    def _update_zoom_label(self) -> None:
        self.zoom_label.setText(f"{int(round(self.canvas._zoom * 100))}%")
