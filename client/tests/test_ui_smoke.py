"""UI smoke tests — build the whole window headless and exercise the widgets."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from app.config import Settings  # noqa: E402
from app.context import AppContext  # noqa: E402
from app.core.api_client import ApiError, RemoteBlueprint  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.theme import THEME_NAMES, build_stylesheet, resolve_theme  # noqa: E402
from app.ui.views.my_blueprints_view import _preview_key  # noqa: E402
from app.ui.widgets import (  # noqa: E402
    BlueprintCard,
    CardGrid,
    DetailDrawer,
    FiltersBar,
    PreviewCanvas,
    ZoomablePreviewDialog,
    show_toast,
)

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "tests" / "fixtures"


class StubApi:
    """Offline stand-in for :class:`ApiClient`."""

    def __init__(self, items=None):
        self._items = items or []
        self.preview_views: list = []
        self.reported = None

    def healthz(self) -> bool:
        return True

    def categories(self):
        from app.core.api_client import RemoteCategory

        return [RemoteCategory(name="Power", slug="power", count=1)]

    def list_blueprints(self, **_kwargs):
        return list(self._items), len(self._items)

    def preview_svg(self, _blueprint_id: str, *, max_level=None, hide_walls=False) -> str:
        self.preview_views.append((max_level, hide_walls))
        return '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'

    def download(self, _blueprint_id: str):
        raise ApiError("offline")

    def set_liked(self, _blueprint_id: str, liked: bool):
        return (1 if liked else 0, liked)

    def report(self, _blueprint_id: str, reason: str = ""):
        self.reported = (_blueprint_id, reason)
        return "thanks, we'll take a look"

    def upload(self, *_args, **_kwargs):
        raise ApiError("offline")

    def my_uploads(self):
        return []

    def register(self, username):
        from app.core.api_client import RemoteAccount, RemoteAuth

        return RemoteAuth(
            token="stub-token",
            account=RemoteAccount(username=username, has_key=True),
            recovery_code="ABCD-EFGH-IJKL-MNOP",
        )

    def login(self):
        from app.core.api_client import RemoteAccount, RemoteAuth

        return RemoteAuth(token="stub-token", account=RemoteAccount(username="aLee", has_key=True))

    def recovery(self):
        return "ABCD-EFGH-IJKL-MNOP"

    def recover(self, username, recovery_code):
        from app.core.api_client import RemoteAccount, RemoteAuth

        return RemoteAuth(
            token="stub-token",
            account=RemoteAccount(username=username, has_key=True),
            recovery_code="NEW1-CODE-2NEW-3COD",
        )

    def me(self):
        from app.core.api_client import RemoteAccount

        return RemoteAccount(username="aLee", has_key=True)

    def logout(self):
        return None


def _spin(ctx, app, rounds: int = 6) -> None:
    ctx.runner.wait(3000)
    for _ in range(rounds):
        app.processEvents()


def _write_install_key(isolated_dirs, key: str = "d" * 64) -> str:
    """Pretend a retail game install wrote its key, so ``has_game_key`` is True."""
    game_dir = isolated_dirs["game"]
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "profile.cfg").write_text(f'[identity]\ninstall_key="{key}"\n', encoding="utf-8")
    return key


def test_theme_stylesheets_have_no_leftover_tokens():
    for name in THEME_NAMES:
        css = build_stylesheet(name)
        assert css
        assert "{{" not in css and "}}" not in css
        assert resolve_theme(name) in ("needlework_light", "midnight_yard", "harvest_warm")


def test_detail_drawer_stats_stay_aligned_and_compact(qapp):
    drawer = DetailDrawer()
    drawer.resize(400, 800)
    drawer.show_details(
        title="Blueprint",
        stats={
            "Pieces": "128",
            "Floors": "3",
            "Total cost": "95,874",
            "Category": "—",
            "Composition": "83 x Enclosed Conveyor\n12 x Compressor\n7 x Compact Splitter",
        },
    )
    qapp.processEvents()

    values_x = drawer._stats.itemAtPosition(0, 1).geometry().x()
    row_gap = (
        drawer._stats.itemAtPosition(1, 0).geometry().y()
        - drawer._stats.itemAtPosition(0, 0).geometry().y()
    )
    assert row_gap < 35

    drawer.show_details(
        title="Blueprint without composition",
        stats={"Pieces": "10", "Floors": "1", "Total cost": "500", "Category": "Power"},
    )
    qapp.processEvents()
    assert drawer._stats.itemAtPosition(0, 1).geometry().x() == values_x
    drawer.close()


def test_runtime_icon_matches_supplied_icon_asset():
    client_dir = Path(__file__).resolve().parents[1]
    source_icon = client_dir / "icon.ico"
    runtime_icon = client_dir / "app" / "assets" / "app.ico"

    assert runtime_icon.read_bytes() == source_icon.read_bytes()
    assert not QIcon(str(runtime_icon)).isNull()


def test_main_window_builds_all_pages(qapp):
    ctx = AppContext(Settings())
    ctx.api = StubApi()
    window = MainWindow(ctx)
    assert window.stack.count() == 4
    for index in range(4):
        window._select(index)
    _spin(ctx, qapp)
    window.close()


def test_blueprint_card_badges_wrap_to_fit(qapp):
    card = BlueprintCard(
        title="A blueprint with a long title that should wrap within the card",
        subtitle="83x Enclosed Conveyor, 12x Compressor, 7x Compact Sorter",
        badges=[
            "128 pieces",
            "3 floors",
            "cost 999,999,999,999,999",
            "0 likes",
            "AnUnbrokenCategoryNameThatIsMuchLongerThanTheCardWidth",
        ],
    )
    card.resize(300, 500)
    card.show()
    qapp.processEvents()

    badges = [widget for widget in card.findChildren(QLabel) if widget.objectName() == "Badge"]
    assert len({badge.y() for badge in badges}) > 1
    assert all(badge.geometry().right() < card.width() for badge in badges)
    assert card.title_label.height() > card.title_label.fontMetrics().height()
    assert card.subtitle_label.height() > card.subtitle_label.fontMetrics().height()


def test_library_view_populates_cards(qapp):
    ctx = AppContext(Settings())
    ctx.api = StubApi(
        [RemoteBlueprint(id="1", title="Power Station", piece_count=201, total_cost=1234, category="Power",
                         author_name="aLee", tags=["power"], distinct_builds={"build:switch_box": 201})]
    )
    window = MainWindow(ctx)
    view = window.library_view
    view.refresh()
    _spin(ctx, qapp)
    assert len(view.grid.cards) == 1
    card = view.grid.cards[0]
    assert card.title_label.text() == "Power Station"
    window.close()


def test_drawer_level_slider_requests_the_matching_preview(qapp):
    ctx = AppContext(Settings())
    api = StubApi(
        [RemoteBlueprint(id="1", title="Tower", piece_count=201, total_cost=1234, category="Power",
                         level_count=4, distinct_builds={"build:switch_box": 201})]
    )
    ctx.api = api
    window = MainWindow(ctx)
    view = window.library_view
    view.refresh()
    _spin(ctx, qapp)

    card = view.grid.cards[0]
    badges = [w.text() for w in card.findChildren(QLabel) if w.objectName() == "Badge"]
    assert "4 floors" in badges

    view._on_details(view._remote["1"])
    _spin(ctx, qapp)
    drawer = view.drawer
    assert not drawer._view_host.isHidden()
    assert drawer.level_slider.maximum() == 3
    assert drawer.level_slider.value() == 3
    assert drawer.level_value_label.text() == "4/4"

    drawer.level_slider.setValue(1)  # cumulative: levels 0..1
    _spin(ctx, qapp)
    assert api.preview_views[-1] == (1, False)
    assert drawer.max_level == 1
    assert drawer.level_value_label.text() == "2/4"

    drawer.walls_check.setChecked(True)
    _spin(ctx, qapp)
    assert api.preview_views[-1] == (1, True)

    calls_before = len(api.preview_views)
    drawer.walls_check.setChecked(False)  # cached (1, False)
    drawer.level_slider.setValue(3)       # top of the slider -> cached default view
    _spin(ctx, qapp)
    assert len(api.preview_views) == calls_before
    window.close()


def test_zoom_preview_dialog_has_level_and_wall_controls(qapp):
    dialog = ZoomablePreviewDialog(
        svg='<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>',
        title="Tower",
        level_count=4,
    )
    changes = []
    dialog.view_changed.connect(changes.append)

    assert dialog.level_slider.maximum() == 3
    assert dialog.level_slider.value() == 3
    assert dialog.level_value_label.text() == "4/4"
    dialog.level_slider.setValue(1)
    assert changes[-1] == (1, False)
    dialog.walls_check.setChecked(True)
    assert changes[-1] == (1, True)
    dialog.close()


def test_library_filters_wrap_categories_under_search(qapp):
    bar = FiltersBar(categories=[])
    bar.setFixedWidth(440)
    bar.resize(440, 180)
    bar.show()
    qapp.processEvents()
    bar.set_categories([
        "Power", "Production", "Logistics", "Water", "Buildings", "Compact", "Misc"
    ])
    qapp.processEvents()

    category_y = [button.y() for key, button in bar._chips.items() if key]
    assert len(set(category_y)) > 1
    assert all(button.y() >= bar.search.geometry().bottom() + 1 for button in bar._chips.values())
    assert bar.current_filters()["direction"] == "desc"
    assert bar.current_filters()["sort"] == "newest"
    bar.close()


def test_library_like_button_updates_server_count(qapp):
    from app.core.api_client import RemoteAccount, RemoteAuth

    bp = RemoteBlueprint(id="liked", title="Tower", likes=0, liked=False)
    ctx = AppContext(Settings())
    # Rating needs an account now, so sign in before liking.
    ctx.sign_in(RemoteAuth(token="tok", account=RemoteAccount(username="aLee", has_key=True)))
    ctx.api = StubApi([bp])
    window = MainWindow(ctx)
    view = window.library_view
    view.refresh()
    _spin(ctx, qapp)
    view._on_details(bp)
    view.drawer.like_button.click()
    _spin(ctx, qapp)

    assert bp.likes == 1 and bp.liked is True
    assert view.drawer.like_button.text() == "♥ 1"
    assert view.drawer.like_button.objectName() == "Like"
    assert view.drawer.close_button.objectName() == "CloseButton"
    window.close()


def test_library_report_requires_sign_in(qapp, monkeypatch):
    bp = RemoteBlueprint(id="r1", title="Spam")
    ctx = AppContext(Settings())
    ctx.api = StubApi([bp])
    window = MainWindow(ctx)
    view = window.library_view
    view.refresh()
    _spin(ctx, qapp)

    opened: dict = {}

    class FakeAccountDialog:
        def __init__(self, *_args, **_kwargs):
            opened["shown"] = True

        def exec(self):
            return 0

    monkeypatch.setattr("app.ui.views.library_view.AccountDialog", FakeAccountDialog)

    view._on_details(bp)
    assert view.drawer.report_button.isVisible() or not view.drawer.isVisible()
    view.drawer.report_button.click()
    assert opened.get("shown") is True
    window.close()


def test_library_report_submits_when_signed_in(qapp, monkeypatch):
    from app.core.api_client import RemoteAccount, RemoteAuth

    bp = RemoteBlueprint(id="r2", title="Spam")
    ctx = AppContext(Settings())
    ctx.sign_in(RemoteAuth(token="tok", account=RemoteAccount(username="aLee", has_key=True)))
    api = StubApi([bp])
    ctx.api = api
    window = MainWindow(ctx)
    view = window.library_view
    view.refresh()
    _spin(ctx, qapp)

    monkeypatch.setattr(
        "app.ui.views.library_view.QInputDialog.getMultiLineText",
        lambda *_a, **_k: ("clearly spam", True),
    )

    view._on_details(bp)
    view.drawer.report_button.click()
    _spin(ctx, qapp)

    assert api.reported == ("r2", "clearly spam")
    window.close()


def test_single_level_blueprint_hides_the_slider(qapp):
    ctx = AppContext(Settings())
    ctx.api = StubApi([RemoteBlueprint(id="2", title="Flat", piece_count=10, level_count=1)])
    window = MainWindow(ctx)
    view = window.library_view
    view.refresh()
    _spin(ctx, qapp)
    view._on_details(view._remote["2"])
    _spin(ctx, qapp)
    drawer = view.drawer
    assert drawer._level_row.isHidden()
    assert drawer.level_slider.maximum() == 0
    assert not drawer.walls_check.isHidden()
    window.close()


def test_card_grid_toggles_between_grid_and_list(qapp):
    grid = CardGrid()
    grid.resize(640, 500)
    grid.show()
    cards = [BlueprintCard(title=f"Blueprint {i}", parent=grid) for i in range(4)]
    grid.set_cards(cards)
    qapp.processEvents()
    assert all(card.height() > 100 for card in cards)
    assert all(
        not first.geometry().intersects(second.geometry())
        for index, first in enumerate(cards)
        for second in cards[index + 1:]
    )
    assert grid.is_grid is True
    grid.set_grid(False)
    qapp.processEvents()
    assert grid.is_grid is False
    assert len(grid.cards) == 4
    grid.set_grid(True)
    qapp.processEvents()
    assert grid.is_grid is True
    grid.close()


def test_preview_canvas_renders_svg(qapp):
    from ftn_blueprint import parse_blueprint, render_svg

    meta = parse_blueprint(FIXTURES / "1794505172_2ff6.blueprint")
    svg = render_svg(meta, width=320, height=200, theme="dark")
    canvas = PreviewCanvas()
    canvas.resize(320, 200)
    canvas.set_svg(svg)
    assert canvas.has_preview()
    pixmap = canvas.grab()  # forces a paint pass
    assert not pixmap.isNull()


def test_preview_canvas_placeholder_when_empty(qapp):
    canvas = PreviewCanvas()
    canvas.resize(200, 120)
    assert canvas.has_preview() is False
    assert not canvas.grab().isNull()


def test_my_blueprints_view_scans_folder(qapp, isolated_dirs):
    blueprints = isolated_dirs["blueprints"]
    blueprints.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURES / "1794505172_2ff6.blueprint", blueprints / "power.blueprint")
    ctx = AppContext(Settings())
    ctx.api = StubApi()
    window = MainWindow(ctx)
    window._select(1)
    _spin(ctx, qapp, rounds=12)
    view = window.my_view
    assert len(view.grid.cards) == 1
    assert "1 blueprint" in view.status.text()
    entry = view._entries[0]
    card_key = _preview_key(entry, None, False, show_legend=False)
    assert ">Legend</text>" not in view._preview_cache[card_key]
    assert card_key != _preview_key(entry, None, False)
    window.close()


def test_toast_is_created_and_parented(qapp):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    host.resize(600, 400)
    host.show()
    qapp.processEvents()
    toast = show_toast(host, "hello", level="success")
    qapp.processEvents()
    assert toast.parentWidget() is host
    assert host.rect().contains(toast.geometry())

    available = host.screen().availableGeometry()
    host.setGeometry(0, 0, 600, available.height() + 200)
    qapp.processEvents()
    toast.reposition()
    qapp.processEvents()
    window_bounds = QRect(host.mapToGlobal(QPoint(0, 0)), host.size())
    visible_bounds = window_bounds.intersected(available)
    toast_bounds = QRect(host.mapToGlobal(toast.pos()), toast.size())
    assert visible_bounds.contains(toast_bounds)
    assert toast_bounds.bottom() <= visible_bounds.bottom() - 24

    toast.dismiss()
    host.close()
    assert toast not in type(toast)._active


def test_settings_view_applies_theme(qapp):
    ctx = AppContext(Settings())
    ctx.api = StubApi()
    window = MainWindow(ctx)
    view = window.settings_view
    view.refresh()
    index = view.theme_combo.findData("harvest_warm")
    view.theme_combo.setCurrentIndex(index)
    _spin(ctx, qapp)
    assert ctx.settings.theme == "harvest_warm"
    window.close()


def test_api_address_is_hidden_and_connection_status_is_visible(qapp):
    ctx = AppContext(Settings())
    ctx.api = StubApi()
    window = MainWindow(ctx)
    view = window.settings_view
    view.refresh()
    _spin(ctx, qapp)
    assert not hasattr(view, "server_address")
    assert view.server_status.text() == "Online"
    assert view.server_check_button.isEnabled()
    window.close()


def test_upload_page_follows_the_sign_in_state(qapp):
    from app.core.api_client import RemoteAccount, RemoteAuth

    ctx = AppContext(Settings())
    ctx.api = StubApi()
    window = MainWindow(ctx)
    view = window.upload_view

    assert view.signin_button.isHidden() is False
    assert view.upload_button.isEnabled() is False
    assert view.author_edit.isReadOnly() is True
    assert window.account_button.text() == "Sign in"

    ctx.sign_in(RemoteAuth(token="tok", account=RemoteAccount(username="aLee", has_key=True)))
    _spin(ctx, qapp)
    assert view.signin_button.isHidden() is True
    assert view.author_edit.text() == "aLee"  # auto-filled with the registered name
    assert window.account_button.text() == "aLee"

    ctx.sign_out()
    _spin(ctx, qapp)
    assert view.signin_button.isHidden() is False
    assert view.author_edit.text() == ""
    assert window.account_button.text() == "Sign in"
    window.close()


def test_account_dialog_reports_a_conflicting_key_then_signs_in(qapp, isolated_dirs):
    from app.ui.widgets import AccountDialog

    _write_install_key(isolated_dirs)

    class ConflictApi(StubApi):
        def register(self, username):
            raise ApiError(
                "this game key already has an account (aLee); you are signed in "
                "automatically from this install",
                status_code=409,
            )

    ctx = AppContext(Settings())
    ctx.api = ConflictApi()
    dialog = AccountDialog(ctx)
    assert dialog.form_host.isHidden() is False

    dialog.username_edit.setText("newbie")
    dialog._register()
    _spin(ctx, qapp)
    assert "already has an account" in dialog.status_label.text().lower()
    assert ctx.account is None

    ctx.api = StubApi()
    dialog._register()
    _spin(ctx, qapp)
    assert ctx.account is not None and ctx.account.username == "newbie"
    assert dialog.form_host.isHidden() is True
    assert dialog.signout_button.isHidden() is False
    dialog.close()


def test_account_dialog_warns_when_there_is_no_game_key(qapp, isolated_dirs):
    from app.ui.widgets import AccountDialog

    # No profile.cfg written -> no install key, i.e. a non-retail copy.
    ctx = AppContext(Settings())
    ctx.api = StubApi()
    dialog = AccountDialog(ctx)

    assert dialog.form_host.isHidden() is True
    assert dialog.register_button.isHidden() is True
    assert "retail version" in dialog.hint.text().lower()
    dialog.close()


def test_account_dialog_registration_surfaces_the_recovery_code(qapp, isolated_dirs):
    from app.ui.widgets import AccountDialog

    _write_install_key(isolated_dirs)

    ctx = AppContext(Settings())
    ctx.api = StubApi()
    dialog = AccountDialog(ctx)

    dialog.username_edit.setText("newbie")
    dialog._register()
    _spin(ctx, qapp)

    assert ctx.account is not None and ctx.account.username == "newbie"
    assert dialog.recovery_box.isHidden() is False
    assert dialog.recovery_code_label.text() == "ABCD-EFGH-IJKL-MNOP"
    assert dialog.recovery_code_label.minimumHeight() >= 40
    assert dialog.recovery_code_label.textInteractionFlags()
    assert "shown only once" in dialog.status_label.text().lower()
    dialog.close()


def test_account_dialog_recovers_onto_a_new_install(qapp, isolated_dirs):
    from app.ui.widgets import AccountDialog

    _write_install_key(isolated_dirs)

    ctx = AppContext(Settings())
    ctx.api = StubApi()
    dialog = AccountDialog(ctx)

    dialog._begin_recover()
    assert dialog.register_button.isHidden() is True
    assert dialog.submit_recover_button.isHidden() is False
    assert dialog.recovery_edit.isHidden() is False

    dialog.username_edit.setText("aLee")
    dialog.recovery_edit.setText("ABCD-EFGH-IJKL-MNOP")
    dialog._submit_recover()
    _spin(ctx, qapp)

    assert ctx.account is not None and ctx.account.username == "aLee"
    # A fresh code is issued after a successful restore.
    assert dialog.recovery_code_label.text() == "NEW1-CODE-2NEW-3COD"
    dialog.close()


def test_account_dialog_can_issue_a_fresh_recovery_code(qapp, isolated_dirs):
    from app.core.api_client import RemoteAccount, RemoteAuth
    from app.ui.widgets import AccountDialog

    _write_install_key(isolated_dirs)

    ctx = AppContext(Settings())
    ctx.sign_in(RemoteAuth(token="tok", account=RemoteAccount(username="aLee", has_key=True)))
    ctx.api = StubApi()
    dialog = AccountDialog(ctx)

    assert dialog.get_recovery_button.isHidden() is False
    dialog._get_recovery()
    _spin(ctx, qapp)

    assert dialog.recovery_code_label.text() == "ABCD-EFGH-IJKL-MNOP"
    dialog.close()


def test_perf_card_grid_and_large_preview(qapp):
    """200 cards and a 201-piece preview must build without hanging (plan perf item)."""
    import time

    from ftn_blueprint import parse_blueprint, render_svg

    start = time.perf_counter()
    grid = CardGrid()
    grid.set_cards(
        [BlueprintCard(title=f"Blueprint {i}", subtitle="aLee", badges=["Power", "201 pieces"]) for i in range(200)]
    )
    qapp.processEvents()
    grid_seconds = time.perf_counter() - start
    assert len(grid.cards) == 200
    assert grid_seconds < 10.0

    meta = parse_blueprint(FIXTURES / "1794505172_2ff6.blueprint")
    assert meta.piece_count == 201
    start = time.perf_counter()
    svg = render_svg(meta, width=900, height=560, theme="dark")
    canvas = PreviewCanvas()
    canvas.resize(900, 560)
    canvas.set_svg(svg)
    assert canvas.has_preview()
    assert not canvas.grab().isNull()
    assert time.perf_counter() - start < 10.0
