"""Data-page construction and metadata controls."""

from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt, QSignalBlocker

from ..acquisition_datacard import (
    ACQUISITION_DATACARD_NAME,
    CAMPAIGN_DATACARD_NAME,
    SESSION_DATACARD_NAME,
)
from ..datacard_labels import label_for_metadata_field
from ..metadata import (
    clear_metadata_cache,
    extract_path_metadata,
    path_has_acquisition_datacard,
)
from ..scan_settings import save_skip_patterns
from ..ui_primitives import (
    ChipSpec,
    SummaryItem,
    build_page_header,
    build_summary_strip,
    make_status_chip,
)
from ..widgets import install_large_header_resize_cursor


class _SkipRulesEditorDialog(qtw.QDialog):
    """Dedicated editor window for dataset skip rules."""

    def __init__(self, host: DataPageMixin) -> None:
        super().__init__(None)
        self._host = host
        self.setWindowTitle("Edit Skip Rules")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(920, 360)
        self.setMinimumSize(720, 280)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        row = qtw.QHBoxLayout()
        row.setSpacing(8)

        self.pattern_edit = qtw.QLineEdit()
        self.pattern_edit.setPlaceholderText(
            "Wildcard or exact name (e.g. temp, */cache/*, *.bak)",
        )
        self.pattern_edit.setToolTip(
            "Add file/folder patterns that should be ignored during scan.",
        )
        self.pattern_edit.returnPressed.connect(
            lambda: self._host._add_skip_pattern(self.pattern_edit),
        )
        row.addWidget(self.pattern_edit, 1)

        add_button = qtw.QPushButton("Add Rule")
        add_button.setToolTip("Add a new folder/file skip pattern.")
        add_button.clicked.connect(
            lambda _checked=False: self._host._add_skip_pattern(
                self.pattern_edit,
            ),
        )
        row.addWidget(add_button)

        delete_button = qtw.QPushButton("Remove Selected")
        delete_button.setToolTip("Remove selected skip rules.")
        delete_button.clicked.connect(
            lambda _checked=False: self._host._delete_selected_skip_patterns(
                self.pattern_list,
            ),
        )
        row.addWidget(delete_button)

        reset_button = qtw.QPushButton("Clear All")
        reset_button.setToolTip("Remove all skip rules.")
        reset_button.clicked.connect(
            lambda _checked=False: self._host._reset_skip_patterns(),
        )
        row.addWidget(reset_button)
        layout.addLayout(row)

        self.pattern_list = qtw.QListWidget()
        self.pattern_list.setSelectionMode(
            qtw.QAbstractItemView.ExtendedSelection,
        )
        self.pattern_list.setAlternatingRowColors(True)
        layout.addWidget(self.pattern_list, 1)

        self.hint_label = qtw.QLabel()
        self.hint_label.setObjectName("MutedLabel")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        button_row = qtw.QHBoxLayout()
        button_row.addStretch(1)
        close_button = qtw.QPushButton("Close")
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)


