"""Settings page — paths, server URL, theme and data locations."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import THEMES
from ...core.paths import app_data_dir, default_blueprints_dir
from ...core.shell import open_folder
from ...theme import load_palettes, resolve_theme
from .base import View

__all__ = ["SettingsView"]


class SettingsView(View):
    page_title = "Settings"
    page_subtitle = "Where your blueprints live and how the app looks"

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)

        self.root.addWidget(self._build_folder_panel())
        self.root.addWidget(self._build_server_panel())
        self.root.addWidget(self._build_appearance_panel())
        self.root.addWidget(self._build_about_panel())
        self.root.addStretch(1)

    # -- panels ------------------------------------------------------------
    def _panel(self, title: str) -> tuple[QFrame, QFormLayout]:
        frame = QFrame(self)
        frame.setObjectName("Panel")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        heading = QLabel(title, frame)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        layout.addLayout(form)
        return frame, form

    def _build_folder_panel(self) -> QFrame:
        frame, form = self._panel("Blueprint folder")
        row = QWidget(frame)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        self.folder_edit = QLineEdit(row)
        self.folder_edit.setPlaceholderText("Detected automatically")
        row_layout.addWidget(self.folder_edit, 1)

        browse = QPushButton("Browse…", row)
        browse.clicked.connect(self._browse_folder)
        row_layout.addWidget(browse)

        detect = QPushButton("Auto-detect", row)
        detect.clicked.connect(self._detect_folder)
        row_layout.addWidget(detect)

        apply_button = QPushButton("Apply", row)
        apply_button.setObjectName("Primary")
        apply_button.clicked.connect(self._apply_folder)
        row_layout.addWidget(apply_button)
        form.addRow("Folder", row)

        self.folder_status = QLabel("", frame)
        self.folder_status.setObjectName("CardMeta")
        self.folder_status.setWordWrap(True)
        form.addRow("Status", self.folder_status)

        open_button = QPushButton("Open folder", frame)
        open_button.setObjectName("Ghost")
        open_button.clicked.connect(lambda: open_folder(self.ctx.blueprints_dir() or default_blueprints_dir()))
        form.addRow("", open_button)
        return frame

    def _build_server_panel(self) -> QFrame:
        frame, form = self._panel("Server")
        status_row = QWidget(frame)
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        self.server_status = QLabel("Not checked", status_row)
        self.server_status.setObjectName("CardMeta")
        self.server_status.setWordWrap(True)
        status_layout.addWidget(self.server_status, 1)
        self.server_check_button = QPushButton("Check status", status_row)
        self.server_check_button.clicked.connect(self._check_connection)
        status_layout.addWidget(self.server_check_button)
        form.addRow("Connection", status_row)
        return frame

    def _build_appearance_panel(self) -> QFrame:
        frame, form = self._panel("Appearance")
        self.theme_combo = QComboBox(frame)
        labels = {
            "system": "Follow system",
            "needlework_light": "Needlework Light",
            "midnight_yard": "Midnight Yard",
            "harvest_warm": "Harvest Warm",
        }
        palettes = load_palettes()
        for name in THEMES:
            self.theme_combo.addItem(labels.get(name, palettes.get(name, {}).get("name", name)), name)
        self.theme_combo.currentIndexChanged.connect(self._apply_theme)
        form.addRow("Theme", self.theme_combo)
        return frame

    def _build_about_panel(self) -> QFrame:
        frame, form = self._panel("About")
        data_label = QLabel(str(app_data_dir()), frame)
        data_label.setObjectName("PathLabel")
        data_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        data_label.setWordWrap(True)
        form.addRow("App data", data_label)

        reveal = QPushButton("Reveal app data folder", frame)
        reveal.setObjectName("Ghost")
        reveal.clicked.connect(lambda: open_folder(app_data_dir()))
        form.addRow("", reveal)
        return frame

    # -- lifecycle ---------------------------------------------------------
    def refresh(self) -> None:
        self.folder_edit.setText(self.ctx.settings.blueprints_dir_override or "")
        index = self.theme_combo.findData(self.ctx.settings.theme)
        if index >= 0:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)
        self._update_folder_status()
        self._check_connection()

    def _update_folder_status(self) -> None:
        library = self.ctx.library
        if library is None:
            self.folder_status.setText("Unknown")
            return
        path = library.blueprints_dir
        if path.is_dir():
            count = len(list(path.glob("*.blueprint")))
            self.folder_status.setText(f"Found — {count} blueprint file(s) at {path}")
        else:
            detected = default_blueprints_dir()
            hint = f"The game folder was not found. Default location: {detected}"
            self.folder_status.setText(hint)

    # -- actions -----------------------------------------------------------
    def _browse_folder(self) -> None:
        start = str(self.ctx.blueprints_dir() or default_blueprints_dir())
        path = QFileDialog.getExistingDirectory(self, "Select the blueprints folder", start)
        if path:
            self.folder_edit.setText(path)

    def _detect_folder(self) -> None:
        self.folder_edit.setText("")
        self.ctx.set_blueprints_override(None)
        self._update_folder_status()
        self.notify("Using the auto-detected game folder.", level="info")

    def _apply_folder(self) -> None:
        value = self.folder_edit.text().strip()
        self.ctx.set_blueprints_override(value or None)
        self._update_folder_status()
        self.notify("Blueprint folder updated.", level="success")

    def _check_connection(self) -> None:
        api = self.ctx.api
        if api is None:
            self.server_status.setText("Offline")
            return
        self.server_status.setText("Contacting server…")
        self.server_check_button.setEnabled(False)

        def done(ok: bool) -> None:
            self.server_status.setText("Online" if ok else "Offline — no response from the server")
            self.server_check_button.setEnabled(True)

        def failed(message: str) -> None:
            self.server_status.setText(f"Offline — {message}")
            self.server_check_button.setEnabled(True)

        self.ctx.runner.run(api.healthz, on_done=done, on_error=failed)

    def _apply_theme(self) -> None:
        name = self.theme_combo.currentData()
        self.ctx.set_theme(name)
        resolved = resolve_theme(name)
        self.notify(f"Theme set to “{resolved.replace('_', ' ').title()}”.", level="info")
