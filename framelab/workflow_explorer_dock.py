"""Persistent workflow explorer dock for shell-level hierarchy navigation."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt

from .dock_title_bar import DockTitleBar, should_use_custom_dock_title_bar
from .metadata_inspector_panel import METADATA_FIELD_MIME_TYPE
from .ui_density import DensityTokens, comfortable_density_tokens
from .ui_primitives import make_status_chip
from .workflow_widgets import WorkflowLineageEntry, WorkflowLineageRail


class WorkflowExplorerTree(qtw.QTreeWidget):
    """Workflow tree that accepts metadata-field drops from the inspector."""

    def __init__(self, dock: "WorkflowExplorerDock") -> None:
        super().__init__(dock)
        self._dock = dock
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(qtw.QAbstractItemView.DropOnly)

    @staticmethod
    def _decode_metadata_payload(event) -> dict[str, object] | None:
        mime = event.mimeData()
        if mime is None or not mime.hasFormat(METADATA_FIELD_MIME_TYPE):
            return None
        raw_payload = bytes(mime.data(METADATA_FIELD_MIME_TYPE))
        if not raw_payload:
            return None
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        payload = self._decode_metadata_payload(event)
        if payload is None:
            super().dragEnterEvent(event)
            return
        event.acceptProposedAction()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        payload = self._decode_metadata_payload(event)
        item = self.itemAt(event.position().toPoint())
        if payload is None or item is None:
            event.ignore()
            return
        self.setCurrentItem(item)
        event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        payload = self._decode_metadata_payload(event)
        item = self.itemAt(event.position().toPoint())
        if payload is None or item is None:
            event.ignore()
            return
        node_id = item.data(0, Qt.UserRole)
        if not node_id:
            event.ignore()
            return
        handled = self._dock._handle_metadata_field_drop(
            payload,
            str(node_id),
        )
        if handled:
            event.acceptProposedAction()
            return
        event.ignore()


class WorkflowExplorerDock(qtw.QDockWidget):
    """Docked workflow explorer that drives the active app scope."""

    PANEL_STATE_KEY = "workflow.explorer_dock"

    def __init__(self, host_window: qtw.QWidget) -> None:
        super().__init__("Workflow Explorer", host_window)
        self._host_window = host_window
        self._item_by_node_id: dict[str, qtw.QTreeWidgetItem] = {}
        self._tree_structure_signature: tuple[
            tuple[str, str, str, str, str],
            ...,
        ] = ()
        self._syncing_selection = False
        self._pending_scroll_restore: tuple[int, int] | None = None
        self._pending_session_parent_node_id: str | None = None
        self._pending_session_item: qtw.QTreeWidgetItem | None = None
        self._pending_session_editor: qtw.QLineEdit | None = None
        self._pending_child_type_id: str | None = None
        self._density_tokens = comfortable_density_tokens()

        self.setObjectName("WorkflowExplorerDock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            qtw.QDockWidget.DockWidgetClosable
            | qtw.QDockWidget.DockWidgetMovable
            | qtw.QDockWidget.DockWidgetFloatable,
        )
        window_icon = host_window.windowIcon()
        if window_icon.isNull():
            window_icon = self.style().standardIcon(qtw.QStyle.SP_DirOpenIcon)
        self.setWindowIcon(window_icon)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        if should_use_custom_dock_title_bar():
            self.setTitleBarWidget(DockTitleBar(self))

        container = qtw.QWidget()
        container.setObjectName("WorkflowExplorerDockContent")
        container.setAttribute(Qt.WA_StyledBackground, True)
        container.setAutoFillBackground(True)
        layout = qtw.QVBoxLayout(container)
        self._layout = layout

        self._main_splitter = qtw.QSplitter(Qt.Vertical)
        self._main_splitter.setObjectName("WorkflowExplorerSplitter")
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.setOpaqueResize(False)
        self._main_splitter.setHandleWidth(10)
        layout.addWidget(self._main_splitter, 1)

        overview = qtw.QWidget()
        overview.setObjectName("WorkflowExplorerOverview")
        overview.setAttribute(Qt.WA_StyledBackground, True)
        overview.setAutoFillBackground(True)
        overview_layout = qtw.QVBoxLayout(overview)
        self._overview_widget = overview
        self._overview_layout = overview_layout

        summary_panel = qtw.QFrame()
        summary_panel.setObjectName("SubtlePanel")
        summary_layout = qtw.QHBoxLayout(summary_panel)
        self._summary_layout = summary_layout
        self._profile_chip = make_status_chip(
            "No workflow",
            level="neutral",
            tooltip="Current workflow profile",
            parent=summary_panel,
        )
        self._workspace_chip = make_status_chip(
            "Folder mode",
            level="warning",
            tooltip="Current workspace mode",
            parent=summary_panel,
        )
        self._active_chip = make_status_chip(
            "No active scope",
            level="neutral",
            tooltip="Current active workflow node",
            parent=summary_panel,
        )
        summary_layout.addWidget(self._profile_chip)
        summary_layout.addWidget(self._workspace_chip)
        summary_layout.addWidget(self._active_chip)
        summary_layout.addStretch(1)
        overview_layout.addWidget(summary_panel)

        controls = qtw.QFrame()
        controls.setObjectName("CommandBar")
        controls_layout = qtw.QGridLayout(controls)
        self._controls_layout = controls_layout
        controls_layout.setColumnStretch(0, 1)
        controls_layout.setColumnStretch(1, 1)
        controls_layout.setColumnStretch(2, 1)

        self._select_workflow_button = qtw.QToolButton()
        self._select_workflow_button.setObjectName("DockActionButton")
        self._select_workflow_button.setText("Workflow")
        self._select_workflow_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._select_workflow_button.setToolTip("Select or switch workflow context.")
        self._select_workflow_button.clicked.connect(self._open_workflow_selector)
        controls_layout.addWidget(self._select_workflow_button, 0, 0)

        self._refresh_button = qtw.QToolButton()
        self._refresh_button.setObjectName("DockActionButton")
        self._refresh_button.setText("Refresh")
        self._refresh_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._refresh_button.setToolTip("Reload the current workflow tree.")
        self._refresh_button.clicked.connect(self._refresh_workflow)
        controls_layout.addWidget(self._refresh_button, 0, 1)

        self._scan_button = qtw.QToolButton()
        self._scan_button.setObjectName("DockActionButton")
        self._scan_button.setText("Scan")
        self._scan_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._scan_button.setToolTip("Scan the selected workflow scope on the Data page.")
        self._scan_button.clicked.connect(self._scan_scope)
        controls_layout.addWidget(self._scan_button, 0, 2)

        self._metadata_button = qtw.QToolButton()
        self._metadata_button.setObjectName("DockActionButton")
        self._metadata_button.setText("Metadata")
        self._metadata_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._metadata_button.setToolTip("Reveal the Metadata Inspector for the selected node.")
        self._metadata_button.clicked.connect(self._open_metadata_manager)
        controls_layout.addWidget(self._metadata_button, 1, 0)

        self._structure_button = qtw.QToolButton()
        self._structure_button.setObjectName("DockActionButton")
        self._structure_button.setText("Structure...")
        self._structure_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._structure_button.setPopupMode(qtw.QToolButton.InstantPopup)
        self._structure_button.setToolTip("Create, rename, delete, or normalize acquisitions.")
        self._structure_menu = qtw.QMenu(self._structure_button)
        self._new_session_action = self._structure_menu.addAction("New Session...")
        self._new_session_action.triggered.connect(self._new_session)
        self._delete_session_action = self._structure_menu.addAction("Delete Session...")
        self._delete_session_action.triggered.connect(self._delete_session)
        self._structure_menu.addSeparator()
        self._new_acquisition_action = self._structure_menu.addAction("New Acquisition...")
        self._new_acquisition_action.triggered.connect(self._new_acquisition)
        self._batch_create_action = self._structure_menu.addAction("Batch Create...")
        self._batch_create_action.triggered.connect(self._batch_create_acquisitions)
        self._reindex_action = self._structure_menu.addAction("Normalize/Reindex...")
        self._reindex_action.triggered.connect(self._reindex_session)
        self._structure_menu.addSeparator()
        self._rename_acquisition_action = self._structure_menu.addAction(
            "Rename / Relabel...",
        )
        self._rename_acquisition_action.triggered.connect(self._rename_acquisition)
        self._delete_acquisition_action = self._structure_menu.addAction(
            "Delete Acquisition...",
        )
        self._delete_acquisition_action.triggered.connect(self._delete_acquisition)
        self._structure_button.setMenu(self._structure_menu)
        controls_layout.addWidget(self._structure_button, 1, 1)

        self._advanced_button = qtw.QToolButton()
        self._advanced_button.setObjectName("DockActionButton")
        self._advanced_button.setText("More")
        self._advanced_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._advanced_button.setPopupMode(qtw.QToolButton.InstantPopup)
        self._advanced_button.setToolTip("Open the selected folder or advanced workflow tools.")
        self._advanced_menu = qtw.QMenu(self._advanced_button)
        self._advanced_open_folder_action = self._advanced_menu.addAction(
            "Open in File Explorer",
        )
        self._advanced_open_folder_action.triggered.connect(self._open_selected_folder)
        self._advanced_menu.addSeparator()
        self._advanced_workflow_tools_action = self._advanced_menu.addAction(
            "Workflow Tools (Advanced)...",
        )
        self._advanced_workflow_tools_action.triggered.connect(
            self._open_workflow_tools,
        )
        self._advanced_button.setMenu(self._advanced_menu)
        controls_layout.addWidget(self._advanced_button, 1, 2)

        overview_layout.addWidget(controls)

        self._warning_label = qtw.QLabel("")
        self._warning_label.setObjectName("MutedLabel")
        self._warning_label.setWordWrap(True)
        self._warning_label.setVisible(False)
        overview_layout.addWidget(self._warning_label)

        self._lineage_scroll = qtw.QScrollArea()
        self._lineage_scroll.setObjectName("WorkflowActivePathScroll")
        self._lineage_scroll.setFrameShape(qtw.QFrame.NoFrame)
        self._lineage_scroll.setWidgetResizable(True)
        self._lineage_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._lineage_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._lineage_scroll.setSizePolicy(
            qtw.QSizePolicy.Preferred,
            qtw.QSizePolicy.Fixed,
        )
        self._lineage_rail = WorkflowLineageRail(self._lineage_scroll)
        self._lineage_scroll.setWidget(self._lineage_rail)
        self._lineage_scroll.setVisible(False)
        overview_layout.addWidget(self._lineage_scroll)
        overview_layout.addStretch(1)

        self._tree = WorkflowExplorerTree(self)
        self._tree.setObjectName("WorkflowTree")
        self._tree.setHeaderLabels(["Workflow", "Kind", "Flags"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(qtw.QAbstractItemView.SingleSelection)
        self._tree.setSelectionBehavior(qtw.QAbstractItemView.SelectRows)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionsMovable(False)
        for column in range(3):
            self._tree.header().setSectionResizeMode(
                column,
                qtw.QHeaderView.Interactive,
            )
        self._tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(
            lambda _item, _column: self._scan_scope(),
        )
        self._tree.setMinimumHeight(240)
        self._tree.setSizePolicy(
            qtw.QSizePolicy.Expanding,
            qtw.QSizePolicy.Expanding,
        )
        self._tree.setColumnWidth(0, 280)
        self._tree.setColumnWidth(1, 120)
        self._tree.setColumnWidth(2, 150)

        self._main_splitter.addWidget(overview)
        self._main_splitter.addWidget(self._tree)
        self._main_splitter.setStretchFactor(0, 0)
        self._main_splitter.setStretchFactor(1, 1)
        self._main_splitter.setSizes([240, 640])

        self.setWidget(container)
        self.visibilityChanged.connect(self._on_visibility_changed)
        self.apply_density(self._density_tokens)
        self.sync_from_host()

    def apply_density(self, tokens: DensityTokens) -> None:
        """Apply active density spacing tokens to the dock layout."""

        self._density_tokens = tokens
        self._layout.setContentsMargins(
            tokens.panel_margin_h,
            tokens.panel_margin_v,
            tokens.panel_margin_h,
            tokens.panel_margin_v,
        )
        self._layout.setSpacing(tokens.panel_spacing)
        self._overview_layout.setContentsMargins(0, 0, 0, 0)
        self._overview_layout.setSpacing(tokens.panel_spacing)
        self._summary_layout.setContentsMargins(
            tokens.panel_margin_h,
            tokens.panel_margin_v,
            tokens.panel_margin_h,
            tokens.panel_margin_v,
        )
        self._summary_layout.setSpacing(tokens.chip_spacing)
        self._controls_layout.setContentsMargins(
            tokens.command_bar_margin_h,
            tokens.command_bar_margin_v,
            tokens.command_bar_margin_h,
            tokens.command_bar_margin_v,
        )
        self._controls_layout.setHorizontalSpacing(tokens.command_bar_spacing)
        self._controls_layout.setVerticalSpacing(tokens.command_bar_spacing)
        self._tree.setIndentation(max(16, tokens.panel_margin_h + 8))
        lineage_min_height = max(96, 72 + tokens.panel_spacing * 3)
        lineage_max_height = max(
            lineage_min_height,
            92 + tokens.panel_spacing * 7,
        )
        self._lineage_scroll.setMinimumHeight(lineage_min_height)
        self._lineage_scroll.setMaximumHeight(lineage_max_height)
        self._overview_widget.setMinimumHeight(
            max(188, lineage_min_height + tokens.panel_spacing * 5),
        )
        if hasattr(self._lineage_rail, "apply_density"):
            self._lineage_rail.apply_density(tokens)

    def sync_from_host(self) -> None:
        """Refresh dock content from the host workflow state."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        active_node = controller.active_node() if controller is not None else None
        workspace_root = controller.workspace_root if controller is not None else None
        warnings = controller.warnings() if controller is not None else ()
        has_workflow = controller is not None and controller.profile is not None

        self._profile_chip.set_status(
            controller.profile.display_name if has_workflow else "No workflow",
            level="info" if has_workflow else "neutral",
            tooltip="Current workflow profile",
        )
        self._workspace_chip.set_status(
            (
                controller.anchor_summary_label()
                if controller is not None and workspace_root is not None
                else "Folder mode"
            ),
            level="success" if workspace_root is not None else "warning",
            tooltip=(
                (
                    f"{workspace_root}\n"
                    f"Selected scope: {controller.anchor_summary_label()}"
                )
                if controller is not None and workspace_root is not None
                else "No workflow workspace is loaded."
            ),
        )
        self._active_chip.set_status(
            active_node.display_name if active_node is not None else "No active scope",
            level="success" if active_node is not None else "neutral",
            tooltip=str(active_node.folder_path) if active_node is not None else "No active workflow node",
        )
        warning_text = "\n".join(warnings[:2]).strip()
        self._warning_label.setText(warning_text)
        self._warning_label.setVisible(bool(warning_text))
        self._select_workflow_button.setText("Workflow")
        ancestry = (
            controller.ancestry_for(active_node.node_id)
            if controller is not None and active_node is not None
            else ()
        )
        profile = controller.profile if controller is not None else None
        self._lineage_rail.set_entries(
            tuple(
                WorkflowLineageEntry(
                    label=node.display_name,
                    detail=(
                        profile.node_type(node.type_id).display_name
                        if profile is not None
                        else node.type_id.replace("_", " ").title()
                    ),
                    tooltip=str(node.folder_path),
                    is_active=node.node_id == controller.active_node_id,
                )
                for node in ancestry
            ),
            context_label=(
                controller.anchor_summary_label()
                if controller is not None and controller.is_partial_workspace()
                else None
            ),
            empty_text="Load a workflow and choose an active node to see the current path.",
        )
        self._lineage_scroll.setVisible(not self._lineage_rail.isHidden())
        tree_signature = self._tree_signature(controller)
        if tree_signature != self._tree_structure_signature:
            self._populate_tree()
            self._tree_structure_signature = tree_signature
        else:
            self._refresh_tree_items()
        self._select_active_node()
        self._sync_action_state()
        self._restore_pending_scroll_position()

    def _populate_tree(self) -> None:
        """Rebuild the tree from the host workflow controller."""

        self._clear_pending_session_creation(remove_item=False)
        expanded_node_ids = self._expanded_node_ids()
        vertical_value = self._tree.verticalScrollBar().value()
        horizontal_value = self._tree.horizontalScrollBar().value()
        self._item_by_node_id.clear()
        self._tree.clear()
        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None or controller.root_node_id is None:
            self._tree_structure_signature = ()
            return

        active_lineage = {
            node.node_id
            for node in controller.ancestry_for(controller.active_node_id)
        }
        profile = controller.profile
        metadata_controller = getattr(self._host_window, "metadata_state_controller", None)

        def _make_item(node_id: str) -> qtw.QTreeWidgetItem | None:
            node = controller.node(node_id)
            if node is None:
                return None
            type_label = (
                profile.node_type(node.type_id).display_name
                if profile is not None
                else node.type_id.replace("_", " ").title()
            )
            status_parts: list[str] = []
            if node.node_id == controller.active_node_id:
                status_parts.append("Active")
            elif node.node_id in active_lineage:
                status_parts.append("Path")

            if metadata_controller is not None:
                try:
                    local_card = metadata_controller.load_node_metadata(node.folder_path)
                except Exception:
                    local_card = None
                if local_card is not None and local_card.metadata:
                    status_parts.append("Local")

            item = qtw.QTreeWidgetItem(
                [
                    node.display_name,
                    type_label,
                    " | ".join(status_parts) if status_parts else "",
                ],
            )
            item.setData(0, Qt.UserRole, node.node_id)
            item.setIcon(0, self._icon_for_type(node.type_id))
            item.setToolTip(0, str(node.folder_path))
            item.setToolTip(1, node.type_id)
            item.setToolTip(2, item.text(2))

            if node.node_id == controller.active_node_id:
                font = item.font(0)
                font.setBold(True)
                for column in range(3):
                    item.setFont(column, font)
            self._item_by_node_id[node.node_id] = item
            for child in controller.children_of(node.node_id):
                child_item = _make_item(child.node_id)
                if child_item is not None:
                    item.addChild(child_item)
            return item

        root_item = _make_item(controller.root_node_id)
        if root_item is not None:
            self._tree.addTopLevelItem(root_item)
            if expanded_node_ids:
                for node_id in expanded_node_ids:
                    item = self._item_by_node_id.get(node_id)
                    if item is not None:
                        item.setExpanded(True)
            else:
                self._tree.expandToDepth(2)
            for node in controller.ancestry_for(controller.active_node_id):
                item = self._item_by_node_id.get(node.node_id)
                if item is not None:
                    item.setExpanded(True)
        self._tree.verticalScrollBar().setValue(vertical_value)
        self._tree.horizontalScrollBar().setValue(horizontal_value)

    def _tree_signature(
        self,
        controller,
    ) -> tuple[tuple[str, str, str, str, str], ...]:
        """Return a stable signature so pure selection changes avoid rebuilds."""

        if controller is None or controller.root_node_id is None:
            return ()
        return tuple(
            (
                node.node_id,
                node.parent_id or "",
                node.type_id,
                node.display_name,
                str(node.folder_path),
            )
            for node in controller.nodes()
        )

    def _expanded_node_ids(self) -> set[str]:
        """Return expanded workflow-node ids so tree refreshes can preserve view."""

        expanded: set[str] = set()

        def _visit(item: qtw.QTreeWidgetItem) -> None:
            node_id = item.data(0, Qt.UserRole)
            if item.isExpanded() and node_id:
                expanded.add(str(node_id))
            for index in range(item.childCount()):
                _visit(item.child(index))

        for index in range(self._tree.topLevelItemCount()):
            _visit(self._tree.topLevelItem(index))
        return expanded

    def _refresh_tree_items(self) -> None:
        """Refresh row text and status without rebuilding the whole tree."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None or controller.root_node_id is None:
            return
        profile = controller.profile
        metadata_controller = getattr(self._host_window, "metadata_state_controller", None)
        active_lineage = {
            node.node_id for node in controller.ancestry_for(controller.active_node_id)
        }
        for node in controller.nodes():
            item = self._item_by_node_id.get(node.node_id)
            if item is None:
                continue
            type_label = (
                profile.node_type(node.type_id).display_name
                if profile is not None
                else node.type_id.replace("_", " ").title()
            )
            status_parts: list[str] = []
            if node.node_id == controller.active_node_id:
                status_parts.append("Active")
            elif node.node_id in active_lineage:
                status_parts.append("Path")
            if metadata_controller is not None:
                try:
                    local_card = metadata_controller.load_node_metadata(node.folder_path)
                except Exception:
                    local_card = None
                if local_card is not None and local_card.metadata:
                    status_parts.append("Local")
            item.setText(0, node.display_name)
            item.setText(1, type_label)
            item.setText(2, " | ".join(status_parts) if status_parts else "")
            item.setToolTip(0, str(node.folder_path))
            item.setToolTip(1, node.type_id)
            item.setToolTip(2, item.text(2))
            item.setIcon(0, self._icon_for_type(node.type_id))
            font = item.font(0)
            font.setBold(node.node_id == controller.active_node_id)
            for column in range(3):
                item.setFont(column, font)

    def _selected_node(self):
        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None:
            return None
        items = self._tree.selectedItems()
        if not items:
            return controller.active_node()
        node_id = items[0].data(0, Qt.UserRole)
        return controller.node(node_id)

    def _select_active_node(self) -> None:
        """Select the host active node without recursing into updates."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None or controller.active_node_id is None:
            return
        item = self._item_by_node_id.get(controller.active_node_id)
        if item is None:
            return
        current_item = self._tree.currentItem()
        if current_item is not None and current_item.data(0, Qt.UserRole) == controller.active_node_id:
            return
        self._syncing_selection = True
        try:
            self._tree.setCurrentItem(item)
        finally:
            self._syncing_selection = False

    def _sync_action_state(self) -> None:
        """Enable or disable dock actions from current workflow state."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        has_workflow = controller is not None and controller.profile is not None
        has_selection = self._selected_node() is not None
        self._refresh_button.setEnabled(has_workflow)
        self._scan_button.setEnabled(has_selection)
        self._metadata_button.setEnabled(has_selection)
        self._advanced_open_folder_action.setEnabled(has_selection)
        self._advanced_button.setEnabled(has_workflow)
        self._sync_structure_actions()

    def _structure_action_state(self) -> dict[str, object]:
        state_fn = getattr(self._host_window, "_workflow_structure_action_state", None)
        node = self._selected_node()
        if callable(state_fn) and node is not None:
            try:
                return dict(state_fn(node.node_id))
            except Exception:
                return {}
        return {}

    def _sync_structure_actions(self) -> None:
        """Enable or disable structure-authoring actions for the selected node."""

        state = self._structure_action_state()
        can_create_session = bool(state.get("can_create_session", False))
        can_delete_session = bool(state.get("can_delete_session", False))
        can_create = bool(state.get("can_create", False))
        can_batch_create = bool(state.get("can_batch_create", False))
        can_rename = bool(state.get("can_rename", False))
        can_delete = bool(state.get("can_delete", False))
        can_reindex = bool(state.get("can_reindex", False))
        self._structure_button.setEnabled(
            can_create_session
            or can_delete_session
            or can_create
            or can_batch_create
            or can_rename
            or can_delete
            or can_reindex,
        )
        self._new_session_action.setEnabled(can_create_session)
        self._delete_session_action.setEnabled(can_delete_session)
        self._new_acquisition_action.setEnabled(can_create)
        self._batch_create_action.setEnabled(can_batch_create)
        self._rename_acquisition_action.setEnabled(can_rename)
        self._delete_acquisition_action.setEnabled(can_delete)
        self._reindex_action.setEnabled(can_reindex)
        warning_text = str(state.get("warning_text", "") or "").strip()
        tooltip = warning_text or "Create, rename, delete, or normalize workflow folders."
        self._structure_button.setToolTip(tooltip)
        self._new_session_action.setToolTip(tooltip)
        self._delete_session_action.setToolTip(tooltip)
        self._new_acquisition_action.setToolTip(tooltip)
        self._batch_create_action.setToolTip(tooltip)
        self._rename_acquisition_action.setToolTip(tooltip)
        self._delete_acquisition_action.setToolTip(tooltip)
        self._reindex_action.setToolTip(tooltip)
        controller = getattr(self._host_window, "workflow_state_controller", None)
        workflow_warnings = controller.warnings() if controller is not None else ()
        combined = list(workflow_warnings[:2])
        if warning_text and warning_text not in combined:
            combined.append(warning_text)
        self._warning_label.setText("\n".join(combined))

    def _on_selection_changed(self) -> None:
        """Push the selected node into the host active workflow context."""

        if self._syncing_selection:
            return
        node = self._selected_node()
        if node is None:
            self._sync_action_state()
            return
        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is not None and node.node_id != controller.active_node_id:
            self._pending_scroll_restore = (
                self._tree.verticalScrollBar().value(),
                self._tree.horizontalScrollBar().value(),
            )
            self._host_window.set_active_workflow_node(node.node_id)
            return
        self._sync_action_state()

    def _open_workflow_selector(self) -> None:
        """Open the host workflow selector dialog."""

        open_dialog = getattr(self._host_window, "_open_workflow_selection_dialog", None)
        if callable(open_dialog):
            open_dialog()

    def _refresh_workflow(self) -> None:
        """Reload the current workflow tree and preserve active node."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None or controller.workspace_root is None or controller.profile_id is None:
            return
        self._host_window.set_workflow_context(
            str(controller.workspace_root),
            controller.profile_id,
            active_node_id=controller.active_node_id,
        )

    def _scan_scope(self) -> None:
        """Scan the currently active workflow scope through the Data page."""

        load_folder = getattr(self._host_window, "load_folder", None)
        tabs = getattr(self._host_window, "workflow_tabs", None)
        if tabs is not None:
            tabs.setCurrentIndex(0)
        if callable(load_folder):
            load_folder()

    def _open_metadata_manager(self) -> None:
        """Reveal the persistent metadata inspector for the active node."""

        reveal = getattr(self._host_window, "_reveal_metadata_inspector_dock", None)
        if callable(reveal):
            reveal()

    def _open_workflow_tools(self) -> None:
        """Reveal the advanced workflow management dialog."""

        open_dialog = getattr(self._host_window, "_open_workflow_manager_dialog", None)
        if callable(open_dialog):
            open_dialog()

    def _new_acquisition(self) -> None:
        """Create one acquisition under the selected workflow session."""

        node = self._selected_node()
        if node is None:
            return
        handler = getattr(self._host_window, "_open_workflow_acquisition_creation_dialog", None)
        if callable(handler):
            handler(node.node_id, batch=False)

    def _batch_create_acquisitions(self) -> None:
        """Create several acquisitions under the selected workflow session."""

        node = self._selected_node()
        if node is None:
            return
        handler = getattr(self._host_window, "_open_workflow_acquisition_creation_dialog", None)
        if callable(handler):
            handler(node.node_id, batch=True)

    def _new_session(self) -> None:
        """Create a new session inline under the selected campaign node."""

        node = self._selected_node()
        if node is None or node.type_id != "campaign":
            return
        self._begin_inline_session_creation(node.node_id)

    def _rename_acquisition(self) -> None:
        """Rename the selected workflow acquisition."""

        node = self._selected_node()
        if node is None:
            return
        handler = getattr(self._host_window, "_rename_workflow_acquisition", None)
        if callable(handler):
            handler(node.node_id)

    def _delete_acquisition(self) -> None:
        """Delete the selected workflow acquisition."""

        node = self._selected_node()
        if node is None:
            return
        handler = getattr(self._host_window, "_delete_workflow_acquisition", None)
        if callable(handler):
            handler(node.node_id)

    def _delete_session(self) -> None:
        """Delete the selected workflow session."""

        node = self._selected_node()
        if node is None:
            return
        handler = getattr(self._host_window, "_delete_workflow_session", None)
        if callable(handler):
            handler(node.node_id)

    def _reindex_session(self) -> None:
        """Normalize acquisition numbering for the selected workflow session."""

        node = self._selected_node()
        if node is None:
            return
        handler = getattr(self._host_window, "_reindex_workflow_session", None)
        if callable(handler):
            handler(node.node_id)

    def _new_context_node(self) -> None:
        """Trigger the primary create action for the selected workflow node."""

        state = self._structure_action_state()
        if not bool(state.get("can_create_child", False)):
            return
        node = self._selected_node()
        if node is None:
            return
        child_type_id = str(state.get("create_child_type_id", "") or "").strip().lower()
        if child_type_id == "acquisition":
            self._new_acquisition()
            return
        if child_type_id == "session":
            self._begin_inline_session_creation(node.node_id)
            return
        if child_type_id:
            self._begin_inline_child_creation(node.node_id, child_type_id)

    def _delete_context_node(self) -> None:
        """Trigger the primary delete action for the selected workflow node."""

        node = self._selected_node()
        if node is None:
            return
        handler = getattr(self._host_window, "_delete_workflow_node", None)
        if callable(handler):
            handler(node.node_id)

    def _build_tree_context_menu(self) -> qtw.QMenu:
        """Build the right-click menu for the current tree selection."""

        self._sync_structure_actions()
        state = self._structure_action_state()
        menu = qtw.QMenu(self)

        new_action = menu.addAction(
            str(state.get("create_action_text", "New...") or "New..."),
        )
        new_action.setEnabled(bool(state.get("can_create_child", False)))
        new_action.triggered.connect(self._new_context_node)

        has_secondary_actions = any(
            (
                self._batch_create_action.isEnabled(),
                self._reindex_action.isEnabled(),
                self._rename_acquisition_action.isEnabled(),
            ),
        )
        if has_secondary_actions:
            menu.addSeparator()
        if self._batch_create_action.isEnabled():
            action = menu.addAction("Batch Create...")
            action.triggered.connect(self._batch_create_acquisitions)
        if self._reindex_action.isEnabled():
            action = menu.addAction("Normalize/Reindex...")
            action.triggered.connect(self._reindex_session)
        if self._rename_acquisition_action.isEnabled():
            action = menu.addAction("Rename / Relabel...")
            action.triggered.connect(self._rename_acquisition)

        menu.addSeparator()
        delete_action = menu.addAction(
            str(state.get("delete_action_text", "Delete...") or "Delete..."),
        )
        delete_action.setEnabled(bool(state.get("can_delete_node", False)))
        delete_action.triggered.connect(self._delete_context_node)

        menu.addSeparator()
        open_action = menu.addAction("Open in File Explorer")
        open_action.setEnabled(bool(state.get("can_open_folder", False)))
        open_action.triggered.connect(self._open_selected_folder)
        return menu

    def _show_tree_context_menu(self, position: QtCore.QPoint) -> None:
        """Show structure-authoring actions for the selected workflow node."""

        item = self._tree.itemAt(position)
        if item is not None:
            self._tree.setCurrentItem(item)
        menu = self._build_tree_context_menu()
        if not menu.actions():
            return
        menu.exec(self._tree.viewport().mapToGlobal(position))

    def _handle_metadata_field_drop(
        self,
        payload: dict[str, object],
        target_node_id: str,
    ) -> bool:
        """Move one metadata field onto the dropped workflow-tree target."""

        mover = getattr(
            self._host_window,
            "_move_metadata_field_to_workflow_node_payload",
            None,
        )
        if not callable(mover):
            return False
        try:
            return bool(mover(payload, target_node_id))
        except Exception as exc:
            qtw.QMessageBox.warning(
                self,
                "Move Metadata Field",
                str(exc),
            )
            return False

    def _begin_inline_child_creation(
        self,
        parent_node_id: str,
        child_type_id: str,
    ) -> None:
        """Add a temporary inline editor row under one workflow item."""

        self._clear_pending_session_creation(remove_item=True)
        parent_item = self._item_by_node_id.get(parent_node_id)
        if parent_item is None:
            return
        parent_item.setExpanded(True)
        child_label = child_type_id.replace("_", " ").title()
        controller = getattr(self._host_window, "workflow_state_controller", None)
        profile = controller.profile if controller is not None else None
        if profile is not None:
            try:
                child_label = profile.node_type(child_type_id).display_name
            except KeyError:
                pass

        pending_item = qtw.QTreeWidgetItem(["", child_label, "Pending"])
        pending_item.setIcon(0, self._icon_for_type(child_type_id))
        pending_item.setToolTip(0, f"Enter the new {child_label.lower()} folder label.")
        parent_item.addChild(pending_item)

        editor = qtw.QLineEdit(self._tree)
        editor.setPlaceholderText(f"New {child_label.lower()} folder")
        editor.editingFinished.connect(self._finalize_pending_session_creation)
        self._tree.setItemWidget(pending_item, 0, editor)
        self._tree.scrollToItem(pending_item, qtw.QAbstractItemView.PositionAtBottom)

        self._pending_session_parent_node_id = parent_node_id
        self._pending_session_item = pending_item
        self._pending_session_editor = editor
        self._pending_child_type_id = child_type_id

        editor.setFocus(Qt.OtherFocusReason)
        editor.selectAll()

    def _begin_inline_session_creation(self, campaign_node_id: str) -> None:
        """Add a temporary inline editor row for creating one session child."""

        self._begin_inline_child_creation(campaign_node_id, "session")

    def _clear_pending_session_creation(self, *, remove_item: bool) -> None:
        """Tear down any active inline session-creation editor."""

        editor = self._pending_session_editor
        item = self._pending_session_item
        self._pending_session_parent_node_id = None
        self._pending_session_editor = None
        self._pending_session_item = None
        self._pending_child_type_id = None

        if editor is not None:
            try:
                editor.editingFinished.disconnect(self._finalize_pending_session_creation)
            except (RuntimeError, TypeError):
                pass
            if item is not None and self._tree.itemWidget(item, 0) is editor:
                self._tree.removeItemWidget(item, 0)
            editor.deleteLater()

        if not remove_item or item is None:
            return
        parent_item = item.parent()
        if parent_item is not None:
            parent_item.removeChild(item)
            return
        index = self._tree.indexOfTopLevelItem(item)
        if index >= 0:
            self._tree.takeTopLevelItem(index)

    def _finalize_pending_session_creation(self) -> None:
        """Commit or cancel the active inline session-creation editor."""

        editor = self._pending_session_editor
        parent_node_id = self._pending_session_parent_node_id
        child_type_id = self._pending_child_type_id
        if editor is None or not parent_node_id or not child_type_id:
            return
        folder_label = editor.text().strip()
        self._clear_pending_session_creation(remove_item=True)
        if not folder_label:
            return

        handler = getattr(self._host_window, "_create_workflow_child_node", None)
        if not callable(handler):
            return
        try:
            handler(parent_node_id, folder_label)
        except Exception as exc:
            qtw.QMessageBox.warning(
                self,
                f"New {child_type_id.replace('_', ' ').title()}",
                str(exc),
            )

    def _open_selected_folder(self) -> None:
        """Open the selected node folder in the desktop file browser."""

        node = self._selected_node()
        if node is None:
            return
        opened = QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(node.folder_path)),
        )
        if not opened:
            qtw.QMessageBox.warning(
                self,
                "Open Folder",
                f"Could not open folder:\n{node.folder_path}",
            )

    def _on_visibility_changed(self, visible: bool) -> None:
        """Persist explorer visibility using the host panel-state store."""

        remember = getattr(self._host_window, "_remember_panel_state", None)
        if callable(remember):
            remember(self.PANEL_STATE_KEY, bool(visible))
        sync_shell = getattr(
            self._host_window,
            "_sync_workflow_context_row_visibility",
            None,
        )
        if callable(sync_shell):
            sync_shell()

    def _restore_pending_scroll_position(self) -> None:
        """Restore the tree viewport after host-driven selection sync."""

        if self._pending_scroll_restore is None:
            return
        vertical_value, horizontal_value = self._pending_scroll_restore
        self._pending_scroll_restore = None

        def _restore() -> None:
            self._tree.verticalScrollBar().setValue(vertical_value)
            self._tree.horizontalScrollBar().setValue(horizontal_value)

        QtCore.QTimer.singleShot(0, _restore)

    def _icon_for_type(self, type_id: str) -> QtGui.QIcon:
        """Return a lightweight standard icon for one workflow node type."""

        style = self.style()
        icon_map = {
            "root": qtw.QStyle.SP_DirHomeIcon,
            "trial": qtw.QStyle.SP_FileDialogDetailedView,
            "camera": qtw.QStyle.SP_ComputerIcon,
            "campaign": qtw.QStyle.SP_FileDialogListView,
            "session": qtw.QStyle.SP_DirOpenIcon,
            "acquisition": qtw.QStyle.SP_FileIcon,
        }
        return style.standardIcon(icon_map.get(type_id, qtw.QStyle.SP_DirIcon))
