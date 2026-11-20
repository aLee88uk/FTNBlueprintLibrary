"""Library page — the remote catalogue of community blueprints."""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from ftn_blueprint import pretty_building_name

from ...core.installer import STATUS_ALREADY, STATUS_INSTALLED, STATUS_BLOCKED, install
from ...core.shell import reveal_in_file_manager
from ..widgets import AccountDialog, BlueprintCard, CardGrid, DetailDrawer, EditBlueprintDialog, FiltersBar
from .base import View

__all__ = ["LibraryView"]

PAGE_SIZE = 24


def _preview_key(blueprint_id: str, max_level: int | None, hide_walls: bool) -> str:
    """Cache key for one preview variant (``None`` = every level, walls on)."""
    parts = ["all" if max_level is None else f"L{max_level}"]
    if hide_walls:
        parts.append("NW")
    return f"{blueprint_id}:{'.'.join(parts)}"


def _resolve_view(level_count: int, max_level: int, hide_walls: bool) -> tuple[int | None, bool]:
    """Collapse "top of the slider, walls on" onto the default all-levels view.

    The renderer's default (``max_level=None``) is identical to rendering every
    level, so mapping the top slider position onto it lets us reuse the preview
    the server already cached at upload time.
    """
    if max_level >= max(level_count - 1, 0) and not hide_walls:
        return (None, False)
    return (int(max_level), bool(hide_walls))


def _format_composition(distinct_builds: dict[str, int], *, limit: int = 8) -> str:
    """Render the distinct_builds dict as a multi-line "N x Pretty Name" list."""
    if not distinct_builds:
        return "—"
    lines = [f"{count} x {pretty_building_name(bid)}" for bid, count in distinct_builds.items()]
    shown = lines[:limit]
    if len(lines) > limit:
        shown.append(f"and {len(lines) - limit} more kind(s)")
    return "\n".join(shown)


def _library_stats(bp) -> dict[str, str]:
    """Build the detail-drawer stats for a remote (library) blueprint.

    Drops the noisy fields (icon, size, SHA-256) and surfaces the composition
    (which buildings and how many) instead.
    """
    stats: dict[str, str] = {
        "Author": bp.author_name or "unknown",
        "Category": bp.category or "—",
        "Pieces": f"{bp.piece_count:,}",
        "Floors": f"{max(int(getattr(bp, 'level_count', 1) or 1), 1)}",
        "Total cost": f"{bp.total_cost:,.0f}",
        "Downloads": f"{bp.downloads:,}",
        "Likes": f"{int(getattr(bp, 'likes', 0) or 0):,}",
    }
    if getattr(bp, "tags", None):
        stats["Tags"] = ", ".join(bp.tags)
    composition = _format_composition(getattr(bp, "distinct_builds", None) or {})
    if composition != "—":
        stats["Composition"] = composition
    return stats


def _like_badge_text(count: int) -> str:
    count = max(int(count or 0), 0)
    return f"{count:,} {'like' if count == 1 else 'likes'}"


