"""Standalone data plugin for eBUS config inspection and comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtWidgets as qtw

from ....ebus import describe_ebus_source
from ...registry import register_page_plugin
from ._dialogs import (
    EbusCompareDialog,
    EbusInspectDialog,
    _choose_ebus_file,
)


def _selected_acquisition_root(host_window: qtw.QWidget) -> Optional[Path]:
    """Return the currently selected acquisition folder from the host window."""
    folder_edit = getattr(host_window, "folder_edit", None)
    if not isinstance(folder_edit, qtw.QLineEdit):
        return None
    folder = Path(folder_edit.text().strip()).expanduser()
    return folder if folder.is_dir() else None


def _ebus_browse_start(host_window: qtw.QWidget) -> str:
    """Prefer the selected acquisition root when browsing for eBUS files."""
    acquisition_root = _selected_acquisition_root(host_window)
    if acquisition_root is not None:
        return str(acquisition_root)
    return str(Path.home())


class EbusConfigToolsPlugin:
    """Runtime menu actions for eBUS config tooling."""

    plugin_id = "ebus_config_tools"
    display_name = "eBUS Config Tools"
    dependencies: tuple[str, ...] = ()

    @staticmethod
    def populate_page_menu(host_window: qtw.QWidget, menu: qtw.QMenu) -> None:
        """Populate the Plugins menu with eBUS runtime actions."""
        inspect_action = menu.addAction("Inspect eBUS Config File...")
        inspect_action.setToolTip("Open a standalone eBUS config file for read-only inspection.")
        inspect_action.setStatusTip(inspect_action.toolTip())
        inspect_action.triggered.connect(
            lambda _checked=False: EbusConfigToolsPlugin.inspect_file(host_window),
        )

        compare_action = menu.addAction("Compare eBUS Configs...")
        compare_action.setToolTip("Compare two or more raw or effective eBUS sources.")
        compare_action.setStatusTip(compare_action.toolTip())
        compare_action.triggered.connect(
            lambda _checked=False: EbusConfigToolsPlugin.compare_sources(host_window),
        )

        enabled_ids = getattr(host_window, "_enabled_plugin_ids", frozenset())
        if "acquisition_datacard_wizard" in enabled_ids:
            menu.addSeparator()
            wizard_action = menu.addAction("Open Datacard Wizard")
            wizard_action.setToolTip(
                "Open the datacard wizard to author acquisition metadata and any eBUS-backed fields that the catalog marks as overridable.",
            )
            wizard_action.setStatusTip(wizard_action.toolTip())
            wizard_action.triggered.connect(
                lambda _checked=False: EbusConfigToolsPlugin.open_datacard_wizard(host_window),
            )

    @staticmethod
    def inspect_file(host_window: qtw.QWidget) -> None:
        """Open a standalone ``.pvcfg`` file in the inspect dialog."""
        path = _choose_ebus_file(host_window, _ebus_browse_start(host_window))
        if not path:
            return
        try:
            dialog = EbusInspectDialog(path, parent=None)
        except Exception as exc:
            qtw.QMessageBox.warning(host_window, "Inspect eBUS Config", str(exc))
            return
        dialog.exec()

    @staticmethod
    def compare_sources(host_window: qtw.QWidget) -> None:
        """Open raw/effective eBUS compare dialog."""
        acquisition_root = _selected_acquisition_root(host_window)
        dialog = EbusCompareDialog(
            parent=None,
            initial_path=_ebus_browse_start(host_window),
        )
        if acquisition_root is not None and describe_ebus_source(acquisition_root) is not None:
            dialog.add_source(acquisition_root)
        dialog.exec()

    @staticmethod
    def open_datacard_wizard(host_window: qtw.QWidget) -> None:
        """Open the datacard wizard when that plugin is enabled."""
        from ..acquisition_datacard_wizard import AcquisitionDatacardWizardPlugin

        AcquisitionDatacardWizardPlugin.open_wizard(host_window)


register_page_plugin(EbusConfigToolsPlugin, page="data")
