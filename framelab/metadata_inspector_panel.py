"""Reusable metadata inspector surface for dialogs and docks."""

from __future__ import annotations

import json
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt

from .datacard_labels import label_for_metadata_field
from .payload_utils import flatten_payload_dict, unflatten_payload_dict
from .ui_density import DensityTokens, comfortable_density_tokens
from .ui_primitives import (
    ChipSpec,
    SummaryItem,
    build_page_header,
    build_summary_strip,
    make_status_chip,
)
from .workflow_widgets import WorkflowBreadcrumbBar, set_chip_cell

METADATA_FIELD_MIME_TYPE = "application/x-framelab-metadata-field"


def display_metadata_value(value: Any) -> str:
    """Format one metadata value for table display."""

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    if value is None:
        return "null"
    return str(value)


def parse_metadata_editor_value(text: str) -> Any:
    """Parse one local-metadata editor cell into a JSON-like value."""

    cleaned = str(text).strip()
    if cleaned == "":
        return ""
    try:
        return json.loads(cleaned)
    except Exception:
        return cleaned


def format_metadata_source_badge(
    key: str,
    source,
    field_def,
    *,
    active_node_path,
) -> tuple[str, str, str, str, str]:
    """Return compact badge text, level, tooltip, node label, and node tooltip."""

    if source is None:
        return ("None", "neutral", f"{key}\nNo resolved source.", "", "")

    provenance_text = str(source.provenance or "none").replace("_", " ").strip()
    if source.provenance == "node_local":
        base_text = "Local"
        level = "success"
    elif source.provenance == "node_inherited":
        base_text = "Inherited"
        level = "info"
    elif source.provenance == "acquisition_datacard":
        base_text = "Datacard"
        level = "success"
    elif source.provenance == "acquisition_override":
        base_text = "Override"
        level = "warning"
    else:
        base_text = provenance_text.title()
        level = "neutral"
    schema_kind = (
        str(field_def.source_kind).replace("_", " ").strip()
        if field_def is not None and str(field_def.source_kind).strip()
        else "ad hoc"
    )
    if field_def is not None and field_def.source_kind == "ad_hoc":
        base_text = f"{base_text} ad-hoc"
        level = "warning"
    source_path = source.source_path.resolve()
    active_path = active_node_path.resolve() if active_node_path is not None else None
    node_label = "This node" if active_path is not None and source_path == active_path else source_path.name
    tooltip = "\n".join(
        [
            key,
            f"Resolved from: {provenance_text}",
            f"Schema source: {schema_kind}",
            f"Node: {source_path}",
        ],
    )
    if source.provenance == "acquisition_override":
        tooltip += "\nValue varies by frame due to acquisition override rows."
    return (base_text, level, tooltip, node_label, str(source_path))


class MetadataDragTable(qtw.QTableWidget):
    """Table widget that can start a metadata-field drag when a row is selected."""

    def __init__(
        self,
        *,
        payload_provider,
        parent: qtw.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._payload_provider = payload_provider
        self.setDragEnabled(True)
        self.setDragDropMode(qtw.QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.MoveAction)

    def startDrag(self, supported_actions: Qt.DropActions) -> None:
        """Start a field-move drag when the current selection resolves to metadata."""

        payload = self._payload_provider() if callable(self._payload_provider) else None
        if not isinstance(payload, dict):
            return
        mime = QtCore.QMimeData()
        mime.setData(
            METADATA_FIELD_MIME_TYPE,
            QtCore.QByteArray(
                json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8"),
            ),
        )
        mime.setText(str(payload.get("label") or payload.get("key") or "Metadata Field"))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)


