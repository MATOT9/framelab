"""Core dialogs and host actions for eBUS config tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from ..file_dialogs import choose_existing_directory, choose_open_file
from ..ui_primitives import (
    ChipSpec,
    SummaryItem,
    build_page_header,
    build_summary_strip,
)
from ..window_drag import configure_secondary_window
from .catalog import ebus_catalog_index, mapped_datacard_key_for_ebus
from .effective import describe_ebus_source, effective_ebus_parameters


def _display_value(value: Any) -> str:
    """Return a compact display string for UI tables."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _apply_tooltip(target: Any, text: str) -> None:
    """Apply matching tooltip and status-tip text."""

    if hasattr(target, "setToolTip"):
        target.setToolTip(text)
    if hasattr(target, "setStatusTip"):
        target.setStatusTip(text)


def _choose_ebus_file(parent: qtw.QWidget, start: str = "") -> str:
    """Open a themed file picker for ``.pvcfg`` files."""

    return choose_open_file(
        parent,
        "Select eBUS Config File",
        start,
        name_filters=("eBUS Config (*.pvcfg)", "All files (*)"),
        selected_name_filter="eBUS Config (*.pvcfg)",
    )


def _choose_folder(parent: qtw.QWidget, title: str, start: str = "") -> str:
    """Open a themed directory picker for a generic folder selection."""

    return choose_existing_directory(parent, title, start)


def _selected_acquisition_root(host_window: qtw.QWidget) -> Path | None:
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


class EbusInspectDialog(qtw.QDialog):
    """Read-only inspection dialog for one eBUS source."""

    def __init__(self, source_path: str | Path, parent: Optional[qtw.QWidget] = None) -> None:
        super().__init__(parent)
        descriptor = describe_ebus_source(source_path)
        if descriptor is None or descriptor.snapshot is None:
            raise ValueError("Could not load eBUS source.")

        self.setWindowTitle(f"Inspect eBUS Config - {descriptor.display_name}")
        configure_secondary_window(self)
        self.resize(1080, 720)

        layout = qtw.QVBoxLayout(self)
        mapped_count = sum(
            1
            for parameter in descriptor.snapshot.parameters
            if mapped_datacard_key_for_ebus(parameter.qualified_key)
        )
        catalogued_count = sum(
            1
            for parameter in descriptor.snapshot.parameters
            if parameter.catalog_entry is not None
        )
        self._header = build_page_header(
            "Inspect eBUS Config",
            f"Browse raw and normalized parameters for {descriptor.display_name}.",
            chips=[
                ChipSpec(descriptor.source_kind, level="info"),
                ChipSpec(
                    f"{len(descriptor.snapshot.parameters)} parameters",
                    level="success",
                ),
            ],
        )
        layout.addWidget(self._header)
        self._summary_strip = build_summary_strip(
            [
                SummaryItem("Source", descriptor.display_name, level="info"),
                SummaryItem("Catalogued", str(catalogued_count), level="success"),
                SummaryItem(
                    "Mapped Fields",
                    str(mapped_count),
                    level="success" if mapped_count else "neutral",
                ),
                SummaryItem("Kind", descriptor.source_kind, level="neutral"),
            ],
        )
        layout.addWidget(self._summary_strip)

        self.tree = qtw.QTreeWidget()
        self.tree.setObjectName("EbusInspectTree")
        self.tree.viewport().setObjectName("EbusInspectTreeViewport")
        self.tree.viewport().setAutoFillBackground(True)
        header = self.tree.header()
        header.setObjectName("EbusInspectTreeHeader")
        header.viewport().setObjectName("EbusInspectTreeHeaderViewport")
        header.viewport().setAutoFillBackground(True)
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(
            [
                "Label",
                "Qualified Key",
                "Raw Value",
                "Normalized",
                "Relevance",
                "Overridable",
                "Canonical Mapping",
            ],
        )
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        for column in range(self.tree.columnCount()):
            header.setSectionResizeMode(column, qtw.QHeaderView.Interactive)
        _apply_tooltip(
            self.tree,
            "Browse raw and normalized eBUS parameters grouped by section. Drag column separators in the header to resize widths.",
        )
        layout.addWidget(self.tree, 1)

        grouped: dict[str, list[Any]] = {}
        for parameter in descriptor.snapshot.parameters:
            grouped.setdefault(parameter.section, []).append(parameter)
        for section_name in sorted(grouped):
            section_item = qtw.QTreeWidgetItem(
                [section_name, "", "", "", "", "", ""],
            )
            self.tree.addTopLevelItem(section_item)
            for parameter in grouped[section_name]:
                entry = parameter.catalog_entry
                section_item.addChild(
                    qtw.QTreeWidgetItem(
                        [
                            parameter.label,
                            parameter.qualified_key,
                            parameter.raw_value,
                            _display_value(parameter.normalized_value),
                            entry.relevance if entry is not None else "uncatalogued",
                            "yes" if entry is not None and entry.overridable else "no",
                            mapped_datacard_key_for_ebus(parameter.qualified_key),
                        ],
                    ),
                )
            section_item.setExpanded(True)

        close_button = qtw.QPushButton("Close")
        _apply_tooltip(close_button, "Close the inspector.")
        close_button.clicked.connect(self.accept)
        row = qtw.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_button)
        layout.addLayout(row)


