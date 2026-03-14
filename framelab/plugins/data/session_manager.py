"""Data-page plugin for session-level acquisition management."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets as qtw
from PySide6.QtCore import Qt

from ..registry import register_page_plugin
from .session_manager_ui_state import (
    SessionManagerActionState,
    build_session_manager_action_state,
)
from ...acquisition_datacard import find_session_root
from ...session_manager import (
    AcquisitionDatacardClipboard,
    AcquisitionEntry,
    SessionIndex,
    add_acquisition,
    copy_acquisition_datacard,
    delete_acquisition,
    inspect_session,
    paste_acquisition_datacard,
    reindex_acquisitions,
    rename_acquisition_label,
    set_acquisition_ebus_enabled,
)
from ...ui_primitives import ChipSpec, SummaryItem, build_page_header, build_summary_strip
from ...widgets import install_large_header_resize_cursor
from ...window_drag import enable_window_content_drag


def _selected_folder(host_window: qtw.QWidget) -> Path | None:
    """Return the currently selected folder from the host window."""
    folder_edit = getattr(host_window, "folder_edit", None)
    if not isinstance(folder_edit, qtw.QLineEdit):
        return None
    text = folder_edit.text().strip()
    if not text:
        return None
    folder = Path(text).expanduser()
    return folder if folder.exists() else None


def _initial_session_root(host_window: qtw.QWidget) -> str:
    """Resolve the best initial session root from the host selection."""
    selected = _selected_folder(host_window)
    if selected is None:
        return ""
    session_root = find_session_root(selected)
    if session_root is not None:
        return str(session_root)
    if selected.is_dir():
        candidate = selected.joinpath("session_datacard.json")
        if candidate.is_file():
            return str(selected)
    return str(selected)


def _current_clipboard(
    host_window: qtw.QWidget,
) -> AcquisitionDatacardClipboard | None:
    """Return the host-owned session-manager clipboard payload."""
    clipboard = getattr(host_window, "_session_manager_datacard_clipboard", None)
    return (
        clipboard
        if isinstance(clipboard, AcquisitionDatacardClipboard)
        else None
    )


def _set_current_clipboard(
    host_window: qtw.QWidget,
    clipboard: AcquisitionDatacardClipboard | None,
) -> None:
    """Store the host-owned session-manager clipboard payload."""
    setattr(host_window, "_session_manager_datacard_clipboard", clipboard)


class SessionManagerDialog(qtw.QDialog):
    """Dialog for managing acquisitions inside one session."""

    def __init__(
        self,
        host_window: qtw.QWidget,
        *,
        initial_session_root: str = "",
    ) -> None:
        super().__init__(host_window)
        self._host_window = host_window
        self._session_index: SessionIndex | None = None
        self._selected_path: Path | None = None
        self._has_ebus_tools = (
            "ebus_config_tools"
            in getattr(host_window, "_enabled_plugin_ids", frozenset())
        )

        self.setWindowTitle("Session Manager")
        self.setWindowFlag(Qt.Window, True)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._header = build_page_header(
            "Session Manager",
            (
                "Manage acquisition folders, numbering, datacard copy/paste, "
                "and acquisition-local eBUS enable state for one session."
            ),
        )
        layout.addWidget(self._header)
        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)

        command_row = qtw.QHBoxLayout()
        self._session_edit = qtw.QLineEdit(initial_session_root)
        self._session_edit.setPlaceholderText("Select session folder")
        command_row.addWidget(self._session_edit, 1)

        self._browse_button = qtw.QPushButton("Browse...")
        self._browse_button.clicked.connect(self._browse_session)
        command_row.addWidget(self._browse_button)

        self._load_button = qtw.QPushButton("Load Session")
        self._load_button.setObjectName("AccentButton")
        self._load_button.clicked.connect(self._load_session)
        command_row.addWidget(self._load_button)
        layout.addLayout(command_row)

        controls_row = qtw.QHBoxLayout()
        controls_row.setSpacing(8)
        index_label = qtw.QLabel("Starting Number")
        index_label.setObjectName("SectionTitle")
        controls_row.addWidget(index_label)

        self._starting_number_spin = qtw.QSpinBox()
        self._starting_number_spin.setRange(0, 999999)
        self._starting_number_spin.setValue(1)
        controls_row.addWidget(self._starting_number_spin)

        self._reindex_button = qtw.QPushButton("Normalize/Reindex")
        self._reindex_button.clicked.connect(self._reindex_session)
        controls_row.addWidget(self._reindex_button)
        controls_row.addStretch(1)
        layout.addLayout(controls_row)

        self._warning_label = qtw.QLabel("")
        self._warning_label.setObjectName("MutedLabel")
        self._warning_label.setWordWrap(True)
        layout.addWidget(self._warning_label)

        self._table = qtw.QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            [
                "Number",
                "Name",
                "Folder",
                "Datacard",
                "eBUS Snapshot",
                "eBUS",
                "Frames",
            ],
        )
        self._table.setSelectionBehavior(qtw.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(qtw.QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(qtw.QAbstractItemView.NoEditTriggers)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(
            self._show_table_context_menu,
        )
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            2,
            qtw.QHeaderView.Stretch,
        )
        install_large_header_resize_cursor(self._table.horizontalHeader())
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(
            lambda _index: self._load_selected_acquisition(),
        )
        layout.addWidget(self._table, 1)

        actions_row = qtw.QHBoxLayout()
        actions_row.setSpacing(8)

        self._load_selected_button = qtw.QPushButton("Load Selected")
        self._load_selected_button.clicked.connect(self._load_selected_acquisition)
        actions_row.addWidget(self._load_selected_button)

        self._add_button = qtw.QPushButton("Add Acquisition")
        self._add_button.clicked.connect(self._add_acquisition)
        actions_row.addWidget(self._add_button)

        self._rename_button = qtw.QPushButton("Rename")
        self._rename_button.clicked.connect(self._rename_selected_label)
        actions_row.addWidget(self._rename_button)

        self._delete_button = qtw.QPushButton("Delete Acquisition")
        self._delete_button.clicked.connect(self._delete_selected_acquisition)
        actions_row.addWidget(self._delete_button)

        self._edit_datacard_button = qtw.QPushButton("Edit Datacard")
        self._edit_datacard_button.clicked.connect(self._open_datacard_wizard)
        actions_row.addWidget(self._edit_datacard_button)

        self._copy_datacard_button = qtw.QPushButton("Copy Datacard")
        self._copy_datacard_button.clicked.connect(self._copy_datacard)
        actions_row.addWidget(self._copy_datacard_button)

        self._paste_datacard_button = qtw.QPushButton("Paste Datacard")
        self._paste_datacard_button.clicked.connect(self._paste_datacard)
        actions_row.addWidget(self._paste_datacard_button)

        self._toggle_ebus_button = qtw.QPushButton("Toggle eBUS")
        self._toggle_ebus_button.clicked.connect(self._toggle_ebus)
        actions_row.addWidget(self._toggle_ebus_button)

        actions_row.addStretch(1)
        layout.addLayout(actions_row)

        close_row = qtw.QHBoxLayout()
        close_row.addStretch(1)
        self._close_button = qtw.QPushButton("Close")
        self._close_button.clicked.connect(self.accept)
        close_row.addWidget(self._close_button)
        layout.addLayout(close_row)

        enable_window_content_drag(self)

        self.apply_initial_session_root(initial_session_root)

    def _browse_session(self) -> None:
        """Browse to one session folder."""
        start = self._session_edit.text().strip() or str(Path.home())
        folder = qtw.QFileDialog.getExistingDirectory(
            self,
            "Select Session Folder",
            start,
            qtw.QFileDialog.ShowDirsOnly,
        )
        if not folder:
            return
        self._session_edit.setText(folder)
        self._load_session()

    def _load_session(self) -> None:
        """Load one session into the manager table."""
        text = self._session_edit.text().strip()
        if not text:
            self._session_index = None
            self._table.setRowCount(0)
            self._warning_label.setText("No session selected.")
            self._refresh_header_state()
            self._refresh_action_state()
            return
        candidate = Path(text).expanduser()
        session_root = find_session_root(candidate)
        if session_root is None and candidate.is_dir():
            datacard_path = candidate.joinpath("session_datacard.json")
            if datacard_path.is_file():
                session_root = candidate
        if session_root is None or not session_root.is_dir():
            qtw.QMessageBox.warning(
                self,
                "Load Session",
                "Choose a folder inside a valid session tree.",
            )
            return
        self._session_edit.setText(str(session_root))
        self._session_index = inspect_session(session_root)
        self._starting_number_spin.setValue(self._session_index.starting_number)
        self._selected_path = None
        self._refresh_table()
        self._refresh_header_state()
        self._refresh_action_state()
        enable_window_content_drag(self)

    def apply_initial_session_root(self, session_root: str) -> None:
        """Update the dialog to one initial session root from the host."""
        text = str(session_root or "").strip()
        if text:
            current = self._session_edit.text().strip()
            if current != text or self._session_index is None:
                self._session_edit.setText(text)
                self._load_session()
                return
        if self._session_index is None:
            self._refresh_header_state()
            self._refresh_action_state()

    def _refresh_table(self) -> None:
        """Rebuild the acquisition table from the current session index."""
        self._table.setRowCount(0)
        if self._session_index is None:
            self._warning_label.setText("No session loaded.")
            return
        self._warning_label.setText(self._session_index.warning_text)
        for row_index, entry in enumerate(self._session_index.entries):
            self._table.insertRow(row_index)
            values = [
                str(entry.number),
                entry.label or "",
                entry.folder_name,
                "Present" if entry.datacard_present else "Missing",
                "Present" if entry.ebus_snapshot_present else "None",
                "Enabled" if entry.ebus_enabled else "Disabled",
                (
                    str(entry.frame_count)
                    if entry.frame_count is not None
                    else "Unknown"
                ),
            ]
            for column, value in enumerate(values):
                item = qtw.QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                if column == 2:
                    item.setData(Qt.UserRole, str(entry.path))
                    item.setToolTip(str(entry.path))
                self._table.setItem(row_index, column, item)
        self._table.resizeColumnsToContents()
        self._restore_selection()

    def _restore_selection(self) -> None:
        """Restore row selection after a table rebuild."""
        if self._selected_path is None:
            if self._table.rowCount() > 0:
                self._table.selectRow(0)
            return
        selected_text = str(self._selected_path)
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 2)
            if item is not None and item.data(Qt.UserRole) == selected_text:
                self._table.selectRow(row)
                return
        if self._table.rowCount() > 0:
            self._table.selectRow(0)

    def _selected_entry(self) -> AcquisitionEntry | None:
        """Return the currently selected acquisition entry."""
        if self._session_index is None:
            return None
        selected_ranges = self._table.selectedRanges()
        if not selected_ranges:
            return None
        row = selected_ranges[0].topRow()
        if not (0 <= row < len(self._session_index.entries)):
            return None
        return self._session_index.entries[row]

    def _on_selection_changed(self) -> None:
        """Update current selection bookkeeping."""
        entry = self._selected_entry()
        self._selected_path = entry.path if entry is not None else None
        self._refresh_header_state()
        self._refresh_action_state()

    def _current_action_state(self) -> SessionManagerActionState:
        """Return current pure action-state snapshot for the dialog."""
        return build_session_manager_action_state(
            self._session_index,
            self._selected_entry(),
            clipboard_ready=_current_clipboard(self._host_window) is not None,
            has_ebus_tools=self._has_ebus_tools,
        )

    def _refresh_header_state(self) -> None:
        """Refresh header chips and summary state."""
        session_loaded = self._session_index is not None
        numbering_valid = (
            self._session_index.numbering_valid
            if self._session_index is not None
            else True
        )
        clipboard_ready = _current_clipboard(self._host_window) is not None
        chips = [
            ChipSpec(
                "Session loaded" if session_loaded else "No session",
                level="success" if session_loaded else "neutral",
            ),
            ChipSpec(
                "Numbering valid" if numbering_valid else "Needs reindex",
                level="success" if numbering_valid else "warning",
            ),
            ChipSpec(
                "Clipboard ready" if clipboard_ready else "Clipboard empty",
                level="info" if clipboard_ready else "neutral",
            ),
        ]
        if self._has_ebus_tools:
            chips.append(ChipSpec("eBUS toggle available", level="info"))
        self._header.set_chips(chips)

        selected_entry = self._selected_entry()
        self._summary_strip.set_items(
            [
                SummaryItem(
                    "Session",
                    self._session_index.session_root.name
                    if self._session_index is not None
                    else "None",
                    level="success" if session_loaded else "neutral",
                    tooltip=(
                        str(self._session_index.session_root)
                        if self._session_index is not None
                        else ""
                    ),
                ),
                SummaryItem(
                    "Acquisitions",
                    str(len(self._session_index.entries))
                    if self._session_index is not None
                    else "0",
                    level="info" if session_loaded else "neutral",
                ),
                SummaryItem(
                    "Starting Number",
                    str(self._starting_number_spin.value()),
                    level="info" if session_loaded else "neutral",
                ),
                SummaryItem(
                    "Numbering",
                    "Valid" if numbering_valid else "Warning",
                    level="success" if numbering_valid else "warning",
                ),
                SummaryItem(
                    "Selected",
                    selected_entry.folder_name if selected_entry is not None else "None",
                    level="info" if selected_entry is not None else "neutral",
                    tooltip=str(selected_entry.path) if selected_entry is not None else "",
                ),
            ]
        )

    def _refresh_action_state(self) -> None:
        """Enable or disable action buttons for the current state."""
        action_state = self._current_action_state()
        self._load_selected_button.setEnabled(action_state.load_selected_enabled)
        self._add_button.setEnabled(action_state.add_enabled)
        self._rename_button.setEnabled(action_state.rename_enabled)
        self._delete_button.setEnabled(action_state.delete_enabled)
        self._edit_datacard_button.setEnabled(action_state.edit_datacard_enabled)
        self._copy_datacard_button.setEnabled(action_state.copy_datacard_enabled)
        self._paste_datacard_button.setEnabled(action_state.paste_datacard_enabled)
        self._toggle_ebus_button.setEnabled(action_state.toggle_ebus_enabled)
        self._reindex_button.setEnabled(action_state.reindex_enabled)

    def _load_selected_acquisition(self) -> None:
        """Load the selected acquisition into the host application."""
        entry = self._selected_entry()
        if entry is None:
            return
        folder_edit = getattr(self._host_window, "folder_edit", None)
        if isinstance(folder_edit, qtw.QLineEdit):
            folder_edit.setText(str(entry.path))
        load_folder = getattr(self._host_window, "load_folder", None)
        if callable(load_folder):
            load_folder()

    def _prompt_label(
        self,
        title: str,
        current: str = "",
    ) -> str | None:
        """Prompt for an optional acquisition name suffix."""
        text, accepted = qtw.QInputDialog.getText(
            self,
            title,
            "Name (leave blank for no __name suffix):",
            text=current,
        )
        if not accepted:
            return None
        clean = text.strip()
        return clean or ""

    def _add_acquisition(self) -> None:
        """Create a new acquisition folder."""
        if self._session_index is None:
            return
        label = self._prompt_label("Add Acquisition")
        if label is None:
            return
        try:
            result = add_acquisition(
                self._session_index.session_root,
                label=label or None,
                starting_number=self._starting_number_spin.value(),
            )
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Add Acquisition", str(exc))
            return
        self._load_session()
        if result.created_path is not None:
            self._selected_path = result.created_path
            self._restore_selection()
            self._refresh_header_state()
            self._refresh_action_state()

    def _rename_selected_label(self) -> None:
        """Rename the selected acquisition name suffix."""
        entry = self._selected_entry()
        if entry is None:
            return
        label = self._prompt_label("Rename Acquisition", entry.label or "")
        if label is None:
            return
        try:
            result = rename_acquisition_label(entry.path, label or None)
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Rename Acquisition", str(exc))
            return
        self._apply_host_path_mutation(result)
        self._selected_path = (
            result.renamed_paths[0][1]
            if result.renamed_paths
            else entry.path
        )
        self._load_session()

    def _show_table_context_menu(self, position: QtCore.QPoint) -> None:
        """Show row actions for the acquisition under the cursor."""
        item = self._table.itemAt(position)
        if item is not None:
            self._table.selectRow(item.row())
        entry = self._selected_entry()
        if entry is None:
            return
        action_state = self._current_action_state()

        menu = qtw.QMenu(self)
        load_action = menu.addAction("Load Selected Acquisition")
        load_action.setEnabled(action_state.load_selected_enabled)
        load_action.triggered.connect(self._load_selected_acquisition)

        menu.addSeparator()
        rename_action = menu.addAction("Rename")
        rename_action.setEnabled(action_state.rename_enabled)
        rename_action.triggered.connect(self._rename_selected_label)
        delete_action = menu.addAction("Delete Acquisition")
        delete_action.setEnabled(action_state.delete_enabled)
        delete_action.triggered.connect(self._delete_selected_acquisition)

        menu.addSeparator()
        edit_action = menu.addAction("Edit Datacard")
        edit_action.setEnabled(action_state.edit_datacard_enabled)
        edit_action.triggered.connect(self._open_datacard_wizard)
        copy_action = menu.addAction("Copy Datacard")
        copy_action.setEnabled(action_state.copy_datacard_enabled)
        copy_action.triggered.connect(self._copy_datacard)
        paste_action = menu.addAction("Paste Datacard")
        paste_action.setEnabled(action_state.paste_datacard_enabled)
        paste_action.triggered.connect(self._paste_datacard)

        if self._has_ebus_tools:
            menu.addSeparator()
            toggle_action = menu.addAction(action_state.toggle_ebus_text)
            toggle_action.setEnabled(action_state.toggle_ebus_enabled)
            toggle_action.triggered.connect(self._toggle_ebus)

        menu.exec(self._table.viewport().mapToGlobal(position))

    def _confirm_delete_message(self, entry: AcquisitionEntry) -> str:
        """Return confirmation text for a delete operation."""
        loaded_folder = _selected_folder(self._host_window)
        loaded_note = ""
        if loaded_folder is not None:
            loaded_note = (
                "\n\nA dataset is currently loaded. Confirming will trigger a full refresh."
            )
            if entry.path in loaded_folder.parents or loaded_folder == entry.path:
                loaded_note = (
                    "\n\nThe currently loaded dataset is inside this acquisition. "
                    "Confirming will unload it and refresh the UI."
                )
        return (
            f"Delete acquisition folder '{entry.folder_name}'?\n"
            "Later acquisitions will be renumbered to close the gap."
            f"{loaded_note}"
        )

    def _delete_selected_acquisition(self) -> None:
        """Delete the selected acquisition after confirmation."""
        entry = self._selected_entry()
        if entry is None or self._session_index is None:
            return
        answer = qtw.QMessageBox.question(
            self,
            "Delete Acquisition",
            self._confirm_delete_message(entry),
            qtw.QMessageBox.Yes | qtw.QMessageBox.No,
            qtw.QMessageBox.No,
        )
        if answer != qtw.QMessageBox.Yes:
            return
        try:
            result = delete_acquisition(self._session_index.session_root, entry.path)
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Delete Acquisition", str(exc))
            return
        self._selected_path = None
        self._apply_host_path_mutation(result, force_refresh_if_loaded=True)
        self._load_session()

    def _open_datacard_wizard(self) -> None:
        """Open the acquisition datacard wizard for the selected acquisition."""
        entry = self._selected_entry()
        if entry is None:
            return
        from .acquisition_datacard_wizard import AcquisitionDatacardWizardDialog

        dialog = AcquisitionDatacardWizardDialog(None, str(entry.path))
        if hasattr(dialog, "place_near_host"):
            dialog.place_near_host(self._host_window)
        dialog.exec()
        self._load_session()
        self._reload_loaded_dataset_if_inside(entry.path)

    def _copy_datacard(self) -> None:
        """Copy the selected acquisition datacard."""
        entry = self._selected_entry()
        if entry is None:
            return
        clipboard = copy_acquisition_datacard(entry.path)
        if clipboard is None:
            qtw.QMessageBox.information(
                self,
                "Copy Datacard",
                "The selected acquisition does not have an acquisition datacard yet.",
            )
            return
        _set_current_clipboard(self._host_window, clipboard)
        self._refresh_header_state()
        self._refresh_action_state()

    def _paste_datacard(self) -> None:
        """Paste the copied datacard onto the selected acquisition."""
        entry = self._selected_entry()
        clipboard = _current_clipboard(self._host_window)
        if entry is None or clipboard is None:
            return
        try:
            paste_acquisition_datacard(entry.path, clipboard)
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Paste Datacard", str(exc))
            return
        self._load_session()
        self._reload_loaded_dataset_if_inside(entry.path)

    def _toggle_ebus(self) -> None:
        """Toggle acquisition-local eBUS enabled state."""
        entry = self._selected_entry()
        if entry is None:
            return
        try:
            set_acquisition_ebus_enabled(entry.path, not entry.ebus_enabled)
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Toggle eBUS", str(exc))
            return
        self._load_session()
        self._reload_loaded_dataset_if_inside(entry.path)

    def _reindex_session(self) -> None:
        """Normalize or reindex acquisition numbering from the chosen base."""
        if self._session_index is None:
            return
        answer = qtw.QMessageBox.question(
            self,
            "Normalize/Reindex",
            (
                f"Renumber acquisitions contiguously from {self._starting_number_spin.value()}?\n"
                "Acquisition folder names will change and loaded datasets may be reloaded."
            ),
            qtw.QMessageBox.Yes | qtw.QMessageBox.No,
            qtw.QMessageBox.No,
        )
        if answer != qtw.QMessageBox.Yes:
            return
        try:
            result = reindex_acquisitions(
                self._session_index.session_root,
                starting_number=self._starting_number_spin.value(),
            )
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Normalize/Reindex", str(exc))
            return
        self._apply_host_path_mutation(result)
        self._load_session()

    def _reload_loaded_dataset_if_inside(self, acquisition_root: Path) -> None:
        """Reload the host dataset when it belongs to the edited acquisition."""
        loaded_folder = _selected_folder(self._host_window)
        if loaded_folder is None:
            return
        if acquisition_root == loaded_folder or acquisition_root in loaded_folder.parents:
            load_folder = getattr(self._host_window, "load_folder", None)
            if callable(load_folder):
                load_folder()

    def _apply_host_path_mutation(
        self,
        result: object,
        *,
        force_refresh_if_loaded: bool = False,
    ) -> None:
        """Apply acquisition-path mutations to the host dataset selection."""
        if not hasattr(result, "deleted_paths") or not hasattr(result, "renamed_paths"):
            return
        loaded_folder = _selected_folder(self._host_window)
        if loaded_folder is None:
            return
        unloaded = False
        deleted_paths = tuple(getattr(result, "deleted_paths", ()))
        renamed_paths = tuple(getattr(result, "renamed_paths", ()))
        for deleted_path in deleted_paths:
            if loaded_folder == deleted_path or deleted_path in loaded_folder.parents:
                unload = getattr(self._host_window, "unload_folder", None)
                if callable(unload):
                    unload(clear_folder_edit=True)
                unloaded = True
                break
        if unloaded:
            return

        new_loaded_path = loaded_folder
        for old_path, new_path in renamed_paths:
            if loaded_folder == old_path or old_path in loaded_folder.parents:
                relative = loaded_folder.relative_to(old_path)
                new_loaded_path = new_path.joinpath(relative)
                folder_edit = getattr(self._host_window, "folder_edit", None)
                if isinstance(folder_edit, qtw.QLineEdit):
                    folder_edit.setText(str(new_loaded_path))
                load_folder = getattr(self._host_window, "load_folder", None)
                if callable(load_folder):
                    load_folder()
                return

        if deleted_paths and force_refresh_if_loaded:
            load_folder = getattr(self._host_window, "load_folder", None)
            if callable(load_folder):
                load_folder()


class SessionManagerPlugin:
    """Runtime plugin entrypoint for session-level acquisition management."""

    plugin_id = "session_manager"
    display_name = "Session Manager"
    dependencies = ("acquisition_datacard_wizard",)

    @staticmethod
    def populate_page_menu(host_window: qtw.QWidget, menu: qtw.QMenu) -> None:
        """Populate runtime actions for the session manager."""
        open_action = menu.addAction("Open Session Manager...")
        open_action.setToolTip(
            "Manage acquisition folders, numbering, datacard copy/paste, and eBUS enable state for one session.",
        )
        open_action.setStatusTip(open_action.toolTip())
        open_action.triggered.connect(
            lambda _checked=False: SessionManagerPlugin.open_manager(host_window),
        )

    @staticmethod
    def open_manager(host_window: qtw.QWidget) -> None:
        """Launch the session manager dialog."""
        dialog = getattr(host_window, "_session_manager_dialog", None)
        if isinstance(dialog, SessionManagerDialog):
            dialog.apply_initial_session_root(_initial_session_root(host_window))
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        dialog = SessionManagerDialog(
            host_window,
            initial_session_root=_initial_session_root(host_window),
        )
        setattr(host_window, "_session_manager_dialog", dialog)
        dialog.destroyed.connect(
            lambda _obj=None, host=host_window: setattr(
                host,
                "_session_manager_dialog",
                None,
            ),
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()


register_page_plugin(SessionManagerPlugin, page="data")
