"""Offline documentation helpers for the Help menu."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

from PySide6 import QtCore, QtGui, QtWidgets as qtw


_HELP_BUILD_COMMAND = "python3 scripts/docs/build.py"
_HELP_PAGE_PATHS = {
    "home": Path("index.html"),
    "quick_start": Path("user-guide/quick-start.html"),
    "user_guide": Path("user-guide/index.html"),
    "plugin_guide": Path("user-guide/plugins.html"),
    "developer_guide": Path("developer-guide/index.html"),
    "reference": Path("reference/index.html"),
    "troubleshooting": Path("troubleshooting/index.html"),
    "keyboard_shortcuts": Path("reference/keyboard-shortcuts.html"),
}


def help_site_dir() -> Path:
    """Return bundled offline-help root directory."""
    return Path(__file__).resolve().parent / "assets" / "help"


def help_page_path(page_key: str) -> Path:
    """Return local HTML file for one Help page key."""
    relative_path = _HELP_PAGE_PATHS.get(page_key)
    if relative_path is None:
        supported = ", ".join(sorted(_HELP_PAGE_PATHS))
        raise KeyError(f"unknown help page '{page_key}', expected one of: {supported}")
    return help_site_dir() / relative_path


def _sanitized_desktop_open_env() -> dict[str, str]:
    """Return a reduced environment for launching external help viewers."""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("CONDA_") or key.startswith("MAMBA_"):
            env.pop(key, None)
    for key in (
        "GTK_MODULES",
        "GTK_PATH",
        "GTK_EXE_PREFIX",
        "GTK_DATA_PREFIX",
        "PYTHONHOME",
        "PYTHONPATH",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "LD_LIBRARY_PATH",
    ):
        env.pop(key, None)
    return env


def _open_url_with_linux_desktop(url: QtCore.QUrl) -> bool:
    """Open a URL via Linux desktop launcher with sanitized environment."""
    launcher = shutil.which("xdg-open") or shutil.which("gio")
    if launcher is None:
        return False

    command = [launcher, url.toString()]
    if Path(launcher).name == "gio":
        command = [launcher, "open", url.toString()]

    try:
        subprocess.Popen(
            command,
            env=_sanitized_desktop_open_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return False
    return True


def open_help_page(
    host_window: qtw.QWidget,
    page_key: str,
    *,
    fragment: str | None = None,
) -> None:
    """Open one bundled offline help page or show a clear fallback dialog."""
    try:
        page_path = help_page_path(page_key)
    except KeyError as exc:
        qtw.QMessageBox.warning(
            host_window,
            "Help Page Error",
            str(exc),
        )
        return

    if not page_path.exists():
        qtw.QMessageBox.information(
            host_window,
            "Offline Help Not Available",
            (
                "The offline documentation bundle is missing.\n\n"
                f"Expected page: {page_path}\n\n"
                "Build it with:\n"
                f"{_HELP_BUILD_COMMAND}"
            ),
        )
        return

    url = QtCore.QUrl.fromLocalFile(str(page_path.resolve()))
    if fragment:
        url.setFragment(fragment)

    opened = False
    if sys.platform.startswith("linux"):
        opened = _open_url_with_linux_desktop(url)
    if not opened:
        opened = QtGui.QDesktopServices.openUrl(url)
    if opened:
        return

    qtw.QMessageBox.warning(
        host_window,
        "Open Help Page",
        (
            "Could not open the offline documentation page automatically.\n\n"
            f"Page: {page_path}"
        ),
    )