class EbusCompareDialog(qtw.QDialog):
    """Compare raw or effective eBUS settings across multiple sources."""

    def __init__(
        self,
        parent: Optional[qtw.QWidget] = None,
        *,
        initial_path: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare eBUS Configs")
        configure_secondary_window(self)
        self.resize(1280, 760)
        self._initial_path = initial_path
        self._source_path_role = int(Qt.UserRole)
        self._source_header_role = int(Qt.UserRole) + 1
        self._empty_summary_text = (
            "Add at least two sources, then compare them in raw or effective mode."
        )

        layout = qtw.QVBoxLayout(self)
        self._header = build_page_header(
            "Compare eBUS Configs",
            "Compare raw snapshots or effective acquisition-wide eBUS state across sources.",
        )
        layout.addWidget(self._header)
        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)
        source_group = qtw.QGroupBox("Sources")
        source_layout = qtw.QVBoxLayout(source_group)
        source_layout.setContentsMargins(10, 10, 10, 10)
        source_layout.setSpacing(8)

        source_buttons = qtw.QHBoxLayout()
        add_file_button = qtw.QPushButton("Add File...")
        _apply_tooltip(
            add_file_button,
            "Add one standalone .pvcfg file to the compare set.",
        )
        add_file_button.clicked.connect(
            lambda _checked=False: self._add_file_source(),
        )
        source_buttons.addWidget(add_file_button)
        add_folder_button = qtw.QPushButton("Add Folder...")
        _apply_tooltip(
            add_folder_button,
            "Recursively find all .pvcfg files under one folder and add each file as its own compare source. You can select one acquisition folder for a single source or a higher-level folder for bulk discovery.",
        )
        add_folder_button.clicked.connect(
            lambda _checked=False: self._add_folder_sources(),
        )
        source_buttons.addWidget(add_folder_button)
        remove_button = qtw.QPushButton("Remove Selected")
        _apply_tooltip(
            remove_button,
            "Remove selected sources from this compare session.",
        )
        remove_button.clicked.connect(self._remove_selected_sources)
        source_buttons.addWidget(remove_button)
        clear_button = qtw.QPushButton("Clear All")
        _apply_tooltip(clear_button, "Remove every source from this compare session.")
        clear_button.clicked.connect(self._clear_sources)
        source_buttons.addWidget(clear_button)
        source_buttons.addStretch(1)
        source_layout.addLayout(source_buttons)

        self._source_list = qtw.QListWidget()
        self._source_list.setSelectionMode(qtw.QAbstractItemView.ExtendedSelection)
        self._source_list.setAlternatingRowColors(True)
        _apply_tooltip(
            self._source_list,
            "Transient compare set for this session. The first added source is not treated specially; all sources are compared together.",
        )
        source_layout.addWidget(self._source_list, 1)
        layout.addWidget(source_group)

        controls = qtw.QHBoxLayout()
        controls.addWidget(qtw.QLabel("Mode"))
        self._mode_combo = qtw.QComboBox()
        self._mode_combo.addItem("Raw eBUS Compare", "raw")
        self._mode_combo.addItem("Effective Acquisition Compare", "effective")
        _apply_tooltip(
            self._mode_combo,
            "Raw mode compares the saved snapshots directly. Effective mode compares acquisition-wide snapshot baselines plus app-side acquisition-wide eBUS overrides; it does not apply frame-targeted datacard overrides.",
        )
        controls.addWidget(self._mode_combo)
        self._changed_only = qtw.QCheckBox("Changed only")
        self._changed_only.setChecked(True)
        _apply_tooltip(
            self._changed_only,
            "Show only parameters whose values differ across the loaded sources.",
        )
        controls.addWidget(self._changed_only)
        self._mapped_only = qtw.QCheckBox("Mapped fields only")
        _apply_tooltip(
            self._mapped_only,
            "Restrict the view to eBUS parameters that map to canonical app metadata fields.",
        )
        controls.addWidget(self._mapped_only)
        controls.addWidget(qtw.QLabel("Relevance"))
        self._relevance_combo = qtw.QComboBox()
        self._relevance_combo.addItem("Scientific + Operational", "focus")
        self._relevance_combo.addItem("Scientific", "scientific")
        self._relevance_combo.addItem("Operational", "operational")
        self._relevance_combo.addItem("UI Noise", "ui_noise")
        self._relevance_combo.addItem("All", "all")
        _apply_tooltip(
            self._relevance_combo,
            "Filter the result table by catalog relevance classification.",
        )
        controls.addWidget(self._relevance_combo)
        controls.addStretch(1)
        compare_button = qtw.QPushButton("Compare")
        compare_button.setObjectName("AccentButton")
        _apply_tooltip(compare_button, "Compare all currently listed sources.")
        compare_button.clicked.connect(self._compare)
        controls.addWidget(compare_button)
        layout.addLayout(controls)

        self._summary_label = qtw.QLabel(self._empty_summary_text)
        self._summary_label.setObjectName("MutedLabel")
        self._summary_label.setWordWrap(True)
        _apply_tooltip(
            self._summary_label,
            "Summary of the current compare mode, source count, and visible changed rows.",
        )
        layout.addWidget(self._summary_label)

        self.table = qtw.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                "Section",
                "Parameter",
                "Status",
                "Overridable",
                "Canonical Mapping",
            ],
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, qtw.QHeaderView.Stretch)
        header.setSectionResizeMode(2, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, qtw.QHeaderView.Stretch)
        _apply_tooltip(
            self.table,
            "One row per parameter. Value columns are added dynamically for each source in the compare set.",
        )
        layout.addWidget(self.table, 1)

        close_row = qtw.QHBoxLayout()
        close_row.addStretch(1)
        close_button = qtw.QPushButton("Close")
        _apply_tooltip(close_button, "Close the compare dialog.")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)
        self._reset_compare_results()

    def add_source(self, path: str | Path) -> None:
        """Add one source path to the transient compare list."""

        self._add_source(path)

    def _add_source(
        self,
        path: str | Path,
        *,
        list_label: str | None = None,
        header_label: str | None = None,
    ) -> bool:
        """Add one source path to the transient compare list."""

        source = describe_ebus_source(path)
        if source is None or source.snapshot is None:
            return False
        normalized = str(Path(path).resolve())
        for index in range(self._source_list.count()):
            item = self._source_list.item(index)
            if item is not None and item.data(self._source_path_role) == normalized:
                return False
        effective_header = header_label or source.display_name
        effective_list_label = list_label or f"{effective_header} ({source.source_kind})"
        item = qtw.QListWidgetItem(effective_list_label)
        item.setData(self._source_path_role, normalized)
        item.setData(self._source_header_role, effective_header)
        item.setToolTip(normalized)
        self._source_list.addItem(item)
        self._reset_compare_results()
        return True

    def _add_file_source(self) -> None:
        path = _choose_ebus_file(self, self._initial_path)
        if path:
            candidate = Path(path)
            header_label = candidate.parent.name or candidate.name
            list_label = f"{header_label} - {candidate.name} (standalone_file)"
            self._add_source(
                candidate,
                list_label=list_label,
                header_label=header_label,
            )

    def _add_folder_sources(self) -> None:
        folder = _choose_folder(
            self,
            "Select Folder to Search for eBUS Configs",
            self._initial_path,
        )
        if not folder:
            return
        root = Path(folder).expanduser()
        if not root.is_dir():
            return
        discovered = sorted(
            path for path in root.rglob("*.pvcfg") if path.is_file()
        )
        if not discovered:
            qtw.QMessageBox.warning(
                self,
                "Add Folder",
                "No .pvcfg files were found under the selected folder.",
            )
            return

        added = 0
        for path in discovered:
            relative_path = path.relative_to(root)
            parent_label = path.parent.name
            header_label = parent_label or path.name
            list_label = f"{relative_path.as_posix()} (standalone_file)"
            if self._add_source(
                path,
                list_label=list_label,
                header_label=header_label,
            ):
                added += 1
        if added == 0:
            qtw.QMessageBox.information(
                self,
                "Add Folder",
                "All discovered .pvcfg files were already present in the compare list.",
            )
            return
        self._summary_label.setText(
            f"Added {added} .pvcfg file(s) from {root}. Click Compare to refresh parameter changes.",
        )
        self._refresh_compare_header_state()

    def _remove_selected_sources(self) -> None:
        for item in reversed(self._source_list.selectedItems()):
            row = self._source_list.row(item)
            self._source_list.takeItem(row)
        self._reset_compare_results()

    def _clear_sources(self) -> None:
        self._source_list.clear()
        self._reset_compare_results()

    def _reset_compare_results(self) -> None:
        """Clear stale compare results after the source list changes."""

        fixed_headers = [
            "Section",
            "Parameter",
            "Status",
            "Overridable",
            "Canonical Mapping",
        ]
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(len(fixed_headers))
        self.table.setHorizontalHeaderLabels(fixed_headers)
        source_count = self._source_list.count()
        if source_count >= 2:
            self._summary_label.setText(
                f"Sources loaded: {source_count}. Click Compare to refresh parameter changes.",
            )
        else:
            self._summary_label.setText(self._empty_summary_text)
        self._refresh_compare_header_state()

    def _refresh_compare_header_state(
        self,
        *,
        visible_rows: int = 0,
        changed: int = 0,
        identical: int = 0,
    ) -> None:
        """Refresh compare dialog header chips and summary strip."""

        source_count = self._source_list.count()
        mode = str(self._mode_combo.currentData()) if hasattr(self, "_mode_combo") else "raw"
        self._header.set_chips(
            [
                ChipSpec(
                    f"{source_count} source(s)",
                    level="success" if source_count >= 2 else "warning",
                ),
                ChipSpec(
                    "effective" if mode == "effective" else "raw",
                    level="info",
                ),
            ],
        )
        self._summary_strip.set_items(
            [
                SummaryItem(
                    "Mode",
                    "Effective" if mode == "effective" else "Raw",
                    level="info",
                ),
                SummaryItem(
                    "Sources",
                    str(source_count),
                    level="success" if source_count >= 2 else "warning",
                ),
                SummaryItem(
                    "Visible Rows",
                    str(visible_rows),
                    level="info" if visible_rows else "neutral",
                ),
                SummaryItem(
                    "Changed",
                    str(changed),
                    level="warning" if changed else "neutral",
                ),
                SummaryItem(
                    "Identical",
                    str(identical),
                    level="neutral",
                ),
            ],
        )

    def _passes_filters(
        self,
        *,
        status: str,
        mapped_datacard_key: str,
        relevance: str,
        show_in_compare: bool,
    ) -> bool:
        if not show_in_compare:
            return False
        if self._changed_only.isChecked() and status != "changed":
            return False
        if self._mapped_only.isChecked() and not mapped_datacard_key:
            return False
        mode = str(self._relevance_combo.currentData())
        if mode == "all":
            return True
        if mode == "focus":
            return relevance in {"scientific", "operational"}
        return relevance == mode

    def _compare(self) -> None:
        sources = []
        for index in range(self._source_list.count()):
            item = self._source_list.item(index)
            if item is None:
                continue
            source = describe_ebus_source(item.data(self._source_path_role))
            if source is None or source.snapshot is None:
                continue
            custom_header = str(item.data(self._source_header_role) or "").strip()
            if custom_header:
                source.display_name = custom_header
            sources.append(source)
        if len(sources) < 2:
            qtw.QMessageBox.warning(
                self,
                "Compare",
                "Add at least two valid eBUS sources to compare.",
            )
            return

        mode = str(self._mode_combo.currentData())
        source_maps: list[tuple[str, dict[str, Any]]] = []
        for source in sources:
            if mode == "effective":
                effective = effective_ebus_parameters(
                    source.snapshot,
                    source.overrides,
                )
                source_maps.append((source.display_name, effective))
            else:
                source_maps.append((source.display_name, source.snapshot.by_key()))

        all_keys = sorted(
            {
                key
                for _name, parameter_map in source_maps
                for key in parameter_map
            },
        )
        rows: list[tuple[tuple[str, str, str, bool, str], list[str]]] = []
        changed = 0
        identical = 0
        source_headers: list[str] = []
        seen_headers: dict[str, int] = {}
        for source in sources:
            base_name = source.display_name
            count = seen_headers.get(base_name, 0) + 1
            seen_headers[base_name] = count
            header_name = base_name if count == 1 else f"{base_name} ({count})"
            source_headers.append(header_name)
        catalog_index = ebus_catalog_index()
        for qualified_key in all_keys:
            catalog_entry = catalog_index.get(qualified_key)
            label = (
                catalog_entry.label
                if catalog_entry is not None and catalog_entry.label
                else qualified_key.rsplit(".", 1)[-1]
            )
            section = (
                catalog_entry.section
                if catalog_entry is not None and catalog_entry.section
                else qualified_key.rsplit(".", 1)[0]
            )
            overridable = bool(catalog_entry is not None and catalog_entry.overridable)
            relevance = (
                catalog_entry.relevance if catalog_entry is not None else "operational"
            )
            show_in_compare = (
                catalog_entry.show_in_compare if catalog_entry is not None else True
            )
            mapped_key = mapped_datacard_key_for_ebus(qualified_key)
            value_cells: list[str] = []
            normalized_values: list[Any] = []
            for _source_name, parameter_map in source_maps:
                item = parameter_map.get(qualified_key)
                if mode == "effective":
                    if item is None:
                        value_cells.append("")
                        normalized_values.append(None)
                    else:
                        display = _display_value(item.effective_normalized_value)
                        if item.provenance == "app override":
                            display = f"{display} [override]"
                        value_cells.append(display)
                        normalized_values.append(item.effective_normalized_value)
                else:
                    if item is None:
                        value_cells.append("")
                        normalized_values.append(None)
                    else:
                        value_cells.append(item.raw_value)
                        normalized_values.append(item.normalized_value)
            present_values = [value for value in normalized_values if value is not None]
            if not present_values:
                status = "identical"
            elif len(present_values) != len(normalized_values):
                status = "changed"
            else:
                first_value = present_values[0]
                status = (
                    "identical"
                    if all(value == first_value for value in present_values[1:])
                    else "changed"
                )
            if status == "changed":
                changed += 1
            else:
                identical += 1
            if not self._passes_filters(
                status=status,
                mapped_datacard_key=mapped_key,
                relevance=relevance,
                show_in_compare=show_in_compare,
            ):
                continue
            rows.append(
                ((section, label, status, overridable, mapped_key), value_cells),
            )

        self.table.clear()
        fixed_headers = [
            "Section",
            "Parameter",
            "Status",
            "Overridable",
            "Canonical Mapping",
        ]
        self.table.setColumnCount(len(fixed_headers) + len(source_headers))
        self.table.setHorizontalHeaderLabels(fixed_headers + source_headers)
        for column, source in enumerate(sources, start=len(fixed_headers)):
            header_item = self.table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(str(source.path))
        self.table.setRowCount(len(rows))
        for row_index, (fixed_values, value_cells) in enumerate(rows):
            values = [
                fixed_values[0],
                fixed_values[1],
                fixed_values[2],
                "yes" if fixed_values[3] else "no",
                fixed_values[4],
                *value_cells,
            ]
            for column, value in enumerate(values):
                item = qtw.QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, column, item)
        header = self.table.horizontalHeader()
        for column in range(self.table.columnCount()):
            if column in {0, 2, 3}:
                header.setSectionResizeMode(column, qtw.QHeaderView.ResizeToContents)
            elif column == 1 or column >= 5:
                header.setSectionResizeMode(column, qtw.QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(column, qtw.QHeaderView.ResizeToContents)
        self._summary_label.setText(
            f"Mode: {mode} | Sources: {len(sources)} | Visible rows: {len(rows)} | "
            f"Changed: {changed} | Identical: {identical}",
        )
        self._refresh_compare_header_state(
            visible_rows=len(rows),
            changed=changed,
            identical=identical,
        )


def open_ebus_inspect_dialog(host_window: qtw.QWidget) -> None:
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


def open_ebus_compare_dialog(host_window: qtw.QWidget) -> None:
    """Open raw/effective eBUS compare dialog."""

    acquisition_root = _selected_acquisition_root(host_window)
    dialog = EbusCompareDialog(
        parent=None,
        initial_path=_ebus_browse_start(host_window),
    )
    if acquisition_root is not None and describe_ebus_source(acquisition_root) is not None:
        dialog.add_source(acquisition_root)
    dialog.exec()


def open_ebus_datacard_wizard(host_window: qtw.QWidget) -> None:
    """Open the datacard wizard from the core eBUS tools menu."""

    from ..plugins.data.acquisition_datacard_wizard import (
        AcquisitionDatacardWizardPlugin,
    )

    AcquisitionDatacardWizardPlugin.open_wizard(host_window)
