"""Right-hand detail panel: large interactive preview plus metadata."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .preview_canvas import PreviewCanvas
from .zoom_preview import ZoomablePreviewDialog

__all__ = ["DetailDrawer"]


class DetailDrawer(QFrame):
    """Shows one blueprint in detail; hidden by default."""

    action_clicked = Signal(object)
    like_clicked = Signal(object)
    closed = Signal()
    #: Emitted with the payload when the user clicks the Edit button.
    edit_clicked = Signal(object)
    #: Emitted with the payload when the user clicks the Delete button.
    delete_clicked = Signal(object)
    #: Emitted with the payload when the user clicks the Report button.
    report_clicked = Signal(object)
    #: Emitted with ``(max_level, hide_walls)`` when the view options change.
    #: ``max_level`` is 0-based and cumulative (0 = ground only).
    view_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Drawer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(380)
        self.payload: object = None
        self.level_count: int = 1
        self.max_level: int = 0
        self.hide_walls: bool = False
        self._loading_view = False
        self._current_svg: str | None = None
        self._screenshot_pixmap: QPixmap | None = None
        self._zoom_dialog: ZoomablePreviewDialog | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        self.title_label = QLabel("Details", self)
        self.title_label.setObjectName("CardTitle")
        self.title_label.setWordWrap(True)
        header.addWidget(self.title_label, 1)
        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("CloseButton")
        self.close_button.setFixedSize(32, 32)
        self.close_button.setToolTip("Close preview")
        self.close_button.clicked.connect(self._on_close)
        header.addWidget(self.close_button)
        outer.addLayout(header)

        self.subtitle_label = QLabel("", self)
        self.subtitle_label.setObjectName("CardMeta")
        self.subtitle_label.setWordWrap(True)
        outer.addWidget(self.subtitle_label)

        self._view_host = QWidget(self)
        view_layout = QVBoxLayout(self._view_host)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(6)

        self._level_row = QWidget(self._view_host)
        level_row = QHBoxLayout(self._level_row)
        level_row.setContentsMargins(0, 0, 0, 0)
        level_row.setSpacing(8)
        level_label = QLabel("Levels", self._level_row)
        level_label.setObjectName("CardMeta")
        level_row.addWidget(level_label)
        self.level_slider = QSlider(Qt.Horizontal, self._level_row)
        self.level_slider.setSingleStep(1)
        self.level_slider.setPageStep(1)
        self.level_slider.valueChanged.connect(self._on_level_slid)
        level_row.addWidget(self.level_slider, 1)
        self.level_value_label = QLabel("", self._level_row)
        self.level_value_label.setObjectName("CardMeta")
        self.level_value_label.setMinimumWidth(56)
        self.level_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        level_row.addWidget(self.level_value_label)
        view_layout.addWidget(self._level_row)

        self.walls_check = QCheckBox("Hide walls", self._view_host)
        self.walls_check.setToolTip("Drop the vertical side faces to see inside a stack")
        self.walls_check.toggled.connect(self._on_walls_toggled)
        view_layout.addWidget(self.walls_check)

        self._view_host.hide()
        outer.addWidget(self._view_host)

        self.preview = PreviewCanvas(self, interactive=True, placeholder="Select a blueprint")
        self.preview.setMinimumHeight(260)
        self.preview.clicked.connect(self._open_zoomable)
        outer.addWidget(self.preview, 3)

        self.hint_label = QLabel("Click the map to zoom · scroll to zoom · drag to pan", self)
        self.hint_label.setObjectName("CardMeta")
        self.hint_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.hint_label)

        # Optional uploader screenshot, shown as a section below the map preview.
        self._screenshot_host = QWidget(self)
        shot_layout = QVBoxLayout(self._screenshot_host)
        shot_layout.setContentsMargins(0, 0, 0, 0)
        shot_layout.setSpacing(4)
        shot_heading = QLabel("Screenshot", self._screenshot_host)
        shot_heading.setObjectName("CardMeta")
        shot_layout.addWidget(shot_heading)
        self.screenshot_label = QLabel(self._screenshot_host)
        self.screenshot_label.setAlignment(Qt.AlignCenter)
        self.screenshot_label.setFixedHeight(180)
        self.screenshot_label.setStyleSheet("background: transparent;")
        self.screenshot_label.setCursor(Qt.PointingHandCursor)
        self.screenshot_label.setToolTip("Click to view larger")
        self.screenshot_label.installEventFilter(self)
        shot_layout.addWidget(self.screenshot_label)
        self._screenshot_host.hide()
        outer.addWidget(self._screenshot_host)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        stats_host = QWidget()
        stats_host.setAutoFillBackground(False)
        self._stats = QGridLayout(stats_host)
        self._stats.setContentsMargins(0, 0, 0, 0)
        self._stats.setHorizontalSpacing(12)
        self._stats.setVerticalSpacing(6)
        self._stats.setAlignment(Qt.AlignTop)
        scroll.setWidget(stats_host)
        outer.addWidget(scroll, 2)

        self.description_label = QLabel("", self)
        self.description_label.setObjectName("CardMeta")
        self.description_label.setWordWrap(True)
        outer.addWidget(self.description_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.like_button = QPushButton("♡ 0", self)
        self.like_button.setObjectName("Like")
        self.like_button.setToolTip("Like this blueprint")
        self.like_button.clicked.connect(lambda: self.like_clicked.emit(self.payload))
        action_row.addWidget(self.like_button)

        self.report_button = QPushButton("Report", self)
        self.report_button.setObjectName("Ghost")
        self.report_button.setToolTip("Flag this blueprint for moderator review")
        self.report_button.clicked.connect(lambda: self.report_clicked.emit(self.payload))
        self.report_button.hide()
        action_row.addWidget(self.report_button)

        self.edit_button = QPushButton("Edit", self)
        self.edit_button.setObjectName("Ghost")
        self.edit_button.setToolTip("Edit title, description, category or tags")
        self.edit_button.clicked.connect(lambda: self.edit_clicked.emit(self.payload))
        action_row.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete", self)
        self.delete_button.setObjectName("Ghost")
        self.delete_button.setToolTip("Remove this blueprint from the library")
        self.delete_button.clicked.connect(lambda: self.delete_clicked.emit(self.payload))
        action_row.addWidget(self.delete_button)

        self.action_button = QPushButton("Download & install", self)
        self.action_button.setObjectName("Primary")
        self.action_button.clicked.connect(lambda: self.action_clicked.emit(self.payload))
        action_row.addWidget(self.action_button, 1)
        outer.addLayout(action_row)

        self.hide()

    # -- content -----------------------------------------------------------
    def show_details(
        self,
        *,
        title: str,
        subtitle: str = "",
        svg: str | None = None,
        image: bytes | None = None,
        stats: dict[str, str] | None = None,
        description: str = "",
        action_text: str | None = "Download & install",
        action_enabled: bool = True,
        payload: object = None,
        placeholder: str = "Preview unavailable",
        level_count: int = 1,
        likes: int = 0,
        liked: bool = False,
        max_level: int | None = None,
        hide_walls: bool = False,
        is_owner: bool = False,
        can_report: bool = False,
    ) -> None:
        self.payload = payload
        self.set_like_state(likes, liked)
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        self._apply_view_state(level_count, max_level, hide_walls)

        self._current_svg = svg or None

        if svg:
            self.preview.set_svg(svg)
        else:
            self.preview.set_placeholder(placeholder)

        # The screenshot (if any) renders as an extra section below the map.
        self.set_image(image)

        _clear_layout(self._stats)
        key_column_width = QFontMetrics(self.font()).horizontalAdvance("Composition")
        self._stats.setColumnMinimumWidth(0, key_column_width)
        for row, (key, value) in enumerate((stats or {}).items()):
            key_label = QLabel(key, self)
            key_label.setObjectName("CardMeta")
            value_label = QLabel(str(value), self)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._stats.addWidget(key_label, row, 0, Qt.AlignTop)
            self._stats.addWidget(value_label, row, 1)
        self._stats.setColumnStretch(1, 1)

        self.description_label.setText(description)
        self.description_label.setVisible(bool(description))

        if action_text:
            self.action_button.setText(action_text)
            self.action_button.setEnabled(action_enabled)
            self.action_button.show()
        else:
            self.action_button.hide()

        # Edit/Delete are only for blueprints the caller owns.
        self.edit_button.setVisible(bool(is_owner))
        self.edit_button.setEnabled(bool(is_owner))
        self.delete_button.setVisible(bool(is_owner))
        self.delete_button.setEnabled(bool(is_owner))

        # Reporting is only offered for other players' uploads.
        self.report_button.setVisible(bool(can_report))
        self.report_button.setEnabled(bool(can_report))

        self._refresh_controls_visibility()
        self.show()

    # -- view options ------------------------------------------------------
    def _apply_view_state(self, level_count: int, max_level: int | None, hide_walls: bool) -> None:
        """Load ``level_count``/``max_level``/``hide_walls`` into the controls."""
        self.level_count = max(int(level_count or 1), 1)
        top = self.level_count - 1
        self.max_level = top if max_level is None else min(max(int(max_level), 0), top)

        self._loading_view = True
        self.level_slider.setMinimum(0)
        self.level_slider.setMaximum(top)
        self.level_slider.setValue(self.max_level)
        self.walls_check.setChecked(bool(hide_walls))
        self.hide_walls = bool(hide_walls)
        self._loading_view = False

        self._level_row.setVisible(self.level_count > 1)
        self._update_level_label()

    def _update_level_label(self) -> None:
        self.level_value_label.setText(f"{self.max_level + 1}/{self.level_count}")

    def _refresh_controls_visibility(self) -> None:
        """Only offer the view controls when there is a preview to drive."""
        self._view_host.setVisible(bool(self._current_svg))

    def current_view(self) -> tuple[int, bool]:
        """The ``(max_level, hide_walls)`` the slider/toggle currently describe."""
        return (self.max_level, self.hide_walls)

    def set_like_state(self, likes: int, liked: bool) -> None:
        """Update the like button label and accessible state."""
        count = max(int(likes or 0), 0)
        self.like_button.setText(f"{'♥' if liked else '♡'} {count}")
        self.like_button.setProperty("liked", bool(liked))
        self.like_button.setToolTip("Unlike this blueprint" if liked else "Like this blueprint")
        self.like_button.style().unpolish(self.like_button)
        self.like_button.style().polish(self.like_button)

    def _on_level_slid(self, value: int) -> None:
        self.max_level = int(value)
        self._update_level_label()
        self._emit_view()

    def _on_walls_toggled(self, checked: bool) -> None:
        self.hide_walls = bool(checked)
        self._emit_view()

    def _emit_view(self) -> None:
        if self._loading_view:
            return
        self.view_changed.emit((self.max_level, self.hide_walls))

    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()

    def set_image(self, image: bytes | None) -> None:
        """Set (or clear) the screenshot shown below the map preview."""
        pix = QPixmap()
        if image:
            pix.loadFromData(image)
        self._screenshot_pixmap = None if pix.isNull() else pix
        if image and self._screenshot_pixmap is None:
            self.screenshot_label.setText("Could not decode screenshot")
        else:
            self.screenshot_label.setText("")
        self._screenshot_host.setVisible(self._screenshot_pixmap is not None)
        self._rescale_screenshot()
        # The label may not have been laid out yet when first revealed, so
        # rescale once more after the layout has settled.
        QTimer.singleShot(0, self._rescale_screenshot)

    def _rescale_screenshot(self) -> None:
        """Scale the screenshot to the label, preserving its aspect ratio."""
        if self._screenshot_pixmap is None:
            return
        self.screenshot_label.setPixmap(
            self._screenshot_pixmap.scaled(
                max(self.screenshot_label.width(), 1),
                max(self.screenshot_label.height(), 1),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale_screenshot()

    def set_svg(self, svg: str | None) -> None:
        """Update the map preview (e.g. after a level/walls change).

        Keeps ``self._current_svg`` in sync so the zoom dialog opens the
        preview the user is currently looking at.
        """
        self._current_svg = svg or None
        self.preview.set_svg(svg)
        if self._zoom_dialog is not None:
            self._zoom_dialog.set_svg(svg)
        self._refresh_controls_visibility()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt virtual
        if obj is self.screenshot_label and event.type() == QEvent.MouseButtonRelease:
            self._open_screenshot()
            return True
        return super().eventFilter(obj, event)

    def _open_screenshot(self) -> None:
        """Open the screenshot in the same full-screen zoomable viewer as the map."""
        if self._screenshot_pixmap is None:
            return
        dialog = ZoomablePreviewDialog(
            pixmap=self._screenshot_pixmap,
            title=f"{self.title_label.text() or 'Blueprint'} — Screenshot",
            parent=self.window(),
        )
        dialog.exec()

    def _open_zoomable(self) -> None:
        """Open the full-screen zoomable map viewer for the current preview."""
        if not self._current_svg:
            return
        dialog = ZoomablePreviewDialog(
            svg=self._current_svg,
            title=self.title_label.text() or "Blueprint map",
            level_count=self.level_count,
            max_level=self.max_level,
            hide_walls=self.hide_walls,
            parent=self.window(),
        )
        dialog.view_changed.connect(self._on_zoom_view_changed)
        self._zoom_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._zoom_dialog = None

    def _on_zoom_view_changed(self, view: tuple[int, bool]) -> None:
        """Keep the drawer controls and server preview request in sync."""
        max_level, hide_walls = view
        self._loading_view = True
        self.level_slider.setValue(max_level)
        self.walls_check.setChecked(hide_walls)
        self.max_level = int(max_level)
        self.hide_walls = bool(hide_walls)
        self._loading_view = False
        self._update_level_label()
        self._emit_view()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
