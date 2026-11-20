"""Renders the shared SVG preview (or a direct fallback) inside a widget."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QWidget

__all__ = ["PreviewCanvas"]

#: Padding (px) kept between the rendered SVG and the widget edges so the
#: preview never sits flush against neighbouring elements (e.g. the divider
#: line below a card preview).
INNER_PAD = 14.0


class PreviewCanvas(QWidget):
    """Draws a blueprint preview.

    Feed it an SVG string (from :func:`ftn_blueprint.render_svg`, either rendered
    locally or fetched from the server) and it rasterises it with
    ``QSvgRenderer``. When an interactive canvas is requested the user can zoom
    with the wheel and pan by dragging.
    """

    clicked = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        interactive: bool = False,
        background: str | None = None,
        placeholder: str = "No preview available",
    ) -> None:
        super().__init__(parent)
        self._renderer: QSvgRenderer | None = None
        self._image: QPixmap | None = None
        self._placeholder = placeholder
        self._background = QColor(background) if background else None
        self._interactive = interactive
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._dragging = False
        self._drag_moved = False
        self._press_pos = QPointF()
        self._last_pos = QPointF()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(140, 90)
        if interactive:
            self.setCursor(Qt.OpenHandCursor)

    # -- content -----------------------------------------------------------
    def set_svg(self, svg: str | None) -> None:
        if not svg:
            self.clear()
            return
        self._renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        self._image = None
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        """Show a raster image (e.g. a screenshot) instead of an SVG preview."""
        if pixmap is None or pixmap.isNull():
            self.clear()
            return
        self._renderer = None
        self._image = pixmap
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def set_meta(
        self,
        meta,
        *,
        width: int = 900,
        height: int = 560,
        theme: str = "dark",
        max_level: int | None = None,
        hide_walls: bool = False,
    ) -> None:
        """Render a parsed blueprint locally (used for local files)."""
        from ftn_blueprint import render_svg

        try:
            svg = render_svg(
                meta,
                width=width,
                height=height,
                theme=theme,
                author=None,
                max_level=max_level,
                hide_walls=hide_walls,
            )
        except Exception:  # noqa: BLE001 - never let a bad blueprint break the UI
            svg = None
        self.set_svg(svg)

    def clear(self) -> None:
        self._renderer = None
        self._image = None
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.clear()

    def has_preview(self) -> bool:
        if self._image is not None and not self._image.isNull():
            return True
        return self._renderer is not None and self._renderer.isValid()

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = self.rect()
        # Clip to our own bounds so the SVG can never bleed into neighbouring
        # widgets (e.g. the divider line below the preview in a card).
        painter.setClipRect(rect)
        painter.fillRect(rect, self._background or QColor("#00000000"))

        if not self.has_preview():
            painter.setPen(QPen(QColor(140, 150, 165)))
            painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, self._placeholder)
            return

        painter.save()
        painter.translate(rect.center())
        painter.translate(self._pan)
        painter.scale(self._zoom, self._zoom)
        painter.translate(-rect.center())

        # Leave a small inner margin so the preview never touches the widget
        # edges (and neighbouring elements like the divider below a card).
        inner = QRectF(rect).adjusted(INNER_PAD, INNER_PAD, -INNER_PAD, -INNER_PAD)
        if self._image is not None and not self._image.isNull():
            target = _fit(inner, float(self._image.width()), float(self._image.height()))
            painter.drawPixmap(target, self._image, QRectF(self._image.rect()))
        else:
            size = self._renderer.defaultSize()
            if size.width() <= 0 or size.height() <= 0:
                size = rect.size()
            target = _fit(inner, float(size.width()), float(size.height()))
            self._renderer.render(painter, target)
        painter.restore()

    # -- interaction -------------------------------------------------------
    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        if not self._interactive:
            return
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.2, min(self._zoom * factor, 8.0))
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._interactive:
            self._dragging = True
            self._drag_moved = False
            self._press_pos = event.position()
            self._last_pos = event.position()
            self.setCursor(Qt.ClosedHandCursor)
        else:
            self.clicked.emit()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._interactive and self._dragging:
            delta = event.position() - self._last_pos
            self._last_pos = event.position()
            if (event.position() - self._press_pos).manhattanLength() > 4:
                self._drag_moved = True
            self._pan += delta
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._interactive:
            was_click = not self._drag_moved
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            if was_click:
                self.clicked.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._interactive:
            self._zoom = 1.0
            self._pan = QPointF(0.0, 0.0)
            self.update()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()


def _fit(bounds: QRectF, content_w: float, content_h: float) -> QRectF:
    """Aspect-preserving fit of ``content`` inside ``bounds``."""
    if content_w <= 0 or content_h <= 0:
        return bounds
    scale = min(bounds.width() / content_w, bounds.height() / content_h)
    width = content_w * scale
    height = content_h * scale
    x = bounds.x() + (bounds.width() - width) / 2.0
    y = bounds.y() + (bounds.height() - height) / 2.0
    return QRectF(x, y, width, height)
