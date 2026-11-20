"""Modal account dialog — passwordless, name-only registration + recovery.

Uploading *and* rating a blueprint need an account, so everything a player
shares is attributed to a name and votes cannot be farmed by anonymous callers.
There is no password: the game's install key *is* the credential, so an account
is created from a name alone and this install is signed back in automatically
on later launches.

Because that key is generated per install, a new PC (or a wiped drive) would
otherwise strand the account. A recovery code — issued at registration and
re-issuable here — moves the account onto a new install.

When the game install has no key (a non-retail copy), account creation is
disabled and the dialog explains that only the retail version of the game works
here — browsing and downloading stay available.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["AccountDialog"]


class AccountDialog(QDialog):
    """Create an account (a name is all it takes), sign in/out, or recover."""

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Account")
        self.setMinimumWidth(580)

        #: ``"auth"`` for the normal form, ``"recover"`` for the restore flow.
        self._mode = "auth"
        self._recovery_code = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        self.heading = QLabel("Account", self)
        self.heading.setObjectName("SectionTitle")
        root.addWidget(self.heading)

        self.hint = QLabel("", self)
        self.hint.setObjectName("CardMeta")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.form_host = QWidget(self)
        form = QFormLayout(self.form_host)
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)
        self.username_edit = QLineEdit(self.form_host)
        self.username_edit.setPlaceholderText("Your player name")
        form.addRow("Name", self.username_edit)

        self.recovery_label = QLabel("Recovery code", self.form_host)
        self.recovery_edit = QLineEdit(self.form_host)
        self.recovery_edit.setPlaceholderText("XXXX-XXXX-XXXX-…")
        form.addRow(self.recovery_label, self.recovery_edit)
        root.addWidget(self.form_host)

        # A box that surfaces an issued recovery code (shown exactly once).
        self.recovery_box = QWidget(self)
        self.recovery_box.setObjectName("RecoveryBox")
        self.recovery_box.setAttribute(Qt.WA_StyledBackground, True)
        recovery_row = QHBoxLayout(self.recovery_box)
        recovery_row.setContentsMargins(8, 8, 8, 8)
        recovery_row.setSpacing(8)
        self.recovery_code_label = QLabel("", self.recovery_box)
        self.recovery_code_label.setObjectName("RecoveryCode")
        self.recovery_code_label.setMinimumHeight(40)
        self.recovery_code_label.setMinimumWidth(400)
        self.recovery_code_label.setToolTip("Select and copy this one-time recovery code.")
        self.recovery_code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        recovery_row.addWidget(self.recovery_code_label, 1)
        self.copy_button = QPushButton("Copy", self.recovery_box)
        self.copy_button.setObjectName("Ghost")
        self.copy_button.setFixedWidth(64)
        self.copy_button.clicked.connect(self._copy_recovery)
        recovery_row.addWidget(self.copy_button)
        root.addWidget(self.recovery_box)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("CardMeta")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.register_button = QPushButton("Create account", self)
        self.register_button.setObjectName("Primary")
        self.register_button.clicked.connect(self._register)
        buttons.addWidget(self.register_button)

        self.signin_button = QPushButton("Sign in", self)
        self.signin_button.clicked.connect(self._sign_in)
        buttons.addWidget(self.signin_button)

        self.recover_toggle_button = QPushButton("Use a recovery code", self)
        self.recover_toggle_button.setObjectName("Ghost")
        self.recover_toggle_button.clicked.connect(self._begin_recover)
        buttons.addWidget(self.recover_toggle_button)

        self.submit_recover_button = QPushButton("Restore account", self)
        self.submit_recover_button.setObjectName("Primary")
        self.submit_recover_button.clicked.connect(self._submit_recover)
        buttons.addWidget(self.submit_recover_button)

        self.cancel_recover_button = QPushButton("Cancel", self)
        self.cancel_recover_button.setObjectName("Ghost")
        self.cancel_recover_button.clicked.connect(self._cancel_recover)
        buttons.addWidget(self.cancel_recover_button)

        buttons.addStretch(1)

        self.get_recovery_button = QPushButton("Get recovery code", self)
        self.get_recovery_button.setObjectName("Ghost")
        self.get_recovery_button.clicked.connect(self._get_recovery)
        buttons.addWidget(self.get_recovery_button)

        self.signout_button = QPushButton("Sign out", self)
        self.signout_button.setObjectName("Ghost")
        self.signout_button.clicked.connect(self._sign_out)
        buttons.addWidget(self.signout_button)
        root.addLayout(buttons)

        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.rejected.connect(self.reject)
        root.addWidget(close)

        self.ctx.account_changed.connect(self._sync)
        self._sync()

    # -- state -------------------------------------------------------------
    def _sync(self) -> None:
        account = self.ctx.account
        signed_in = account is not None
        has_key = self.ctx.has_game_key
        recover_mode = self._mode == "recover"

        self.status_label.setText("")

        show_form = not signed_in and has_key
        self.form_host.setVisible(show_form)
        self.recovery_label.setVisible(recover_mode)
        self.recovery_edit.setVisible(recover_mode)

        self.register_button.setVisible(show_form and not recover_mode)
        self.signin_button.setVisible(show_form and not recover_mode)
        self.recover_toggle_button.setVisible(show_form and not recover_mode)
        self.submit_recover_button.setVisible(show_form and recover_mode)
        self.cancel_recover_button.setVisible(show_form and recover_mode)
        self.signout_button.setVisible(signed_in)
        self.get_recovery_button.setVisible(signed_in)

        show_code = signed_in and bool(self._recovery_code)
        self.recovery_code_label.setText(self._recovery_code)
        self.recovery_box.setVisible(show_code)

        if recover_mode:
            self.heading.setText("Restore your account")
            self.hint.setText(
                "On a new PC — or after reinstalling Windows — your game key "
                "changes. Enter the name you picked and the recovery code you "
                "saved to move your account onto this install."
            )
        elif signed_in:
            self.heading.setText(f"Signed in as {account.username}")
            self.hint.setText(
                "Uploads and ratings from this install are published under this "
                "name and tied to your account. There is no password — you are "
                "signed back in automatically from this game install. Save your "
                "recovery code so you can restore the account on a new PC."
            )
            self.username_edit.setText(account.username)
        elif not has_key:
            self.heading.setText("Retail version required")
            self.hint.setText(
                "No game install key was found on this PC. Accounts — and "
                "uploading or rating blueprints — only work with the retail "
                "version of the game. You can still browse and download "
                "blueprints."
            )
        else:
            self.heading.setText("Create your account")
            self.hint.setText(
                "Account creation only needs a name — no password. Your account "
                "is tied to this game install, so you'll be signed in "
                "automatically next time. You'll also get a recovery code to "
                "save in case you move to a new PC."
            )
            self.username_edit.setPlaceholderText("Your player name")

    def _set_busy(self, busy: bool, message: str = "") -> None:
        for widget in (
            self.register_button,
            self.signin_button,
            self.recover_toggle_button,
            self.submit_recover_button,
            self.cancel_recover_button,
            self.get_recovery_button,
            self.signout_button,
            self.username_edit,
            self.recovery_edit,
        ):
            widget.setEnabled(not busy)
        self.status_label.setText(message)

    # -- actions -----------------------------------------------------------
    def _register(self) -> None:
        username = self.username_edit.text().strip()
        if not username:
            self.status_label.setText("Enter a name to create your account.")
            return
        self._run(self.ctx.api.register, username)

    def _sign_in(self) -> None:
        self._run(self.ctx.api.login)

    def _begin_recover(self) -> None:
        self._mode = "recover"
        self.recovery_edit.setText("")
        self._sync()

    def _cancel_recover(self) -> None:
        self._mode = "auth"
        self._sync()

    def _submit_recover(self) -> None:
        username = self.username_edit.text().strip()
        code = self.recovery_edit.text().strip()
        if not username or not code:
            self.status_label.setText("Enter both your name and your recovery code.")
            return
        self._run(self.ctx.api.recover, username, code)

    def _get_recovery(self) -> None:
        self._run(self.ctx.api.recovery)

    def _run(self, call, *args) -> None:
        api = self.ctx.api
        if api is None:
            return
        self._set_busy(True, "Contacting the server…")
        self.ctx.runner.run(call, *args, on_done=self._on_result, on_error=self._on_error)

    def _on_result(self, result) -> None:
        self._set_busy(False)
        if isinstance(result, str):  # a recovery code from api.recovery()
            self._recovery_code = result
            self._sync()
            self.status_label.setText(
                "Save this recovery code now — it is shown only once. Use it to "
                "restore your account on a new PC."
            )
            return
        # register / sign in / recover all hand back a RemoteAuth
        self._recovery_code = getattr(result, "recovery_code", "") or ""
        self._mode = "auth"
        self.ctx.sign_in(result)  # emits account_changed -> _sync updates the form
        if self._recovery_code:
            self.status_label.setText(
                "Save this recovery code now — it is shown only once. Use it to "
                "restore your account on a new PC."
            )
        else:
            self.status_label.setText(f"Signed in as {result.account.username}.")

    def _on_error(self, message: str) -> None:
        self._set_busy(False)
        self.status_label.setText(str(message))

    def _copy_recovery(self) -> None:
        if not self._recovery_code:
            return
        QGuiApplication.clipboard().setText(self._recovery_code)
        self.status_label.setText("Recovery code copied to the clipboard.")

    def _sign_out(self) -> None:
        api = self.ctx.api  # captured before sign_out() swaps in a tokenless client
        self._recovery_code = ""
        self._mode = "auth"
        self.ctx.sign_out()
        if api is not None and api.auth_token:
            self.ctx.runner.run(api.logout, on_done=lambda _r: None, on_error=lambda _m: None)
