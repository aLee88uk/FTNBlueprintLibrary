"""API client behaviour against a mocked transport (no real server)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.core.api_client import ApiClient, ApiError, RemoteBlueprint


def make_client(handler) -> ApiClient:
    transport = httpx.MockTransport(handler)
    return ApiClient("http://test.local", install_key="key-123", client=httpx.Client(transport=transport))


def test_list_blueprints_parses_and_sends_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-install-key")
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "1", "title": "Power Station", "piece_count": 201, "total_cost": 1234.5,
                     "tags": ["power"], "distinct_builds": {"build:switch_box": 201}, "author_name": "aLee"}
                ],
                "total": 1,
            },
        )

    client = make_client(handler)
    items, total = client.list_blueprints(
        q="power", category="Power", sort="newest", direction="asc"
    )
    assert total == 1
    assert len(items) == 1
    assert isinstance(items[0], RemoteBlueprint)
    assert items[0].title == "Power Station"
    assert items[0].build_summary() == "201x Power Station"
    assert seen["key"] == "key-123"
    assert "q=power" in seen["url"] and "category=Power" in seen["url"]
    assert "direction=asc" in seen["url"]


def test_download_returns_bytes_and_filename():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"BLUEPRINT-BYTES",
            headers={"content-disposition": 'attachment; filename="Power Station.blueprint"'},
        )

    client = make_client(handler)
    data, filename = client.download("42")
    assert data == b"BLUEPRINT-BYTES"
    assert filename == "Power Station.blueprint"


def test_set_liked_uses_idempotent_like_routes():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        return httpx.Response(200, json={"likes": 3, "liked": request.method == "PUT"})

    client = make_client(handler)
    assert client.set_liked("42", True) == (3, True)
    assert client.set_liked("42", False) == (3, False)
    assert [method for method, _url in requests] == ["PUT", "DELETE"]
    assert all(url.endswith("/api/v1/blueprints/42/like") for _method, url in requests)


def test_upload_posts_multipart():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.read()
        return httpx.Response(201, json={"id": "9", "title": "Mine"})

    client = make_client(handler)
    result = client.upload(
        b"DATA", filename="Mine.blueprint", title="Mine", description="d",
        category="Logistics", tags=["a", "b"],
    )
    assert result.id == "9"
    assert "multipart/form-data" in captured["content_type"]
    assert b"DATA" in captured["body"]


def test_error_raises_api_error_with_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(413, json={"detail": "file too large"})

    client = make_client(handler)
    with pytest.raises(ApiError) as exc:
        client.upload(b"x", filename="x.blueprint", title="x")
    assert exc.value.status_code == 413
    assert "file too large" in str(exc.value)


def test_network_failure_is_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = make_client(handler)
    with pytest.raises(ApiError):
        client.list_blueprints()


def test_healthz_false_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = make_client(handler)
    assert client.healthz() is False


def test_remote_blueprint_from_dict_ignores_unknown_fields():
    item = RemoteBlueprint.from_dict({"id": 5, "title": "T", "unknown": "x", "tags": None})
    assert item.id == "5"
    assert item.tags == []
    assert item.distinct_builds == {}


def test_categories_parsing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [{"name": "Power", "slug": "power", "count": 3}]})

    client = make_client(handler)
    cats = client.categories()
    assert cats[0].name == "Power"
    assert cats[0].count == 3


def test_preview_svg_sends_the_view_options():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="<svg/>", headers={"content-type": "image/svg+xml"})

    client = make_client(handler)
    assert client.preview_svg("42") == "<svg/>"
    assert client.preview_svg("42", max_level=2, hide_walls=True) == "<svg/>"
    assert "max_level" not in seen[0] and "hide_walls" not in seen[0]
    assert "max_level=2" in seen[1]
    assert "hide_walls=true" in seen[1]


def test_remote_blueprint_parses_level_count():
    item = RemoteBlueprint.from_dict({"id": "5", "title": "Tower", "level_count": 4})
    assert item.level_count == 4
    assert RemoteBlueprint.from_dict({"id": "6"}).level_count == 1


def test_register_posts_only_the_name_and_parses_account():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.read())
        return httpx.Response(
            201,
            json={
                "token": "tok-1",
                "expires_at": "2026-01-01T00:00:00+00:00",
                "account": {"username": "aLee", "has_key": True},
                "recovery_code": "ABCD-EFGH-IJKL-MNOP",
            },
        )

    client = make_client(handler)
    auth = client.register("aLee")
    assert auth.token == "tok-1"
    assert auth.account.username == "aLee"
    assert auth.account.has_key is True
    assert auth.recovery_code == "ABCD-EFGH-IJKL-MNOP"
    assert seen["url"].endswith("/api/v1/auth/register")
    assert seen["body"] == {"username": "aLee"}  # passwordless: no password field


def test_token_is_sent_as_a_bearer_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"username": "aLee"})

    client = make_client(handler)
    client.set_token("tok-9")
    account = client.me()
    assert account.username == "aLee"
    assert seen["auth"] == "Bearer tok-9"


def test_login_posts_no_body_and_parses_account():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(200, json={"token": "tok-2", "account": {"username": "aLee", "has_key": True}})

    client = make_client(handler)
    auth = client.login()
    assert auth.token == "tok-2"
    assert auth.account.username == "aLee"
    assert seen["url"].endswith("/api/v1/auth/login")
    assert seen["body"] == b""  # the install-key header is the whole credential


def test_login_failure_raises_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no account is linked to this game install yet"})

    client = make_client(handler)
    with pytest.raises(ApiError) as exc:
        client.login()
    assert exc.value.status_code == 404


def test_recovery_posts_and_returns_the_code():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"recovery_code": "WXYZ-1234-5678-9000"})

    client = make_client(handler)
    client.set_token("tok-3")
    code = client.recovery()
    assert code == "WXYZ-1234-5678-9000"
    assert seen["url"].endswith("/api/v1/auth/recovery")
    assert seen["auth"] == "Bearer tok-3"


def test_recover_posts_name_and_code_then_parses_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "token": "tok-4",
                "account": {"username": "aLee", "has_key": True},
                "recovery_code": "NEW1-CODE-2NEW-3COD",
            },
        )

    client = make_client(handler)
    auth = client.recover("aLee", "OLD1-CODE-2OLD-3COD")
    assert auth.token == "tok-4"
    assert auth.account.username == "aLee"
    assert auth.recovery_code == "NEW1-CODE-2NEW-3COD"
    assert seen["url"].endswith("/api/v1/auth/recover")
    assert seen["body"] == {"username": "aLee", "recovery_code": "OLD1-CODE-2OLD-3COD"}
