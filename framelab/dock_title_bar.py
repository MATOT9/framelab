"""Custom dock title bars with clearer controls in themed shells."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt
from shiboken6 import isValid


def _draw_close_icon(color: QtGui.QColor) -> QtGui.QIcon:
    """Return a small high-contrast close icon."""

    pixmap = QtGui.QPixmap(18, 18)
    pixmap.fill(Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(5, 5, 13, 13)
    painter.drawLine(13, 5, 5, 13)
    painter.end()
    return QtGui.QIcon(pixmap)


def _draw_float_icon(color: QtGui.QColor) -> QtGui.QIcon:
    """Return a small high-contrast undock icon."""

    pixmap = QtGui.QPixmap(18, 18)
    pixmap.fill(Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawRect(4, 5, 8, 8)
    painter.drawLine(8, 9, 13, 4)
    painter.drawLine(10, 4, 13, 4)
    painter.drawLine(13, 4, 13, 7)
    painter.end()
    return QtGui.QIcon(pixmap)


def _draw_dock_icon(color: QtGui.QColor) -> QtGui.QIcon:
    """Return a small high-contrast dock icon."""

    pixmap = QtGui.QPixmap(18, 18)
    pixmap.fill(Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawRect(3, 4, 12, 10)
    painter.drawLine(7, 4, 7, 14)
    painter.end()
    return QtGui.QIcon(pixmap)


class DockTitleBar(qtw.QWidget):
    """Small themed title bar used by primary workflow docks."""

    def __init__(self, dock: qtw.QDockWidget) -> None:
        super().__init__(dock)
        self._dock: qtw.QDockWidget | None = dock
        self.setObjectName("DockTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = qtw.QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(6)
        self._layout = layout

        self._title_label = qtw.QLabel(dock.windowTitle(), self)
        self._title_label.setObjectName("DockTitleLabel")
        self._title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(self._title_label, 1)

        self._float_button = qtw.QToolButton(self)
        self._float_button.setObjectName("DockTitleButton")
        self._float_button.setAutoRaise(False)
        self._float_button.setCursor(Qt.ArrowCursor)
        self._float_button.clicked.connect(self._toggle_floating)
        layout.addWidget(self._float_button, 0, Qt.AlignVCenter)

        self._close_button = qtw.QToolButton(self)
        self._close_button.setObjectName("DockTitleButton")
        self._close_button.setAutoRaise(False)
        self._close_button.setCursor(Qt.ArrowCursor)
        self._close_button.clicked.connect(dock.close)
        layout.addWidget(self._close_button, 0, Qt.AlignVCenter)

        dock.windowTitleChanged.connect(self._title_label.setText)
        dock.topLevelChanged.connect(lambda _floating: self._refresh_icons())
        dock.destroyed.connect(self._on_dock_destroyed)
        self._refresh_icons()

    def sizeHint(self) -> QtCore.QSize:
        """Return a compact but comfortable titlebar height."""

        return QtCore.QSize(140, 30)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        """Refresh icons when palette/style changes alter contrast."""

        super().changeEvent(event)
        if event.type() in (
            QtCore.QEvent.PaletteChange,
            QtCore.QEvent.StyleChange,
            QtCore.QEvent.ApplicationPaletteChange,
        ):
            self._refresh_icons()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        """Mirror native dock-title double click behavior."""

        if event.button() == Qt.LeftButton:
            self._toggle_floating()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _toggle_floating(self) -> None:
        """Detach or re-dock the associated panel."""

        dock = self._dock
        if not self._qt_object_is_valid(dock):
            return
        if not (dock.features() & qtw.QDockWidget.DockWidgetFloatable):
            return
        dock.setFloating(not dock.isFloating())
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        """Rebuild icons and tooltips using the current palette."""

        dock = self._dock
        if not (
            self._qt_object_is_valid(self)
            and self._qt_object_is_valid(dock)
            and self._qt_object_is_valid(self._float_button)
            and self._qt_object_is_valid(self._close_button)
        ):
            return
        color = self.palette().color(QtGui.QPalette.ButtonText)
        if not color.isValid():
            color = self.palette().color(QtGui.QPalette.WindowText)
        self._close_button.setIcon(_draw_close_icon(color))
        if dock.isFloating():
            self._float_button.setIcon(_draw_dock_icon(color))
            self._float_button.setToolTip("Dock this panel back into the main window.")
        else:
            self._float_button.setIcon(_draw_float_icon(color))
            self._float_button.setToolTip("Detach this panel into a floating window.")
        self._close_button.setToolTip("Hide this panel.")

    def _on_dock_destroyed(self, _obj: object | None = None) -> None:
        """Drop the dock reference so late palette/style events stay harmless."""

        self._dock = None

    @staticmethod
    def _qt_object_is_valid(obj: object | None) -> bool:
        """Return whether one wrapped Qt object is still alive."""

        return obj is not None and isValid(obj)