class DataPageMixin:
    """Dataset input, skip rules, and metadata table helpers."""

    def _apply_data_page_density(self, tokens) -> None:
        """Apply density tokens to shared Data-page layouts."""

        layout = getattr(self, "_data_page_layout", None)
        if layout is not None:
            layout.setSpacing(tokens.page_spacing)
        command_layout = getattr(self, "_data_command_layout", None)
        if command_layout is not None:
            self._set_uniform_layout_margins(
                command_layout,
                tokens.command_bar_margin_h,
                tokens.command_bar_margin_v,
            )
            command_layout.setSpacing(tokens.command_bar_spacing)
        advanced_row = getattr(self, "_data_advanced_row_layout", None)
        if advanced_row is not None:
            advanced_row.setSpacing(tokens.page_spacing)
        for name in (
            "_data_skip_layout",
            "_data_metadata_outer_layout",
            "_data_table_layout",
        ):
            panel_layout = getattr(self, name, None)
            if panel_layout is None:
                continue
            self._set_uniform_layout_margins(
                panel_layout,
                tokens.panel_margin_h,
                tokens.panel_margin_v,
            )
            panel_layout.setSpacing(tokens.panel_spacing)
        for name in (
            "_data_metadata_header_row",
            "_data_metadata_group_layout",
            "_data_metadata_row",
            "_data_skip_header_row",
        ):
            nested_layout = getattr(self, name, None)
            if nested_layout is None:
                continue
            nested_layout.setSpacing(tokens.panel_spacing)

    def _build_data_page(self) -> qtw.QWidget:
        """Build dataset-loading and metadata inspection page."""
        page = qtw.QWidget()
        layout = qtw.QVBoxLayout(page)
        self._data_page_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._data_header = build_page_header(
            "Dataset Workbench",
            (
                "Load a dataset, control intake rules, and verify metadata "
                "before measurement and analysis."
            ),
        )
        layout.addWidget(self._data_header)
        layout.addWidget(self._build_processing_failure_banner("Data"))

        command_bar = qtw.QFrame()
        command_bar.setObjectName("CommandBar")
        command_layout = qtw.QHBoxLayout(command_bar)
        self._data_command_layout = command_layout
        command_layout.setContentsMargins(14, 12, 14, 12)
        command_layout.setSpacing(8)

        folder_label = qtw.QLabel("Dataset")
        folder_label.setObjectName("SectionTitle")
        command_layout.addWidget(folder_label)

        self.folder_edit = qtw.QLineEdit()
        self.folder_edit.setPlaceholderText(
            "Select folder containing TIFF files",
        )
        self.folder_edit.setToolTip(
            "Root folder to scan recursively for TIFF images.",
        )
        self.folder_edit.textChanged.connect(
            lambda text: self._refresh_ebus_config_status(
                Path(text).expanduser() if text.strip() else None,
            ),
        )
        self.folder_edit.returnPressed.connect(self.load_folder)
        command_layout.addWidget(self.folder_edit, 1)

        browse_button = qtw.QPushButton("Browse Folder...")
        browse_button.setToolTip("Open dataset folder chooser.")
        browse_button.clicked.connect(
            lambda _checked=False: self.browse_folder(),
        )
        command_layout.addWidget(browse_button)

        load_button = qtw.QPushButton("Scan Folder")
        load_button.setObjectName("AccentButton")
        load_button.setToolTip(
            "Scan folder, load metadata, and initialize image metrics.",
        )
        load_button.clicked.connect(
            lambda _checked=False: self.load_folder(),
        )
        command_layout.addWidget(load_button)

        self.data_advanced_toggle = qtw.QToolButton()
        self.data_advanced_toggle.setObjectName("DisclosureButton")
        self.data_advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonTextBesideIcon
        )
        self.data_advanced_toggle.setArrowType(Qt.RightArrow)
        self.data_advanced_toggle.setCheckable(True)
        self.data_advanced_toggle.setChecked(False)
        self.data_advanced_toggle.setText("Intake Controls (Show)")
        self.data_advanced_toggle.setToolTip(
            "Expand/collapse skip rules and metadata intake controls.",
        )
        self.data_advanced_toggle.toggled.connect(
            self._on_data_advanced_row_toggled,
        )
        command_layout.addWidget(self.data_advanced_toggle)
        layout.addWidget(command_bar)

        self._data_summary_strip = build_summary_strip()
        layout.addWidget(self._data_summary_strip)

        advanced_container = qtw.QWidget()
        self._data_advanced_container = advanced_container
        advanced_row = qtw.QHBoxLayout(advanced_container)
        self._data_advanced_row_layout = advanced_row
        advanced_row.setContentsMargins(0, 0, 0, 0)
        advanced_row.setSpacing(10)

        skip_panel = qtw.QFrame()
        skip_panel.setObjectName("SubtlePanel")
        skip_layout = qtw.QVBoxLayout(skip_panel)
        self._data_skip_layout = skip_layout
        skip_layout.setContentsMargins(12, 10, 12, 10)
        skip_layout.setSpacing(8)

        skip_header_row = qtw.QHBoxLayout()
        self._data_skip_header_row = skip_header_row
        skip_header_row.setSpacing(8)

        skip_title = qtw.QLabel("Skip Rules")
        skip_title.setObjectName("SectionTitle")
        skip_header_row.addWidget(skip_title)

        self.skip_pattern_count_chip = make_status_chip(
            "0 rules",
            parent=skip_panel,
        )
        skip_header_row.addWidget(self.skip_pattern_count_chip)
        skip_header_row.addStretch(1)

        edit_skip_rules_button = qtw.QPushButton("Edit...")
        edit_skip_rules_button.setToolTip(
            "Open the skip-rule editor in a separate window.",
        )
        edit_skip_rules_button.clicked.connect(
            lambda _checked=False: self._open_skip_rules_dialog(),
        )
        skip_header_row.addWidget(edit_skip_rules_button)
        skip_layout.addLayout(skip_header_row)

        self.skip_pattern_hint = qtw.QLabel()
        self.skip_pattern_hint.setObjectName("MutedLabel")
        self.skip_pattern_hint.setWordWrap(True)
        skip_layout.addWidget(self.skip_pattern_hint)

        self.skip_pattern_preview_label = qtw.QLabel()
        self.skip_pattern_preview_label.setObjectName("MutedLabel")
        self.skip_pattern_preview_label.setWordWrap(True)
        self.skip_pattern_preview_label.setVisible(False)
        skip_layout.addWidget(self.skip_pattern_preview_label)
        self._refresh_skip_pattern_ui()
        advanced_row.addWidget(skip_panel, 1)

        metadata_panel = qtw.QFrame()
        metadata_panel.setObjectName("SubtlePanel")
        metadata_outer_layout = qtw.QVBoxLayout(metadata_panel)
        self._data_metadata_outer_layout = metadata_outer_layout
        metadata_outer_layout.setContentsMargins(12, 10, 12, 10)
        metadata_outer_layout.setSpacing(8)

        metadata_header_row = qtw.QHBoxLayout()
        self._data_metadata_header_row = metadata_header_row
        metadata_header_row.setSpacing(8)
        metadata_title = qtw.QLabel("Metadata Controls")
        metadata_title.setObjectName("SectionTitle")
        metadata_header_row.addWidget(metadata_title)
        metadata_header_row.addStretch(1)
        metadata_outer_layout.addLayout(metadata_header_row)

        self.ebus_config_status_label = qtw.QLabel("")
        self.ebus_config_status_label.setObjectName("MutedLabel")
        self.ebus_config_status_label.setWordWrap(True)
        metadata_outer_layout.addWidget(self.ebus_config_status_label)
        self._refresh_ebus_config_status()

        self.metadata_controls_body = qtw.QWidget()
        metadata_group_layout = qtw.QVBoxLayout(self.metadata_controls_body)
        self._data_metadata_group_layout = metadata_group_layout
        metadata_group_layout.setContentsMargins(0, 0, 0, 0)
        metadata_group_layout.setSpacing(8)

        metadata_row = qtw.QHBoxLayout()
        self._data_metadata_row = metadata_row
        metadata_row.setSpacing(8)

        group_label = qtw.QLabel("Group Rows By")
        group_label.setObjectName("SectionTitle")
        metadata_row.addWidget(group_label)

        self.metadata_group_combo = qtw.QComboBox()
        for label, value in self.BASE_METADATA_GROUP_FIELDS:
            self.metadata_group_combo.addItem(label, value)
        self.metadata_group_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_metadata_table(),
        )
        self.metadata_group_combo.setToolTip(
            "Assign group numbers using the selected metadata field.",
        )
        metadata_row.addWidget(self.metadata_group_combo)

        filter_label = qtw.QLabel("Quick Filter")
        filter_label.setObjectName("SectionTitle")
        metadata_row.addWidget(filter_label)

        self.metadata_filter_edit = qtw.QLineEdit()
        self.metadata_filter_edit.setPlaceholderText(
            "Filter by path or metadata...",
        )
        self.metadata_filter_edit.setToolTip(
            "Filter visible metadata rows by any displayed text.",
        )
        self.metadata_filter_edit.textChanged.connect(
            lambda _text: self._refresh_metadata_table(),
        )
        metadata_row.addWidget(self.metadata_filter_edit, 1)

        metadata_source_label = qtw.QLabel("Metadata Source")
        metadata_source_label.setObjectName("SectionTitle")
        metadata_row.addWidget(metadata_source_label)
        self.metadata_source_combo = qtw.QComboBox()
        self.metadata_source_combo.addItem("Acquisition JSON", "json")
        self.metadata_source_combo.addItem("Path", "path")
        self.metadata_source_combo.currentIndexChanged.connect(
            self._on_metadata_source_changed,
        )
        self.metadata_source_combo.setToolTip(
            "Choose where exposure/iris metadata are read from.",
        )
        metadata_row.addWidget(self.metadata_source_combo)
        metadata_group_layout.addLayout(metadata_row)
        self._update_metadata_source_options(has_json=False)

        metadata_outer_layout.addWidget(self.metadata_controls_body)
        advanced_row.addWidget(metadata_panel, 2)
        self._set_metadata_controls_expanded(True)

        self._set_data_advanced_row_expanded(False)
        layout.addWidget(advanced_container)

        table_panel = qtw.QFrame()
        table_panel.setObjectName("TablePanel")
        table_layout = qtw.QVBoxLayout(table_panel)
        self._data_table_layout = table_layout
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(8)

        table_title = qtw.QLabel("Dataset Metadata")
        table_title.setObjectName("SectionTitle")
        table_layout.addWidget(table_title)
        self.metadata_summary_label = qtw.QLabel(
            "Load a dataset to populate metadata.",
        )
        self.metadata_summary_label.setObjectName("MutedLabel")
        self.metadata_summary_label.setWordWrap(True)
        table_layout.addWidget(self.metadata_summary_label)

        self.metadata_table = qtw.QTableWidget(0, 7)
        self.metadata_table.setHorizontalHeaderLabels(
            [
                label_for_metadata_field("path"),
                label_for_metadata_field("parent_folder"),
                label_for_metadata_field("grandparent_folder"),
                label_for_metadata_field("iris_position"),
                label_for_metadata_field("exposure_ms"),
                label_for_metadata_field("exposure_source"),
                label_for_metadata_field("group_index"),
            ]
        )
        self.metadata_table.setEditTriggers(qtw.QAbstractItemView.NoEditTriggers)
        self.metadata_table.setSelectionBehavior(
            qtw.QAbstractItemView.SelectRows,
        )
        self.metadata_table.setSelectionMode(
            qtw.QAbstractItemView.SingleSelection,
        )
        self.metadata_table.verticalHeader().setVisible(False)
        header = self.metadata_table.horizontalHeader()
        header.setSectionResizeMode(0, qtw.QHeaderView.Stretch)
        header.setSectionResizeMode(1, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, qtw.QHeaderView.ResizeToContents)
        install_large_header_resize_cursor(header)
        self.metadata_table.cellDoubleClicked.connect(
            self._open_metadata_row_in_inspect,
        )
        self.metadata_table.setToolTip(
            "Double-click a row to open that image in the Measure tab.",
        )
        table_layout.addWidget(self.metadata_table, 1)
        layout.addWidget(table_panel, 1)
        self._apply_data_table_visibility()
        self._refresh_data_header_state()
        if hasattr(self, "_policy_for_page"):
            self._apply_data_page_visibility_policy(
                self._policy_for_page("data"),
            )
        if hasattr(self, "_active_density_tokens"):
            self._apply_data_page_density(self._active_density_tokens)
        return page

    def _open_skip_rules_dialog(self) -> None:
        """Show skip-rule editor dialog, creating it on first use."""
        dialog = getattr(self, "_skip_rules_dialog", None)
        if dialog is None:
            dialog = _SkipRulesEditorDialog(self)
            dialog.finished.connect(self._on_skip_rules_dialog_finished)
            self._skip_rules_dialog = dialog
            self._refresh_skip_pattern_ui()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_skip_rules_dialog_finished(self, _result: int) -> None:
        """Clear skip-rule dialog reference after the window closes."""
        self._skip_rules_dialog = None

    @staticmethod
    def _normalize_skip_pattern(pattern: str) -> str:
        """Normalize user-entered skip pattern for matching."""
        return pattern.strip().replace("\\", "/")

    def _set_skip_patterns(
        self,
        patterns: list[str],
        *,
        persist: bool = True,
    ) -> None:
        """Set in-memory skip patterns and optionally persist them."""
        normalized = [
            self._normalize_skip_pattern(item)
            for item in patterns
        ]
        unique: list[str] = []
        seen: set[str] = set()
        for item in normalized:
            if not item or item in seen:
                continue
            seen.add(item)
            unique.append(item)
        self.skip_patterns = unique
        if persist:
            save_skip_patterns(self.skip_patterns)
        self._refresh_skip_pattern_ui()

    def _refresh_skip_pattern_ui(self) -> None:
        """Refresh visual list + hint of active skip patterns."""
        count = len(self.skip_patterns)
        rule_word = "rule" if count == 1 else "rules"
        if count:
            hint_text = (
                f"{count} active {rule_word}. "
                "Scan skips matching names, wildcards, and relative paths."
            )
        else:
            hint_text = (
                "No active skip rules. Matching supports names, wildcards, "
                "and relative paths."
            )
        preview_text = self._skip_pattern_preview_text()
        if hasattr(self, "skip_pattern_hint"):
            self.skip_pattern_hint.setText(hint_text)
        if hasattr(self, "skip_pattern_preview_label"):
            self.skip_pattern_preview_label.setText(preview_text)
            self.skip_pattern_preview_label.setVisible(bool(preview_text))
        if hasattr(self, "skip_pattern_count_chip"):
            self.skip_pattern_count_chip.set_status(
                f"{count} {rule_word}",
                level="warning" if count else "neutral",
                tooltip="\n".join(self.skip_patterns),
            )

        dialog = getattr(self, "_skip_rules_dialog", None)
        if dialog is not None:
            dialog.pattern_list.clear()
            dialog.pattern_list.addItems(self.skip_patterns)
            dialog.hint_label.setText(
                hint_text if not preview_text else f"{hint_text}\n{preview_text}",
            )
        self._refresh_data_header_state()

    def _skip_pattern_preview_text(self) -> str:
        """Return a short inline preview of the active skip rules."""

        if not self.skip_patterns:
            return ""
        preview = ", ".join(self.skip_patterns[:3])
        remainder = len(self.skip_patterns) - 3
        if remainder > 0:
            preview = f"{preview} +{remainder} more"
        return f"Active patterns: {preview}"

    def _apply_data_page_visibility_policy(self, policy) -> None:
        """Apply page-specific visibility policy to Data-page widgets."""

        if hasattr(self, "_data_summary_strip"):
            self._data_summary_strip.set_collapsed(not policy.show_summary_strip)
        advanced_expanded = not policy.collapse_data_advanced_row
        caps = self._active_plugin_capabilities()
        if caps.show_metadata_controls:
            advanced_expanded = True
        self._set_data_advanced_row_expanded(advanced_expanded)

    def _set_data_advanced_row_expanded(self, expanded: bool) -> None:
        """Show or hide the Data-page advanced controls row."""

        container = getattr(self, "_data_advanced_container", None)
        if container is not None:
            container.setVisible(bool(expanded))
        toggle = getattr(self, "data_advanced_toggle", None)
        if toggle is None:
            return
        blocker = QSignalBlocker(toggle)
        toggle.setChecked(bool(expanded))
        toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        toggle.setText(
            "Intake Controls (Hide)"
            if expanded
            else "Intake Controls (Show)"
        )
        del blocker

    def _on_data_advanced_row_toggled(self, checked: bool) -> None:
        """Handle user disclosure toggles for the advanced Data row."""

        if hasattr(self, "_remember_panel_state"):
            self._remember_panel_state("data.advanced_row", bool(checked))
        if hasattr(self, "_apply_dynamic_visibility_policy"):
            self._apply_dynamic_visibility_policy()
            return
        self._set_data_advanced_row_expanded(bool(checked))

    def _refresh_data_header_state(self) -> None:
        """Refresh page header and summary-strip state for the Data tab."""
        dataset = self.dataset_state
        has_loaded = dataset.has_loaded_data()
        folder_text = self.folder_edit.text().strip() if hasattr(self, "folder_edit") else ""
        folder = Path(folder_text).expanduser() if folder_text else None
        ebus_configs = self._discover_recursive_ebus_configs(folder)
        ebus_tooltip = self._ebus_config_tooltip(folder, ebus_configs)
        metadata_mode = "JSON" if dataset.metadata_source_mode == "json" else "Path"
        metadata_level = (
            "info"
            if dataset.metadata_source_mode == "json" and dataset.has_json_metadata_source
            else "neutral"
        )
        datacard_present = bool(dataset.has_json_metadata_source)
        chips = [
            ChipSpec(
                "Dataset loaded" if has_loaded else "No dataset",
                level="success" if has_loaded else "neutral",
            ),
            ChipSpec(
                "JSON metadata available" if datacard_present else "Path-only metadata",
                level="info" if datacard_present else "warning",
            ),
        ]
        if len(ebus_configs) > 1:
            chips.append(
                ChipSpec(
                    "eBUS configs detected",
                    level="success",
                    tooltip=ebus_tooltip,
                ),
            )
        elif len(ebus_configs) == 1:
            chips.append(
                ChipSpec(
                    "eBUS config detected",
                    level="success",
                    tooltip=ebus_tooltip,
                ),
            )
        elif folder is not None and folder.is_dir():
            chips.append(
                ChipSpec(
                    "No eBUS config",
                    level="neutral",
                ),
            )
        failure_count = len(getattr(self, "_processing_failures", []))
        if failure_count > 0:
            chips.append(
                ChipSpec(
                    f"{failure_count} processing issue(s)",
                    level="error",
                    tooltip=self._processing_failure_summary_text(),
                ),
            )
        self._data_header.set_chips(chips)
        self._data_summary_strip.set_items(
            [
                SummaryItem(
                    "Images",
                    str(dataset.path_count()),
                    level="success" if has_loaded else "neutral",
                ),
                SummaryItem(
                    "Metadata Source",
                    metadata_mode,
                    level=metadata_level,
                ),
                SummaryItem(
                    "Datacard",
                    "Present" if datacard_present else "Missing",
                    level="info" if datacard_present else "warning",
                ),
                SummaryItem(
                    "eBUS",
                    self._ebus_summary_value(ebus_configs),
                    level="success" if ebus_configs else "neutral",
                    tooltip=ebus_tooltip,
                ),
                SummaryItem(
                    "Skip Rules",
                    str(len(self.skip_patterns)),
                    level="warning" if self.skip_patterns else "neutral",
                ),
            ]
        )

    def _add_skip_pattern(
        self,
        pattern_edit: qtw.QLineEdit | None = None,
    ) -> None:
        """Add one skip pattern from an editor widget."""
        editor = pattern_edit
        if editor is None:
            dialog = getattr(self, "_skip_rules_dialog", None)
            editor = dialog.pattern_edit if dialog is not None else None
        if editor is None:
            return

        text = self._normalize_skip_pattern(editor.text())
        if not text:
            return
        updated = list(self.skip_patterns)
        updated.append(text)
        self._set_skip_patterns(updated, persist=True)
        editor.clear()

    def _delete_selected_skip_patterns(
        self,
        pattern_list: qtw.QListWidget | None = None,
    ) -> None:
        """Delete selected skip patterns from a list widget."""
        source_list = pattern_list
        if source_list is None:
            dialog = getattr(self, "_skip_rules_dialog", None)
            source_list = dialog.pattern_list if dialog is not None else None
        if source_list is None:
            return

        selected = source_list.selectedItems()
        if not selected:
            return
        delete_set = {item.text() for item in selected}
        updated = [
            pattern for pattern in self.skip_patterns
            if pattern not in delete_set
        ]
        self._set_skip_patterns(updated, persist=True)

    def _reset_skip_patterns(self) -> None:
        """Clear all skip patterns."""
        self._set_skip_patterns([], persist=True)

    @staticmethod
    def _skip_match(
        pattern: str,
        *,
        name: str,
        rel_path: str,
        abs_path: str,
    ) -> bool:
        """Return whether a single pattern matches an entry."""
        token = pattern.strip().lower()
        if not token:
            return False

        entry_name = name.lower()
        rel = rel_path.lower().replace("\\", "/")
        absolute = abs_path.lower().replace("\\", "/")
        has_sep = "/" in token
        if has_sep:
            return fnmatch(rel, token) or fnmatch(absolute, token)
        return fnmatch(entry_name, token) or fnmatch(rel, token)

    def _is_path_skipped(
        self,
        *,
        name: str,
        rel_path: str,
        abs_path: str,
    ) -> bool:
        """Return True when any configured skip pattern matches."""
        for pattern in self.skip_patterns:
            if self._skip_match(
                pattern,
                name=name,
                rel_path=rel_path,
                abs_path=abs_path,
            ):
                return True
        return False

    def _apply_data_table_visibility(self) -> None:
        """Apply Data-table visibility policy (core + plugin + overrides)."""
        if not hasattr(self, "metadata_table"):
            return
        caps = self._active_plugin_capabilities()
        visible: set[str] = set(self.BASE_VISIBLE_DATA_COLUMNS)
        visible.update(caps.reveal_data_columns)
        current_group_field = (
            self.metadata_group_combo.currentData()
            if hasattr(self, "metadata_group_combo")
            else None
        )
        if current_group_field is not None:
            visible.add("group")

        for key, override in self._manual_data_column_visibility.items():
            if override:
                visible.add(key)
            else:
                visible.discard(key)

        for key, column in self.DATA_COLUMN_INDEX.items():
            self.metadata_table.setColumnHidden(column, key not in visible)

    def _apply_grouping_field_visibility(self) -> None:
        """Expose metadata grouping fields according to active plugin hints."""
        if not hasattr(self, "metadata_group_combo"):
            return
        caps = self._active_plugin_capabilities()
        current = self.metadata_group_combo.currentData()
        fields = list(self.BASE_METADATA_GROUP_FIELDS)
        extra_fields: list[tuple[str, str]] = []
        for field in caps.metadata_group_fields:
            label = self.EXTRA_METADATA_GROUP_FIELD_LABELS.get(field)
            if label is None:
                continue
            extra_fields.append((label, field))
        fields.extend(extra_fields)

        existing = [
            (
                self.metadata_group_combo.itemText(i),
                self.metadata_group_combo.itemData(i),
            )
            for i in range(self.metadata_group_combo.count())
        ]
        if existing != fields:
            blocker = QSignalBlocker(self.metadata_group_combo)
            self.metadata_group_combo.clear()
            for label, value in fields:
                self.metadata_group_combo.addItem(label, value)
            del blocker

        selected_index = self.metadata_group_combo.findData(current)
        if selected_index < 0:
            selected_index = self.metadata_group_combo.findData(None)
        if selected_index < 0 and self.metadata_group_combo.count() > 0:
            selected_index = 0
        if selected_index >= 0:
            blocker = QSignalBlocker(self.metadata_group_combo)
            self.metadata_group_combo.setCurrentIndex(selected_index)
            del blocker
        if self.dataset_state.has_loaded_data():
            self._refresh_metadata_table()

    def _set_metadata_controls_expanded(self, expanded: bool) -> None:
        """Keep metadata controls visible inside the intake panel."""

        if not hasattr(self, "metadata_controls_body"):
            return
        _ = expanded
        self.metadata_controls_body.setVisible(True)

    def _update_metadata_controls_visibility(self) -> None:
        """Keep metadata controls available when intake controls are shown."""

        self._set_metadata_controls_expanded(True)
        caps = self._active_plugin_capabilities()
        if caps.show_metadata_controls:
            self._set_data_advanced_row_expanded(True)

    def _set_metadata_source_combo_value(self, mode: str) -> None:
        """Select a metadata-source combo entry without emitting signals."""
        if not hasattr(self, "metadata_source_combo"):
            return
        target_index = self.metadata_source_combo.findData(mode)
        if target_index < 0:
            return
        blocker = QSignalBlocker(self.metadata_source_combo)
        self.metadata_source_combo.setCurrentIndex(target_index)
        del blocker

    def _dataset_has_json_metadata(self, paths: list[str]) -> bool:
        """Return True when at least one loaded path has a datacard."""
        for path in paths:
            if path_has_acquisition_datacard(path):
                return True
        return False

    @staticmethod
    def _folder_has_json_metadata(folder: Path) -> bool:
        """Return True when at least one datacard exists under folder tree."""
        for _root, _dirs, files in os.walk(folder):
            if any(
                name.lower() in {
                    ACQUISITION_DATACARD_NAME,
                    SESSION_DATACARD_NAME,
                    CAMPAIGN_DATACARD_NAME,
                }
                for name in files
            ):
                return True
        return False

    def _update_metadata_source_options(self, has_json: bool) -> None:
        """Enable/disable metadata-source options according to dataset content."""
        active_mode = self.dataset_state.update_metadata_source_availability(
            has_json,
        )
        if not hasattr(self, "metadata_source_combo"):
            return

        json_index = self.metadata_source_combo.findData("json")
        if json_index >= 0:
            model = self.metadata_source_combo.model()
            model_item = (
                model.item(json_index)
                if hasattr(model, "item")
                else None
            )
            if model_item is not None:
                model_item.setEnabled(self._has_json_metadata_source)
            else:
                flags = (
                    (
                        int(Qt.ItemFlag.ItemIsSelectable)
                        | int(Qt.ItemFlag.ItemIsEnabled)
                    )
                    if self._has_json_metadata_source
                    else int(Qt.ItemFlag.NoItemFlags)
                )
                self.metadata_source_combo.setItemData(
                    json_index,
                    flags,
                    Qt.UserRole - 1,
                )

        self._set_metadata_source_combo_value(active_mode)

        tooltip = (
            ""
            if self._has_json_metadata_source
            else "Acquisition JSON source unavailable in this dataset."
        )
        self.metadata_source_combo.setToolTip(tooltip)
        self._refresh_data_header_state()

    def _on_metadata_source_changed(self, _index: int) -> None:
        """Handle metadata-source selection changes from Data page controls."""
        metrics = self.metrics_state
        data = self.metadata_source_combo.currentData()
        selected = str(data) if data is not None else "path"
        if not self.dataset_state.request_metadata_source_mode(selected):
            return

        if not self._has_loaded_data():
            self._apply_dynamic_visibility_policy()
            return

        self._refresh_metadata_cache()
        self._refresh_metadata_table()
        if (
            metrics.background_config.enabled
            and metrics.background_library.has_any_reference()
        ):
            self._invalidate_background_cache()
            self._apply_live_update()
            return

        self._refresh_table()
        self._apply_dynamic_visibility_policy()
        self._set_status()

    def _refresh_metadata_cache(self) -> None:
        """Rebuild metadata mapping for currently loaded paths."""
        clear_metadata_cache()
        self.dataset_state.set_path_metadata(
            {
                path: extract_path_metadata(
                    path,
                    metadata_source=self.dataset_state.metadata_source_mode,
                )
                for path in self.dataset_state.paths
            },
        )

    def _refresh_ebus_config_status(self, folder: Path | None = None) -> None:
        """Update compact status text for recursively discovered eBUS configs."""
        if not hasattr(self, "ebus_config_status_label"):
            return
        candidate = folder
        if candidate is None and hasattr(self, "folder_edit"):
            text = self.folder_edit.text().strip()
            candidate = Path(text).expanduser() if text else None
        if candidate is None or not candidate.is_dir():
            self.ebus_config_status_label.setText("")
            self.ebus_config_status_label.setToolTip("")
            self._refresh_data_header_state()
            return
        ebus_configs = self._discover_recursive_ebus_configs(candidate)
        if not ebus_configs:
            self.ebus_config_status_label.setText("")
            self.ebus_config_status_label.setToolTip("")
            self._refresh_data_header_state()
            return
        if len(ebus_configs) == 1:
            self.ebus_config_status_label.setText(
                f"eBUS config: {ebus_configs[0].name}"
            )
            self.ebus_config_status_label.setToolTip(
                self._ebus_config_tooltip(candidate, ebus_configs),
            )
            self._refresh_data_header_state()
            return
        self.ebus_config_status_label.setText(
            f"eBUS configs found: {len(ebus_configs)}"
        )
        self.ebus_config_status_label.setToolTip(
            self._ebus_config_tooltip(candidate, ebus_configs),
        )
        self._refresh_data_header_state()

    @staticmethod
    def _discover_recursive_ebus_configs(folder: Path | None) -> list[Path]:
        """Return ``.pvcfg`` files discovered anywhere under the selected root."""

        if folder is None or not folder.is_dir():
            return []
        discovered: list[Path] = []
        for root, _dirs, files in os.walk(folder, onerror=lambda _err: None):
            for name in sorted(files):
                if Path(name).suffix.lower() != ".pvcfg":
                    continue
                discovered.append(Path(root).joinpath(name))
        discovered.sort(key=lambda path: str(path).lower())
        return discovered

    @staticmethod
    def _ebus_summary_value(configs: list[Path]) -> str:
        """Return summary-strip value for discovered eBUS config files."""

        if not configs:
            return "None"
        if len(configs) == 1:
            return "1 file"
        return f"{len(configs)} files"

    @staticmethod
    def _ebus_config_tooltip(root: Path | None, configs: list[Path]) -> str:
        """Return concise tooltip text for detected eBUS config files."""

        if not configs:
            return ""
        if len(configs) == 1:
            return str(configs[0])
        preview: list[str] = []
        for path in configs[:3]:
            if root is None:
                preview.append(path.name)
                continue
            try:
                preview.append(str(path.relative_to(root)))
            except ValueError:
                preview.append(path.name)
        suffix = f" +{len(configs) - 3} more" if len(configs) > 3 else ""
        root_label = str(root) if root is not None else "selected root"
        return (
            f"{len(configs)} eBUS config files under {root_label}: "
            f"{', '.join(preview)}{suffix}"
        )

    def _refresh_metadata_table(self) -> None:
        """Refresh metadata table with grouping/filtering controls."""
        if not hasattr(self, "metadata_table"):
            return

        group_field = self.metadata_group_combo.currentData()
        group_key = str(group_field) if group_field is not None else None
        filter_text = self.metadata_filter_edit.text().strip().lower()
        dataset = self.dataset_state
        rows: list[tuple[str, str, dict[str, object]]] = []
        for path in dataset.paths:
            metadata = dataset.metadata_for_path(path)
            searchable = " ".join(
                [
                    path.lower(),
                    str(metadata.get("parent_folder", "")).lower(),
                    str(metadata.get("grandparent_folder", "")).lower(),
                    str(metadata.get("iris_position", "")).lower(),
                    str(metadata.get("exposure_ms", "")).lower(),
                    str(metadata.get("exposure_source", "")).lower(),
                ]
            )
            if filter_text and filter_text not in searchable:
                continue
            group_value = (
                str(metadata.get(group_key, ""))
                if group_key is not None
                else ""
            )
            rows.append((group_value, path, metadata))

        rows.sort(key=lambda row: (row[0].lower(), Path(row[1]).name.lower()))
        self.dataset_state.set_metadata_visible_paths(
            [path for _grp, path, _md in rows],
        )

        group_tokens: list[str] = []
        for group_value, _path, _metadata in rows:
            if group_key is None:
                group_tokens.append("__all__")
            else:
                group_tokens.append(group_value.strip())

        group_ids: dict[str, int] = {}
        if group_key is None:
            group_ids["__all__"] = 1
        else:
            unique_tokens = sorted({token for token in group_tokens if token})
            for idx, token in enumerate(unique_tokens, start=1):
                group_ids[token] = idx
            if any(token == "" for token in group_tokens):
                group_ids[""] = 0

        self.metadata_table.setRowCount(len(rows))
        for row_idx, (group_value, path, metadata) in enumerate(rows):
            iris = metadata.get("iris_position", "-")
            exp_ms = metadata.get("exposure_ms", "-")
            try:
                iris_text = "-" if iris == "-" else f"{float(iris):g}"
            except Exception:
                iris_text = "-"
            try:
                exp_text = "-" if exp_ms == "-" else f"{float(exp_ms):g}"
            except Exception:
                exp_text = "-"
            if group_key is None:
                group_token = "__all__"
            else:
                group_token = group_value.strip()
            group_id = group_ids.get(group_token, 0)
            values = [
                path,
                str(metadata.get("parent_folder", "")),
                str(metadata.get("grandparent_folder", "")),
                iris_text,
                exp_text,
                str(metadata.get("exposure_source", "")).lower() or "-",
                str(int(group_id)),
            ]
            for col_idx, value in enumerate(values):
                item = qtw.QTableWidgetItem(value)
                align = Qt.AlignLeft if col_idx == 0 else Qt.AlignCenter
                item.setTextAlignment(int(align | Qt.AlignVCenter))
                self.metadata_table.setItem(row_idx, col_idx, item)

        group_count = len(
            {
                group_id
                for group_id in group_ids.values()
                if group_id > 0
            }
        )
        self.metadata_summary_label.setText(
            (
                f"{len(rows)}/{dataset.path_count()} images listed "
                "(filter active) | "
                f"{group_count} groups"
                if filter_text
                else f"{len(rows)} images listed | {group_count} groups"
            ),
        )
        self._apply_data_table_visibility()
        self._refresh_data_header_state()

    def _open_metadata_row_in_inspect(self, row: int, _col: int) -> None:
        """Open selected metadata row in Inspect page."""
        dataset = self.dataset_state
        path = dataset.visible_metadata_path(row)
        if path is None:
            return
        source_idx = dataset.source_index_for_path(path)
        if source_idx is None:
            return

        self.metadata_table.setCurrentCell(row, 0)
        self.metadata_table.selectRow(row)
        self.dataset_state.set_selected_index(
            source_idx,
            path_count=dataset.path_count(),
        )
        if hasattr(self, "table_model"):
            self._set_table_current_source_row(source_idx)
        self._display_image(source_idx)
        self.workflow_tabs.setCurrentIndex(1)
