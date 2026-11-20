"""My Blueprints page — the player's own local folder."""

from __future__ import annotations

import os

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMenu, QPushButton, QWidget

from ftn_blueprint import pretty_building_name, render_svg

from ...core.shell import open_folder, open_path, reveal_in_file_manager
from ...core.paths import trash_subdir
from ..widgets import BlueprintCard, CardGrid, DetailDrawer
from .base import View

__all__ = ["MyBlueprintsView"]


def _preview_key(
    entry,
    max_level: int | None,
    hide_walls: bool,
    *,
    show_legend: bool = True,
) -> str:
    """Cache key for a view variant, including card-vs-drawer legend state."""
    parts = ["all" if max_level is None else f"L{max_level}"]
    if hide_walls:
        parts.append("NW")
    if not show_legend:
        parts.append("NL")
    return f"{entry.path}:{entry.mtime}:{'.'.join(parts)}"


def _resolve_view(level_count: int, max_level: int, hide_walls: bool) -> tuple[int | None, bool]:
    """Collapse "top of the slider, walls on" onto the default all-levels view."""
    if max_level >= max(level_count - 1, 0) and not hide_walls:
        return (None, False)
    return (int(max_level), bool(hide_walls))


class MyBlueprintsView(View):
    """Lists every blueprint in the game folder and lets you share or tidy them."""

    page_title = "My Blueprints"
    page_subtitle = "Blueprints found in your game folder"

    upload_requested = Signal(str)

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)
        self._entries: list = []
        self._preview_cache: dict[str, str] = {}
        #: View currently shown in the drawer (``(max_level, hide_walls)``).
        self._drawer_view: tuple[int | None, bool] = (None, False)

        self.path_label = QLabel("", self)
        self.path_label.setObjectName("PathLabel")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.root.addWidget(self.path_label)

        self.scan_button = QPushButton("Rescan", self)
        self.scan_button.setObjectName("Primary")
        self.scan_button.clicked.connect(self.refresh)
        self.folder_button = QPushButton("Open folder", self)
        self.folder_button.setObjectName("Ghost")
        self.folder_button.clicked.connect(self._open_folder)
        self.actions.addWidget(self.folder_button)
        self.actions.addWidget(self.scan_button)

        self.status = QLabel("", self)
        self.status.setObjectName("PageSubtitle")
        self.root.addWidget(self.status)

        self.grid = CardGrid(card_width=300, parent=self)
        self.grid.set_empty_text(
            "No blueprints found yet.\nCreate one in-game, then press Rescan."
        )
        self.root.addWidget(self.grid, 1)

        self.drawer = DetailDrawer(self)
        self.drawer.hide()
        self.drawer.action_clicked.connect(self._on_drawer_action)
        self.drawer.view_changed.connect(self._on_drawer_view_changed)
        self.ctx.library_changed.connect(self.refresh)

    # -- lifecycle ---------------------------------------------------------
    def refresh(self) -> None:
        library = self.ctx.library
        if library is None:
            return
        self.path_label.setText(str(library.blueprints_dir))
        self.status.setText("Scanning…")
        self.ctx.runner.run(
            library.refresh,
            on_done=self._on_scanned,
            on_error=lambda msg: self.notify(f"Scan failed: {msg}", level="error"),
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.drawer.isVisible():
            self.drawer.setGeometry(QRect(self.width() - 400, 0, 400, self.height()))

    # -- results -----------------------------------------------------------
    def _on_scanned(self, entries) -> None:
        self._entries = list(entries)
        readable = [e for e in entries if e.is_readable]
        pieces = sum(e.piece_count for e in readable)
        unreadable = len(entries) - len(readable)
        summary = f"{len(entries)} blueprint(s) · {pieces:,} pieces"
        if unreadable:
            summary += f" · {unreadable} unreadable"
        self.status.setText(summary)

        cards = [self._make_card(entry) for entry in entries]
        self.grid.set_cards(cards)
        for entry in readable:
            self._render_preview(entry)

    def _make_card(self, entry) -> BlueprintCard:
        if entry.is_readable:
            meta = entry.meta
            badges = [f"{entry.piece_count:,} pieces"]
            if getattr(meta, "level_count", 1) > 1:
                badges.append(f"{meta.level_count} floors")
            badges.append(f"cost {entry.total_cost:,.0f}")
            if meta.category:
                badges.append(meta.category)
            subtitle = meta.distinct_builds and ", ".join(
                f"{count}x {pretty_building_name(bid)}" for bid, count in list(meta.distinct_builds.items())[:3]
            ) or ""
            author = ""
            if entry.provenance is not None and entry.provenance.remote_author:
                author = f"downloaded · by {entry.provenance.remote_author}"
            card = BlueprintCard(
                title=entry.name,
                subtitle=subtitle,
                badges=badges,
                author=author or entry.filename,
                primary_text="Upload",
                secondary_text="Reveal",
                payload=entry,
                parent=self.grid,
            )
            card.primary.connect(self._on_upload)
        else:
            card = BlueprintCard(
                title=entry.filename,
                subtitle=entry.error or "Not a readable blueprint",
                badges=["unreadable"],
                author="",
                primary_text=None,
                secondary_text="Reveal",
                payload=entry,
                parent=self.grid,
            )
            card.set_preview_text("This file could not be parsed")
        card.secondary.connect(self._on_reveal)
        card.activated.connect(self._on_details)
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(lambda pos, e=entry, c=card: self._context_menu(e, c, pos))
        return card

    def _render_preview(self, entry) -> None:
        key = _preview_key(entry, None, False, show_legend=False)
        cached = self._preview_cache.get(key)
        if cached:
            for card in self.grid.cards:
                if card.payload is entry:
                    card.set_preview_svg(cached)
                    break
            return
        theme = self.ctx.preview_theme()

        def done(svg: str) -> None:
            self._preview_cache[key] = svg
            for card in self.grid.cards:
                if card.payload is entry:
                    try:
                        card.set_preview_svg(svg)
                    except RuntimeError:
                        pass
                    break

        self.ctx.runner.run(
            render_svg, entry.meta, width=900, height=560, theme=theme, show_legend=False,
            on_done=done, on_error=lambda _m: None,
        )

    # -- actions -----------------------------------------------------------
    def _on_upload(self, entry) -> None:
        self.upload_requested.emit(str(entry.path))

    def _on_reveal(self, entry) -> None:
        reveal_in_file_manager(entry.path)

    def _open_folder(self) -> None:
        library = self.ctx.library
        if library is not None:
            open_folder(library.blueprints_dir)

    def _on_details(self, entry) -> None:
        self.drawer.setGeometry(QRect(self.width() - 400, 0, 400, self.height()))
        if entry.is_readable:
            meta = entry.meta
            self._drawer_view = (None, False)
            self.drawer.show_details(
                title=entry.name,
                subtitle="",
                svg=self._preview_cache.get(_preview_key(entry, None, False)),
                stats=_build_stats(meta, entry),
                description=meta.desc,
                action_text="Upload to library",
                payload=entry,
                level_count=max(int(getattr(meta, "level_count", 1) or 1), 1),
            )
            self._render_preview_for_drawer(entry, None, False)
        else:
            self.drawer.show_details(
                title=entry.filename,
                subtitle="Unreadable file",
                stats={"Error": entry.error or "unknown", "Size": f"{entry.size:,} bytes"},
                action_text=None,
                payload=entry,
            )
        self.drawer.raise_()

    def _on_drawer_view_changed(self, view) -> None:
        entry = self.drawer.payload
        if entry is None or not getattr(entry, "is_readable", False):
            return
        level_count = max(int(getattr(entry.meta, "level_count", 1) or 1), 1)
        max_level, hide_walls = _resolve_view(level_count, view[0], view[1])
        self._drawer_view = (max_level, hide_walls)
        cached = self._preview_cache.get(_preview_key(entry, max_level, hide_walls))
        if cached is not None:
            self.drawer.set_svg(cached)
            return
        self.drawer.preview.set_placeholder("Loading preview…")
        self._render_preview_for_drawer(entry, max_level, hide_walls)

    def _render_preview_for_drawer(self, entry, max_level: int | None, hide_walls: bool) -> None:
        key = _preview_key(entry, max_level, hide_walls)
        cached = self._preview_cache.get(key)
        if cached is not None:
            self.drawer.preview.set_svg(cached)
            return
        theme = self.ctx.preview_theme()

        def done(svg: str) -> None:
            self._preview_cache[key] = svg
            if (
                self.drawer.isVisible()
                and getattr(self.drawer.payload, "path", None) == entry.path
                and self._drawer_view == (max_level, hide_walls)
            ):
                self.drawer.set_svg(svg)

        self.ctx.runner.run(
            render_svg,
            entry.meta,
            theme=theme,
            max_level=max_level,
            hide_walls=hide_walls,
            on_done=done,
            on_error=lambda _m: None,
        )

    def _on_drawer_action(self, entry) -> None:
        self._on_upload(entry)

    # -- context menu ------------------------------------------------------
    def _context_menu(self, entry, card, pos) -> None:
        menu = QMenu(self)
        reveal = QAction("Reveal in folder", self)
        reveal.triggered.connect(lambda: reveal_in_file_manager(entry.path))
        menu.addAction(reveal)

        open_action = QAction("Open with default app", self)
        open_action.triggered.connect(lambda: open_path(entry.path))
        menu.addAction(open_action)

        copy = QAction("Copy full path", self)
        copy.triggered.connect(lambda: _copy_to_clipboard(str(entry.path)))
        menu.addAction(copy)

        menu.addSeparator()
        trash = QAction("Move to game trash", self)
        trash.triggered.connect(lambda: self._move_to_trash(entry))
        menu.addAction(trash)

        if entry.is_readable:
            menu.addSeparator()
            upload = QAction("Upload to library…", self)
            upload.triggered.connect(lambda: self._on_upload(entry))
            menu.addAction(upload)

        menu.exec(card.mapToGlobal(pos))

    def _move_to_trash(self, entry) -> None:
        library = self.ctx.library
        if library is None:
            return
        destination_dir = trash_subdir(library.blueprints_dir)
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / entry.path.name
            index = 2
            while destination.exists():
                destination = destination_dir / f"{entry.path.stem} ({index}){entry.path.suffix}"
                index += 1
            os.replace(entry.path, destination)
        except OSError as exc:
            self.notify(f"Could not move to trash: {exc}", level="error")
            return
        self.notify(f"Moved “{entry.filename}” to the game's trash.", level="info")
        self.refresh()


def _format_composition(distinct_builds: dict[str, int], *, limit: int = 8) -> str:
    """Render the distinct_builds dict as a multi-line "N x Pretty Name" list."""
    if not distinct_builds:
        return "—"
    lines = [f"{count} x {pretty_building_name(bid)}" for bid, count in distinct_builds.items()]
    shown = lines[:limit]
    if len(lines) > limit:
        shown.append(f"and {len(lines) - limit} more kind(s)")
    return "\n".join(shown)


def _build_stats(meta, entry) -> dict[str, str]:
    """Build the detail-drawer stats for a readable local blueprint.

    Drops the noisy fields (file name, icon, modified time, size, SHA-256) and
    surfaces the composition (which buildings and how many) instead.
    """
    stats: dict[str, str] = {
        "Pieces": f"{entry.piece_count:,}",
        "Floors": f"{getattr(meta, 'level_count', 1)}",
        "Total cost": f"{entry.total_cost:,.0f}",
        "Category": meta.category or "—",
    }
    if meta.tags:
        stats["Tags"] = ", ".join(meta.tags)
    composition = _format_composition(meta.distinct_builds or {})
    if composition != "—":
        stats["Composition"] = composition
    return stats


def _copy_to_clipboard(text: str) -> None:
    from PySide6.QtGui import QGuiApplication

    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)
