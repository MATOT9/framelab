"""Minimal Phase 1 workflow manager dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt

from .ui_primitives import ChipSpec, SummaryItem, build_page_header, build_summary_strip
from .window_drag import apply_secondary_window_geometry, configure_secondary_window
from .workflow import workflow_profile_by_id
from .workflow_widgets import WorkflowBreadcrumbBar


class WorkflowManagerDialog(qtw.QDialog):
    """Advanced workflow dialog kept secondary to the explorer dock."""

    def __init__(self, host_window: qtw.QWidget) -> None:
        super().__init__(host_window)
        self._host_window = host_window
        self._item_by_node_id: dict[str, qtw.QTreeWidgetItem] = {}

        self.setWindowTitle("Workflow Tools")
        configure_secondary_window(self)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(920, 620)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._header = build_page_header(
            "Workflow Tools",
            (
                "Use Workflow Explorer for day-to-day navigation. This window is "
                "for workspace rebinding, validation, and scope troubleshooting."
            ),
        )
        layout.addWidget(self._header)
        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)

        controls = qtw.QFrame()
        controls.setObjectName("CommandBar")
        controls_layout = qtw.QGridLayout(controls)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setHorizontalSpacing(8)
        controls_layout.setVerticalSpacing(8)

        profile_label = qtw.QLabel("Profile")
        profile_label.setObjectName("SectionTitle")
        controls_layout.addWidget(profile_label, 0, 0)

        self._profile_combo = qtw.QComboBox()
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        controls_layout.addWidget(self._profile_combo, 0, 1)

        workspace_label = qtw.QLabel("Workspace Root")
        workspace_label.setObjectName("SectionTitle")
        controls_layout.addWidget(workspace_label, 1, 0)

        self._workspace_edit = qtw.QLineEdit()
        self._workspace_edit.setPlaceholderText("Select workflow workspace root")
        self._workspace_edit.textChanged.connect(lambda _text: self._update_anchor_hint())
        controls_layout.addWidget(self._workspace_edit, 1, 1)

        self._browse_button = qtw.QPushButton("Browse...")
        self._browse_button.clicked.connect(self._browse_workspace)
        controls_layout.addWidget(self._browse_button, 1, 2)

        anchor_label = qtw.QLabel("Open As")
        anchor_label.setObjectName("SectionTitle")
        controls_layout.addWidget(anchor_label, 2, 0)

        self._anchor_combo = qtw.QComboBox()
        self._anchor_combo.currentIndexChanged.connect(self._on_anchor_changed)
        controls_layout.addWidget(self._anchor_combo, 2, 1)

        self._anchor_hint = qtw.QLabel("")
        self._anchor_hint.setObjectName("MutedLabel")
        self._anchor_hint.setWordWrap(True)
        controls_layout.addWidget(self._anchor_hint, 2, 2, 1, 2)

        self._load_button = qtw.QPushButton("Rebind Workflow")
        self._load_button.setObjectName("AccentButton")
        self._load_button.clicked.connect(self._load_workflow)
        controls_layout.addWidget(self._load_button, 0, 2)

        self._refresh_button = qtw.QPushButton("Refresh Tree")
        self._refresh_button.clicked.connect(self._refresh_workflow)
        controls_layout.addWidget(self._refresh_button, 0, 3)

        layout.addWidget(controls)

        self._breadcrumb = WorkflowBreadcrumbBar()
        layout.addWidget(self._breadcrumb)

        self._warning_label = qtw.QLabel("")
        self._warning_label.setObjectName("MutedLabel")
        self._warning_label.setWordWrap(True)
        layout.addWidget(self._warning_label)

        self._tree = qtw.QTreeWidget()
        self._tree.setObjectName("WorkflowTree")
        self._tree.setHeaderLabels(["Node", "Type", "Relative Path"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.setSelectionMode(qtw.QAbstractItemView.SingleSelection)
        self._tree.setSelectionBehavior(qtw.QAbstractItemView.SelectRows)
        self._tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(
            lambda _item, _column: self._set_selected_node_active(),
        )
        self._tree.header().setStretchLastSection(True)
        self._tree.header().setSectionResizeMode(0, qtw.QHeaderView.Stretch)
        layout.addWidget(self._tree, 1)

        actions = qtw.QHBoxLayout()
        actions.setSpacing(8)

        self._set_active_button = qtw.QPushButton("Set Active Scope")
        self._set_active_button.clicked.connect(self._set_selected_node_active)
        actions.addWidget(self._set_active_button)

        self._load_scope_button = qtw.QPushButton("Scan Selected Scope")
        self._load_scope_button.clicked.connect(self._load_selected_scope)
        actions.addWidget(self._load_scope_button)

        self._structure_button = qtw.QPushButton("Structure...")
        self._structure_menu = qtw.QMenu(self._structure_button)
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
        self._structure_button.clicked.connect(self._show_structure_menu)
        actions.addWidget(self._structure_button)

        self._metadata_button = qtw.QPushButton("Reveal Metadata Inspector")
        self._metadata_button.clicked.connect(self._reveal_metadata_inspector)
        actions.addWidget(self._metadata_button)

        self._open_folder_button = qtw.QPushButton("Open Folder")
        self._open_folder_button.clicked.connect(self._open_selected_folder)
        actions.addWidget(self._open_folder_button)

        actions.addStretch(1)
        close_button = qtw.QPushButton("Close")
        close_button.clicked.connect(self.close)
        actions.addWidget(close_button)
        layout.addLayout(actions)

        self._populate_profiles()
        self.sync_from_host()
        apply_secondary_window_geometry(
            self,
            preferred_size=(1080, 760),
            host_window=host_window,
        )

    def _populate_profiles(self) -> None:
        """Populate the profile picker from the host workflow controller."""

        self._profile_combo.clear()
        controller = getattr(self._host_window, "workflow_state_controller", None)
        profiles = controller.available_profiles() if controller is not None else ()
        for profile in profiles:
            self._profile_combo.addItem(profile.display_name, profile.profile_id)
        self._populate_anchor_options()

    def _selected_profile(self):
        profile_id = self._profile_combo.currentData()
        if profile_id is None:
            return None
        return workflow_profile_by_id(str(profile_id))

    def _anchor_label_for(
        self,
        profile_id: str | None,
        anchor_type_id: str | None,
    ) -> str:
        if not profile_id or not anchor_type_id:
            return "Full workspace"
        profile = workflow_profile_by_id(profile_id)
        if profile is None:
            return anchor_type_id.replace("_", " ").title()
        try:
            if anchor_type_id == "root":
                return "Full workspace"
            return f"{profile.node_type(anchor_type_id).display_name} subtree"
        except KeyError:
            return anchor_type_id.replace("_", " ").title()

    def _populate_anchor_options(
        self,
        preferred_anchor_type_id: str | None = None,
    ) -> None:
        """Populate explicit anchor choices for the selected profile."""

        profile = self._selected_profile()
        previous = preferred_anchor_type_id
        if previous is None:
            current_data = self._anchor_combo.currentData()
            previous = str(current_data).strip().lower() if current_data else None
        blocker = QtCore.QSignalBlocker(self._anchor_combo)
        self._anchor_combo.clear()
        self._anchor_combo.addItem("Auto Detect", None)
        if profile is not None:
            for node_type in profile.node_types:
                label = "Full workspace" if node_type.type_id == "root" else (
                    f"{node_type.display_name} subtree"
                )
                self._anchor_combo.addItem(label, node_type.type_id)
        if previous is None:
            self._anchor_combo.setCurrentIndex(0)
        else:
            index = self._anchor_combo.findData(previous)
            self._anchor_combo.setCurrentIndex(index if index >= 0 else 0)
        del blocker
        self._update_anchor_hint()

    def _current_anchor_type_id(self) -> str | None:
        data = self._anchor_combo.currentData()
        text = str(data).strip().lower() if data is not None else ""
        return text or None

    def _update_anchor_hint(self) -> None:
        """Show how the current rebinding path will be interpreted."""

        workspace_root = self._workspace_edit.text().strip()
        profile = self._selected_profile()
        if profile is None:
            self._anchor_hint.setText("Choose a workflow profile first.")
            return
        explicit_anchor = self._current_anchor_type_id()
        if explicit_anchor is not None:
            self._anchor_hint.setText(
                f"Rebinding will open this folder as {self._anchor_label_for(profile.profile_id, explicit_anchor)}.",
            )
            return
        if not workspace_root:
            self._anchor_hint.setText(
                "Auto Detect chooses the most likely workflow node type for the selected folder.",
            )
            return
        controller = getattr(self._host_window, "workflow_state_controller", None)
        inferred = (
            controller.infer_anchor_type(workspace_root, profile.profile_id)
            if controller is not None
            else None
        )
        if inferred is None:
            self._anchor_hint.setText(
                "Auto Detect is currently uncertain; rebinding will fall back to Full workspace.",
            )
            return
        self._anchor_hint.setText(
            f"Auto Detect would open this folder as {self._anchor_label_for(profile.profile_id, inferred)}.",
        )

    def sync_from_host(self) -> None:
        """Refresh dialog content from the host window state."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None:
            return
        root = controller.workspace_root
        if controller.profile_id:
            profile_index = self._profile_combo.findData(controller.profile_id)
            if profile_index >= 0:
                blocker = QtCore.QSignalBlocker(self._profile_combo)
                self._profile_combo.setCurrentIndex(profile_index)
                del blocker
            self._populate_anchor_options(controller.anchor_type_id)
        else:
            self._populate_anchor_options()
        blocker = QtCore.QSignalBlocker(self._workspace_edit)
        self._workspace_edit.setText(str(root) if root is not None else "")
        del blocker
        self._update_anchor_hint()
        self._populate_tree()
        self._select_active_node()
        self._refresh_summary()

    def _browse_workspace(self) -> None:
        """Browse for one workflow workspace root."""

        start = self._workspace_edit.text().strip() or str(Path.home())
        folder = qtw.QFileDialog.getExistingDirectory(
            self,
            "Select Workflow Workspace",
            start,
            qtw.QFileDialog.ShowDirsOnly,
        )
        if folder:
            self._workspace_edit.setText(folder)
            self._update_anchor_hint()

    def _load_workflow(self) -> None:
        """Load one workflow workspace/profile into the host window."""

        workspace_root = self._workspace_edit.text().strip()
        profile_id = self._profile_combo.currentData()
        if not workspace_root or not profile_id:
            self._warning_label.setText("Choose both a workflow profile and a workspace root.")
            return
        resolve_load = getattr(self._host_window, "_resolve_workflow_load_request", None)
        if not callable(resolve_load):
            self._warning_label.setText("Host window does not support workflow loading.")
            return
        resolution = resolve_load(
            workspace_root,
            str(profile_id),
            anchor_type_id=self._current_anchor_type_id(),
            prompt_parent=self,
        )
        if resolution is None:
            return
        try:
            self._host_window.set_workflow_context(
                workspace_root,
                resolution.profile_id,
                anchor_type_id=resolution.anchor_type_id,
            )
        except Exception as exc:
            self._warning_label.setText(f"Could not load workflow: {exc}")
            return
        self.sync_from_host()
        self._warning_label.setText(resolution.info_text)

    def _refresh_workflow(self) -> None:
        """Reload the currently selected workflow workspace."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None or controller.workspace_root is None or controller.profile_id is None:
            self._warning_label.setText("Load a workflow workspace first.")
            return
        self._host_window.set_workflow_context(
            str(controller.workspace_root),
            controller.profile_id,
            anchor_type_id=controller.anchor_type_id,
            active_node_id=controller.active_node_id,
        )
        self._warning_label.setText("")
        self.sync_from_host()

    def _on_profile_changed(self) -> None:
        """Rebuild Open As choices when the profile changes."""

        self._populate_anchor_options()

    def _on_anchor_changed(self) -> None:
        """Refresh the anchor summary text when the choice changes."""

        self._update_anchor_hint()

    def _populate_tree(self) -> None:
        """Rebuild the workflow tree from the host controller state."""

        self._item_by_node_id.clear()
        self._tree.clear()
        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None or controller.root_node_id is None:
            return

        def _make_item(node_id: str) -> qtw.QTreeWidgetItem | None:
            node = controller.node(node_id)
            if node is None:
                return None
            item = qtw.QTreeWidgetItem(
                [
                    node.display_name,
                    node.type_id.replace("_", " ").title(),
                    node.relative_path or ".",
                ],
            )
            item.setData(0, Qt.UserRole, node.node_id)
            item.setToolTip(0, str(node.folder_path))
            item.setToolTip(1, node.type_id)
            item.setToolTip(2, str(node.folder_path))
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
            self._tree.expandToDepth(2)

    def _selected_node_id(self) -> str | None:
        """Return the currently selected workflow node id."""

        items = self._tree.selectedItems()
        if not items:
            return None
        data = items[0].data(0, Qt.UserRole)
        return str(data).strip() if data else None

    def _select_active_node(self) -> None:
        """Select the host active node in the tree when present."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None or controller.active_node_id is None:
            return
        item = self._item_by_node_id.get(controller.active_node_id)
        if item is None:
            return
        self._tree.setCurrentItem(item)
        self._tree.scrollToItem(item)

    def _node_for_selected_item(self):
        controller = getattr(self._host_window, "workflow_state_controller", None)
        if controller is None:
            return None
        return controller.node(self._selected_node_id())

    def _on_selection_changed(self) -> None:
        """Refresh breadcrumbs and button state for the current tree selection."""

        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """Update header chips, summary strip, and breadcrumb."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        selected_node = self._node_for_selected_item()
        active_node = controller.active_node() if controller is not None else None
        warnings = controller.warnings() if controller is not None else ()
        profile = controller.profile if controller is not None else None
        has_workspace = controller is not None and controller.workspace_root is not None
        self._header.set_chips(
            [
                ChipSpec(
                    profile.display_name if profile is not None else "No workflow loaded",
                    level="info" if profile is not None else "neutral",
                ),
                ChipSpec(
                    "Active node selected" if active_node is not None else "No active node",
                    level="success" if active_node is not None else "warning",
                ),
                ChipSpec(
                    controller.anchor_summary_label()
                    if controller is not None and profile is not None
                    else "Auto Detect",
                    level="info" if controller is not None and profile is not None else "neutral",
                ),
                ChipSpec(
                    f"{len(warnings)} warning(s)",
                    level="warning" if warnings else "neutral",
                    tooltip="\n".join(warnings),
                ),
            ],
        )
        self._summary_strip.set_items(
            [
                SummaryItem(
                    "Workspace",
                    str(controller.workspace_root.name) if has_workspace else "None",
                    level="info" if has_workspace else "neutral",
                ),
                SummaryItem(
                    "Nodes",
                    str(len(controller.nodes())) if controller is not None else "0",
                    level="success" if controller is not None and controller.nodes() else "neutral",
                ),
                SummaryItem(
                    "Open As",
                    (
                        controller.anchor_summary_label()
                        if controller is not None and profile is not None
                        else "Auto Detect"
                    ),
                    level="info" if controller is not None and profile is not None else "neutral",
                ),
                SummaryItem(
                    "Active",
                    active_node.display_name if active_node is not None else "None",
                    level="success" if active_node is not None else "neutral",
                ),
                SummaryItem(
                    "Selected",
                    selected_node.display_name if selected_node is not None else "None",
                    level="info" if selected_node is not None else "neutral",
                ),
            ],
        )
        ancestry = ()
        if selected_node is not None and controller is not None:
            ancestry = controller.ancestry_for(selected_node.node_id)
        elif active_node is not None and controller is not None:
            ancestry = controller.ancestry_for(active_node.node_id)
        self._breadcrumb.set_breadcrumb(
            profile_label=profile.display_name if profile is not None else None,
            context_label=(
                controller.anchor_summary_label()
                if controller is not None and controller.is_partial_workspace()
                else None
            ),
            nodes=tuple(
                (node.display_name, str(node.folder_path))
                for node in ancestry
            ),
        )
        self._warning_label.setText("\n".join(warnings[:2]))
        has_selected_node = selected_node is not None
        self._set_active_button.setEnabled(has_selected_node)
        self._load_scope_button.setEnabled(has_selected_node)
        self._metadata_button.setEnabled(has_selected_node)
        self._open_folder_button.setEnabled(has_selected_node)
        self._sync_structure_actions()

    def _structure_action_state(self) -> dict[str, object]:
        state_fn = getattr(self._host_window, "_workflow_structure_action_state", None)
        node = self._node_for_selected_item()
        if callable(state_fn) and node is not None:
            try:
                return dict(state_fn(node.node_id))
            except Exception:
                return {}
        return {}

    def _sync_structure_actions(self) -> None:
        """Enable or disable structure-authoring actions for the selection."""

        state = self._structure_action_state()
        can_create = bool(state.get("can_create", False))
        can_batch_create = bool(state.get("can_batch_create", False))
        can_rename = bool(state.get("can_rename", False))
        can_delete = bool(state.get("can_delete", False))
        can_reindex = bool(state.get("can_reindex", False))
        self._structure_button.setEnabled(
            can_create or can_batch_create or can_rename or can_delete or can_reindex,
        )
        self._new_acquisition_action.setEnabled(can_create)
        self._batch_create_action.setEnabled(can_batch_create)
        self._rename_acquisition_action.setEnabled(can_rename)
        self._delete_acquisition_action.setEnabled(can_delete)
        self._reindex_action.setEnabled(can_reindex)
        warning_text = str(state.get("warning_text", "") or "").strip()
        tooltip = warning_text or "Create, rename, delete, or normalize acquisitions."
        self._structure_button.setToolTip(tooltip)
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

    def _set_selected_node_active(self) -> None:
        """Apply the selected node as the host's active workflow scope."""

        node_id = self._selected_node_id()
        if not node_id:
            return
        self._host_window.set_active_workflow_node(node_id)
        self.sync_from_host()

    def _show_structure_menu(self) -> None:
        """Open the structure menu from the themed dialog button."""

        if not self._structure_button.isEnabled():
            return
        origin = self._structure_button.mapToGlobal(
            QtCore.QPoint(0, self._structure_button.height()),
        )
        self._structure_menu.popup(origin)

    def _load_selected_scope(self) -> None:
        """Apply the selected node and scan its scope on the Data page."""

        self._set_selected_node_active()
        load_folder = getattr(self._host_window, "load_folder", None)
        if callable(load_folder):
            load_folder()

    def _reveal_metadata_inspector(self) -> None:
        """Reveal the primary metadata inspector for the selected node."""

        self._set_selected_node_active()
        reveal = getattr(self._host_window, "_reveal_metadata_inspector_dock", None)
        if callable(reveal):
            reveal()

    def _new_acquisition(self) -> None:
        node_id = self._selected_node_id()
        if not node_id:
            return
        handler = getattr(self._host_window, "_open_workflow_acquisition_creation_dialog", None)
        if callable(handler):
            handler(node_id, batch=False)
            self.sync_from_host()

    def _batch_create_acquisitions(self) -> None:
        node_id = self._selected_node_id()
        if not node_id:
            return
        handler = getattr(self._host_window, "_open_workflow_acquisition_creation_dialog", None)
        if callable(handler):
            handler(node_id, batch=True)
            self.sync_from_host()

    def _rename_acquisition(self) -> None:
        node_id = self._selected_node_id()
        if not node_id:
            return
        handler = getattr(self._host_window, "_rename_workflow_acquisition", None)
        if callable(handler):
            handler(node_id)
            self.sync_from_host()

    def _delete_acquisition(self) -> None:
        node_id = self._selected_node_id()
        if not node_id:
            return
        handler = getattr(self._host_window, "_delete_workflow_acquisition", None)
        if callable(handler):
            handler(node_id)
            self.sync_from_host()

    def _reindex_session(self) -> None:
        node_id = self._selected_node_id()
        if not node_id:
            return
        handler = getattr(self._host_window, "_reindex_workflow_session", None)
        if callable(handler):
            handler(node_id)
            self.sync_from_host()

    def _show_tree_context_menu(self, position: QtCore.QPoint) -> None:
        """Show structure-authoring actions for the selected tree node."""

        item = self._tree.itemAt(position)
        if item is not None:
            self._tree.setCurrentItem(item)
        self._sync_structure_actions()
        menu = qtw.QMenu(self)
        if self._new_acquisition_action.isEnabled():
            action = menu.addAction("New Acquisition...")
            action.triggered.connect(self._new_acquisition)
        if self._batch_create_action.isEnabled():
            action = menu.addAction("Batch Create...")
            action.triggered.connect(self._batch_create_acquisitions)
        if self._reindex_action.isEnabled():
            action = menu.addAction("Normalize/Reindex...")
            action.triggered.connect(self._reindex_session)
        if self._rename_acquisition_action.isEnabled() or self._delete_acquisition_action.isEnabled():
            if not menu.isEmpty():
                menu.addSeparator()
        if self._rename_acquisition_action.isEnabled():
            action = menu.addAction("Rename / Relabel...")
            action.triggered.connect(self._rename_acquisition)
        if self._delete_acquisition_action.isEnabled():
            action = menu.addAction("Delete Acquisition...")
            action.triggered.connect(self._delete_acquisition)
        if menu.isEmpty():
            return
        menu.exec(self._tree.viewport().mapToGlobal(position))

    def _open_selected_folder(self) -> None:
        """Open the selected node folder in the desktop file browser."""

        node = self._node_for_selected_item()
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
