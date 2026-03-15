"""Application entrypoint."""

from __future__ import annotations

import sys

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import QTimer

from .icons import apply_app_identity, prepare_process_identity
from .mpl_config import ensure_matplotlib_config_dir
from .plugins import discover_plugin_manifests
from .plugins.selection import (
    PluginStartupDialog,
    load_selected_plugin_ids,
    save_selected_plugin_ids,
)
from .window import FrameLabWindow
from stylesheets import DARK_THEME


def main() -> int:
    """Run the Qt application entry point.

    Returns
    -------
    int
        Process exit code from the Qt event loop.
    """
    prepare_process_identity()
    ensure_matplotlib_config_dir()
    app = qtw.QApplication(sys.argv)
    apply_app_identity(app)
    app.setStyleSheet(DARK_THEME)

    try:
        manifests = discover_plugin_manifests()
        selected_ids = load_selected_plugin_ids(manifests)
    except Exception as exc:
        qtw.QMessageBox.critical(
            None,
            "Plugin Startup Error",
            str(exc),
        )
        return 1

    selector = PluginStartupDialog(
        manifests,
        selected_plugin_ids=selected_ids,
    )
    if selector.exec() != qtw.QDialog.Accepted:
        return 0

    enabled_plugin_ids = selector.enabled_plugin_ids()
    save_selected_plugin_ids(enabled_plugin_ids)

    try:
        win = FrameLabWindow(enabled_plugin_ids=enabled_plugin_ids)
    except Exception as exc:
        qtw.QMessageBox.critical(
            None,
            "Plugin Load Error",
            str(exc),
        )
        return 1
    apply_app_identity(app, win)
    win.showMaximized()
    # Re-apply once native window handle exists (helps Windows taskbar icon).
    apply_app_identity(app, win)
    if win.workflow_state_controller.workspace_root is None:
        QTimer.singleShot(0, win._open_workflow_selection_dialog)
    return app.exec()