class LibraryView(View):
    """Browse, preview and install blueprints from the server."""

    page_title = "Library"
    page_subtitle = "Browse blueprints shared by other players and install them with one click"

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)
        self._filters: dict = {"q": "", "category": "", "sort": "newest", "direction": "desc"}
        self._page = 1
        self._total = 0
        self._categories_loaded = False
        self._categories: list[str] = []
        self._preview_cache: dict[str, str] = {}
        self._remote: dict[str, object] = {}
        self._cards_by_id: dict[str, BlueprintCard] = {}
        #: View currently shown in the drawer (``(max_level, hide_walls)``).
        self._drawer_view: tuple[int | None, bool] = (None, False)

        self.filters = FiltersBar(show_view_toggle=True, parent=self)
        self.filters.filters_changed.connect(self._on_filters_changed)
        self.filters.view_changed.connect(self._on_view_changed)
        self.filters.refresh_requested.connect(self.refresh)
        self.root.addWidget(self.filters)

        self.status = QLabel("", self)
        self.status.setObjectName("PageSubtitle")
        self.root.addWidget(self.status)

        self.grid = CardGrid(card_width=300, parent=self)
        self.grid.set_empty_text("No blueprints match your filters yet.")
        self.root.addWidget(self.grid, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.load_more = QPushButton("Load more", self)
        self.load_more.setObjectName("Ghost")
        self.load_more.clicked.connect(self._load_next_page)
        self.load_more.hide()
        footer.addWidget(self.load_more)
        self.root.addLayout(footer)

        self.drawer = DetailDrawer(self)
        self.drawer.hide()
        self.drawer.action_clicked.connect(self._on_drawer_action)
        self.drawer.like_clicked.connect(self._on_like)
        self.drawer.edit_clicked.connect(self._on_edit)
        self.drawer.delete_clicked.connect(self._on_delete)
        self.drawer.report_clicked.connect(self._on_report)
        self.drawer.view_changed.connect(self._on_drawer_view_changed)
        self.drawer.closed.connect(lambda: None)

        self.grid.set_grid(bool(self.ctx.settings.grid_view))
        self._busy = False

    # -- lifecycle ---------------------------------------------------------
    def refresh(self) -> None:
        self._page = 1
        self._load_categories()
        self._load_page(1, replace=True)

    def on_shown(self) -> None:
        if not self.grid.cards:
            self.refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.drawer.isVisible():
            self.drawer.setGeometry(QRect(self.width() - 400, 0, 400, self.height()))

    # -- filters -----------------------------------------------------------
    def _on_filters_changed(self, values: dict) -> None:
        self._filters = values
        self._page = 1
        self._load_page(1, replace=True)

    def _on_view_changed(self, is_grid: bool) -> None:
        self.ctx.settings.grid_view = is_grid
        self.ctx.save_settings()
        self.grid.set_grid(is_grid)

    # -- data loading ------------------------------------------------------
    def _api(self):
        return self.ctx.api

    def _load_categories(self) -> None:
        if self._categories_loaded:
            return
        api = self._api()
        if api is None:
            return

        def done(categories):
            names = [c.name for c in categories if c.name]
            self._categories = names
            if names:
                self.filters.set_categories(names)
            self._categories_loaded = True

        self.ctx.runner.run(api.categories, on_done=done, on_error=lambda msg: None)

    def _load_page(self, page: int, *, replace: bool) -> None:
        api = self._api()
        if api is None or self._busy:
            return
        self._busy = True
        self.status.setText("Loading blueprints…")
        self.load_more.setEnabled(False)

        filters = dict(self._filters)
        self.ctx.runner.run(
            api.list_blueprints,
            q=filters.get("q") or None,
            category=filters.get("category") or None,
            sort=filters.get("sort") or None,
            direction=filters.get("direction") or "desc",
            page=page,
            page_size=PAGE_SIZE,
            on_done=lambda result: self._on_page_loaded(result, page, replace),
            on_error=self._on_load_error,
        )

    def _on_page_loaded(self, result, page: int, replace: bool) -> None:
        self._busy = False
        items, total = result
        self._total = total
        self._page = page
        for item in items:
            self._remote[item.id] = item

        if replace:
            self.grid.clear_cards()
            self._cards_by_id.clear()
        cards = [self._make_card(item) for item in items]
        if cards:
            self.grid.add_cards(cards)
        self.status.setText(self._status_text(len(self.grid.cards)))
        self.load_more.setVisible(self._page * PAGE_SIZE < self._total)
        self.load_more.setEnabled(True)

    def _on_load_error(self, message: str) -> None:
        self._busy = False
        self.load_more.setEnabled(True)
        self.status.setText(f"Could not reach the server at {self.ctx.settings.api_base_url}.")
        if not self.grid.cards:
            self.grid.set_empty_text(
                "Cannot reach the blueprint server.\n"
                "Check your internet connection and try again."
            )
        self.notify(f"Server error: {message}", level="error")

    def _status_text(self, shown: int) -> str:
        if self._total <= 0:
            return "No blueprints found."
        return f"Showing {shown} of {self._total} blueprints"

    def _load_next_page(self) -> None:
        self._load_page(self._page + 1, replace=False)

    # -- cards -------------------------------------------------------------
    def _make_card(self, bp) -> BlueprintCard:
        badges = [f"{bp.piece_count} pieces"]
        if getattr(bp, "level_count", 1) > 1:
            badges.append(f"{bp.level_count} floors")
        badges.append(f"cost {bp.total_cost:,.0f}")
        badges.append(_like_badge_text(getattr(bp, "likes", 0)))
        if bp.category:
            badges.append(bp.category)
        card = BlueprintCard(
            title=bp.title or bp.id,
            subtitle=bp.build_summary(),
            badges=badges,
            author=f"by {bp.author_name}" if bp.author_name else "",
            primary_text="Download",
            secondary_text="Details",
            payload=bp,
            parent=self.grid,
        )
        card.primary.connect(self._on_download)
        card.secondary.connect(self._on_details)
        card.activated.connect(self._on_details)
        self._cards_by_id[bp.id] = card
        cached = self._preview_cache.get(_preview_key(bp.id, None, False))
        if cached is not None:
            card.set_preview_svg(cached)
        else:
            self._fetch_preview(bp, card)
        return card

    def _fetch_preview(self, bp, card: BlueprintCard) -> None:
        api = self._api()
        if api is None or not bp.id:
            card.set_preview_text("No preview")
            return
        key = _preview_key(bp.id, None, False)

        def done(svg: str) -> None:
            self._preview_cache[key] = svg
            try:
                card.set_preview_svg(svg)
            except RuntimeError:
                pass  # card was destroyed while loading

        def failed(_msg: str) -> None:
            try:
                card.set_preview_text("Preview unavailable")
            except RuntimeError:
                pass

        self.ctx.runner.run(api.preview_svg, bp.id, on_done=done, on_error=failed)

    # -- actions -----------------------------------------------------------
    def _on_details(self, bp) -> None:
        self.drawer.setGeometry(QRect(self.width() - 400, 0, 400, self.height()))
        self._drawer_view = (None, False)
        self.drawer.show_details(
            title=bp.title or bp.id,
            subtitle="",
            svg=self._preview_cache.get(_preview_key(bp.id, None, False)),
            stats=_library_stats(bp),
            description=bp.description,
            action_text="Download & install",
            payload=bp,
            level_count=max(int(getattr(bp, "level_count", 1) or 1), 1),
            likes=int(getattr(bp, "likes", 0) or 0),
            liked=bool(getattr(bp, "liked", False)),
            is_owner=bool(getattr(bp, "is_owner", False)),
            can_report=not bool(getattr(bp, "is_owner", False)),
        )
        if bp.id and _preview_key(bp.id, None, False) not in self._preview_cache:
            self._fetch_preview_for_drawer(bp, None, False)
        # A screenshot, when one exists, appears below the map preview.
        if getattr(bp, "screenshot_url", ""):
            self._fetch_screenshot_for_drawer(bp)
        self.drawer.raise_()

    def _on_drawer_view_changed(self, view) -> None:
        bp = self.drawer.payload
        if bp is None or not getattr(bp, "id", None):
            return
        level_count = max(int(getattr(bp, "level_count", 1) or 1), 1)
        max_level, hide_walls = _resolve_view(level_count, view[0], view[1])
        self._drawer_view = (max_level, hide_walls)
        cached = self._preview_cache.get(_preview_key(bp.id, max_level, hide_walls))
        if cached is not None:
            self.drawer.set_svg(cached)
            return
        self.drawer.preview.set_placeholder("Loading preview…")
        self._fetch_preview_for_drawer(bp, max_level, hide_walls)

    def _fetch_preview_for_drawer(self, bp, max_level: int | None, hide_walls: bool) -> None:
        api = self._api()
        if api is None:
            return
        key = _preview_key(bp.id, max_level, hide_walls)

        def done(svg: str) -> None:
            self._preview_cache[key] = svg
            if (
                self.drawer.isVisible()
                and getattr(self.drawer.payload, "id", None) == bp.id
                and self._drawer_view == (max_level, hide_walls)
            ):
                self.drawer.set_svg(svg)

        self.ctx.runner.run(
            api.preview_svg,
            bp.id,
            max_level=max_level,
            hide_walls=hide_walls,
            on_done=done,
            on_error=lambda _m: None,
        )

    def _fetch_screenshot_for_drawer(self, bp) -> None:
        api = self._api()
        if api is None:
            return
        cache = self.ctx.screenshot_cache
        key = cache.key_for(bp.id, getattr(bp, "screenshot_url", ""))

        cached = cache.get(key)
        if cached is not None:
            self._show_screenshot(bp, cached)
            return

        def done(image: bytes | None) -> None:
            if not image:
                return
            cache.put(key, image)
            self._show_screenshot(bp, image)

        self.ctx.runner.run(
            api.download_screenshot, bp.id, on_done=done, on_error=lambda _m: None
        )

    def _show_screenshot(self, bp, image: bytes) -> None:
        if self.drawer.isVisible() and getattr(self.drawer.payload, "id", None) == bp.id:
            self.drawer.set_image(image)

    def _on_drawer_action(self, bp) -> None:
        self._on_download(bp)

    def _on_like(self, bp) -> None:
        if self.ctx.account is None:
            self.notify("Sign in to rate blueprints.", level="warning")
            AccountDialog(self.ctx, self.window()).exec()
            return
        api = self._api()
        if api is None:
            self.notify("No API client available.", level="error")
            return
        self.drawer.like_button.setEnabled(False)
        self.ctx.runner.run(
            api.set_liked,
            bp.id,
            not bool(getattr(bp, "liked", False)),
            on_done=lambda result: self._on_like_updated(bp, result),
            on_error=lambda message: self._on_like_error(bp, message),
        )

    def _on_like_updated(self, bp, result) -> None:
        likes, liked = result
        bp.likes = likes
        bp.liked = liked
        card = self._cards_by_id.get(bp.id)
        if card is not None:
            previous_likes = max(likes - (1 if liked else -1), 0)
            card.update_badge(_like_badge_text(previous_likes), _like_badge_text(likes))
        if getattr(self.drawer.payload, "id", None) == bp.id:
            self.drawer.set_like_state(likes, liked)
            self.drawer.like_button.setEnabled(True)
            for row in range(self.drawer._stats.rowCount()):
                key = self.drawer._stats.itemAtPosition(row, 0)
                if key is not None and key.widget().text() == "Likes":
                    value = self.drawer._stats.itemAtPosition(row, 1)
                    if value is not None:
                        value.widget().setText(f"{likes:,}")
                    break
        if self._filters.get("sort") == "popularity":
            self._load_page(1, replace=True)

    def _on_like_error(self, bp, message: str) -> None:
        if getattr(self.drawer.payload, "id", None) == bp.id:
            self.drawer.like_button.setEnabled(True)
        self.notify(f"Could not update like: {message}", level="error")

    # -- report (other players' uploads) -----------------------------------
    def _on_report(self, bp) -> None:
        if self.ctx.account is None:
            self.notify("Sign in to report a blueprint.", level="warning")
            AccountDialog(self.ctx, self.window()).exec()
            return
        api = self._api()
        if api is None:
            self.notify("No API client available.", level="error")
            return
        reason, ok = QInputDialog.getMultiLineText(
            self.window(),
            "Report blueprint",
            f"Report “{bp.title or bp.id}” to the moderators?\n"
            "Tell us what's wrong (optional):",
        )
        if not ok:
            return
        self.drawer.report_button.setEnabled(False)
        self.ctx.runner.run(
            api.report,
            bp.id,
            reason or "",
            on_done=lambda detail: self._on_reported(bp, detail),
            on_error=lambda message: self._on_report_error(bp, message),
        )

    def _on_reported(self, bp, detail: str) -> None:
        if getattr(self.drawer.payload, "id", None) == bp.id:
            self.drawer.report_button.setEnabled(True)
        level = "info" if detail == "already reported" else "success"
        self.notify(detail or "Thanks — the moderators will take a look.", level=level)

    def _on_report_error(self, bp, message: str) -> None:
        if getattr(self.drawer.payload, "id", None) == bp.id:
            self.drawer.report_button.setEnabled(True)
        self.notify(f"Could not submit report: {message}", level="error")

    # -- edit / delete (owner only) ----------------------------------------
    def _on_edit(self, bp) -> None:
        if not getattr(bp, "is_owner", False):
            return
        dialog = EditBlueprintDialog(
            title=bp.title or "",
            description=getattr(bp, "description", "") or "",
            category=getattr(bp, "category", "") or "",
            tags=list(getattr(bp, "tags", None) or []),
            categories=self._categories,
            parent=self.window(),
        )
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.result_values()
        api = self._api()
        if api is None:
            self.notify("No API client available.", level="error")
            return
        self.drawer.edit_button.setEnabled(False)
        self.ctx.runner.run(
            api.update_blueprint,
            bp.id,
            title=values.title,
            description=values.description,
            category=values.category,
            tags=values.tags,
            on_done=lambda updated: self._on_edited(bp, updated),
            on_error=lambda message: self._on_edit_error(bp, message),
        )

    def _on_edited(self, old_bp, updated) -> None:
        self.drawer.edit_button.setEnabled(True)
        bp = self._remote.get(updated.id)
        if bp is not None:
            bp.title = updated.title
            bp.description = updated.description
            bp.category = updated.category
            bp.tags = list(updated.tags)
        # Refresh the card title/badge if visible.
        card = self._cards_by_id.get(updated.id)
        if card is not None:
            card.set_title(updated.title)
        # Update the drawer if it still shows this blueprint.
        if getattr(self.drawer.payload, "id", None) == updated.id:
            self.drawer.title_label.setText(updated.title)
            self.drawer.description_label.setText(updated.description or "")
            self.drawer.description_label.setVisible(bool(updated.description))
        # If the title changed, the preview was re-rendered server-side.
        if updated.title != old_bp.title:
            self._preview_cache.pop(_preview_key(updated.id, None, False), None)
            self._fetch_preview(updated, card) if card else None
        self.notify(f"“{updated.title}” updated.", level="success")

    def _on_edit_error(self, bp, message: str) -> None:
        self.drawer.edit_button.setEnabled(True)
        self.notify(f"Could not update blueprint: {message}", level="error")

    def _on_delete(self, bp) -> None:
        if not getattr(bp, "is_owner", False):
            return
        title = bp.title or bp.id
        confirm = QMessageBox.question(
            self.window(),
            "Delete blueprint",
            f'Remove “{title}” from the library?\n\n'
            "This cannot be undone. Download links will stop working.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        api = self._api()
        if api is None:
            self.notify("No API client available.", level="error")
            return
        self.drawer.delete_button.setEnabled(False)
        self.ctx.runner.run(
            api.delete_blueprint,
            bp.id,
            on_done=lambda: self._on_deleted(bp),
            on_error=lambda message: self._on_delete_error(bp, message),
        )

    def _on_deleted(self, bp) -> None:
        title = bp.title or bp.id
        card = self._cards_by_id.pop(bp.id, None)
        if card is not None:
            self.grid.remove_card(card)
        self._remote.pop(bp.id, None)
        self._preview_cache = {k: v for k, v in self._preview_cache.items() if not k.startswith(f"{bp.id}:")}
        self.drawer.hide()
        self.status.setText(self._status_text(len(self.grid.cards)))
        self.notify(f"“{title}” was removed from the library.", level="info")

    def _on_delete_error(self, bp, message: str) -> None:
        self.drawer.delete_button.setEnabled(True)
        self.notify(f"Could not delete blueprint: {message}", level="error")

    def _on_download(self, bp) -> None:
        api = self._api()
        if api is None:
            self.notify("No API client available.", level="error")
            return
        self.notify(f"Downloading “{bp.title or bp.id}”…")

        self.ctx.runner.run(
            api.download,
            bp.id,
            on_done=lambda result: self._install(bp, result),
            on_error=lambda msg: self.notify(f"Download failed: {msg}", level="error"),
        )

    def _install(self, bp, result) -> None:
        data, filename = result
        outcome = install(
            data,
            bp.title or filename,
            source={"id": bp.id, "title": bp.title, "author": bp.author_name, "sha256": bp.sha256},
            blueprints_dir=self.ctx.settings.blueprints_dir_override,
            provenance=self.ctx.provenance,
        )
        if outcome.status == STATUS_INSTALLED:
            level = "success"
        elif outcome.status == STATUS_ALREADY:
            level = "info"
        elif outcome.status == STATUS_BLOCKED:
            level = "warning"
        else:
            level = "error"

        toast = self.notify(outcome.message, level=level, action="Show file" if outcome.ok else None)
        if toast.action_button is not None and outcome.final_path is not None:
            path = outcome.final_path
            toast.action_button.clicked.connect(lambda: reveal_in_file_manager(path))
        self.ctx.refresh_library()
