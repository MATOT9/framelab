"""Application icon and process-identity helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets as qtw


APP_DESKTOP_ID = "framelab"
APP_DISPLAY_NAME = "FrameLab"
APP_WINDOWS_APP_ID = "com.maxime.framelab"


def _set_windows_app_user_model_id(app_id: str) -> None:
    """Set the Windows AppUserModelID for taskbar/process icon grouping."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        return


def prepare_process_identity() -> None:
    """Apply process-level identity before creating QApplication."""
    _set_windows_app_user_model_id(APP_WINDOWS_APP_ID)
    QtCore.QCoreApplication.setApplicationName(APP_DESKTOP_ID)
    if hasattr(QtGui.QGuiApplication, "setApplicationDisplayName"):
        QtGui.QGuiApplication.setApplicationDisplayName(APP_DISPLAY_NAME)
    if sys.platform.startswith("linux"):
        QtGui.QGuiApplication.setDesktopFileName(APP_DESKTOP_ID)


def _icon_candidates() -> list[Path]:
    """Return candidate icon files in priority order."""
    assets_dir = Path(__file__).resolve().parent / "assets"
    if sys.platform == "win32":
        return [
            assets_dir / "app_icon.ico",
            assets_dir / "app_icon.png",
            assets_dir / "app_icon.svg",
        ]
    return [
        assets_dir / "app_icon.png",
        assets_dir / "app_icon.svg",
        assets_dir / "app_icon.ico",
    ]


def _ensure_linux_desktop_entry() -> None:
    """Create a local desktop entry so GNOME dock resolves the app icon."""
    if not sys.platform.startswith("linux"):
        return

    icon_path = next(
        (path for path in _icon_candidates() if path.exists()),
        None,
    )
    if icon_path is None:
        return

    home = Path.home()
    apps_dir = home / ".local" / "share" / "applications"
    desktop_path = apps_dir / f"{APP_DESKTOP_ID}.desktop"
    desktop_text = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_DISPLAY_NAME}\n"
        "Comment=Image analysis workstation\n"
        "Exec=python3 -m framelab\n"
        "Terminal=false\n"
        "Categories=Graphics;Science;\n"
        f"Icon={icon_path}\n"
        f"StartupWMClass={APP_DESKTOP_ID}\n"
    )
    try:
        apps_dir.mkdir(parents=True, exist_ok=True)
        if (
            not desktop_path.exists()
            or desktop_path.read_text(encoding="utf-8") != desktop_text
        ):
            desktop_path.write_text(desktop_text, encoding="utf-8")
    except Exception:
        return


def load_app_icon() -> QtGui.QIcon:
    """Load application icon from package assets."""
    icon = QtGui.QIcon()
    for icon_path in _icon_candidates():
        if icon_path.exists():
            icon.addFile(str(icon_path))
    if not icon.isNull():
        return icon

    for icon_path in _icon_candidates():
        if not icon_path.exists():
            continue
        fallback = QtGui.QIcon(str(icon_path))
        if not fallback.isNull():
            return fallback
    return icon


def _apply_icon_to_widget(widget: object, icon: QtGui.QIcon) -> None:
    """Apply the app icon to one widget and its native window handle when present."""

    if isinstance(widget, qtw.QWidget):
        try:
            if not _should_apply_native_icon(widget):
                return
            widget.setWindowIcon(icon)
        except Exception:
            return
        if not widget.isVisible():
            return
        try:
            handle = widget.windowHandle()
        except Exception:
            return
    else:
        try:
            widget.setWindowIcon(icon)
            handle = widget.windowHandle()
        except Exception:
            return
    if handle is None:
        return
    try:
        handle.setIcon(icon)
    except Exception:
        return


def _should_apply_native_icon(widget: qtw.QWidget) -> bool:
    """Return whether one QWidget should receive native-window icon updates."""

    if not isinstance(widget, qtw.QWidget):
        return False
    if isinstance(widget, qtw.QDockWidget):
        return False
    try:
        if widget.window() is not widget:
            return False
    except Exception:
        return False
    return isinstance(widget, (qtw.QMainWindow, qtw.QDialog, qtw.QSplashScreen))


def apply_app_identity(
    app: qtw.QApplication,
    window: Optional[qtw.QWidget] = None,
) -> None:
    """Apply process/window icon identity across supported platforms."""
    _set_windows_app_user_model_id(APP_WINDOWS_APP_ID)
    app.setApplicationName(APP_DESKTOP_ID)
    if hasattr(app, "setApplicationDisplayName"):
        app.setApplicationDisplayName(APP_DISPLAY_NAME)
    if sys.platform.startswith("linux"):
        app.setDesktopFileName(APP_DESKTOP_ID)
        _ensure_linux_desktop_entry()

    icon = load_app_icon()
    if icon.isNull():
        return

    app.setWindowIcon(icon)
    widgets: list[object] = []
    if window is not None:
        widgets.append(window)
    else:
        for top_level in app.topLevelWidgets():
            if top_level not in widgets:
                widgets.append(top_level)
    for widget in widgets:
        _apply_icon_to_widget(widget, icon)
