from __future__ import annotations

import pytest
from PySide6 import QtCore, QtWidgets as qtw

from framelab.dock_title_bar import DockTitleBar


pytestmark = [pytest.mark.fast, pytest.mark.ui]


def test_dock_title_bar_ignores_late_refresh_after_dock_teardown(qapp) -> None:
    dock = qtw.QDockWidget("Workflow Explorer")
    title_bar = DockTitleBar(dock)
    dock.setTitleBarWidget(title_bar)

    title_bar._on_dock_destroyed()
    title_bar._refresh_icons()
    title_bar._toggle_floating()
    title_bar.changeEvent(QtCore.QEvent(QtCore.QEvent.PaletteChange))

    dock.deleteLater()
    qapp.processEvents()
