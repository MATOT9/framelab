"""Shared themed QFileDialog helpers used across the FrameLab UI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import QDir


def resolve_dialog_start_path(start: str | Path = "") -> Path:
    """Return the closest existing directory to use as a dialog start path."""

    if isinstance(start, Path):
        candidate = start.expanduser()
    else:
        text = str(start).strip()
        candidate = Path(text).expanduser() if text else Path.home()
    if candidate.is_file():
        return candidate.parent
    if candidate.is_dir():
        return candidate
    for parent in candidate.parents:
        if parent.is_dir():
            return parent
    return Path.home()


def _theme_stylesheet_for(parent: qtw.QWidget | None) -> str:
    """Return the nearest available host stylesheet for dialogs."""

    for candidate in (parent, parent.window() if isinstance(parent, qtw.QWidget) else None):
        if not isinstance(candidate, qtw.QWidget):
            continue
        getter = getattr(candidate, "_current_theme_stylesheet", None)
        if callable(getter):
            try:
                stylesheet = str(getter() or "")
            except Exception:
                stylesheet = ""
            if stylesheet:
                return stylesheet
    return ""


def _apply_dialog_defaults(
    dialog: qtw.QFileDialog,
    *,
    parent: qtw.QWidget | None,
) -> None:
    """Apply the app's themed non-native dialog configuration."""

    dialog.setOption(qtw.QFileDialog.DontUseNativeDialog, True)
    stylesheet = _theme_stylesheet_for(parent)
    if stylesheet:
        dialog.setStyleSheet(stylesheet)


def choose_existing_directory(
    parent: qtw.QWidget | None,
    title: str,
    start: str | Path = "",
) -> str:
    """Open a themed directory picker and return one selected folder path."""

    start_path = resolve_dialog_start_path(start)
    dialog = qtw.QFileDialog(parent, str(title), str(start_path))
    dialog.setFileMode(qtw.QFileDialog.Directory)
    dialog.setFilter(QDir.AllDirs | QDir.Dirs | QDir.NoDotAndDotDot)
    dialog.setOption(qtw.QFileDialog.ShowDirsOnly, True)
    dialog.setDirectory(str(start_path))
    _apply_dialog_defaults(dialog, parent=parent)
    if not dialog.exec():
        return ""
    selected = dialog.selectedFiles()
    return selected[0] if selected else ""


def choose_open_file(
    parent: qtw.QWidget | None,
    title: str,
    start: str | Path = "",
    *,
    name_filters: Iterable[str] = (),
    selected_name_filter: str | None = None,
) -> str:
    """Open a themed file picker and return one selected file path."""

    if isinstance(start, Path):
        start_path = start.expanduser()
    else:
        start_path = Path(str(start).strip()).expanduser() if str(start).strip() else Path.home()
    start_dir = resolve_dialog_start_path(start_path)
    dialog = qtw.QFileDialog(parent, str(title), str(start_dir))
    dialog.setAcceptMode(qtw.QFileDialog.AcceptOpen)
    dialog.setFileMode(qtw.QFileDialog.ExistingFile)
    dialog.setDirectory(str(start_dir))
    filters = [str(name_filter).strip() for name_filter in name_filters if str(name_filter).strip()]
    if filters:
        dialog.setNameFilters(filters)
        preferred = str(selected_name_filter or "").strip()
        if preferred:
            dialog.selectNameFilter(preferred)
        else:
            dialog.selectNameFilter(filters[0])
    file_name = start_path.name.strip()
    if file_name:
        dialog.selectFile(file_name)
    _apply_dialog_defaults(dialog, parent=parent)
    if not dialog.exec():
        return ""
    selected = dialog.selectedFiles()
    return selected[0] if selected else ""


def choose_save_file(
    parent: qtw.QWidget | None,
    title: str,
    start: str | Path = "",
    *,
    name_filters: Iterable[str] = (),
    selected_name_filter: str | None = None,
) -> tuple[str, str]:
    """Open a themed save dialog and return the chosen path and filter."""

    if isinstance(start, Path):
        start_path = start.expanduser()
    else:
        start_path = Path(str(start).strip()).expanduser() if str(start).strip() else Path.home()
    start_dir = resolve_dialog_start_path(start_path)
    dialog = qtw.QFileDialog(parent, str(title), str(start_dir))
    dialog.setAcceptMode(qtw.QFileDialog.AcceptSave)
    dialog.setDirectory(str(start_dir))
    filters = [str(name_filter).strip() for name_filter in name_filters if str(name_filter).strip()]
    if filters:
        dialog.setNameFilters(filters)
        preferred = str(selected_name_filter or "").strip()
        if preferred:
            dialog.selectNameFilter(preferred)
        else:
            dialog.selectNameFilter(filters[0])
    file_name = start_path.name.strip()
    if file_name:
        dialog.selectFile(file_name)
    _apply_dialog_defaults(dialog, parent=parent)
    if not dialog.exec():
        return "", ""
    selected = dialog.selectedFiles()
    return (selected[0] if selected else "", dialog.selectedNameFilter())