class MetadataInspectorPanel(qtw.QWidget):
    """Shared metadata inspector widget used by dialog and dock surfaces."""

    def __init__(
        self,
        host_window: qtw.QWidget,
        *,
        show_header: bool = True,
        advanced_mode: bool = False,
        splitter_state_key: str | None = None,
        parent: qtw.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._host_window = host_window
        self._show_header = bool(show_header)
        self._advanced_mode = bool(advanced_mode)
        self._splitter_state_key = str(splitter_state_key).strip() or None
        self._density_tokens = comfortable_density_tokens()
        self._last_effective_snapshot = None
        self._last_active_node = None
        self._last_profile_id: str | None = None
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        layout = qtw.QVBoxLayout(self)
        self._layout = layout

        self._header = build_page_header(
            "Metadata Inspector",
            (
                "Inspect effective inherited metadata and edit the local "
                "nodecard for the currently active workflow node."
            ),
        )
        layout.addWidget(self._header)
        self._header.setVisible(self._show_header)

        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)

        self._breadcrumb = WorkflowBreadcrumbBar(compact=not self._show_header)
        layout.addWidget(self._breadcrumb)

        self._node_path_label = qtw.QLabel("", self)
        self._node_path_label.setObjectName("MutedLabel")
        self._node_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._node_path_label.setWordWrap(True)
        layout.addWidget(self._node_path_label)

        self._provenance_hint = qtw.QLabel(
            "Badges show whether values are local, inherited, or ad-hoc. "
            "Use the node column to see where each effective value came from.",
            self,
        )
        self._provenance_hint.setObjectName("MutedLabel")
        self._provenance_hint.setWordWrap(True)
        layout.addWidget(self._provenance_hint)

        self._group_status_panel = qtw.QFrame()
        self._group_status_panel.setObjectName("SubtlePanel")
        group_status_layout = qtw.QHBoxLayout(self._group_status_panel)
        self._group_status_layout = group_status_layout
        group_status_layout.addStretch(1)
        layout.addWidget(self._group_status_panel)
        self._group_status_panel.setVisible(False)

        splitter = qtw.QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._splitter = splitter

        effective_panel = qtw.QFrame()
        effective_panel.setObjectName("SubtlePanel")
        effective_layout = qtw.QVBoxLayout(effective_panel)
        self._effective_layout = effective_layout
        effective_title = qtw.QLabel("Effective Metadata", effective_panel)
        effective_title.setObjectName("SectionTitle")
        effective_layout.addWidget(effective_title)
        self._effective_table = MetadataDragTable(
            payload_provider=self._drag_payload_for_selected_field,
        )
        self._effective_table.setColumnCount(4)
        self._effective_table.setHorizontalHeaderLabels(
            ["Field", "Value", "Source", "Node"],
        )
        self._effective_table.setEditTriggers(qtw.QAbstractItemView.NoEditTriggers)
        self._effective_table.setSelectionBehavior(qtw.QAbstractItemView.SelectRows)
        self._effective_table.setAlternatingRowColors(True)
        self._effective_table.verticalHeader().setVisible(False)
        self._effective_table.horizontalHeader().setStretchLastSection(False)
        self._effective_table.horizontalHeader().setSectionResizeMode(
            0,
            qtw.QHeaderView.Interactive,
        )
        self._effective_table.horizontalHeader().setSectionResizeMode(
            1,
            qtw.QHeaderView.Stretch,
        )
        self._effective_table.horizontalHeader().setSectionResizeMode(
            2,
            qtw.QHeaderView.Interactive,
        )
        self._effective_table.horizontalHeader().setSectionResizeMode(
            3,
            qtw.QHeaderView.Interactive,
        )
        self._effective_table.setColumnWidth(0, 220)
        self._effective_table.setColumnWidth(2, 170)
        self._effective_table.setColumnWidth(3, 190)
        effective_layout.addWidget(self._effective_table, 1)
        splitter.addWidget(effective_panel)

        local_panel = qtw.QFrame()
        local_panel.setObjectName("SubtlePanel")
        local_layout = qtw.QVBoxLayout(local_panel)
        self._local_layout = local_layout
        local_title = qtw.QLabel("Local Metadata", local_panel)
        local_title.setObjectName("SectionTitle")
        local_layout.addWidget(local_title)
        self._local_table = MetadataDragTable(
            payload_provider=self._drag_payload_for_selected_field,
        )
        self._local_table.setColumnCount(2)
        self._local_table.setHorizontalHeaderLabels(["Key", "Value"])
        self._local_table.setSelectionBehavior(qtw.QAbstractItemView.SelectRows)
        self._local_table.setAlternatingRowColors(True)
        self._local_table.verticalHeader().setVisible(False)
        self._local_table.horizontalHeader().setStretchLastSection(True)
        self._local_table.horizontalHeader().setSectionResizeMode(
            0,
            qtw.QHeaderView.Stretch,
        )
        local_layout.addWidget(self._local_table, 1)
        self._editor_hint = qtw.QLabel(
            "Value editor accepts plain text or JSON literals like 1200, true, "
            "\"label\", [1, 2], or {\"x\": 1}.",
            local_panel,
        )
        self._editor_hint.setObjectName("MutedLabel")
        self._editor_hint.setWordWrap(True)
        local_layout.addWidget(self._editor_hint)
        splitter.addWidget(local_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        actions = qtw.QHBoxLayout()
        self._actions_layout = actions
        self._add_field_button = qtw.QPushButton("Add Ad-Hoc Field")
        self._add_field_button.clicked.connect(self._add_local_row)
        self._add_group_button = qtw.QPushButton("Add Ad-Hoc Group")
        self._add_group_button.clicked.connect(self._add_ad_hoc_group)
        self._apply_template_button = qtw.QPushButton("Apply Template")
        self._apply_template_button.clicked.connect(self._apply_template)
        self._promote_field_button = qtw.QPushButton("Promote Field")
        self._promote_field_button.clicked.connect(self._promote_selected_field)
        self._demote_field_button = qtw.QPushButton("Demote Field")
        self._demote_field_button.clicked.connect(self._demote_selected_field)
        self._advanced_button = qtw.QToolButton()
        self._advanced_button.setObjectName("DockActionButton")
        self._advanced_button.setText("Advanced")
        self._advanced_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._advanced_button.setPopupMode(qtw.QToolButton.InstantPopup)
        self._advanced_menu = qtw.QMenu(self._advanced_button)
        self._advanced_add_field_action = self._advanced_menu.addAction(
            "Add Ad-Hoc Field",
        )
        self._advanced_add_field_action.triggered.connect(self._add_local_row)
        self._advanced_add_group_action = self._advanced_menu.addAction(
            "Add Ad-Hoc Group",
        )
        self._advanced_add_group_action.triggered.connect(self._add_ad_hoc_group)
        self._advanced_apply_template_action = self._advanced_menu.addAction(
            "Apply Template",
        )
        self._advanced_apply_template_action.triggered.connect(self._apply_template)
        self._advanced_promote_action = self._advanced_menu.addAction(
            "Promote Field to Profile",
        )
        self._advanced_promote_action.triggered.connect(
            self._promote_selected_field,
        )
        self._advanced_demote_action = self._advanced_menu.addAction(
            "Demote Field from Profile",
        )
        self._advanced_demote_action.triggered.connect(
            self._demote_selected_field,
        )
        self._advanced_menu.addSeparator()
        self._advanced_open_dialog_action = self._advanced_menu.addAction(
            "Open Metadata Governance Tools...",
        )
        self._advanced_open_dialog_action.triggered.connect(
            self._open_advanced_metadata_tools,
        )
        self._advanced_button.setMenu(self._advanced_menu)
        self._apply_action_tooltips()
        if self._advanced_mode:
            actions.addWidget(self._add_field_button)
            actions.addWidget(self._add_group_button)
            actions.addWidget(self._apply_template_button)
            actions.addWidget(self._promote_field_button)
            actions.addWidget(self._demote_field_button)
            self._advanced_button.setVisible(False)
        else:
            actions.addWidget(self._advanced_button)
            self._add_field_button.setVisible(False)
            self._add_group_button.setVisible(False)
            self._apply_template_button.setVisible(False)
            self._promote_field_button.setVisible(False)
            self._demote_field_button.setVisible(False)
        self._remove_field_button = qtw.QPushButton("Remove Selected")
        self._remove_field_button.clicked.connect(self._remove_selected_rows)
        actions.addWidget(self._remove_field_button)
        self._revert_button = qtw.QPushButton("Revert")
        self._revert_button.clicked.connect(self.sync_from_host)
        actions.addWidget(self._revert_button)
        self._refresh_button = qtw.QPushButton("Refresh")
        self._refresh_button.clicked.connect(self.sync_from_host)
        actions.addWidget(self._refresh_button)
        self._save_button = qtw.QPushButton("Save Local Metadata")
        self._save_button.setObjectName("AccentButton")
        self._save_button.clicked.connect(self._save_local_metadata)
        actions.addWidget(self._save_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        if self._splitter_state_key and hasattr(host_window, "_persist_splitter_state"):
            splitter.splitterMoved.connect(
                lambda _pos, _index, key=self._splitter_state_key, splitter=splitter: (
                    host_window._persist_splitter_state(key, splitter)
                ),
            )
        self._effective_table.itemSelectionChanged.connect(self._on_selection_changed)
        self._local_table.itemSelectionChanged.connect(self._on_selection_changed)

        self.apply_density(self._density_tokens)
        self.sync_from_host()

    def apply_density(self, tokens: DensityTokens) -> None:
        """Apply active density tokens to the inspector layout."""

        self._density_tokens = tokens
        self._layout.setContentsMargins(
            tokens.panel_margin_h,
            tokens.panel_margin_v,
            tokens.panel_margin_h,
            tokens.panel_margin_v,
        )
        self._layout.setSpacing(tokens.panel_spacing)
        for nested in (
            self._effective_layout,
            self._local_layout,
            self._actions_layout,
        ):
            if nested is self._actions_layout:
                nested.setSpacing(tokens.panel_spacing)
                continue
            nested.setContentsMargins(
                tokens.panel_margin_h,
                tokens.panel_margin_v,
                tokens.panel_margin_h,
                tokens.panel_margin_v,
            )
            nested.setSpacing(tokens.panel_spacing)
        self._group_status_layout.setContentsMargins(
            tokens.panel_margin_h,
            max(4, tokens.panel_margin_v - 1),
            tokens.panel_margin_h,
            max(4, tokens.panel_margin_v - 1),
        )
        self._group_status_layout.setSpacing(tokens.chip_spacing)
        if hasattr(self._header, "apply_density"):
            self._header.apply_density(tokens)
        if hasattr(self._summary_strip, "apply_density"):
            self._summary_strip.apply_density(tokens)
        self._splitter.setHandleWidth(max(8, tokens.panel_spacing + 2))
        self._resize_effective_table_columns()

    def sync_from_host(self) -> None:
        """Refresh effective and local metadata from the active workflow node."""

        host = self._host_window
        workflow = getattr(host, "workflow_state_controller", None)
        metadata_controller = getattr(host, "metadata_state_controller", None)
        active_node = workflow.active_node() if workflow is not None else None
        if active_node is None or metadata_controller is None:
            self._last_effective_snapshot = None
            self._last_active_node = None
            self._last_profile_id = None
            self._header.set_chips(
                [ChipSpec("No active workflow node", level="warning")],
            )
            self._summary_strip.set_items(
                [SummaryItem("Scope", "None", level="neutral")],
            )
            self._breadcrumb.set_breadcrumb(
                profile_label=None,
                context_label=None,
                nodes=(),
                empty_text="No metadata context",
            )
            self._node_path_label.setText(
                "Load a workflow workspace and choose an active node first.",
            )
            self._set_group_statuses(())
            self._effective_table.setRowCount(0)
            self._local_table.setRowCount(0)
            self._sync_action_state(has_active_node=False)
            return

        local_card = metadata_controller.load_node_metadata(active_node.folder_path)
        effective = metadata_controller.resolve_active_node_metadata()
        if effective is None:
            self._last_effective_snapshot = None
            self._last_active_node = None
            self._last_profile_id = None
            self._effective_table.setRowCount(0)
            self._local_table.setRowCount(0)
            self._set_group_statuses(())
            self._sync_action_state(has_active_node=False)
            return
        profile = workflow.profile
        ancestry = workflow.ancestry_for(active_node.node_id)
        local_flat = flatten_payload_dict(local_card.metadata)
        ad_hoc_count = sum(
            1
            for field in effective.schema.fields
            if field.source_kind == "ad_hoc"
        )
        inherited_count = sum(
            1
            for source in effective.field_sources.values()
            if source.provenance == "node_inherited"
        )
        validation = effective.validation
        missing_count = len(validation.missing_required_keys)
        template_count = len(validation.template_keys)
        self._last_effective_snapshot = effective
        self._last_active_node = active_node
        self._last_profile_id = workflow.profile_id
        self._header.set_chips(
            [
                ChipSpec(
                    profile.display_name if profile is not None else "Unknown profile",
                    level="info",
                ),
                ChipSpec(
                    active_node.type_id.replace("_", " ").title(),
                    level="success",
                    tooltip="Active workflow node type",
                ),
                ChipSpec(
                    "Local metadata present" if local_flat else "No local metadata",
                    level="success" if local_flat else "neutral",
                ),
                ChipSpec(
                    f"{ad_hoc_count} ad-hoc field(s)",
                    level="warning" if ad_hoc_count else "neutral",
                ),
                ChipSpec(
                    f"{missing_count} missing required",
                    level="warning" if missing_count else "success",
                    tooltip=(
                        "\n".join(
                            label_for_metadata_field(key)
                            for key in validation.missing_required_keys
                        )
                        if missing_count
                        else "No required metadata is missing for this node."
                    ),
                ),
            ],
        )
        self._summary_strip.set_items(
            [
                SummaryItem(
                    "Scope",
                    host.dataset_state.scope_summary_value(),
                    level="info",
                ),
                SummaryItem(
                    "Effective Fields",
                    str(len(effective.flat_metadata)),
                    level="success" if effective.flat_metadata else "neutral",
                ),
                SummaryItem(
                    "Local Fields",
                    str(len(local_flat)),
                    level="info" if local_flat else "neutral",
                ),
                SummaryItem(
                    "Inherited",
                    str(inherited_count),
                    level="success" if inherited_count else "neutral",
                ),
                SummaryItem(
                    "Template",
                    str(template_count),
                    level="info" if template_count else "neutral",
                    tooltip=(
                        "\n".join(validation.template_keys)
                        if template_count
                        else "No profile template is defined for this node type."
                    ),
                ),
            ],
        )
        self._breadcrumb.set_breadcrumb(
            profile_label=profile.display_name if profile is not None else None,
            context_label=(
                workflow.anchor_summary_label()
                if workflow is not None and workflow.is_partial_workspace()
                else None
            ),
            nodes=tuple((node.display_name, str(node.folder_path)) for node in ancestry),
        )
        self._node_path_label.setText(f"Node path: {active_node.folder_path}")
        self._populate_effective_table(effective.flat_metadata, effective.field_sources)
        self._populate_local_table(local_flat)
        self._set_group_statuses(validation.group_statuses)
        self._restore_splitter_state_if_needed()
        self._sync_action_state(has_active_node=True)

    def _restore_splitter_state_if_needed(self) -> None:
        if not self._splitter_state_key:
            return
        restore = getattr(self._host_window, "_restore_splitter_state", None)
        if callable(restore):
            restore(self._splitter_state_key, self._splitter)

    def _populate_effective_table(
        self,
        flat_metadata: dict[str, Any],
        field_sources,
    ) -> None:
        """Populate the effective read-only metadata table."""

        rows = sorted(flat_metadata.items(), key=lambda item: item[0])
        self._effective_table.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            field_def = (
                self._last_effective_snapshot.schema.by_key().get(key)
                if self._last_effective_snapshot is not None
                else None
            )
            label_item = qtw.QTableWidgetItem(
                field_def.label if field_def is not None else label_for_metadata_field(key),
            )
            label_item.setToolTip(key)
            source = field_sources.get(key)
            display_value = (
                ""
                if source is not None and source.provenance == "acquisition_override"
                else display_metadata_value(value)
            )
            value_tooltip = (
                "Value varies by frame in acquisition override rows."
                if source is not None and source.provenance == "acquisition_override"
                else display_value
            )
            value_item = qtw.QTableWidgetItem(display_value)
            value_item.setToolTip(value_tooltip)
            source_text, source_level, source_tooltip, node_text, node_tooltip = (
                format_metadata_source_badge(
                    key,
                    source,
                    field_def,
                    active_node_path=(
                        self._last_active_node.folder_path
                        if self._last_active_node is not None
                        else None
                    ),
                )
            )
            node_item = qtw.QTableWidgetItem(node_text)
            node_item.setToolTip(node_tooltip)
            self._effective_table.setItem(row, 0, label_item)
            self._effective_table.setItem(row, 1, value_item)
            set_chip_cell(
                self._effective_table,
                row,
                2,
                source_text,
                level=source_level,
                tooltip=source_tooltip,
            )
            self._effective_table.setItem(row, 3, node_item)
        self._effective_table.resizeRowsToContents()
        self._resize_effective_table_columns()

    def _populate_local_table(self, local_flat: dict[str, Any]) -> None:
        """Populate the editable local metadata table."""

        rows = sorted(local_flat.items(), key=lambda item: item[0])
        self._local_table.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            self._local_table.setItem(row, 0, qtw.QTableWidgetItem(str(key)))
            self._local_table.setItem(
                row,
                1,
                qtw.QTableWidgetItem(display_metadata_value(value)),
            )
        self._local_table.resizeRowsToContents()

    def _set_group_statuses(self, group_statuses) -> None:
        """Render compact completeness chips for metadata groups."""

        while self._group_status_layout.count() > 1:
            item = self._group_status_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        visible = False
        for status in group_statuses:
            label = f"{status.group} {status.present_fields}/{status.total_fields}"
            tooltip_parts = [
                f"Present: {status.present_fields}/{status.total_fields}",
            ]
            if status.missing_required:
                tooltip_parts.append(f"Missing required: {status.missing_required}")
            if status.ad_hoc_fields:
                tooltip_parts.append(f"Ad-hoc: {status.ad_hoc_fields}")
            chip = make_status_chip(
                label,
                level=status.status,
                tooltip="\n".join(tooltip_parts),
                parent=self._group_status_panel,
            )
            self._group_status_layout.insertWidget(
                self._group_status_layout.count() - 1,
                chip,
            )
            visible = True
        self._group_status_panel.setVisible(visible)

    def _add_local_row(self) -> None:
        """Append a blank local metadata row and start editing it."""

        if not self._can_add_ad_hoc_fields():
            return
        row = self._local_table.rowCount()
        self._local_table.insertRow(row)
        self._local_table.setItem(row, 0, qtw.QTableWidgetItem(""))
        self._local_table.setItem(row, 1, qtw.QTableWidgetItem(""))
        self._local_table.setCurrentCell(row, 0)
        self._local_table.editItem(self._local_table.item(row, 0))
        self._remove_field_button.setEnabled(True)

    def _append_local_metadata_key(
        self,
        key: str,
        *,
        value: str = "",
    ) -> None:
        """Append one metadata key/value row and start editing its value."""

        clean_key = str(key).strip()
        if not clean_key:
            return
        row = self._local_table.rowCount()
        self._local_table.insertRow(row)
        self._local_table.setItem(row, 0, qtw.QTableWidgetItem(clean_key))
        self._local_table.setItem(row, 1, qtw.QTableWidgetItem(str(value)))
        self._local_table.setCurrentCell(row, 1)
        self._local_table.editItem(self._local_table.item(row, 1))
        self._remove_field_button.setEnabled(True)

    def _add_ad_hoc_group(self) -> None:
        """Prompt for a new ad-hoc group and append a starter field."""

        if not self._can_add_ad_hoc_groups():
            return
        group_name, accepted = qtw.QInputDialog.getText(
            self,
            "Add Ad-Hoc Group",
            "Group name:",
            text="custom",
        )
        if not accepted:
            return
        field_name, accepted = qtw.QInputDialog.getText(
            self,
            "Add Ad-Hoc Group",
            "Starter field name:",
            text="note",
        )
        if not accepted:
            return
        group_key = self._sanitize_key_token(group_name)
        field_key = self._sanitize_key_token(field_name)
        if not group_key or not field_key:
            return
        self._append_local_metadata_key(f"{group_key}.{field_key}")

    def _remove_selected_local_rows(self) -> None:
        """Remove selected local metadata rows from the editor."""

        selected_rows = sorted(
            {index.row() for index in self._local_table.selectionModel().selectedRows()},
            reverse=True,
        )
        for row in selected_rows:
            self._local_table.removeRow(row)
        self._sync_action_state(has_active_node=self._last_active_node is not None)

    def _selected_effective_removal_payload(self) -> dict[str, Any] | None:
        """Return removable storage payload for the selected effective field."""

        if self._last_effective_snapshot is None or self._last_active_node is None:
            return None
        selected_key = self._selected_metadata_key()
        if not selected_key:
            return None
        source = self._last_effective_snapshot.field_sources.get(selected_key)
        if source is None:
            return None
        active_path = self._last_active_node.folder_path.resolve()
        source_path = source.source_path.resolve()
        if source_path != active_path:
            return None
        if source.storage_kind not in {
            "nodecard",
            "acquisition_datacard_defaults",
            "acquisition_datacard_override",
        }:
            return None
        field_def = self._last_effective_snapshot.schema.by_key().get(selected_key)
        return {
            "key": selected_key,
            "label": (
                field_def.label
                if field_def is not None
                else label_for_metadata_field(selected_key)
            ),
            "source_path": str(source_path),
            "storage_kind": source.storage_kind,
        }

    def _remove_selected_rows(self) -> None:
        """Remove selected metadata from the local editor or backing store."""

        has_local_selection = bool(
            self._local_table.selectionModel().selectedRows(),
        )
        if has_local_selection:
            self._remove_selected_local_rows()
            return

        payload = self._selected_effective_removal_payload()
        if payload is None:
            return
        remove_field = getattr(self._host_window, "_remove_metadata_field_payload", None)
        if not callable(remove_field):
            return
        remove_field(payload)
        self.sync_from_host()

    def _collect_local_metadata(self) -> dict[str, Any]:
        """Collect nested metadata payload from the editor table."""

        flat: dict[str, Any] = {}
        for row in range(self._local_table.rowCount()):
            key_item = self._local_table.item(row, 0)
            value_item = self._local_table.item(row, 1)
            key = key_item.text().strip() if key_item is not None else ""
            if not key:
                continue
            value_text = value_item.text() if value_item is not None else ""
            flat[key] = parse_metadata_editor_value(value_text)
        return unflatten_payload_dict(flat)

    def _save_local_metadata(self) -> None:
        """Write the current local metadata table into the active nodecard."""

        host = self._host_window
        workflow = getattr(host, "workflow_state_controller", None)
        metadata_controller = getattr(host, "metadata_state_controller", None)
        active_node = workflow.active_node() if workflow is not None else None
        if active_node is None or metadata_controller is None:
            return
        existing_card = metadata_controller.load_node_metadata(active_node.folder_path)
        metadata_controller.save_node_metadata(
            active_node.folder_path,
            self._collect_local_metadata(),
            profile_id=workflow.profile_id,
            node_type_id=active_node.type_id,
            extra_top_level=dict(existing_card.extra_top_level),
        )
        notify = getattr(host, "_notify_metadata_context_changed", None)
        if callable(notify):
            notify(changed_root=active_node.folder_path)
        self.sync_from_host()

    def _apply_template(self) -> None:
        """Apply the profile/node template to the active node metadata."""

        host = self._host_window
        workflow = getattr(host, "workflow_state_controller", None)
        metadata_controller = getattr(host, "metadata_state_controller", None)
        active_node = workflow.active_node() if workflow is not None else None
        if active_node is None or metadata_controller is None:
            return
        saved_path = metadata_controller.apply_template(
            active_node.folder_path,
            profile_id=workflow.profile_id,
            node_type_id=active_node.type_id,
            preserve_existing=True,
        )
        if saved_path is None:
            return
        notify = getattr(host, "_notify_metadata_context_changed", None)
        if callable(notify):
            notify(changed_root=active_node.folder_path)
        self.sync_from_host()

    def _selected_metadata_key(self) -> str | None:
        """Return the currently selected metadata key from either table."""

        effective_row = self._effective_table.currentRow()
        if effective_row >= 0:
            item = self._effective_table.item(effective_row, 0)
            if item is not None and item.toolTip().strip():
                return item.toolTip().strip()
        local_row = self._local_table.currentRow()
        if local_row >= 0:
            item = self._local_table.item(local_row, 0)
            if item is not None and item.text().strip():
                return item.text().strip()
        return None

    def _selected_metadata_source(self):
        """Return the effective source record for the currently selected key."""

        selected_key = self._selected_metadata_key()
        if not selected_key or self._last_effective_snapshot is None:
            return None
        return self._last_effective_snapshot.field_sources.get(selected_key)

    def _drag_payload_for_selected_field(self) -> dict[str, Any] | None:
        """Build one drag payload for the current inspector field selection."""

        selected_key = self._selected_metadata_key()
        if not selected_key or self._last_effective_snapshot is None:
            return None
        source = self._last_effective_snapshot.field_sources.get(selected_key)
        if source is None:
            return None
        field_def = self._last_effective_snapshot.schema.by_key().get(selected_key)
        return {
            "key": selected_key,
            "label": (
                field_def.label
                if field_def is not None
                else label_for_metadata_field(selected_key)
            ),
            "value": source.value,
            "source_path": str(source.source_path),
            "profile_id": source.profile_id,
            "node_type_id": source.node_type_id,
            "provenance": source.provenance,
            "schema_source_kind": source.schema_source_kind,
            "storage_kind": source.storage_kind,
        }

    def _promote_selected_field(self) -> None:
        """Promote the selected ad-hoc field into the profile schema overlay."""

        metadata_controller = getattr(self._host_window, "metadata_state_controller", None)
        selected_key = self._selected_metadata_key()
        if metadata_controller is None or not selected_key or not self._last_profile_id:
            return
        schema = (
            self._last_effective_snapshot.schema.by_key()
            if self._last_effective_snapshot is not None
            else {}
        )
        field_def = schema.get(selected_key)
        if field_def is not None and field_def.source_kind != "ad_hoc":
            return
        label = (
            field_def.label
            if field_def is not None
            else label_for_metadata_field(selected_key)
        )
        group = (
            field_def.group
            if field_def is not None
            else selected_key.split(".", 1)[0].replace("_", " ").title()
        )
        value = self._selected_metadata_value(selected_key)
        metadata_controller.promote_field_to_profile(
            self._last_profile_id,
            key=selected_key,
            label=label,
            group=group,
            value_type=(
                field_def.value_type
                if field_def is not None and field_def.value_type != "any"
                else self._infer_metadata_value_type(value)
            ),
            options=field_def.options if field_def is not None else (),
        )
        self.sync_from_host()

    def _demote_selected_field(self) -> None:
        """Demote the selected field so it becomes ad-hoc for this profile."""

        metadata_controller = getattr(self._host_window, "metadata_state_controller", None)
        selected_key = self._selected_metadata_key()
        if metadata_controller is None or not selected_key or not self._last_profile_id:
            return
        schema = (
            self._last_effective_snapshot.schema.by_key()
            if self._last_effective_snapshot is not None
            else {}
        )
        field_def = schema.get(selected_key)
        if field_def is None or field_def.source_kind == "ad_hoc":
            return
        metadata_controller.demote_field_from_profile(
            self._last_profile_id,
            key=selected_key,
            label=(
                field_def.label
                if field_def is not None
                else label_for_metadata_field(selected_key)
            ),
            group=(
                field_def.group
                if field_def is not None
                else selected_key.split(".", 1)[0].replace("_", " ").title()
            ),
            value_type=(
                field_def.value_type
                if field_def is not None
                else self._infer_metadata_value_type(
                    self._selected_metadata_value(selected_key),
                )
            ),
            options=field_def.options if field_def is not None else (),
            current_source_kind=field_def.source_kind if field_def is not None else None,
        )
        self.sync_from_host()

    def _open_advanced_metadata_tools(self) -> None:
        """Reveal the detached advanced metadata tool surface."""

        open_dialog = getattr(self._host_window, "_open_metadata_manager_dialog", None)
        if callable(open_dialog):
            open_dialog()

    def _on_selection_changed(self) -> None:
        """Refresh action enablement when the current row selection changes."""

        sender = self.sender()
        if sender is self._effective_table:
            blocker = QtCore.QSignalBlocker(self._local_table.selectionModel())
            self._local_table.clearSelection()
            del blocker
        elif sender is self._local_table:
            blocker = QtCore.QSignalBlocker(self._effective_table.selectionModel())
            self._effective_table.clearSelection()
            del blocker
        self._sync_action_state(has_active_node=self._last_active_node is not None)

    def _sync_action_state(self, *, has_active_node: bool) -> None:
        """Enable or disable local-editing actions."""

        metadata_controller = getattr(self._host_window, "metadata_state_controller", None)
        allow_ad_hoc_fields = self._can_add_ad_hoc_fields()
        allow_ad_hoc_groups = self._can_add_ad_hoc_groups()
        can_add_field = bool(has_active_node and allow_ad_hoc_fields)
        can_add_group = bool(has_active_node and allow_ad_hoc_groups)
        self._add_field_button.setEnabled(can_add_field)
        self._add_group_button.setEnabled(can_add_group)
        self._set_control_tooltip(
            self._add_field_button,
            enabled_text=(
                "Add a new local metadata key that exists only on this node unless "
                "you later promote it."
            ),
            disabled_text=(
                "Load an active workflow node and use a profile that allows "
                "ad-hoc metadata fields."
            ),
            enabled=can_add_field,
        )
        self._set_control_tooltip(
            self._add_group_button,
            enabled_text=(
                "Create a new ad-hoc metadata group and seed it with one starter field."
            ),
            disabled_text=(
                "Load an active workflow node and use a profile that allows "
                "ad-hoc metadata groups."
            ),
            enabled=can_add_group,
        )
        can_remove_selected = bool(
            has_active_node
            and (
                self._local_table.selectionModel().selectedRows()
                or self._selected_effective_removal_payload() is not None
            )
        )
        self._remove_field_button.setEnabled(can_remove_selected)
        has_template = bool(
            self._last_effective_snapshot is not None
            and self._last_effective_snapshot.validation.template_keys
        )
        self._apply_template_button.setEnabled(has_active_node and has_template)
        selected_key = self._selected_metadata_key()
        field_def = (
            self._last_effective_snapshot.schema.by_key().get(selected_key)
            if self._last_effective_snapshot is not None and selected_key
            else None
        )
        can_promote = bool(
            has_active_node
            and self._last_profile_id
            and selected_key
            and (
                field_def is None
                or field_def.source_kind == "ad_hoc"
            )
        )
        can_demote = bool(
            has_active_node
            and metadata_controller is not None
            and self._last_profile_id
            and selected_key
            and (
                field_def is not None
                and field_def.source_kind != "ad_hoc"
            )
        )
        self._promote_field_button.setEnabled(can_promote)
        self._demote_field_button.setEnabled(can_demote)
        self._advanced_button.setEnabled(has_active_node)
        self._advanced_add_field_action.setEnabled(
            can_add_field,
        )
        self._advanced_add_group_action.setEnabled(
            can_add_group,
        )
        self._advanced_apply_template_action.setEnabled(has_active_node and has_template)
        self._advanced_promote_action.setEnabled(can_promote)
        self._advanced_demote_action.setEnabled(can_demote)
        self._advanced_open_dialog_action.setEnabled(True)
        self._revert_button.setEnabled(has_active_node)
        self._refresh_button.setEnabled(has_active_node)
        self._save_button.setEnabled(has_active_node)
        self._set_control_tooltip(
            self._apply_template_button,
            enabled_text=(
                "Apply the current profile template for this node type while preserving "
                "existing local values."
            ),
            disabled_text="No profile template is defined for this node type yet.",
            enabled=has_template,
        )
        self._set_control_tooltip(
            self._promote_field_button,
            enabled_text=(
                "Turn the selected ad-hoc field into a profile-defined field so it is "
                "recognized across this workflow profile."
            ),
            disabled_text="Select an ad-hoc field to promote it into the profile schema.",
            enabled=can_promote,
        )
        self._set_control_tooltip(
            self._demote_field_button,
            enabled_text=(
                "Demote the selected field so it becomes ad-hoc for this workflow "
                "profile instead of remaining locked to the governed schema."
            ),
            disabled_text=(
                "Select a governed field to demote it into ad-hoc metadata."
            ),
            enabled=can_demote,
        )
        self._set_control_tooltip(
            self._remove_field_button,
            enabled_text=(
                "Remove the selected metadata from this node. Effective rows remove "
                "their real local backing entry when that source belongs to the "
                "active node."
            ),
            disabled_text=(
                "Select local rows or a removable effective field on this node."
            ),
            enabled=can_remove_selected,
        )
        self._set_control_tooltip(
            self._revert_button,
            enabled_text="Discard unsaved table edits and reload metadata from disk.",
            disabled_text="Load an active workflow node to edit local metadata.",
            enabled=has_active_node,
        )
        self._set_control_tooltip(
            self._refresh_button,
            enabled_text="Reload effective and local metadata for the active node.",
            disabled_text="Load an active workflow node to inspect metadata.",
            enabled=has_active_node,
        )
        self._set_control_tooltip(
            self._save_button,
            enabled_text="Write the Local Metadata table back into this node's nodecard.",
            disabled_text="Load an active workflow node before saving local metadata.",
            enabled=has_active_node,
        )

    def _apply_action_tooltips(self) -> None:
        """Configure persistent button and menu help text."""

        self._set_tooltip(
            self._advanced_button,
            "Open metadata authoring and governance actions for the selected node.",
        )
        self._set_tooltip(
            self._advanced_add_field_action,
            "Add a new local metadata key on this node.",
        )
        self._set_tooltip(
            self._advanced_add_group_action,
            "Create a new ad-hoc metadata group and one starter field.",
        )
        self._set_tooltip(
            self._advanced_apply_template_action,
            "Apply the current profile template for this node type.",
        )
        self._set_tooltip(
            self._advanced_promote_action,
            "Promote the selected ad-hoc field into the profile schema overlay.",
        )
        self._set_tooltip(
            self._advanced_demote_action,
            "Demote the selected field so it becomes ad-hoc in this workflow profile.",
        )
        self._set_tooltip(
            self._advanced_open_dialog_action,
            "Open the detached advanced metadata tools window.",
        )

    @staticmethod
    def _set_tooltip(target: object, text: str) -> None:
        """Apply tooltip and status-tip text when the target supports it."""

        clean_text = " ".join(str(text).split())
        set_tooltip = getattr(target, "setToolTip", None)
        if callable(set_tooltip):
            set_tooltip(clean_text)
        set_status_tip = getattr(target, "setStatusTip", None)
        if callable(set_status_tip):
            set_status_tip(clean_text)

    def _set_control_tooltip(
        self,
        target: object,
        *,
        enabled_text: str,
        disabled_text: str,
        enabled: bool,
    ) -> None:
        """Apply contextual help text for one button-like control."""

        self._set_tooltip(
            target,
            enabled_text if enabled else disabled_text,
        )

    def _resize_effective_table_columns(self) -> None:
        """Size the effective-metadata columns so source and node text stay readable."""

        table = self._effective_table
        if table.columnCount() < 4:
            return

        header = table.horizontalHeader()
        metrics = header.fontMetrics()

        def _header_width(column: int) -> int:
            item = table.horizontalHeaderItem(column)
            label = item.text() if item is not None else ""
            return metrics.horizontalAdvance(label) + 26

        source_width = _header_width(2)
        node_width = _header_width(3)

        for row in range(table.rowCount()):
            source_widget = table.cellWidget(row, 2)
            if source_widget is not None:
                source_width = max(source_width, source_widget.sizeHint().width() + 22)
            node_item = table.item(row, 3)
            if node_item is not None:
                node_width = max(
                    node_width,
                    table.fontMetrics().horizontalAdvance(node_item.text()) + 28,
                )

        table.setColumnWidth(2, max(150, source_width))
        table.setColumnWidth(3, max(170, node_width))

    @staticmethod
    def _sanitize_key_token(value: str) -> str:
        """Convert one free-form token into a safe metadata key segment."""

        text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return "".join(ch for ch in text if ch.isalnum() or ch == "_").strip("_")

    def _governance(self):
        """Return profile governance for the current metadata context."""

        metadata_controller = getattr(self._host_window, "metadata_state_controller", None)
        if metadata_controller is None or not self._last_profile_id:
            return None
        return metadata_controller.governance_for_profile(self._last_profile_id)

    def _can_add_ad_hoc_fields(self) -> bool:
        """Return whether the active profile allows new ad-hoc fields."""

        governance = self._governance()
        return True if governance is None else bool(governance.allow_ad_hoc_fields)

    def _can_add_ad_hoc_groups(self) -> bool:
        """Return whether the active profile allows new ad-hoc groups."""

        governance = self._governance()
        if governance is None:
            return True
        return bool(governance.allow_ad_hoc_fields and governance.allow_ad_hoc_groups)

    def _selected_metadata_value(self, key: str | None) -> Any:
        """Return the current effective value for one metadata key when known."""

        if not key or self._last_effective_snapshot is None:
            return None
        return self._last_effective_snapshot.flat_metadata.get(key)

    @staticmethod
    def _infer_metadata_value_type(value: Any) -> str:
        """Infer a lightweight schema type name from one effective value."""

        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, list):
            return "list"
        if isinstance(value, dict):
            return "dict"
        if value is None:
            return "string"
        return "string"
