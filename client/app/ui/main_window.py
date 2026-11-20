"""Main window: navigation rail plus a stack of pages."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..theme import apply_theme
from .views.library_view import LibraryView
from .views.my_blueprints_view import MyBlueprintsView
from .views.settings_view import SettingsView
from .views.upload_view import UploadView
from .widgets import AccountDialog, SupportDialog

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("FTN Blueprint Library")
        self.resize(1240, 820)
        self.setMinimumSize(940, 620)

        root = QWidget(self)
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_nav())

        self.stack = QStackedWidget(root)
        self.library_view = LibraryView(ctx, self.stack)
        self.my_view = MyBlueprintsView(ctx, self.stack)
        self.upload_view = UploadView(ctx, self.stack)
        self.settings_view = SettingsView(ctx, self.stack)
        self._pages = [self.library_view, self.my_view, self.upload_view, self.settings_view]
        for page in self._pages:
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(root)

        self.my_view.upload_requested.connect(self._start_upload)
        self.upload_view.uploaded.connect(self._after_upload)
        self.ctx.settings_changed.connect(self._reapply_theme)
        self.ctx.api_changed.connect(self._update_status)
        self.ctx.account_changed.connect(self._update_status)

        apply_theme(_app(), self.ctx.settings.theme)
        self._restore_geometry()
        self._select(0)
        self._update_status()
        # Passwordless: if this game install already has an account, sign straight
        # in from the saved key with no user interaction.
        self.ctx.auto_sign_in()

    # -- chrome ------------------------------------------------------------
    def _build_nav(self) -> QFrame:
        rail = QFrame(self)
        rail.setObjectName("NavRail")
        rail.setAttribute(Qt.WA_StyledBackground, True)
        rail.setFixedWidth(214)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(6)

        brand = QLabel("FTN Blueprint Library", rail)
        brand.setObjectName("BrandTitle")
        brand.setWordWrap(True)
        layout.addWidget(brand)
        subtitle = QLabel("Find The Needle", rail)
        subtitle.setObjectName("BrandSubtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(14)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        entries = [
            ("Library", 0),
            ("My Blueprints", 1),
            ("Upload", 2),
            ("Settings", 3),
        ]
        for label, index in entries:
            button = QPushButton(label, rail)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _, i=index: self._select(i))
            self._nav_group.addButton(button)
            layout.addWidget(button)
            if index == 0:
                button.setChecked(True)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)

        self.account_button = QPushButton("Sign in", rail)
        self.account_button.setObjectName("NavButton")
        self.account_button.clicked.connect(self._open_account)
        footer.addWidget(self.account_button, 1)

        self.support_button = QPushButton("☕", rail)
        self.support_button.setObjectName("SupportButton")
        self.support_button.setFixedSize(38, 38)
        self.support_button.setToolTip("Support this project")
        self.support_button.setCursor(Qt.PointingHandCursor)
        self.support_button.clicked.connect(self._open_support)
        footer.addWidget(self.support_button, 0)

        layout.addLayout(footer)

        return rail

    # -- navigation --------------------------------------------------------
    def _select(self, index: int) -> None:
        if index < 0 or index >= len(self._pages):
            return
        buttons = self._nav_group.buttons()
        if 0 <= index < len(buttons):
            buttons[index].setChecked(True)
        self.stack.setCurrentIndex(index)
        page = self._pages[index]
        page.on_shown()

    def _start_upload(self, path: str) -> None:
        self._select(2)
        self.upload_view.load_file(path)

    def _open_account(self) -> None:
        AccountDialog(self.ctx, self).exec()

    def _open_support(self) -> None:
        SupportDialog(self).exec()

    def _after_upload(self, remote) -> None:
        # The upload view already shows a "… is now live in the library" toast.
        self.library_view.refresh()

    # -- theme / status ----------------------------------------------------
    def _reapply_theme(self) -> None:
        apply_theme(_app(), self.ctx.settings.theme)

    def _update_status(self) -> None:
        account = self.ctx.account
        self.account_button.setText(account.username if account else "Sign in")

    def notify_status(self, text: str) -> None:
        from .widgets import show_toast

        show_toast(self, text, level="info")

    # -- geometry ----------------------------------------------------------
    def _restore_geometry(self) -> None:
        stored = self.ctx.settings.window_geometry
        if not stored:
            return
        try:
            self.restoreGeometry(QByteArray.fromBase64(stored.encode("ascii")))
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.ctx.settings.window_geometry = geometry
            self.ctx.settings.save()
        except Exception:  # noqa: BLE001
            pass
        self.ctx.runner.wait(3000)
        super().closeEvent(event)


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance()
