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
    blocked_types: tuple[type[qtw.QWidget], ...] = DEFAULT_DRAG_BLOCKED_TYPES,
) -> None:
    """Apply standard top-level window flags to custom secondary windows."""

    flags = window.windowFlags()
    flags &= ~Qt.Tool
    flags &= ~Qt.Dialog
    flags |= (
        Qt.Window
        | Qt.WindowMinimizeButtonHint
        | Qt.WindowMaximizeButtonHint
        | Qt.WindowCloseButtonHint
    )
    flags &= ~Qt.WindowContextHelpButtonHint
    window.setWindowFlags(flags)
    if draggable:
        enable_window_content_drag(window, blocked_types=blocked_types)
