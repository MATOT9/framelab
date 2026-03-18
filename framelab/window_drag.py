"""Shared helpers for draggable/maximizable secondary windows."""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt


DEFAULT_DRAG_BLOCKED_TYPES = (
    qtw.QAbstractButton,
    qtw.QAbstractItemView,
    qtw.QAbstractSlider,
    qtw.QAbstractSpinBox,
    qtw.QComboBox,
    qtw.QLineEdit,
    qtw.QPlainTextEdit,
    qtw.QScrollBar,
    qtw.QTabBar,
    qtw.QTextEdit,
)


class _WindowDragController(QtCore.QObject):
    """Event-filter controller that moves one top-level window."""

    def __init__(
        self,
        window: qtw.QWidget,
        *,
        blocked_types: tuple[type[qtw.QWidget], ...] = DEFAULT_DRAG_BLOCKED_TYPES,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._blocked_types = blocked_types
        self._drag_offset: Optional[QtCore.QPoint] = None

    def refresh(self) -> None:
        """Install the filter on the window and all current child widgets."""
        self._install_widget(self._window)
        for widget in self._window.findChildren(qtw.QWidget):
            self._install_widget(widget)

    def _install_widget(self, widget: qtw.QWidget) -> None:
        if widget.property("_window_drag_filter_installed"):
            return
        widget.installEventFilter(self)
        widget.setProperty("_window_drag_filter_installed", True)

    def _start_drag(self, event: QtGui.QMouseEvent) -> None:
        if self._window.isMaximized():
            self._drag_offset = None
            return
        self._drag_offset = (
            event.globalPosition().toPoint()
            - self._window.frameGeometry().topLeft()
        )

    def _stop_drag(self) -> None:
        self._drag_offset = None

    def eventFilter(
        self,
        watched: QtCore.QObject,
        event: QtCore.QEvent,
    ) -> bool:
        if (
            isinstance(watched, qtw.QWidget)
            and event.type() == QtCore.QEvent.Type.ChildAdded
        ):
            child_event = event if isinstance(event, QtCore.QChildEvent) else None
            child = child_event.child() if child_event is not None else None
            if isinstance(child, qtw.QWidget):
                self._install_widget(child)
                for widget in child.findChildren(qtw.QWidget):
                    self._install_widget(widget)

        if isinstance(watched, qtw.QWidget) and not isinstance(
            watched,
            self._blocked_types,
        ):
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                if (
                    isinstance(event, QtGui.QMouseEvent)
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    self._start_drag(event)
            elif event.type() == QtCore.QEvent.Type.MouseMove:
                if (
                    isinstance(event, QtGui.QMouseEvent)
                    and self._drag_offset is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                ):
                    self._window.move(
                        event.globalPosition().toPoint() - self._drag_offset,
                    )
                    return True
            elif event.type() in {
                QtCore.QEvent.Type.MouseButtonRelease,
                QtCore.QEvent.Type.Hide,
                QtCore.QEvent.Type.WindowDeactivate,
            }:
                self._stop_drag()
        return super().eventFilter(watched, event)


def enable_window_content_drag(
    window: qtw.QWidget,
    *,
    blocked_types: tuple[type[qtw.QWidget], ...] = DEFAULT_DRAG_BLOCKED_TYPES,
) -> None:
    """Make a top-level dialog movable by dragging non-interactive content."""
    controller = getattr(window, "_window_drag_controller", None)
    if isinstance(controller, _WindowDragController):
        controller.refresh()
        return
    controller = _WindowDragController(window, blocked_types=blocked_types)
    setattr(window, "_window_drag_controller", controller)
    controller.refresh()


def configure_secondary_window(
    window: qtw.QWidget,
    *,
    draggable: bool = False,
    standalone: bool = False,
    blocked_types: tuple[type[qtw.QWidget], ...] = DEFAULT_DRAG_BLOCKED_TYPES,
) -> None:
    """Apply standard top-level window flags to custom secondary windows."""

    flags = window.windowFlags()
    flags &= ~Qt.Tool
    flags &= ~Qt.Dialog
    flags &= ~Qt.Window
    flags |= Qt.Window if standalone else Qt.Dialog
    flags |= (
        Qt.WindowMinimizeButtonHint
        | Qt.WindowMaximizeButtonHint
        | Qt.WindowCloseButtonHint
    )
    flags &= ~Qt.WindowContextHelpButtonHint
    window.setWindowFlags(flags)
    if draggable:
        enable_window_content_drag(window, blocked_types=blocked_types)


def _coerce_size(size: QtCore.QSize | tuple[int, int]) -> QtCore.QSize:
    """Normalize tuple-like preferred sizes into a valid ``QSize``."""

    if isinstance(size, QtCore.QSize):
        return QtCore.QSize(max(0, size.width()), max(0, size.height()))
    width, height = size
    return QtCore.QSize(max(0, int(width)), max(0, int(height)))


def _current_frame_margins(window: qtw.QWidget) -> QtCore.QMargins:
    """Return frame margins for one top-level widget when available."""

    try:
        window.winId()
    except Exception:
        return QtCore.QMargins()

    handle = window.windowHandle()
    if handle is None:
        return QtCore.QMargins()
    try:
        margins = handle.frameMargins()
    except Exception:
        return QtCore.QMargins()
    return margins if isinstance(margins, QtCore.QMargins) else QtCore.QMargins()


def _top_level_host_window(window: qtw.QWidget | None) -> qtw.QWidget | None:
    """Resolve one widget to the top-level host window used for placement."""

    if not isinstance(window, qtw.QWidget):
        return None
    top_level = window.window()
    if isinstance(top_level, qtw.QWidget):
        return top_level
    return window


def secondary_window_available_geometry(
    window: qtw.QWidget,
    *,
    host_window: qtw.QWidget | None = None,
) -> QtCore.QRect:
    """Return the best available screen work area for one secondary window."""

    screen = None
    seen_candidates: set[int] = set()
    for candidate in (_top_level_host_window(host_window), _top_level_host_window(window)):
        if not isinstance(candidate, qtw.QWidget):
            continue
        key = id(candidate)
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        handle = candidate.windowHandle()
        if handle is not None and handle.screen() is not None:
            screen = handle.screen()
            break
        candidate_screen = candidate.screen()
        if candidate_screen is not None:
            screen = candidate_screen
            break
    if screen is None:
        screen = qtw.QApplication.primaryScreen()
    if screen is None:
        return QtCore.QRect(0, 0, 1600, 900)
    return screen.availableGeometry()


def place_secondary_window(
    window: qtw.QWidget,
    *,
    host_window: qtw.QWidget | None = None,
) -> None:
    """Center a secondary window on the host screen and clamp it on-screen."""

    available = secondary_window_available_geometry(window, host_window=host_window)
    margins = _current_frame_margins(window)
    frame_width = max(1, window.width() + margins.left() + margins.right())
    frame_height = max(1, window.height() + margins.top() + margins.bottom())
    resolved_host = _top_level_host_window(host_window)

    reference_rect = (
        resolved_host.frameGeometry()
        if isinstance(resolved_host, qtw.QWidget) and resolved_host.isVisible()
        else available
    )
    frame_x = reference_rect.center().x() - frame_width // 2
    frame_y = reference_rect.center().y() - frame_height // 2
    max_x = available.left() + max(0, available.width() - frame_width)
    max_y = available.top() + max(0, available.height() - frame_height)
    frame_x = min(max(frame_x, available.left()), max_x)
    frame_y = min(max(frame_y, available.top()), max_y)

    window.move(frame_x + margins.left(), frame_y + margins.top())


def apply_secondary_window_geometry(
    window: qtw.QWidget,
    *,
    preferred_size: QtCore.QSize | tuple[int, int],
    host_window: qtw.QWidget | None = None,
) -> None:
    """Clamp one secondary window's startup size and position to the screen."""

    window.ensurePolished()
    preferred = _coerce_size(preferred_size)
    available = secondary_window_available_geometry(window, host_window=host_window)
    margins = _current_frame_margins(window)
    max_client = QtCore.QSize(
        max(240, available.width() - margins.left() - margins.right()),
        max(180, available.height() - margins.top() - margins.bottom()),
    )

    minimum_hint = window.minimumSizeHint()
    configured_minimum = window.minimumSize()
    effective_minimum = QtCore.QSize(
        min(
            max(configured_minimum.width(), minimum_hint.width(), 0),
            max_client.width(),
        ),
        min(
            max(configured_minimum.height(), minimum_hint.height(), 0),
            max_client.height(),
        ),
    )
    if effective_minimum.isValid():
        window.setMinimumSize(effective_minimum)

    size_hint = window.sizeHint()
    target_size = preferred
    if size_hint.isValid():
        target_size = target_size.expandedTo(size_hint)
    if effective_minimum.isValid():
        target_size = target_size.expandedTo(effective_minimum)
    target_size = target_size.boundedTo(max_client)
    window.resize(target_size)
    place_secondary_window(window, host_window=host_window)
