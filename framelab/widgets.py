"""Qt widgets used by FrameLab."""

from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QSize, Signal

from .mpl_canvas import FigureCanvasQTAgg
from .mpl_config import ensure_matplotlib_config_dir
from .mpl_layout import adjust_single_axes_layout

ensure_matplotlib_config_dir()

try:
    from matplotlib.figure import Figure
    from matplotlib import pyplot as plt
    from matplotlib.patches import Rectangle

    MATPLOTLIB_AVAILABLE = FigureCanvasQTAgg is not None
    try:
        plt.style.use("framelab/assets/LabReport.mplstyle")
    except Exception:
        pass
except Exception:
    Figure = None  # type: ignore[assignment]
    Rectangle = None  # type: ignore[assignment]
    MATPLOTLIB_AVAILABLE = False


class MetricsTableView(qtw.QTableView):
    """Table view with spreadsheet-like copy behavior."""

    def __init__(self, parent: Optional[qtw.QWidget] = None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def keyPressEvent(
        self,
        event: QtGui.QKeyEvent,
    ) -> None:  # type: ignore[override]
        """Handle keyboard shortcuts for table interactions."""
        if event.matches(QtGui.QKeySequence.Copy):
            self.copy_selection_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection_to_clipboard(self) -> None:
        """Copy selected cells to clipboard as tab-separated text."""
        model = self.model()
        if model is None:
            return
        indexes = self.selectedIndexes()
        if not indexes:
            return

        sorted_indexes = sorted(
            indexes,
            key=lambda idx: (idx.row(), idx.column()),
        )
        rows = sorted({idx.row() for idx in sorted_indexes})
        cols = sorted({idx.column() for idx in sorted_indexes})
        row_to_pos = {row: i for i, row in enumerate(rows)}
        col_to_pos = {col: i for i, col in enumerate(cols)}
        grid = [["" for _ in cols] for _ in rows]

        for idx in sorted_indexes:
            value = model.data(idx, Qt.DisplayRole)
            grid[row_to_pos[idx.row()]][col_to_pos[idx.column()]] = (
                "" if value is None else str(value)
            )

        text = "\n".join("\t".join(row) for row in grid)
        qtw.QApplication.clipboard().setText(text)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = qtw.QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(bool(self.selectedIndexes()))
        triggered = menu.exec(self.viewport().mapToGlobal(pos))
        if triggered == copy_action:
            self.copy_selection_to_clipboard()


_CURSOR_CACHE: dict[str, QtGui.QCursor] = {}


def _stroke_line(
    painter: QtGui.QPainter,
    start: QPoint,
    end: QPoint,
) -> None:
    painter.setPen(
        QtGui.QPen(
            Qt.black,
            5,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        ),
    )
    painter.drawLine(start, end)
    painter.setPen(
        QtGui.QPen(
            Qt.white,
            2,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        ),
    )
    painter.drawLine(start, end)


def _stroke_polygon(
    painter: QtGui.QPainter,
    points: list[QPoint],
) -> None:
    polygon = QtGui.QPolygon(points)
    painter.setPen(
        QtGui.QPen(
            Qt.black,
            4,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        ),
    )
    painter.setBrush(Qt.black)
    painter.drawPolygon(polygon)
    painter.setPen(
        QtGui.QPen(
            Qt.white,
            1,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        ),
    )
    painter.setBrush(Qt.white)
    painter.drawPolygon(polygon)


def _cursor_pixmap(size: int = 30) -> QtGui.QPixmap:
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    return pixmap


def _large_cross_cursor() -> QtGui.QCursor:
    cached = _CURSOR_CACHE.get("cross")
    if cached is not None:
        return cached
    size = 30
    center = size // 2
    pixmap = _cursor_pixmap(size)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    _stroke_line(painter, QPoint(center, 4), QPoint(center, size - 5))
    _stroke_line(painter, QPoint(4, center), QPoint(size - 5, center))
    painter.end()
    cursor = QtGui.QCursor(pixmap, center, center)
    _CURSOR_CACHE["cross"] = cursor
    return cursor


def _large_move_cursor() -> QtGui.QCursor:
    cached = _CURSOR_CACHE.get("move")
    if cached is not None:
        return cached
    size = 30
    center = size // 2
    pixmap = _cursor_pixmap(size)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    _stroke_line(painter, QPoint(center, 5), QPoint(center, size - 6))
    _stroke_line(painter, QPoint(5, center), QPoint(size - 6, center))
    _stroke_polygon(
        painter,
        [QPoint(center, 2), QPoint(center - 4, 8), QPoint(center + 4, 8)],
    )
    _stroke_polygon(
        painter,
        [
            QPoint(size - 3, center),
            QPoint(size - 9, center - 4),
            QPoint(size - 9, center + 4),
        ],
    )
    _stroke_polygon(
        painter,
        [
            QPoint(center, size - 3),
            QPoint(center - 4, size - 9),
            QPoint(center + 4, size - 9),
        ],
    )
    _stroke_polygon(
        painter,
        [QPoint(2, center), QPoint(8, center - 4), QPoint(8, center + 4)],
    )
    painter.end()
    cursor = QtGui.QCursor(pixmap, center, center)
    _CURSOR_CACHE["move"] = cursor
    return cursor


def _large_split_cursor(orientation: Qt.Orientation) -> QtGui.QCursor:
    cache_key = "split_h" if orientation == Qt.Horizontal else "split_v"
    cached = _CURSOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    size = 30
    center = size // 2
    pixmap = _cursor_pixmap(size)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    if orientation == Qt.Horizontal:
        _stroke_line(painter, QPoint(center, 6), QPoint(center, size - 7))
        _stroke_polygon(
            painter,
            [QPoint(3, center), QPoint(10, center - 4), QPoint(10, center + 4)],
        )
        _stroke_polygon(
            painter,
            [
                QPoint(size - 4, center),
                QPoint(size - 11, center - 4),
                QPoint(size - 11, center + 4),
            ],
        )
    else:
        _stroke_line(painter, QPoint(6, center), QPoint(size - 7, center))
        _stroke_polygon(
            painter,
            [QPoint(center, 3), QPoint(center - 4, 10), QPoint(center + 4, 10)],
        )
        _stroke_polygon(
            painter,
            [
                QPoint(center, size - 4),
                QPoint(center - 4, size - 11),
                QPoint(center + 4, size - 11),
            ],
        )
    painter.end()
    cursor = QtGui.QCursor(pixmap, center, center)
    _CURSOR_CACHE[cache_key] = cursor
    return cursor


class _HeaderResizeCursorFilter(QtCore.QObject):
    """Show a larger resize cursor near header section boundaries."""

    def __init__(self, header: qtw.QHeaderView, *, margin: int = 5) -> None:
        super().__init__(header)
        self._header = header
        self._margin = max(3, int(margin))

    def _viewport(self) -> qtw.QWidget | None:
        """Return the live header viewport, if the header still exists."""
        try:
            return self._header.viewport()
        except RuntimeError:
            return None

    def _is_near_resize_handle(self, pos: QPoint) -> bool:
        try:
            if self._header.count() <= 0:
                return False
            logical = self._header.logicalIndexAt(pos)
            if logical < 0:
                return False
            coordinate = (
                pos.x()
                if self._header.orientation() == Qt.Horizontal
                else pos.y()
            )
            start = self._header.sectionPosition(logical)
            size = self._header.sectionSize(logical)
        except RuntimeError:
            return False
        if size <= 0:
            return False
        local = coordinate - start
        if logical > 0 and 0 <= local <= self._margin:
            return True
        return 0 <= (size - local) <= self._margin

    def eventFilter(
        self,
        watched: QtCore.QObject,
        event: QtCore.QEvent,
    ) -> bool:
        viewport = self._viewport()
        if viewport is None:
            return False
        if watched is not viewport:
            return super().eventFilter(watched, event)
        if event.type() == QtCore.QEvent.Type.Leave:
            viewport.unsetCursor()
            return False
        if event.type() != QtCore.QEvent.Type.MouseMove:
            return super().eventFilter(watched, event)
        mouse_event = event if isinstance(event, QtGui.QMouseEvent) else None
        pos = (
            mouse_event.position().toPoint()
            if mouse_event is not None
            else QPoint()
        )
        if self._is_near_resize_handle(pos):
            try:
                orientation = self._header.orientation()
            except RuntimeError:
                return False
            viewport.setCursor(_large_split_cursor(orientation))
        else:
            viewport.unsetCursor()
        return False


def install_large_header_resize_cursor(
    header: qtw.QHeaderView,
    *,
    margin: int = 5,
) -> None:
    """Install a larger resize cursor on one table/tree header viewport."""
    filter_obj = getattr(header, "_large_resize_cursor_filter", None)
    if isinstance(filter_obj, _HeaderResizeCursorFilter):
        return
    filter_obj = _HeaderResizeCursorFilter(header, margin=margin)
    setattr(header, "_large_resize_cursor_filter", filter_obj)
    header.viewport().installEventFilter(filter_obj)


def install_large_splitter_handle_cursors(
    splitter: qtw.QSplitter,
    *,
    handle_width: int = 12,
) -> None:
    """Increase splitter hit area and apply a larger resize cursor."""
    splitter.setHandleWidth(max(handle_width, splitter.handleWidth()))
    cursor = _large_split_cursor(splitter.orientation())
    for index in range(1, splitter.count()):
        handle = splitter.handle(index)
        if handle is not None:
            handle.setCursor(cursor)


class LeftElideItemDelegate(qtw.QStyledItemDelegate):
    """Delegate that elides long text from the left side."""

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        """Render cell text with left-side elision."""
        opt = qtw.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.textElideMode = Qt.ElideLeft
        style = opt.widget.style() if opt.widget else qtw.QApplication.style()
        style.drawControl(qtw.QStyle.CE_ItemViewItem, opt, painter, opt.widget)


class ImagePreviewLabel(qtw.QLabel):
    """Scales the current image and supports optional ROI drawing."""

    roiSelected = Signal(object)

    def __init__(self, parent: Optional[qtw.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(
            qtw.QSizePolicy.Expanding,
            qtw.QSizePolicy.Expanding,
        )
        self.setMinimumSize(320, 260)
        self.setObjectName("ImagePreview")
        self._source_pixmap: Optional[QtGui.QPixmap] = None
        self._rgb_buffer: Optional[np.ndarray] = None
        self._image_size: Optional[tuple[int, int]] = None
        self._intensity_image: Optional[np.ndarray] = None
        self._roi_mode_enabled = False
        self._roi_rect: Optional[tuple[int, int, int, int]] = None
        self._drag_start: Optional[QPoint] = None
        self._drag_current: Optional[QPoint] = None
        self._hover_text: Optional[str] = None
        self._hover_point: Optional[QPoint] = None
        self._zoom_factor = 1.0
        self._pan_offset = QPointF(0.0, 0.0)
        self._is_panning = False
        self._pan_last_pos: Optional[QPoint] = None
        self._is_moving_roi = False
        self._roi_move_anchor_point: Optional[QPoint] = None
        self._roi_move_anchor_rect: Optional[tuple[int, int, int, int]] = None
        self._hover_roi_hit = "none"
        self._roi_hit_margin_px = 10
        self._min_zoom = 1.0
        self._max_zoom = 20.0
        self.setMouseTracking(True)
        self.clear_image()

    def clear_image(self) -> None:
        """Clear preview content and reset interaction state."""
        self._source_pixmap = None
        self._rgb_buffer = None
        self._image_size = None
        self._intensity_image = None
        self._roi_rect = None
        self._drag_start = None
        self._drag_current = None
        self._hover_text = None
        self._hover_point = None
        self._is_panning = False
        self._pan_last_pos = None
        self._is_moving_roi = False
        self._roi_move_anchor_point = None
        self._roi_move_anchor_rect = None
        self._hover_roi_hit = "none"
        self.reset_view()
        self.setText("No image selected.")

    def set_rgb_image(
        self,
        rgb: np.ndarray,
        *,
        image_size: tuple[int, int] | None = None,
    ) -> None:
        """Set RGB image data used for on-screen rendering."""
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            self.clear_image()
            return

        h, w, _ = rgb.shape
        bytes_per_line = 3 * w
        self._rgb_buffer = np.ascontiguousarray(rgb, dtype=np.uint8)
        image = QtGui.QImage(
            self._rgb_buffer.data,
            w,
            h,
            bytes_per_line,
            QtGui.QImage.Format_RGB888,
        )
        self._source_pixmap = QtGui.QPixmap.fromImage(image)
        if image_size is None:
            self._image_size = (w, h)
        else:
            img_w, img_h = image_size
            self._image_size = (max(1, int(img_w)), max(1, int(img_h)))
        self.setText("")
        self._clamp_pan_offset()
        self._update_cursor()
        self.update()

    def set_intensity_image(self, image: Optional[np.ndarray]) -> None:
        """Set scalar image values used for hover/intensity reporting."""
        if image is None:
            self._intensity_image = None
            self._hover_text = None
            self._hover_point = None
            self.update()
            return
        arr = np.asarray(image)
        self._intensity_image = arr if arr.ndim == 2 else None
        self.update()

    def set_roi_mode(self, enabled: bool) -> None:
        """Enable or disable ROI-drawing mode."""
        self._roi_mode_enabled = enabled
        if not enabled:
            self._drag_start = None
            self._drag_current = None
            self._is_moving_roi = False
            self._roi_move_anchor_point = None
            self._roi_move_anchor_rect = None
            self._hover_roi_hit = "none"
        self._update_cursor()
        self.update()

    def set_roi_rect(self, rect: Optional[tuple[int, int, int, int]]) -> None:
        """Apply an ROI rectangle expressed in image coordinates."""
        self._roi_rect = rect
        if rect is None:
            self._is_moving_roi = False
            self._roi_move_anchor_point = None
            self._roi_move_anchor_rect = None
            self._hover_roi_hit = "none"
            self._update_cursor()
        self.update()

    def reset_view(self) -> None:
        """Reset zoom and pan to default fit-to-view state."""
        self._zoom_factor = 1.0
        self._pan_offset = QPointF(0.0, 0.0)
        self._clamp_pan_offset()
        self._update_cursor()
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Re-clamp pan offset after resize events."""
        super().resizeEvent(event)
        self._clamp_pan_offset()
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Render image, ROI overlays, and hover annotations."""
        super().paintEvent(event)
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return

        target_rect = self._scaled_target_rect()
        if (
            target_rect.isNull()
            or target_rect.width() <= 0
            or target_rect.height() <= 0
        ):
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(
            target_rect,
            self._source_pixmap,
            QRectF(self._source_pixmap.rect()),
        )

        if self._roi_mode_enabled:
            roi_rect = self._roi_rect
            if self._drag_start is not None and self._drag_current is not None:
                roi_rect = self._normalized_rect(
                    self._drag_start,
                    self._drag_current,
                )
            if roi_rect is not None:
                widget_rect = self._image_rect_to_widget_rect(roi_rect)
                if widget_rect is not None:
                    painter.fillRect(
                        widget_rect,
                        QtGui.QColor(37, 99, 235, 55),
                    )
                    painter.setPen(
                        QtGui.QPen(QtGui.QColor(37, 99, 235, 220), 2),
                    )
                    painter.drawRect(widget_rect)

        if self._hover_text and self._hover_point is not None:
            self._draw_hover_label(painter)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """Start ROI drawing or panning based on active interaction mode."""
        if self._source_pixmap is None or self._source_pixmap.isNull():
            super().mousePressEvent(event)
            return

        if (
            event.button() == Qt.LeftButton
            and self._roi_mode_enabled
        ):
            pos = event.position().toPoint()
            hit_region = self._roi_hit_region(pos)
            self._hover_roi_hit = hit_region
            if hit_region != "none" and self._roi_rect is not None:
                image_point = self._widget_point_to_image_point(
                    pos,
                    clamp_to_bounds=True,
                )
                if image_point is not None:
                    self._is_moving_roi = True
                    self._roi_move_anchor_point = image_point
                    self._roi_move_anchor_rect = self._roi_rect
                    self._drag_start = None
                    self._drag_current = None
                    self._update_cursor()
                    self._update_hover_label(pos)
                    self.update()
                    event.accept()
                    return

            image_point = self._widget_point_to_image_point(
                pos,
                clamp_to_bounds=False,
            )
            if image_point is not None:
                self._drag_start = image_point
                self._drag_current = image_point
                self._is_moving_roi = False
                self._roi_move_anchor_point = None
                self._roi_move_anchor_rect = None
                self.update()
                event.accept()
                return

        if (
            event.button() == Qt.MiddleButton
            or (event.button() == Qt.LeftButton and not self._roi_mode_enabled)
        ):
            self._is_panning = True
            self._pan_last_pos = event.position().toPoint()
            self._update_cursor()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        """Update ROI drag, pan, and hover states while moving mouse."""
        pos = event.position().toPoint()
        if (
            self._is_moving_roi
            and self._roi_move_anchor_point is not None
            and self._roi_move_anchor_rect is not None
        ):
            image_point = self._widget_point_to_image_point(
                pos,
                clamp_to_bounds=True,
            )
            if image_point is not None:
                moved_rect = self._translate_roi_rect(image_point)
                if moved_rect is not None:
                    self._roi_rect = moved_rect
            self._hover_roi_hit = self._roi_hit_region(pos)
            self._update_cursor()
            self._update_hover_label(pos)
            self.update()
            event.accept()
            return

        if self._drag_start is not None:
            image_point = self._widget_point_to_image_point(
                pos,
                clamp_to_bounds=True,
            )
            if image_point is not None:
                self._drag_current = image_point
                self._hover_roi_hit = "none"
                self._update_cursor()
                self._update_hover_label(pos)
                self.update()
                event.accept()
                return

        if self._is_panning and self._pan_last_pos is not None:
            delta = pos - self._pan_last_pos
            self._pan_last_pos = pos
            self._pan_offset += QPointF(float(delta.x()), float(delta.y()))
            self._clamp_pan_offset()
            self._hover_text = None
            self._hover_point = None
            if self._roi_mode_enabled:
                self._hover_roi_hit = self._roi_hit_region(pos)
            self._update_cursor()
            self.update()
            event.accept()
            return

        if self._roi_mode_enabled:
            self._hover_roi_hit = self._roi_hit_region(pos)
            self._update_cursor()
        self._update_hover_label(pos)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """Finalize ROI selection or stop panning on button release."""
        if event.button() == Qt.LeftButton and self._is_moving_roi:
            self._is_moving_roi = False
            self._roi_move_anchor_point = None
            self._roi_move_anchor_rect = None
            if self._roi_rect is not None:
                self.roiSelected.emit(self._roi_rect)
            pos = event.position().toPoint()
            self._hover_roi_hit = self._roi_hit_region(pos)
            self._update_cursor()
            self._update_hover_label(pos)
            self.update()
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._drag_start is not None:
            image_point = self._widget_point_to_image_point(
                event.position().toPoint(),
                clamp_to_bounds=True,
            )
            if image_point is not None:
                self._drag_current = image_point

            if self._drag_current is not None:
                roi_rect = self._normalized_rect(
                    self._drag_start,
                    self._drag_current,
                )
                self._roi_rect = roi_rect
                self.roiSelected.emit(roi_rect)

            self._drag_start = None
            self._drag_current = None
            pos = event.position().toPoint()
            self._hover_roi_hit = self._roi_hit_region(pos)
            self._update_cursor()
            self._update_hover_label(pos)
            self.update()
            event.accept()
            return

        if (
            self._is_panning
            and event.button() in (Qt.LeftButton, Qt.MiddleButton)
        ):
            self._is_panning = False
            self._pan_last_pos = None
            pos = event.position().toPoint()
            if self._roi_mode_enabled:
                self._hover_roi_hit = self._roi_hit_region(pos)
            self._update_cursor()
            self._update_hover_label(pos)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        """Reset view on double-click."""
        if event.button() == Qt.LeftButton and self._source_pixmap is not None:
            self.reset_view()
            self._update_hover_label(event.position().toPoint())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """Zoom in/out around pointer location."""
        if self._source_pixmap is None or self._source_pixmap.isNull():
            super().wheelEvent(event)
            return

        angle = event.angleDelta().y()
        if angle == 0:
            super().wheelEvent(event)
            return

        old_zoom = self._zoom_factor
        step = 1.15 if angle > 0 else 1.0 / 1.15
        new_zoom = min(self._max_zoom, max(self._min_zoom, old_zoom * step))
        if abs(new_zoom - old_zoom) < 1e-6:
            event.accept()
            return

        anchor_pos = event.position()
        anchor = self._widget_point_to_image_fraction(anchor_pos)
        if anchor is None:
            anchor = (0.5, 0.5)

        self._zoom_factor = new_zoom
        self._set_pan_for_anchor(anchor_pos, anchor[0], anchor[1])
        self._clamp_pan_offset()
        self._update_hover_label(event.position().toPoint())
        self._update_cursor()
        self.update()
        event.accept()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        """Clear hover annotation when pointer leaves widget area."""
        self._hover_text = None
        self._hover_point = None
        self._hover_roi_hit = "none"
        self._update_cursor()
        self.update()
        super().leaveEvent(event)

    def _fit_size(self) -> QSize:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return QSize()
        contents = self.contentsRect()
        return self._source_pixmap.size().scaled(
            contents.size(),
            Qt.KeepAspectRatio,
        )

    def _scaled_target_rect(self) -> QRectF:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return QRectF()

        fit_size = self._fit_size()
        if fit_size.width() <= 0 or fit_size.height() <= 0:
            return QRectF()

        contents = self.contentsRect()
        width = float(fit_size.width()) * self._zoom_factor
        height = float(fit_size.height()) * self._zoom_factor
        cx = (
            float(contents.x())
            + float(contents.width()) / 2.0
            + float(self._pan_offset.x())
        )
        cy = (
            float(contents.y())
            + float(contents.height()) / 2.0
            + float(self._pan_offset.y())
        )
        return QRectF(cx - width / 2.0, cy - height / 2.0, width, height)

    def _widget_point_to_image_fraction(
        self,
        point: QPointF,
    ) -> Optional[tuple[float, float]]:
        target = self._scaled_target_rect()
        if target.isNull() or target.width() <= 0 or target.height() <= 0:
            return None
        if not target.contains(point):
            return None

        fx = (point.x() - target.left()) / target.width()
        fy = (point.y() - target.top()) / target.height()
        return (
            min(max(float(fx), 0.0), 1.0),
            min(max(float(fy), 0.0), 1.0),
        )

    def _set_pan_for_anchor(
        self,
        anchor: QPointF,
        fx: float,
        fy: float,
    ) -> None:
        fit_size = self._fit_size()
        if fit_size.width() <= 0 or fit_size.height() <= 0:
            self._pan_offset = QPointF(0.0, 0.0)
            return

        contents = self.contentsRect()
        width = float(fit_size.width()) * self._zoom_factor
        height = float(fit_size.height()) * self._zoom_factor
        left = float(anchor.x()) - fx * width
        top = float(anchor.y()) - fy * height
        cx = left + width / 2.0
        cy = top + height / 2.0
        self._pan_offset = QPointF(
            cx - (float(contents.x()) + float(contents.width()) / 2.0),
            cy - (float(contents.y()) + float(contents.height()) / 2.0),
        )

    def _clamp_pan_offset(self) -> None:
        fit_size = self._fit_size()
        if fit_size.width() <= 0 or fit_size.height() <= 0:
            self._pan_offset = QPointF(0.0, 0.0)
            return

        contents = self.contentsRect()
        width = float(fit_size.width()) * self._zoom_factor
        height = float(fit_size.height()) * self._zoom_factor
        max_x = max(0.0, (width - float(contents.width())) / 2.0)
        max_y = max(0.0, (height - float(contents.height())) / 2.0)
        self._pan_offset = QPointF(
            min(max(float(self._pan_offset.x()), -max_x), max_x),
            min(max(float(self._pan_offset.y()), -max_y), max_y),
        )

    def _update_cursor(self) -> None:
        if self._is_panning or self._is_moving_roi:
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self._roi_mode_enabled and self._source_pixmap is not None:
            if (
                self._roi_rect is not None
                and self._hover_roi_hit in {"inside", "edge"}
            ):
                self.setCursor(_large_move_cursor())
                return
            self.setCursor(_large_cross_cursor())
            return
        if self._source_pixmap is not None:
            self.setCursor(Qt.OpenHandCursor)
            return
        self.setCursor(Qt.ArrowCursor)

    def _update_hover_label(self, pos: QPoint) -> None:
        prev_text = self._hover_text
        prev_point = self._hover_point

        if self._source_pixmap is None or self._intensity_image is None:
            self._hover_text = None
            self._hover_point = None
            if prev_text is not None or prev_point is not None:
                self.update()
            return

        p = self._widget_point_to_image_point(pos, clamp_to_bounds=False)
        if p is None:
            self._hover_text = None
            self._hover_point = None
            if prev_text is not None or prev_point is not None:
                self.update()
            return

        x = int(p.x())
        y = int(p.y())
        h, w = self._intensity_image.shape
        if not (0 <= x < w and 0 <= y < h):
            self._hover_text = None
            self._hover_point = None
            if prev_text is not None or prev_point is not None:
                self.update()
            return

        value = self._intensity_image[y, x]
        if np.issubdtype(np.asarray(value).dtype, np.floating):
            value_txt = f"{float(value):.3f}"
        else:
            value_txt = str(int(value))

        self._hover_text = f"x={x}, y={y}, I={value_txt}"
        self._hover_point = pos
        if self._hover_text != prev_text or self._hover_point != prev_point:
            self.update()

    def _draw_hover_label(self, painter: QtGui.QPainter) -> None:
        if self._hover_text is None or self._hover_point is None:
            return

        fm = painter.fontMetrics()
        text_rect = fm.boundingRect(self._hover_text)
        pad_x = 8
        pad_y = 5
        x = self._hover_point.x() + 14
        y = self._hover_point.y() + 16
        box = QRect(
            x,
            y,
            text_rect.width() + pad_x * 2,
            text_rect.height() + pad_y * 2,
        )

        margin = 6
        if box.right() > self.width() - margin:
            box.moveLeft(self._hover_point.x() - box.width() - 14)
        if box.left() < margin:
            box.moveLeft(margin)
        if box.bottom() > self.height() - margin:
            box.moveTop(self._hover_point.y() - box.height() - 14)
        if box.top() < margin:
            box.moveTop(margin)

        win_color = self.palette().color(QtGui.QPalette.Window)
        dark_bg = win_color.lightness() < 128
        bg_color = (
            QtGui.QColor(15, 23, 42, 225)
            if dark_bg
            else QtGui.QColor(255, 255, 255, 235)
        )
        fg_color = (
            QtGui.QColor(241, 245, 249)
            if dark_bg
            else QtGui.QColor(15, 23, 42)
        )
        border_color = QtGui.QColor(59, 130, 246, 205)

        painter.setPen(QtGui.QPen(border_color, 1))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(fg_color)
        painter.drawText(
            box.adjusted(pad_x, pad_y, -pad_x, -pad_y),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._hover_text,
        )

    def _widget_point_to_image_point(
        self,
        point: QPoint,
        clamp_to_bounds: bool,
    ) -> Optional[QPoint]:
        if self._image_size is None:
            return None
        target = self._scaled_target_rect()
        if target.isNull() or target.width() <= 0 or target.height() <= 0:
            return None

        x = float(point.x())
        y = float(point.y())
        tx0 = target.left()
        ty0 = target.top()
        tx1 = target.left() + target.width()
        ty1 = target.top() + target.height()

        if clamp_to_bounds:
            x = min(max(x, tx0), tx1)
            y = min(max(y, ty0), ty1)
        elif not target.contains(QPointF(float(point.x()), float(point.y()))):
            return None

        rel_x = (x - tx0) / target.width()
        rel_y = (y - ty0) / target.height()
        img_w, img_h = self._image_size
        img_x = int(rel_x * img_w)
        img_y = int(rel_y * img_h)
        img_x = min(max(img_x, 0), img_w - 1)
        img_y = min(max(img_y, 0), img_h - 1)
        return QPoint(img_x, img_y)

    def _normalized_rect(
        self,
        p0: QPoint,
        p1: QPoint,
    ) -> tuple[int, int, int, int]:
        img_w, img_h = self._image_size or (1, 1)
        x0 = min(p0.x(), p1.x())
        y0 = min(p0.y(), p1.y())
        x1 = max(p0.x(), p1.x()) + 1
        y1 = max(p0.y(), p1.y()) + 1
        x0 = min(max(x0, 0), img_w - 1)
        y0 = min(max(y0, 0), img_h - 1)
        x1 = min(max(x1, x0 + 1), img_w)
        y1 = min(max(y1, y0 + 1), img_h)
        return (x0, y0, x1, y1)

    def _image_rect_to_widget_rect(
        self,
        rect: tuple[int, int, int, int],
    ) -> Optional[QRect]:
        if self._image_size is None:
            return None
        target = self._scaled_target_rect()
        if target.isNull() or target.width() <= 0 or target.height() <= 0:
            return None

        img_w, img_h = self._image_size
        x0, y0, x1, y1 = rect
        wx0 = target.left() + (float(x0) * target.width() / float(img_w))
        wy0 = target.top() + (float(y0) * target.height() / float(img_h))
        wx1 = target.left() + (float(x1) * target.width() / float(img_w))
        wy1 = target.top() + (float(y1) * target.height() / float(img_h))
        left = int(round(wx0))
        top = int(round(wy0))
        right = int(round(wx1))
        bottom = int(round(wy1))
        return QRect(
            left,
            top,
            max(1, right - left),
            max(1, bottom - top),
        )

    def _roi_hit_region(self, pos: QPoint) -> str:
        """Return whether pointer is over ROI edge/inside, or outside."""
        if not self._roi_mode_enabled or self._roi_rect is None:
            return "none"
        widget_rect = self._image_rect_to_widget_rect(self._roi_rect)
        if widget_rect is None or not widget_rect.contains(pos):
            return "none"
        inner = widget_rect.adjusted(
            self._roi_hit_margin_px,
            self._roi_hit_margin_px,
            -self._roi_hit_margin_px,
            -self._roi_hit_margin_px,
        )
        if inner.width() > 0 and inner.height() > 0 and inner.contains(pos):
            return "inside"
        return "edge"

    def _translate_roi_rect(
        self,
        image_point: QPoint,
    ) -> Optional[tuple[int, int, int, int]]:
        """Translate ROI rectangle while keeping it inside image bounds."""
        if (
            self._image_size is None
            or self._roi_move_anchor_point is None
            or self._roi_move_anchor_rect is None
        ):
            return None

        img_w, img_h = self._image_size
        x0, y0, x1, y1 = self._roi_move_anchor_rect
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        dx = image_point.x() - self._roi_move_anchor_point.x()
        dy = image_point.y() - self._roi_move_anchor_point.y()

        new_x0 = x0 + dx
        new_y0 = y0 + dy
        max_x0 = max(0, img_w - width)
        max_y0 = max(0, img_h - height)
        new_x0 = min(max(new_x0, 0), max_x0)
        new_y0 = min(max(new_y0, 0), max_y0)
        return (new_x0, new_y0, new_x0 + width, new_y0 + height)


class HistogramWidget(qtw.QWidget):
    """Displays histogram of pixel intensity occurrences using matplotlib."""

    _APPROXIMATE_SAMPLE_LIMIT = 200_000
    _EXACT_DEBOUNCE_MS = 140

    def __init__(self, parent: Optional[qtw.QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(340)
        self.setMinimumHeight(280)
        self.setObjectName("HistogramWidget")

        self._counts: Optional[np.ndarray] = None
        self._edges: Optional[np.ndarray] = None
        self._x_min = 0.0
        self._x_max = 1.0
        self._theme_mode = "light"
        self._pending_image: Optional[np.ndarray] = None
        self._view_limits: Optional[tuple[float, float, float, float]] = None
        self._log_scale_y = False
        self._exact_refresh_suppressed = False
        self._is_plot_panning = False
        self._is_plot_selecting = False
        self._plot_pan_state: Optional[
            tuple[
                float,
                float,
                tuple[float, float],
                tuple[float, float],
            ]
        ] = None
        self._plot_select_state: Optional[tuple[float, float]] = None
        self._selection_rect_artist = None
        self._exact_timer = QtCore.QTimer(self)
        self._exact_timer.setSingleShot(True)
        self._exact_timer.setInterval(self._EXACT_DEBOUNCE_MS)
        self._exact_timer.timeout.connect(self._render_pending_image_exact)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._fallback_label: Optional[qtw.QLabel] = None
        self._figure = None
        self._canvas = None
        self._axes = None

        if (
            MATPLOTLIB_AVAILABLE
            and Figure is not None
            and FigureCanvasQTAgg is not None
        ):
            self._figure = Figure()
            self._figure.subplots_adjust(
                left=0.12,
                right=0.985,
                top=0.955,
                bottom=0.16,
            )
            self._canvas = FigureCanvasQTAgg(
                self._figure,
                resize_callback=self._apply_plot_layout,
            )
            self._axes = self._figure.add_subplot(111)
            self._canvas.mpl_connect("scroll_event", self._on_plot_scroll)
            self._canvas.mpl_connect("button_press_event", self._on_plot_press)
            self._canvas.mpl_connect("button_release_event", self._on_plot_release)
            self._canvas.mpl_connect("motion_notify_event", self._on_plot_motion)
            layout.addWidget(self._canvas, 1)
        else:
            self._fallback_label = qtw.QLabel(
                (
                    "matplotlib is not installed.\n"
                    "Install it to display histogram plots."
                )
            )
            self._fallback_label.setAlignment(Qt.AlignCenter)
            self._fallback_label.setWordWrap(True)
            self._fallback_label.setObjectName("MutedLabel")
            layout.addWidget(self._fallback_label, 1)

        self.set_theme("light")
        self.clear_histogram()

    def set_theme(self, mode: str) -> None:
        """Set histogram rendering theme.

        Parameters
        ----------
        mode : str
            Requested theme name. Non-``"dark"`` values fallback to light.
        """
        self._theme_mode = mode if mode == "dark" else "light"
        self._redraw()

    def _apply_plot_layout(self) -> None:
        """Keep the histogram y-axis label visible in narrow panes."""

        adjust_single_axes_layout(
            self._figure,
            self._axes,
            self._canvas,
            base_left=0.13,
            right=0.985,
            bottom=0.16,
            top=0.955,
            max_left=0.97,
        )

    def clear_histogram(self) -> None:
        """Clear current histogram data and redraw empty state."""
        self._exact_timer.stop()
        self._pending_image = None
        self._counts = None
        self._edges = None
        self._x_min = 0.0
        self._x_max = 1.0
        self._view_limits = None
        self._is_plot_panning = False
        self._is_plot_selecting = False
        self._plot_pan_state = None
        self._plot_select_state = None
        self._selection_rect_artist = None
        self._redraw()

    def set_exact_refresh_suppressed(self, suppressed: bool) -> None:
        """Temporarily pause exact histogram refinement while the UI is busy."""

        requested = bool(suppressed)
        if self._exact_refresh_suppressed == requested:
            return
        self._exact_refresh_suppressed = requested
        if not requested and self._pending_image is not None:
            self._exact_timer.start()

    def set_image(self, image: np.ndarray, *, exact: bool = True) -> None:
        """Build histogram data from a 2D intensity image.

        Parameters
        ----------
        image : numpy.ndarray
            Two-dimensional array of pixel intensities.
        exact : bool, default=True
            When ``False``, render a fast approximate histogram first and
            promote it to an exact one after a short debounce.
        """
        arr = np.asarray(image)
        if arr.ndim != 2 or arr.size == 0:
            self.clear_histogram()
            return
        self._view_limits = None
        self._is_plot_panning = False
        self._is_plot_selecting = False
        self._plot_pan_state = None
        self._plot_select_state = None
        self._selection_rect_artist = None
        if exact or arr.size <= self._APPROXIMATE_SAMPLE_LIMIT:
            self._exact_timer.stop()
            self._pending_image = None
            self._set_histogram_data(arr, sample_limit=None)
            return

        self._pending_image = arr
        self._set_histogram_data(
            arr,
            sample_limit=self._APPROXIMATE_SAMPLE_LIMIT,
        )
        if not self._exact_refresh_suppressed:
            self._exact_timer.start()

    def _render_pending_image_exact(self) -> None:
        image = self._pending_image
        self._pending_image = None
        if image is None:
            return
        if self._exact_refresh_suppressed:
            self._pending_image = image
            self._exact_timer.start()
            return
        self._set_histogram_data(image, sample_limit=None)

    def _set_histogram_data(
        self,
        image: np.ndarray,
        *,
        sample_limit: int | None,
    ) -> None:
        arr = np.asarray(image)
        flat = arr.ravel()
        if sample_limit is not None and flat.size > sample_limit:
            stride = max(1, int(np.ceil(float(flat.size) / float(sample_limit))))
            flat = flat[::stride]

        arrf = flat.astype(np.float64, copy=False)
        if np.issubdtype(arrf.dtype, np.floating):
            arrf = arrf[np.isfinite(arrf)]
        if arrf.size == 0:
            self.clear_histogram()
            return

        data_min = float(np.min(arrf))
        data_max = float(np.max(arrf))

        if data_max <= data_min:
            range_min = data_min - 0.5
            range_max = data_max + 0.5
        else:
            range_min = data_min
            range_max = data_max
            if data_min <= 0.0 <= data_max:
                range_min = min(range_min, 0.0)
            if range_max <= range_min:
                range_max = range_min + 1.0

        bins = int(max(32, min(144, np.sqrt(float(arrf.size)) * 0.45)))
        if np.issubdtype(arr.dtype, np.integer):
            span_int = int(round(range_max - range_min))
            if span_int > 0:
                bins = min(bins, span_int + 1)
                bins = max(24, bins)

        counts, edges = np.histogram(
            arrf,
            bins=bins,
            range=(range_min, range_max),
        )
        self._counts = counts.astype(np.float64, copy=False)
        self._edges = edges.astype(np.float64, copy=False)
        self._x_min = float(range_min)
        self._x_max = float(range_max)
        self._redraw()

    def reset_view(self) -> None:
        """Reset histogram axes to the full current histogram extent."""

        self._view_limits = None
        self._clear_plot_selection_overlay()
        self._redraw()

    def set_log_scale_y(self, enabled: bool) -> None:
        """Enable or disable logarithmic scaling on the histogram y-axis."""

        requested = bool(enabled)
        if self._log_scale_y == requested:
            return
        self._log_scale_y = requested
        if self._counts is not None and self._edges is not None:
            if self._view_limits is None:
                x0 = float(self._edges[0])
                x1 = float(self._edges[-1])
            else:
                x0, x1, _y0, _y1 = self._view_limits
            y0, y1 = self._visible_y_limits(x0, x1)
            self._view_limits = (x0, x1, y0, y1)
        self._redraw()

    def zoom_to_x_range(
        self,
        range_min: float,
        range_max: float,
        *,
        autoscale_y: bool = True,
    ) -> bool:
        """Zoom the histogram to one requested x-range."""

        if self._counts is None or self._edges is None or self._axes is None:
            return False
        full_x0 = float(self._edges[0])
        full_x1 = float(self._edges[-1])
        if not np.isfinite(range_min) or not np.isfinite(range_max):
            return False
        x0 = max(full_x0, min(float(range_min), full_x1))
        x1 = max(full_x0, min(float(range_max), full_x1))
        if x1 <= x0:
            span = max(1e-9, full_x1 - full_x0)
            center = max(full_x0, min((x0 + x1) / 2.0, full_x1))
            half = span * 0.01
            x0 = max(full_x0, center - half)
            x1 = min(full_x1, center + half)
            if x1 <= x0:
                x0 = full_x0
                x1 = full_x1

        current_limits = (
            self._view_limits
            if self._view_limits is not None
            else self._full_view_limits()
        )
        y0 = current_limits[2]
        y1 = current_limits[3]
        if autoscale_y:
            y0, y1 = self._visible_y_limits(x0, x1)
        self._view_limits = (x0, x1, y0, y1)
        self._apply_view_limits()
        self._canvas.draw_idle()
        return True

    def zoom_to_view_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> bool:
        """Zoom the histogram to one rectangular selection in plot space."""

        if self._counts is None or self._edges is None or self._axes is None:
            return False
        full_x0, full_x1, full_y0, full_y1 = self._full_view_limits()
        left = max(full_x0, min(min(float(x0), float(x1)), full_x1))
        right = max(full_x0, min(max(float(x0), float(x1)), full_x1))
        bottom = max(full_y0, min(min(float(y0), float(y1)), full_y1))
        top = max(full_y0, min(max(float(y0), float(y1)), full_y1))

        if right <= left:
            return False

        min_y_span = max(1e-9, (full_y1 - full_y0) * 0.01)
        if top - bottom < min_y_span:
            bottom, top = self._visible_y_limits(left, right)

        self._view_limits = (left, right, bottom, top)
        self._apply_view_limits()
        self._canvas.draw_idle()
        return True

    def _full_view_limits(self) -> tuple[float, float, float, float]:
        if self._counts is None or self._edges is None:
            return (0.0, 1.0, 0.0, 1.0)
        x0 = float(self._edges[0])
        x1 = float(self._edges[-1])
        y0, y1 = self._visible_y_limits(x0, x1)
        return (x0, x1, y0, y1)

    def _visible_y_limits(self, x0: float, x1: float) -> tuple[float, float]:
        if self._counts is None or self._edges is None or self._counts.size == 0:
            return (0.0, 1.0)
        left_edges = self._edges[:-1]
        right_edges = self._edges[1:]
        mask = (left_edges < x1) & (right_edges > x0)
        if not np.any(mask):
            visible = np.asarray(self._counts, dtype=np.float64)
        else:
            visible = np.asarray(self._counts[mask], dtype=np.float64)
        visible_max = float(np.max(visible)) if visible.size else 1.0
        if self._log_scale_y:
            positive = visible[visible > 0.0]
            if positive.size == 0:
                return (0.8, 1.2)
            visible_min = float(np.min(positive))
            lower = max(1e-3, visible_min * 0.8)
            upper = max(lower * 10.0, visible_max * 1.08)
            return (lower, upper)
        return (0.0, max(1.0, visible_max * 1.08))

    def _x_view_bounds(self) -> tuple[float, float]:
        """Return bounded x-axis extents used by zoom and pan interactions."""

        if self._edges is None or self._edges.size < 2:
            return (0.0, 1.0)
        full_x0 = float(self._edges[0])
        full_x1 = float(self._edges[-1])
        positive_span = max(1.0, full_x1 - max(full_x0, 0.0))
        margin = max(0.5, positive_span * 0.02)
        lower = full_x0 if full_x0 < 0.0 else -margin
        upper = full_x1 + margin
        if upper <= lower:
            upper = lower + 1.0
        return (lower, upper)

    def _clamp_x_limits(
        self,
        x0: float,
        x1: float,
    ) -> tuple[float, float]:
        """Clamp one requested x-range to the histogram interaction bounds."""

        lower, upper = self._x_view_bounds()
        span = max(1e-9, float(x1) - float(x0))
        max_span = max(1e-9, upper - lower)
        span = min(span, max_span)
        center = (float(x0) + float(x1)) / 2.0
        half = span / 2.0
        center = min(max(center, lower + half), upper - half)
        return (center - half, center + half)

    def _apply_view_limits(self) -> None:
        if self._axes is None:
            return
        x0, x1, y0, y1 = (
            self._view_limits
            if self._view_limits is not None
            else self._full_view_limits()
        )
        x0, x1 = self._clamp_x_limits(x0, x1)
        if self._log_scale_y:
            self._axes.set_yscale("log", nonpositive="clip")
            if y0 <= 0.0 or y1 <= y0:
                y0, y1 = self._visible_y_limits(x0, x1)
            else:
                y0 = max(1e-3, float(y0))
                y1 = max(y0 * 1.0001, float(y1))
        else:
            self._axes.set_yscale("linear")
            y0 = max(0.0, float(y0))
            y1 = max(y0 + 1e-9, float(y1))
        self._view_limits = (x0, x1, y0, y1)
        self._axes.set_xlim(x0, x1)
        self._axes.set_ylim(y0, y1)

    def _plot_spans(self) -> tuple[float, float]:
        full_x0, full_x1, _full_y0, full_y1 = self._full_view_limits()
        return (max(1e-9, full_x1 - full_x0), max(1e-9, full_y1))

    def _remember_current_view_limits(self) -> None:
        if self._axes is None:
            return
        xlim = tuple(self._axes.get_xlim())
        ylim = tuple(self._axes.get_ylim())
        self._view_limits = (
            float(xlim[0]),
            float(xlim[1]),
            float(ylim[0]),
            float(ylim[1]),
        )

    def _clamped_event_plot_point(self, event: object) -> Optional[tuple[float, float]]:
        """Return plot-space event coordinates clamped to the axes bounds."""

        if self._axes is None:
            return None
        x_data = getattr(event, "xdata", None)
        y_data = getattr(event, "ydata", None)
        if x_data is not None and y_data is not None:
            return (float(x_data), float(y_data))

        pixel_x = getattr(event, "x", None)
        pixel_y = getattr(event, "y", None)
        if pixel_x is None or pixel_y is None:
            return None
        try:
            bbox = self._axes.bbox
            clamped_x = min(max(float(pixel_x), float(bbox.x0)), float(bbox.x1))
            clamped_y = min(max(float(pixel_y), float(bbox.y0)), float(bbox.y1))
            data_x, data_y = self._axes.transData.inverted().transform(
                (clamped_x, clamped_y),
            )
        except Exception:
            return None
        return (float(data_x), float(data_y))

    def _show_plot_context_menu(self) -> None:
        """Open right-click actions for histogram navigation."""

        menu = qtw.QMenu(self)
        reset_action = menu.addAction("Reset View")
        log_y_action = menu.addAction("Log Y Axis")
        log_y_action.setCheckable(True)
        log_y_action.setChecked(self._log_scale_y)
        chosen = self._exec_plot_context_menu(menu)
        if chosen == reset_action:
            self.reset_view()
        elif chosen == log_y_action:
            self.set_log_scale_y(bool(log_y_action.isChecked()))

    def _exec_plot_context_menu(self, menu: qtw.QMenu) -> object | None:
        """Execute the histogram context menu.

        Split out for deterministic test patching around the blocking Qt call.
        """

        return menu.exec(QtGui.QCursor.pos())

    def _on_plot_press(self, event: object) -> None:
        """Handle reset, context menu, drag-zoom selection, and pan start."""

        if self._axes is None or self._canvas is None:
            return
        if getattr(event, "inaxes", None) is not self._axes:
            return
        if bool(getattr(event, "dblclick", False)):
            self.reset_view()
            return
        if getattr(event, "button", None) == 3:
            self._show_plot_context_menu()
            return
        if getattr(event, "button", None) not in (1, 2):
            return
        x_data = getattr(event, "xdata", None)
        y_data = getattr(event, "ydata", None)
        if x_data is None or y_data is None:
            return
        if getattr(event, "button", None) == 1:
            self._is_plot_selecting = True
            self._plot_select_state = (float(x_data), float(y_data))
            self._ensure_plot_selection_overlay(
                float(x_data),
                float(y_data),
                float(x_data),
                float(y_data),
            )
            self._canvas.setCursor(Qt.CrossCursor)
            return
        self._is_plot_panning = True
        self._plot_pan_state = (
            float(x_data),
            float(y_data),
            tuple(self._axes.get_xlim()),
            tuple(self._axes.get_ylim()),
        )
        self._canvas.setCursor(Qt.ClosedHandCursor)

    def _on_plot_release(self, event: object) -> None:
        """Finish drag-pan mode or apply one zoom-selection rectangle."""

        if self._canvas is None:
            return
        if self._is_plot_selecting and self._plot_select_state is not None:
            start_x, start_y = self._plot_select_state
            end_point = self._clamped_event_plot_point(event)
            self._clear_plot_selection_overlay()
            self._canvas.setCursor(Qt.ArrowCursor)
            if end_point is not None:
                self.zoom_to_view_rect(start_x, start_y, end_point[0], end_point[1])
            return
        self._is_plot_panning = False
        self._plot_pan_state = None
        self._canvas.setCursor(Qt.ArrowCursor)

    def _on_plot_scroll(self, event: object) -> None:
        """Zoom the histogram around the pointer location."""

        if self._axes is None or self._canvas is None:
            return
        if getattr(event, "inaxes", None) is not self._axes:
            return
        x_data = getattr(event, "xdata", None)
        y_data = getattr(event, "ydata", None)
        if x_data is None or y_data is None:
            return

        xlim = tuple(self._axes.get_xlim())
        ylim = tuple(self._axes.get_ylim())
        if xlim[0] == xlim[1] or ylim[0] == ylim[1]:
            return

        button = str(getattr(event, "button", "up"))
        zoom_scale = 0.92 if button == "up" else 1.08
        x_span = float(xlim[1] - xlim[0])
        y_span = float(ylim[1] - ylim[0])
        x_ratio = (float(x_data) - float(xlim[0])) / x_span
        y_ratio = (float(y_data) - float(ylim[0])) / y_span
        data_x_span, data_y_span = self._plot_spans()

        min_x_span = max(1e-9, data_x_span * 1e-6)
        min_y_span = max(1e-9, data_y_span * 1e-6)
        max_x_span = max(min_x_span * 10.0, data_x_span * 20.0)
        max_y_span = max(min_y_span * 10.0, data_y_span * 20.0)

        new_x_span = min(max(x_span * zoom_scale, min_x_span), max_x_span)
        new_y_span = min(max(y_span * zoom_scale, min_y_span), max_y_span)
        x0 = float(x_data) - x_ratio * new_x_span
        x1 = x0 + new_x_span
        min_y0 = 1e-3 if self._log_scale_y else 0.0
        y0 = max(min_y0, float(y_data) - y_ratio * new_y_span)
        y1 = y0 + new_y_span
        self._view_limits = (x0, x1, y0, y1)
        self._apply_view_limits()
        self._canvas.draw_idle()

    def _on_plot_motion(self, event: object) -> None:
        """Pan the histogram while dragging."""

        if self._axes is None or self._canvas is None:
            return
        if self._is_plot_selecting and self._plot_select_state is not None:
            current_point = self._clamped_event_plot_point(event)
            if current_point is None:
                return
            start_x, start_y = self._plot_select_state
            self._ensure_plot_selection_overlay(
                start_x,
                start_y,
                current_point[0],
                current_point[1],
            )
            self._canvas.draw_idle()
            return
        if (
            not self._is_plot_panning
            or self._plot_pan_state is None
            or getattr(event, "inaxes", None) is not self._axes
            or getattr(event, "xdata", None) is None
            or getattr(event, "ydata", None) is None
        ):
            return

        start_x, start_y, start_xlim, start_ylim = self._plot_pan_state
        delta_x = float(getattr(event, "xdata")) - start_x
        delta_y = float(getattr(event, "ydata")) - start_y
        min_y0 = 1e-3 if self._log_scale_y else 0.0
        y0 = max(min_y0, start_ylim[0] - delta_y)
        y1 = y0 + float(start_ylim[1] - start_ylim[0])
        self._view_limits = (
            start_xlim[0] - delta_x,
            start_xlim[1] - delta_x,
            y0,
            y1,
        )
        self._apply_view_limits()
        self._canvas.draw_idle()

    def _clear_plot_selection_overlay(self) -> None:
        """Remove the transient histogram zoom-selection overlay."""

        artist = self._selection_rect_artist
        self._selection_rect_artist = None
        self._is_plot_selecting = False
        self._plot_select_state = None
        if artist is None:
            return
        try:
            artist.remove()
        except Exception:
            pass

    def _ensure_plot_selection_overlay(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> None:
        """Create or update the transient histogram zoom-selection rectangle."""

        if self._axes is None or Rectangle is None:
            return
        left = min(float(x0), float(x1))
        bottom = min(float(y0), float(y1))
        width = abs(float(x1) - float(x0))
        height = abs(float(y1) - float(y0))
        if self._selection_rect_artist is None:
            edge = "#93c5fd" if self._theme_mode == "dark" else "#1d4ed8"
            fill = "#60a5fa" if self._theme_mode == "dark" else "#3b82f6"
            self._selection_rect_artist = Rectangle(
                (left, bottom),
                width,
                height,
                fill=True,
                facecolor=fill,
                edgecolor=edge,
                linewidth=1.1,
                linestyle="--",
                alpha=0.18,
            )
            self._axes.add_patch(self._selection_rect_artist)
            return
        self._selection_rect_artist.set_xy((left, bottom))
        self._selection_rect_artist.set_width(width)
        self._selection_rect_artist.set_height(height)

    def _redraw(self) -> None:
        if self._axes is None or self._canvas is None or self._figure is None:
            return
        self._is_plot_selecting = False
        self._plot_select_state = None
        self._selection_rect_artist = None

        if self._theme_mode == "dark":
            fig_bg = "#1f2937"
            axes_bg = "#111827"
            text = "#e5e7eb"
            major_grid = "#64748b"
            minor_grid = "#94a3b8"
            major_grid_alpha = 0.42
            minor_grid_alpha = 0.24
            accent = "#60a5fa"
            edge = "#dbeafe"
        else:
            fig_bg = "#ffffff"
            axes_bg = "#f8fbff"
            text = "#1f2937"
            major_grid = "#c7d6ea"
            minor_grid = "#dbe5f3"
            major_grid_alpha = 0.62
            minor_grid_alpha = 0.4
            accent = "#2563eb"
            edge = "#1e3a8a"

        ax = self._axes
        ax.clear()
        self._figure.patch.set_facecolor(fig_bg)
        self._figure.patch.set_edgecolor(fig_bg)
        ax.set_facecolor(axes_bg)
        if self._canvas is not None:
            self._canvas.setStyleSheet(
                f"background-color: {fig_bg}; border: none;",
            )
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(major_grid)
        ax.spines["bottom"].set_color(major_grid)
        ax.tick_params(which="both", colors=text)
        ax.xaxis.label.set_color(text)
        ax.yaxis.label.set_color(text)
        ax.set_yscale("linear")
        ax.set_xlabel("Pixel Intensity")
        ax.set_ylabel("Occurrences")
        ax.minorticks_on()
        ax.grid(
            True,
            which="major",
            color=major_grid,
            alpha=major_grid_alpha,
            linewidth=0.85,
        )
        ax.grid(
            True,
            which="minor",
            color=minor_grid,
            alpha=minor_grid_alpha,
            linewidth=0.65,
            linestyle=":",
        )

        if self._counts is None or self._edges is None:
            ax.text(
                0.5,
                0.5,
                "No histogram available.",
                color=text,
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_xlim(0.0, 1.0)
            ax.set_ylim(0.0, 1.0)
        else:
            centers = (self._edges[:-1] + self._edges[1:]) / 2.0
            bar_width = (
                float(self._edges[1] - self._edges[0])
                if len(self._edges) > 1
                else 1.0
            )
            ax.bar(
                centers,
                self._counts,
                width=bar_width,
                color=accent,
                edgecolor=edge,
                alpha=0.82,
                linewidth=0.65,
            )
            ax.margins(x=0)
            self._apply_view_limits()

        self._apply_plot_layout()
        self._canvas.draw_idle()
