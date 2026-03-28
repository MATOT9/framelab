"""Application entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtGui, QtWidgets as qtw
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
from .stylesheets import DARK_THEME


def _selector_splash_path() -> Path:
    """Return the packaged selector-splash image path."""

    return Path(__file__).resolve().parent / "assets" / "framelab_splash.png"


def _create_selector_splash(
    app: qtw.QApplication,
) -> qtw.QSplashScreen | None:
    """Show the startup splash used before the plugin selector."""

    platform_name = ""
    try:
        platform_name = str(app.platformName()).strip().lower()
    except Exception:
        platform_name = ""
    if platform_name in {"offscreen", "minimal", "minimalegl"}:
        return None

    splash_path = _selector_splash_path()
    if not splash_path.exists():
        return None
    pixmap = QtGui.QPixmap(str(splash_path))
    if pixmap.isNull():
        return None

    splash = qtw.QSplashScreen(pixmap)
    splash.setObjectName("FrameLabSplash")
    splash.show()
    app.processEvents()
    return splash


def _close_selector_splash(
    splash: qtw.QSplashScreen | None,
    *,
    target: qtw.QWidget | None = None,
) -> None:
    """Close the selector splash without leaving a stray top-level window."""

    if splash is None:
        return
    try:
        _ = target
        splash.close()
    finally:
        splash.deleteLater()


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
    splash = _create_selector_splash(app)

    try:
        manifests = discover_plugin_manifests()
        selected_ids = load_selected_plugin_ids(manifests)
    except Exception as exc:
        _close_selector_splash(splash)
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
    _close_selector_splash(splash, target=selector)
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
    if win.workflow_state_controller.workspace_root is None:
        win._open_workflow_selection_dialog()
    win.showMaximized()
    return app.exec()
