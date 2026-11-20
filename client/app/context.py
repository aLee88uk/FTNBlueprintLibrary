"""Shared application state passed to every view.

Holds the loaded settings, the resolved identity, the API client, the local
library scanner and the background task runner, and re-builds the pieces that
depend on settings when those change.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .config import Settings
from .core.api_client import ApiClient, RemoteAccount, RemoteAuth
from .core.identity import read_install_key, resolve_identity
from .core.library import LocalLibrary
from .core.paths import screenshot_cache_dir
from .core.provenance import ProvenanceStore
from .core.screenshot_cache import ScreenshotCache
from .core.tasks import TaskRunner
from .theme import preview_theme_for

__all__ = ["AppContext"]


class AppContext(QObject):
    """Mutable application state with change notifications."""

    identity_changed = Signal(str)
    api_changed = Signal()
    library_changed = Signal()
    settings_changed = Signal()
    account_changed = Signal()

    def __init__(self, settings: Settings | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings or Settings.load()
        self.runner = TaskRunner(max_threads=4, parent=self)
        self.provenance = ProvenanceStore()
        #: On-disk cache of downloaded screenshots, keyed by content version.
        self.screenshot_cache = ScreenshotCache(screenshot_cache_dir())
        self.identity: str = ""
        self.api: ApiClient | None = None
        self.library: LocalLibrary | None = None
        #: Optimistically restored from settings; verified against the server lazily.
        self.account: RemoteAccount | None = (
            RemoteAccount(username=self.settings.auth_username) if self.settings.auth_token else None
        )
        self._rebuild_identity()
        self._rebuild_api()
        self._rebuild_library()

    # -- (re)construction --------------------------------------------------
    def _rebuild_identity(self) -> None:
        self.identity = resolve_identity(self.settings.blueprints_dir_override)

    def _rebuild_api(self) -> None:
        self.api = ApiClient(
            self.settings.api_base_url,
            self.identity,
            token=self.settings.auth_token or None,
        )

    def _rebuild_library(self) -> None:
        self.library = LocalLibrary(self.settings.blueprints_dir_override, provenance=self.provenance)

    # -- mutations ---------------------------------------------------------
    def save_settings(self) -> None:
        try:
            self.settings.save()
        except OSError:
            pass

    def set_blueprints_override(self, path: str | None) -> None:
        self.settings.blueprints_dir_override = path or None
        self.save_settings()
        self._rebuild_identity()
        self._rebuild_library()
        self.identity_changed.emit(self.identity)
        self.library_changed.emit()

    def set_theme(self, name: str) -> None:
        self.settings.theme = name
        self.save_settings()
        self.settings_changed.emit()

    def refresh_library(self) -> None:
        if self.library is not None:
            self.library.provenance = self.provenance
        self.library_changed.emit()

    # -- account -----------------------------------------------------------
    @property
    def is_signed_in(self) -> bool:
        return bool(self.settings.auth_token)

    @property
    def has_game_key(self) -> bool:
        """Whether a real game install wrote an ``install_key`` (retail copy).

        Accounts, uploading and rating all need this key; without it the client
        still browses and downloads, but says so up front.
        """
        return read_install_key(self.settings.blueprints_dir_override) is not None

    def auto_sign_in(self) -> None:
        """Silently sign in from the saved game key — there is no password.

        Runs in the background and stays quiet on failure (e.g. no account is
        linked to this install yet, in which case the player just registers).
        """
        if self.is_signed_in or self.api is None or not self.has_game_key:
            return
        self.runner.run(self.api.login, on_done=self._on_auto_sign_in, on_error=lambda _m: None)

    def _on_auto_sign_in(self, auth) -> None:
        if auth is not None and getattr(auth, "token", "") and not self.is_signed_in:
            self.sign_in(auth)

    def sign_in(self, auth: RemoteAuth) -> None:
        """Adopt the token issued by register/login."""
        self.settings.auth_token = auth.token
        self.settings.auth_username = auth.account.username
        self.account = auth.account
        self.save_settings()
        self._rebuild_api()
        self.api_changed.emit()
        self.account_changed.emit()

    def sign_out(self) -> None:
        self.settings.auth_token = ""
        self.account = None
        self.save_settings()
        self._rebuild_api()
        self.api_changed.emit()
        self.account_changed.emit()

    # -- helpers -----------------------------------------------------------
    def preview_theme(self) -> str:
        """The SVG theme (``dark``/``light``) matching the current UI theme."""
        return preview_theme_for(self.settings.theme)

    def blueprints_dir(self):
        return self.library.blueprints_dir if self.library is not None else None
