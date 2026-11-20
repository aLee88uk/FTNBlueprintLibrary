"""Thin ``httpx`` wrapper around the FTN Blueprint Library API.

Every request carries an ``X-Install-Key`` header so the backend can attribute
uploads/downloads and resolve the player's account; once signed in it also
carries an ``Authorization: Bearer`` token, which is what allows publishing a
blueprint, attaching a screenshot, or rating one. With no password in the
system, ``login`` proves identity with the install key alone.
All network failures are surfaced as :class:`ApiError` with a human-readable
message so the UI can show a toast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

__all__ = [
    "ApiClient",
    "ApiError",
    "RemoteAccount",
    "RemoteAuth",
    "RemoteBlueprint",
    "RemoteCategory",
    "DEFAULT_TIMEOUT",
]

DEFAULT_TIMEOUT = 20.0
_API_PREFIX = "/api/v1"
_MAX_PREVIEW_BYTES = 4 * 1024 * 1024


class ApiError(RuntimeError):
    """Any error talking to the backend."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class RemoteCategory:
    name: str
    slug: str = ""
    count: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteCategory":
        return cls(
            name=str(data.get("name", "")),
            slug=str(data.get("slug", "")),
            count=int(data.get("count", 0) or 0),
        )


@dataclass
class RemoteAccount:
    """The signed-in account as described by the server (no key, no password)."""

    username: str = ""
    created_at: str = ""
    has_key: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteAccount":
        return cls(
            username=str(data.get("username", "")),
            created_at=str(data.get("created_at", "")),
            has_key=bool(data.get("has_key", False)),
        )


@dataclass
class RemoteAuth:
    """What register/login/recover hands back: a bearer token plus its account."""

    token: str = ""
    expires_at: str = ""
    account: RemoteAccount = field(default_factory=RemoteAccount)
    #: A recovery code to save; only present on register/recover, else empty.
    recovery_code: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteAuth":
        account = data.get("account")
        return cls(
            token=str(data.get("token", "")),
            expires_at=str(data.get("expires_at", "")),
            account=RemoteAccount.from_dict(account if isinstance(account, dict) else {}),
            recovery_code=str(data.get("recovery_code", "")),
        )


@dataclass
class RemoteBlueprint:
    """A blueprint as described by the server catalogue."""

    id: str
    title: str = ""
    description: str = ""
    author_name: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    piece_count: int = 0
    level_count: int = 1
    total_cost: float = 0.0
    mk: int = 0
    made: int = 0
    colour: str = ""
    icon: str = ""
    distinct_builds: dict[str, int] = field(default_factory=dict)
    downloads: int = 0
    likes: int = 0
    liked: bool = False
    created_at: str = ""
    size_bytes: int = 0
    sha256: str = ""
    preview_url: str = ""
    screenshot_url: str = ""
    download_url: str = ""
    game_id: str = ""
    is_owner: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteBlueprint":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        payload.setdefault("id", str(data.get("id", "")))
        payload["id"] = str(payload["id"])
        if not isinstance(payload.get("tags"), list):
            payload["tags"] = []
        if not isinstance(payload.get("distinct_builds"), dict):
            payload["distinct_builds"] = {}
        return cls(**payload)

    # -- convenience -------------------------------------------------------
    def build_summary(self, limit: int = 4) -> str:
        """``3x Compact Joiner, 2x Power Station`` style summary."""
        from ftn_blueprint import pretty_building_name

        if not self.distinct_builds:
            return ""
        parts = []
        for build_id, count in list(self.distinct_builds.items())[:limit]:
            parts.append(f"{count}x {pretty_building_name(build_id)}")
        return ", ".join(parts)


