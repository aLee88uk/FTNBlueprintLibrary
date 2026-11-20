"""Upload page — share a local blueprint with the community."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ftn_blueprint import parse_blueprint

from ..widgets import AccountDialog, PreviewCanvas, show_toast
from .base import View

__all__ = ["UploadView"]

SEED_CATEGORIES = [
    "Power", "Production", "Logistics", "Water", "Buildings", "Compact", "Misc",
]
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class UploadView(View):
    """Pick a local blueprint, describe it and publish it."""

    page_title = "Upload"
    page_subtitle = "Share one of your blueprints with the community"

    uploaded = Signal(object)

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)
        self._meta = None
        self._data: bytes | None = None
        self._path: Path | None = None
        self._screenshot_data: bytes | None = None
        self._screenshot_name: str = ""

        columns = QHBoxLayout()
        columns.setSpacing(20)
        self.root.addLayout(columns, 1)

        # -- left: preview + file picker ----------------------------------
        left = QVBoxLayout()
        left.setSpacing(10)
        self.preview = PreviewCanvas(self, placeholder="Choose a .blueprint file to preview it")
        self.preview.setMinimumHeight(300)
        left.addWidget(self.preview, 1)

        pick_row = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("No file selected")
        pick_row.addWidget(self.path_edit, 1)
        browse = QPushButton("Choose file…", self)
        browse.clicked.connect(self._browse)
        pick_row.addWidget(browse)
        left.addLayout(pick_row)

        self.file_status = QLabel("", self)
        self.file_status.setObjectName("CardMeta")
        self.file_status.setWordWrap(True)
        left.addWidget(self.file_status)

        # -- screenshot ----------------------------------------------------
        shot_heading = QLabel("Screenshot (optional)", self)
        shot_heading.setObjectName("SectionTitle")
        left.addWidget(shot_heading)

        self.screenshot_hint = QLabel("", self)
        self.screenshot_hint.setObjectName("CardMeta")
        self.screenshot_hint.setWordWrap(True)
        left.addWidget(self.screenshot_hint)

        self.screenshot_preview = QLabel(self)
        self.screenshot_preview.setAlignment(Qt.AlignCenter)
        self.screenshot_preview.setMinimumHeight(140)
        self.screenshot_preview.setStyleSheet("border: 1px dashed #888; border-radius: 6px;")
        self.screenshot_preview.setText("No screenshot selected")
        left.addWidget(self.screenshot_preview)

        shot_row = QHBoxLayout()
        self.screenshot_path_edit = QLineEdit(self)
        self.screenshot_path_edit.setReadOnly(True)
        self.screenshot_path_edit.setPlaceholderText("No screenshot selected")
        shot_row.addWidget(self.screenshot_path_edit, 1)
        self.shot_browse = QPushButton("Choose screenshot…", self)
        self.shot_browse.clicked.connect(self._browse_screenshot)
        shot_row.addWidget(self.shot_browse)
        self.shot_clear = QPushButton("Clear", self)
        self.shot_clear.setObjectName("Ghost")
        self.shot_clear.clicked.connect(self._clear_screenshot)
        shot_row.addWidget(self.shot_clear)
        left.addLayout(shot_row)

        columns.addLayout(left, 3)

        # -- right: metadata form ----------------------------------------
        form_host = QWidget(self)
        form = QFormLayout(form_host)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)

        self.title_edit = QLineEdit(form_host)
        self.title_edit.setPlaceholderText("Blueprint name shown in the library")
        form.addRow("Title", self.title_edit)

        self.description_edit = QPlainTextEdit(form_host)
        self.description_edit.setPlaceholderText("What does it do? Tips, inputs/outputs, notes…")
        self.description_edit.setFixedHeight(90)
        form.addRow("Description", self.description_edit)

        self.category_combo = QComboBox(form_host)
        self.category_combo.setEditable(False)
        self.category_combo.addItems(SEED_CATEGORIES)
        form.addRow("Category", self.category_combo)

        self.tags_edit = QLineEdit(form_host)
        self.tags_edit.setPlaceholderText("comma, separated, tags")
        form.addRow("Tags", self.tags_edit)

        self.author_edit = QLineEdit(form_host)
        self.author_edit.setReadOnly(True)
        self.author_edit.setPlaceholderText("Sign in to set your author name")
        form.addRow("Author", self.author_edit)

        columns.addWidget(form_host, 2)

        self.signin_button = QPushButton("Sign in to upload…", self)
        self.signin_button.setObjectName("Primary")
        self.signin_button.clicked.connect(self._open_account)
        self.actions.addWidget(self.signin_button)

        self.upload_button = QPushButton("Upload to library", self)
        self.upload_button.setObjectName("Primary")
        self.upload_button.setEnabled(False)
        self.upload_button.clicked.connect(self.submit)
        self.actions.addWidget(self.upload_button)

        self.reset_button = QPushButton("Clear", self)
        self.reset_button.setObjectName("Ghost")
        self.reset_button.clicked.connect(self.reset)
        self.actions.addWidget(self.reset_button)

        self._load_categories()
        self.ctx.account_changed.connect(self._sync_account)
        self._sync_account()

    # -- account -----------------------------------------------------------
    def _open_account(self) -> None:
        AccountDialog(self.ctx, self.window()).exec()

    def _sync_account(self) -> None:
        """Publishing needs an account; the author is always the registered name."""
        account = self.ctx.account
        signed_in = account is not None

        self.author_edit.setText(account.username if signed_in else "")
        self.shot_browse.setEnabled(signed_in)
        self.shot_clear.setEnabled(signed_in)
        self.signin_button.setVisible(not signed_in)

        if signed_in:
            self.screenshot_hint.setText(
                f"Signed in as {account.username} — this blueprint and any "
                "screenshot are published under your name."
            )
        elif not self.ctx.has_game_key:
            self.screenshot_hint.setText(
                "Uploading needs a registered account, and accounts only work with "
                "the retail version of the game. You can still browse and download "
                "blueprints."
            )
        else:
            self.screenshot_hint.setText(
                "Sign in to upload. Publishing needs an account so every blueprint "
                "is attributed to a name and ratings can't be abused."
            )

        if not signed_in and self._screenshot_data is not None:
            self._clear_screenshot()
        self._update_upload_enabled()

    def _update_upload_enabled(self) -> None:
        self.upload_button.setEnabled(self.ctx.account is not None and self._data is not None)

    # -- helpers -----------------------------------------------------------
    def _load_categories(self) -> None:
        api = self.ctx.api
        if api is None:
            return

        def done(categories):
            names = [c.name for c in categories if c.name]
            if not names:
                return
            current = self.category_combo.currentText()
            self.category_combo.clear()
            self.category_combo.addItems(names)
            if current:
                self.category_combo.setCurrentText(current)

        self.ctx.runner.run(api.categories, on_done=done, on_error=lambda _m: None)

    # -- file selection ----------------------------------------------------
    def _browse(self) -> None:
        start = str(self.ctx.settings.blueprints_dir_override or self.ctx.blueprints_dir() or Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Choose a blueprint", start, "Blueprints (*.blueprint)")
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        file_path = Path(path)
        self._path = file_path
        self.path_edit.setText(str(file_path))
        self.file_status.setText("Reading…")
        self.upload_button.setEnabled(False)
        self.ctx.runner.run(
            _read_and_parse, file_path,
            on_done=self._on_parsed,
            on_error=self._on_parse_error,
        )

    # -- screenshot --------------------------------------------------------
    def _browse_screenshot(self) -> None:
        if self.ctx.account is None:
            self.notify("Sign in to attach a screenshot.", level="warning")
            self._open_account()
            return
        start = str(self._path.parent if self._path else Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a screenshot", start, "Images (*.png *.jpg *.jpeg)"
        )
        if not path:
            return
        shot_path = Path(path)
        try:
            data = shot_path.read_bytes()
        except OSError as exc:
            self.notify(f"Could not read screenshot: {exc}", level="error")
            return
        if not _looks_like_image(data):
            self.notify("That file does not look like a PNG or JPEG image.", level="error")
            return
        self._screenshot_data = data
        self._screenshot_name = shot_path.name
        self.screenshot_path_edit.setText(str(shot_path))
        pix = QPixmap()
        pix.loadFromData(data)
        if pix.isNull():
            self.screenshot_preview.setText("Could not decode image")
        else:
            scaled = pix.scaled(
                self.screenshot_preview.width(), self.screenshot_preview.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.screenshot_preview.setPixmap(scaled)

    def _clear_screenshot(self) -> None:
        self._screenshot_data = None
        self._screenshot_name = ""
        self.screenshot_path_edit.clear()
        self.screenshot_preview.clear()
        self.screenshot_preview.setText("No screenshot selected")

    def _on_parsed(self, payload) -> None:
        data, meta = payload
        self._data = data
        self._meta = meta
        self.title_edit.setText(meta.name or meta.filename_stem)
        if meta.desc:
            self.description_edit.setPlainText(meta.desc)
        if meta.category:
            normalized = {
                "storage": "Logistics",
                "processing": "Production",
            }.get(meta.category.strip().casefold(), meta.category.strip())
            index = self.category_combo.findText(normalized)
            if index < 0:
                self.category_combo.addItem(normalized)
                index = self.category_combo.count() - 1
            self.category_combo.setCurrentIndex(index)
        if meta.tags:
            self.tags_edit.setText(", ".join(meta.tags))
        self.file_status.setText(
            f"{meta.piece_count:,} pieces · cost {meta.total_cost:,.0f} · "
            f"{len(data):,} bytes · {meta.icon or 'no icon'}"
        )
        self.preview.set_meta(meta, width=640, height=420, theme=self.ctx.preview_theme())
        self._update_upload_enabled()

    def _on_parse_error(self, message: str) -> None:
        self._meta = None
        self._data = None
        self.file_status.setText(f"Could not read this file: {message}")
        self.preview.set_placeholder("Not a valid blueprint")
        self.upload_button.setEnabled(False)

    # -- submission --------------------------------------------------------
    def submit(self) -> None:
        if self.ctx.account is None:
            self.notify("Sign in to upload a blueprint.", level="warning")
            self._open_account()
            return
        if self._data is None or self._meta is None or self._path is None:
            self.notify("Choose a blueprint file first.", level="warning")
            return
        if len(self._data) > MAX_UPLOAD_BYTES:
            self.notify("This blueprint is larger than the 5 MB upload limit.", level="error")
            return
        title = self.title_edit.text().strip() or self._meta.name
        if not title:
            self.notify("Please give the blueprint a title.", level="warning")
            return

        api = self.ctx.api
        if api is None:
            self.notify("No API client available.", level="error")
            return

        # Check whether this user already published a blueprint with the same
        # in-game id (i.e. the same .blueprint filename). If so, ask whether to
        # overwrite the existing entry or create a new one.
        self.upload_button.setEnabled(False)
        self.upload_button.setText("Checking…")
        self.ctx.runner.run(
            api.my_uploads,
            on_done=self._on_uploads_checked,
            on_error=self._on_upload_error,
        )

    def _on_uploads_checked(self, my_uploads) -> None:
        """Look for an existing upload with the same game id and choose a path."""
        api = self.ctx.api
        if api is None or self._meta is None or self._path is None or self._data is None:
            self._reset_upload_button()
            return

        game_id = getattr(self._meta, "id", "") or ""
        existing = None
        if game_id:
            for bp in my_uploads:
                if bp.game_id == game_id:
                    existing = bp
                    break

        title = self.title_edit.text().strip() or self._meta.name
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        category = self.category_combo.currentText().strip()
        description = self.description_edit.toPlainText().strip()

        if existing is not None:
            choice = self._ask_overwrite(existing, title)
            if choice is None:
                self._reset_upload_button()
                return
            if choice:
                self._do_replace(existing, title, description, category, tags)
                return

        self._do_upload(title, description, category, tags)

    def _ask_overwrite(self, existing, new_title: str) -> bool | None:
        """Return True to overwrite, False to create new, None to cancel."""
        msg = QMessageBox(self.window())
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Blueprint already uploaded")
        msg.setText(f'You already published “{existing.title}” with this build.')
        msg.setInformativeText(
            "Update the existing blueprint on the server (overwrite its file and "
            "metadata, keeping the same id, likes and downloads), or publish a "
            "brand new entry?"
        )
        overwrite_btn = msg.addButton("Update existing", QMessageBox.AcceptRole)
        overwrite_btn.setObjectName("Primary")
        new_btn = msg.addButton("Publish new", QMessageBox.ActionRole)
        cancel_btn = msg.addButton(QMessageBox.Cancel)
        cancel_btn.setObjectName("Ghost")
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is overwrite_btn:
            return True
        if clicked is new_btn:
            return False
        return None

    def _do_upload(self, title: str, description: str, category: str, tags: list[str]) -> None:
        api = self.ctx.api
        if api is None:
            self._reset_upload_button()
            return
        self.upload_button.setText("Uploading…")
        self.ctx.runner.run(
            api.upload,
            self._data,
            filename=self._path.name,
            title=title,
            description=description,
            category=category,
            tags=tags,
            screenshot=self._screenshot_data,
            screenshot_name=self._screenshot_name,
            on_done=self._on_uploaded,
            on_error=self._on_upload_error,
        )

    def _do_replace(self, existing, title: str, description: str, category: str, tags: list[str]) -> None:
        api = self.ctx.api
        if api is None:
            self._reset_upload_button()
            return
        self.upload_button.setText("Updating…")
        self.ctx.runner.run(
            api.replace_blueprint,
            existing.id,
            self._data,
            filename=self._path.name,
            title=title,
            description=description,
            category=category,
            tags=tags,
            screenshot=self._screenshot_data,
            screenshot_name=self._screenshot_name,
            on_done=self._on_uploaded,
            on_error=self._on_upload_error,
        )

    def _reset_upload_button(self) -> None:
        self.upload_button.setText("Upload to library")
        self._update_upload_enabled()

    def _on_uploaded(self, remote) -> None:
        self._reset_upload_button()
        show_toast(self.window(), f"“{remote.title}” is now live in the library.", level="success")
        self.uploaded.emit(remote)

    def _on_upload_error(self, message: str) -> None:
        self._reset_upload_button()
        self.notify(f"Upload failed: {message}", level="error")

    def reset(self) -> None:
        self._meta = None
        self._data = None
        self._path = None
        self.path_edit.clear()
        self.title_edit.clear()
        self.description_edit.clear()
        self.tags_edit.clear()
        self.file_status.setText("")
        self.preview.clear()
        self.preview.set_placeholder("Choose a .blueprint file to preview it")
        self.upload_button.setEnabled(False)
        self._clear_screenshot()


def _read_and_parse(path: Path):
    data = Path(path).read_bytes()
    meta = parse_blueprint(data)
    return data, meta


def _looks_like_image(data: bytes) -> bool:
    """Check magic bytes for PNG or JPEG."""
    return data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")