class ApiClient:
    """Synchronous client; call it from a worker thread to keep the UI alive."""

    def __init__(
        self,
        base_url: str,
        install_key: str | None = None,
        *,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.install_key = install_key
        self.auth_token = token or None
        self._timeout = timeout
        self._client = client

    def set_token(self, token: str | None) -> None:
        """Attach (or drop) the bearer token used for account-gated requests."""
        self.auth_token = token or None

    # -- plumbing ----------------------------------------------------------
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.install_key:
            headers["X-Install-Key"] = self.install_key
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if extra:
            headers.update(extra)
        return headers

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{_API_PREFIX}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = self._url(path)
        client = self._client or httpx.Client(timeout=self._timeout)
        own = self._client is None
        try:
            response = client.request(method, url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(f"cannot reach {self.base_url or 'server'}: {exc}") from exc
        finally:
            if own:
                client.close()
        if response.status_code >= 400:
            raise ApiError(_error_message(response), status_code=response.status_code)
        return response

    # -- read endpoints ----------------------------------------------------
    def healthz(self) -> bool:
        try:
            self._request("GET", "/healthz")
            return True
        except ApiError:
            return False

    def categories(self) -> list[RemoteCategory]:
        data = self._request("GET", "/categories").json()
        items = data.get("items", data) if isinstance(data, dict) else data
        return [RemoteCategory.from_dict(item) for item in items or []]

    def list_blueprints(
        self,
        *,
        q: str | None = None,
        category: str | None = None,
        sort: str | None = None,
        direction: str = "desc",
        page: int = 1,
        page_size: int = 24,
    ) -> tuple[list[RemoteBlueprint], int]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if q:
            params["q"] = q
        if category:
            params["category"] = category
        if sort:
            params["sort"] = sort
        if direction:
            params["direction"] = direction
        data = self._request("GET", "/blueprints", params=params).json()
        if isinstance(data, list):
            return [RemoteBlueprint.from_dict(item) for item in data], len(data)
        items = data.get("items", [])
        total = int(data.get("total", len(items)) or len(items))
        return [RemoteBlueprint.from_dict(item) for item in items], total

    def get_blueprint(self, blueprint_id: str) -> RemoteBlueprint:
        data = self._request("GET", f"/blueprints/{blueprint_id}").json()
        if isinstance(data, dict) and "item" in data:
            data = data["item"]
        return RemoteBlueprint.from_dict(data)

    def download(self, blueprint_id: str) -> tuple[bytes, str]:
        """Return ``(bytes, filename)`` for a blueprint."""
        response = self._request("GET", f"/blueprints/{blueprint_id}/download")
        filename = _filename_from_disposition(response.headers.get("content-disposition")) or f"{blueprint_id}.blueprint"
        return response.content, filename

    def set_liked(self, blueprint_id: str, liked: bool) -> tuple[int, bool]:
        """Set this install's like state and return the server count/state."""
        method = "PUT" if liked else "DELETE"
        payload = self._request(method, f"/blueprints/{blueprint_id}/like").json()
        return int(payload.get("likes", 0) or 0), bool(payload.get("liked", False))

    def preview_svg(
        self,
        blueprint_id: str,
        *,
        max_level: int | None = None,
        hide_walls: bool = False,
    ) -> str:
        """Fetch the SVG preview.

        ``max_level`` renders vertical levels ``0..max_level`` cumulatively
        (``None`` = every level); ``hide_walls`` drops the vertical side faces.
        """
        params: dict[str, Any] = {}
        if max_level is not None:
            params["max_level"] = max_level
        if hide_walls:
            params["hide_walls"] = "true"
        response = self._request("GET", f"/blueprints/{blueprint_id}/preview.svg", params=params or None)
        if len(response.content) > _MAX_PREVIEW_BYTES:
            raise ApiError("preview is unexpectedly large")
        return response.text

    def my_uploads(self) -> list[RemoteBlueprint]:
        data = self._request("GET", "/me/uploads").json()
        items = data.get("items", data) if isinstance(data, dict) else data
        return [RemoteBlueprint.from_dict(item) for item in items or []]

    # -- write endpoints ---------------------------------------------------
    def upload(
        self,
        data: bytes,
        *,
        filename: str,
        title: str,
        description: str = "",
        category: str = "",
        tags: Iterable[str] = (),
        screenshot: bytes | None = None,
        screenshot_name: str = "",
    ) -> RemoteBlueprint:
        form = {
            "title": title,
            "description": description,
            "category": category,
            "tags": ",".join(t for t in tags if t),
        }
        files = {"file": (filename, data, "application/octet-stream")}
        if screenshot is not None:
            files["screenshot"] = (screenshot_name or "screenshot.png", screenshot, "application/octet-stream")
        response = self._request("POST", "/blueprints", data=form, files=files)
        payload = response.json()
        if isinstance(payload, dict) and "item" in payload:
            payload = payload["item"]
        return RemoteBlueprint.from_dict(payload)

    def download_screenshot(self, blueprint_id: str) -> bytes | None:
        """Fetch the screenshot bytes for a blueprint, or ``None`` if none exists."""
        try:
            response = self._request("GET", f"/blueprints/{blueprint_id}/screenshot")
        except ApiError as exc:
            if exc.status_code == 404:
                return None
            raise
        return response.content

    def update_blueprint(
        self,
        blueprint_id: str,
        *,
        title: str = "",
        description: str = "",
        category: str = "",
        tags: Iterable[str] = (),
    ) -> RemoteBlueprint:
        """Edit the title, description, category or tags of your own blueprint."""
        form = {
            "title": title,
            "description": description,
            "category": category,
            "tags": ",".join(t for t in tags if t),
        }
        response = self._request("PATCH", f"/blueprints/{blueprint_id}", data=form)
        payload = response.json()
        if isinstance(payload, dict) and "item" in payload:
            payload = payload["item"]
        return RemoteBlueprint.from_dict(payload)

    def replace_blueprint(
        self,
        blueprint_id: str,
        data: bytes,
        *,
        filename: str,
        title: str = "",
        description: str = "",
        category: str = "",
        tags: Iterable[str] = (),
        screenshot: bytes | None = None,
        screenshot_name: str = "",
    ) -> RemoteBlueprint:
        """Overwrite an existing blueprint with a new file (same id)."""
        form = {
            "title": title,
            "description": description,
            "category": category,
            "tags": ",".join(t for t in tags if t),
        }
        files = {"file": (filename, data, "application/octet-stream")}
        if screenshot is not None:
            files["screenshot"] = (screenshot_name or "screenshot.png", screenshot, "application/octet-stream")
        response = self._request("PUT", f"/blueprints/{blueprint_id}", data=form, files=files)
        payload = response.json()
        if isinstance(payload, dict) and "item" in payload:
            payload = payload["item"]
        return RemoteBlueprint.from_dict(payload)

    def delete_blueprint(self, blueprint_id: str) -> None:
        """Soft-delete your own blueprint from the library."""
        self._request("DELETE", f"/blueprints/{blueprint_id}")

    def report(self, blueprint_id: str, reason: str) -> str:
        """Flag a blueprint for moderator review; returns the server's message."""
        data = self._request(
            "POST", f"/blueprints/{blueprint_id}/report", json={"reason": reason}
        ).json()
        return str((data or {}).get("detail", ""))

    # -- accounts ----------------------------------------------------------
    def register(self, username: str) -> RemoteAuth:
        """Create an account from a name alone, bound to this install key, and sign in."""
        data = self._request("POST", "/auth/register", json={"username": username}).json()
        return RemoteAuth.from_dict(data)

    def login(self) -> RemoteAuth:
        """Sign in using the install key alone — the passwordless credential."""
        data = self._request("POST", "/auth/login").json()
        return RemoteAuth.from_dict(data)

    def recovery(self) -> str:
        """Rotate and return a fresh recovery code for the signed-in account."""
        data = self._request("POST", "/auth/recovery").json()
        return str(data.get("recovery_code", ""))

    def recover(self, username: str, recovery_code: str) -> RemoteAuth:
        """Re-bind an account to this install from a recovery code, and sign in."""
        data = self._request(
            "POST", "/auth/recover", json={"username": username, "recovery_code": recovery_code}
        ).json()
        return RemoteAuth.from_dict(data)

    def me(self) -> RemoteAccount:
        """The account behind the current token (raises ``ApiError`` when stale)."""
        return RemoteAccount.from_dict(self._request("GET", "/auth/me").json())

    def logout(self) -> None:
        """Best-effort server-side revocation of the current token."""
        self._request("POST", "/auth/logout")


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"server returned HTTP {response.status_code}"
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, list) and detail:
            detail = detail[0]
            if isinstance(detail, dict):
                detail = detail.get("msg", detail)
        if detail:
            return f"{detail} (HTTP {response.status_code})"
    return f"server returned HTTP {response.status_code}"


def _filename_from_disposition(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.split(";"):
        part = part.strip()
        if part.lower().startswith("filename*="):
            _, _, encoded = part.partition("''")
            return encoded or part.split("=", 1)[-1].strip('"')
        if part.lower().startswith("filename="):
            return part.split("=", 1)[-1].strip('"')
    return None
