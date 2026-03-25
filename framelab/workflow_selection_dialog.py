"""Dedicated workflow selection dialog for profile/root switching."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets as qtw
from PySide6.QtCore import Qt

from .ui_primitives import ChipSpec, SummaryItem, build_page_header, build_summary_strip
from .ui_settings import RecentWorkflowEntry
from .window_drag import apply_secondary_window_geometry, configure_secondary_window
from .workflow import workflow_profile_by_id
from .workflow_widgets import WorkflowBreadcrumbBar


class WorkflowSelectionDialog(qtw.QDialog):
    """Modal workflow picker kept separate from the workflow manager."""

    def __init__(self, host_window: qtw.QWidget) -> None:
        super().__init__(host_window)
        self._host_window = host_window
        self._selected_recent_entry: RecentWorkflowEntry | None = None

        self.setWindowTitle("Select Workflow")
        configure_secondary_window(self, draggable=True)
        self.setModal(True)
        self.setMinimumSize(700, 520)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._header = build_page_header(
            "Select Workflow",
            (
                "Choose the workflow profile and workspace root that define the "
                "active app context. After loading, use Workflow Explorer for "
                "everyday navigation."
            ),
        )
        layout.addWidget(self._header)

        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)

        self._current_breadcrumb = WorkflowBreadcrumbBar(compact=True)
        layout.addWidget(self._current_breadcrumb)

        self._warning_label = qtw.QLabel("")
        self._warning_label.setObjectName("MutedLabel")
        self._warning_label.setWordWrap(True)
        layout.addWidget(self._warning_label)

        form_panel = qtw.QFrame()
        form_panel.setObjectName("CommandBar")
        form_layout = qtw.QGridLayout(form_panel)
        form_layout.setContentsMargins(12, 10, 12, 10)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(8)

        profile_label = qtw.QLabel("Workflow Profile")
        profile_label.setObjectName("SectionTitle")
        form_layout.addWidget(profile_label, 0, 0)

        self._profile_combo = qtw.QComboBox()
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        form_layout.addWidget(self._profile_combo, 0, 1, 1, 2)

        workspace_label = qtw.QLabel("Workspace Root")
        workspace_label.setObjectName("SectionTitle")
        form_layout.addWidget(workspace_label, 1, 0)

        self._workspace_edit = qtw.QLineEdit()
        self._workspace_edit.setPlaceholderText("Choose workflow workspace root")
        self._workspace_edit.textChanged.connect(self._on_workspace_text_changed)
        form_layout.addWidget(self._workspace_edit, 1, 1)

        self._browse_button = qtw.QPushButton("Browse...")
        self._browse_button.clicked.connect(self._browse_workspace)
        form_layout.addWidget(self._browse_button, 1, 2)

        anchor_label = qtw.QLabel("Open As")
        anchor_label.setObjectName("SectionTitle")
        form_layout.addWidget(anchor_label, 2, 0)

        self._anchor_combo = qtw.QComboBox()
        self._anchor_combo.currentIndexChanged.connect(self._on_anchor_changed)
        form_layout.addWidget(self._anchor_combo, 2, 1)

        self._anchor_hint = qtw.QLabel("")
        self._anchor_hint.setObjectName("MutedLabel")
        self._anchor_hint.setWordWrap(True)
        form_layout.addWidget(self._anchor_hint, 2, 2)

        layout.addWidget(form_panel)

        recent_panel = qtw.QFrame()
        recent_panel.setObjectName("SubtlePanel")
        recent_layout = qtw.QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(12, 10, 12, 10)
        recent_layout.setSpacing(8)

        recent_title = qtw.QLabel("Recent Workflows")
        recent_title.setObjectName("SectionTitle")
        recent_layout.addWidget(recent_title)

        self._recent_list = qtw.QListWidget()
        self._recent_list.setSelectionMode(qtw.QAbstractItemView.SingleSelection)
        self._recent_list.currentItemChanged.connect(self._on_recent_selection_changed)
        self._recent_list.itemDoubleClicked.connect(
            lambda _item: self._load_selected_workflow(),
        )
        recent_layout.addWidget(self._recent_list, 1)

        self._recent_hint = qtw.QLabel(
            "Select a recent workspace to reuse its profile and last active node, "
            "or choose a different profile/root above. This is the primary "
            "workflow entry point, not a plugin-management step.",
        )
        self._recent_hint.setObjectName("MutedLabel")
        self._recent_hint.setWordWrap(True)
        recent_layout.addWidget(self._recent_hint)

        layout.addWidget(recent_panel, 1)

        actions = qtw.QHBoxLayout()
        actions.setSpacing(8)

        self._clear_button = qtw.QPushButton("Clear Workflow")
        self._clear_button.clicked.connect(self._clear_workflow)
        actions.addWidget(self._clear_button)

        actions.addStretch(1)

        cancel_button = qtw.QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)

        self._load_button = qtw.QPushButton("Load Workflow")
        self._load_button.setObjectName("AccentButton")
        self._load_button.clicked.connect(self._load_selected_workflow)
        actions.addWidget(self._load_button)
        layout.addLayout(actions)

        self._populate_profiles()
        self.sync_from_host()
        apply_secondary_window_geometry(
            self,
            preferred_size=(840, 620),
            host_window=host_window,
        )

    def _populate_profiles(self) -> None:
        """Populate known workflow profiles from the host controller."""

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
        """Populate the Open As combo from the selected profile."""

        profile = self._selected_profile()
        previous = preferred_anchor_type_id
        if previous is None:
            current_data = self._anchor_combo.currentData()
            previous = (
                str(current_data).strip().lower()
                if current_data is not None
                else None
            )
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
        """Show how the current folder would be opened."""

        workspace_root = self._workspace_edit.text().strip()
        profile = self._selected_profile()
        if profile is None:
            self._anchor_hint.setText("Choose a workflow profile first.")
            return
        explicit_anchor = self._current_anchor_type_id()
        if explicit_anchor is not None:
            self._anchor_hint.setText(
                f"Will open this folder as {self._anchor_label_for(profile.profile_id, explicit_anchor)}.",
            )
            return
        if not workspace_root:
            self._anchor_hint.setText(
                "Auto Detect picks the most likely workflow node type for the chosen folder.",
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
                "Auto Detect is currently uncertain; loading will fall back to Full workspace.",
            )
            return
        self._anchor_hint.setText(
            f"Auto Detect would open this folder as {self._anchor_label_for(profile.profile_id, inferred)}.",
        )

    def sync_from_host(self) -> None:
        """Refresh current workflow summary and recent entries from the host."""

        controller = getattr(self._host_window, "workflow_state_controller", None)
        profile = controller.profile if controller is not None else None
        active_node = controller.active_node() if controller is not None else None
        workspace_root = controller.workspace_root if controller is not None else None
        ancestry = (
            controller.ancestry_for(active_node.node_id)
            if controller is not None and active_node is not None
            else ()
        )
        recent_entries = tuple(getattr(self._host_window, "recent_workflow_entries")())

        self._header.set_chips(
            [
                ChipSpec(
                    profile.display_name if profile is not None else "No workflow loaded",
                    level="info" if profile is not None else "neutral",
                ),
                ChipSpec(
                    active_node.display_name if active_node is not None else "Folder mode",
                    level="success" if active_node is not None else "warning",
                    tooltip="Current active workflow node",
                ),
                ChipSpec(
                    controller.anchor_summary_label()
                    if controller is not None and controller.profile is not None
                    else "Open as auto",
                    level="info" if controller is not None and controller.profile is not None else "neutral",
                    tooltip="Current workflow anchor scope",
                ),
                ChipSpec(
                    f"{len(recent_entries)} recent",
                    level="neutral" if recent_entries else "warning",
                    tooltip="Recent workflow contexts remembered by the shell",
                ),
            ],
        )
        self._summary_strip.set_items(
            [
                SummaryItem(
                    "Profile",
                    profile.display_name if profile is not None else "None",
                    level="info" if profile is not None else "neutral",
                ),
                SummaryItem(
                    "Workspace",
                    workspace_root.name if workspace_root is not None else "None",
                    level="success" if workspace_root is not None else "neutral",
                    tooltip=str(workspace_root) if workspace_root is not None else "",
                ),
                SummaryItem(
                    "Open As",
                    (
                        controller.anchor_summary_label()
                        if controller is not None and controller.profile is not None
                        else "Auto Detect"
                    ),
                    level="info" if controller is not None and controller.profile is not None else "neutral",
                ),
                SummaryItem(
                    "Active Node",
                    active_node.display_name if active_node is not None else "None",
                    level="success" if active_node is not None else "neutral",
                ),
            ],
        )
        self._current_breadcrumb.set_breadcrumb(
            profile_label=profile.display_name if profile is not None else None,
            context_label=(
                controller.anchor_summary_label()
                if controller is not None and controller.is_partial_workspace()
                else None
            ),
            nodes=tuple(
                (
                    node.display_name,
                    f"{node.type_id.replace('_', ' ').title()}: {node.folder_path}",
                )
                for node in ancestry
            ),
            empty_text="No workflow selected",
        )

        if profile is not None:
            profile_index = self._profile_combo.findData(profile.profile_id)
            if profile_index >= 0:
                blocker = QtCore.QSignalBlocker(self._profile_combo)
                self._profile_combo.setCurrentIndex(profile_index)
                del blocker
            self._populate_anchor_options(controller.anchor_type_id if controller is not None else None)
        elif self._profile_combo.count() > 0 and self._profile_combo.currentIndex() < 0:
            self._profile_combo.setCurrentIndex(0)
            self._populate_anchor_options()

        current_root_text = str(workspace_root) if workspace_root is not None else ""
        blocker = QtCore.QSignalBlocker(self._workspace_edit)
        self._workspace_edit.setText(current_root_text)
        del blocker
        self._populate_recent_list(recent_entries)
        self._selected_recent_entry = None
        self._warning_label.setText("")
        self._update_anchor_hint()
        self._sync_action_state()

    def _populate_recent_list(
        self,
        recent_entries: tuple[RecentWorkflowEntry, ...],
    ) -> None:
        """Rebuild the recent workflow list."""

        self._recent_list.clear()
        controller = getattr(self._host_window, "workflow_state_controller", None)
        current_root = (
            str(controller.workspace_root)
            if controller is not None and controller.workspace_root is not None
            else None
        )
        current_profile_id = controller.profile_id if controller is not None else None
        current_anchor_type_id = (
            controller.anchor_type_id if controller is not None else None
        )
        for entry in recent_entries:
            anchor_label = self._anchor_label_for(entry.profile_id, entry.anchor_type_id)
            label = (
                f"{entry.profile_id.title()}  |  "
                f"{Path(entry.workspace_root).name}  |  {anchor_label}"
            )
            item = qtw.QListWidgetItem(label)
            item.setData(Qt.UserRole, entry)
            item.setToolTip(
                "\n".join(
                    [
                        f"Workspace: {entry.workspace_root}",
                        f"Profile: {entry.profile_id}",
                        f"Open As: {anchor_label}",
                        (
                            f"Last active node: {entry.active_node_id}"
                            if entry.active_node_id
                            else "Last active node: root"
                        ),
                    ],
                ),
            )
            if (
                current_root == entry.workspace_root
                and current_profile_id == entry.profile_id
                and current_anchor_type_id == entry.anchor_type_id
            ):
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._recent_list.addItem(item)
        self._recent_list.setVisible(bool(recent_entries))
        self._recent_hint.setVisible(True)

    def _on_recent_selection_changed(
        self,
        current: qtw.QListWidgetItem | None,
        _previous: qtw.QListWidgetItem | None,
    ) -> None:
        """Mirror a selected recent workflow into the form controls."""

        entry = current.data(Qt.UserRole) if current is not None else None
        if not isinstance(entry, RecentWorkflowEntry):
            self._selected_recent_entry = None
            self._sync_action_state()
            return
        self._selected_recent_entry = entry
        profile_index = self._profile_combo.findData(entry.profile_id)
        if profile_index >= 0:
            self._profile_combo.setCurrentIndex(profile_index)
        anchor_index = self._anchor_combo.findData(entry.anchor_type_id)
        if anchor_index >= 0:
            self._anchor_combo.setCurrentIndex(anchor_index)
        else:
            self._anchor_combo.setCurrentIndex(0)
        self._workspace_edit.setText(entry.workspace_root)
        self._warning_label.setText("")
        self._update_anchor_hint()
        self._sync_action_state()

    def _on_workspace_text_changed(self, text: str) -> None:
        """Clear stale recent selection when the user edits the path manually."""

        self._update_anchor_hint()
        if self._selected_recent_entry is None:
            self._sync_action_state()
            return
        if text.strip() == self._selected_recent_entry.workspace_root:
            self._sync_action_state()
            return
        self._recent_list.clearSelection()
        self._selected_recent_entry = None
        self._sync_action_state()

    def _on_profile_changed(self) -> None:
        """Refresh anchor options when the profile changes."""

        self._populate_anchor_options()
        self._sync_action_state()

    def _on_anchor_changed(self) -> None:
        """Refresh detection text when the Open As mode changes."""

        self._update_anchor_hint()
        self._sync_action_state()

    def _browse_workspace(self) -> None:
        """Browse for a workflow root folder."""

        start = self._workspace_edit.text().strip() or str(Path.home())
        folder = qtw.QFileDialog.getExistingDirectory(
            self,
            "Select Workflow Workspace",
            start,
            qtw.QFileDialog.ShowDirsOnly,
        )
        if folder:
            self._workspace_edit.setText(folder)

    def _clear_workflow(self) -> None:
        """Return the shell to folder-driven mode."""

        self._host_window.set_workflow_context(None, None)
        self.accept()

    def _load_selected_workflow(self) -> None:
        """Load the chosen workflow selection into the host shell."""

        workspace_root = self._workspace_edit.text().strip()
        profile_id = self._profile_combo.currentData()
        if not workspace_root or not profile_id:
            self._warning_label.setText(
                "Choose both a workflow profile and a workspace root.",
            )
            return
        requested_anchor_type_id = self._current_anchor_type_id()
        resolve_load = getattr(self._host_window, "_resolve_workflow_load_request", None)
        if not callable(resolve_load):
            self._warning_label.setText("Host window does not support workflow loading.")
            return
        resolution = resolve_load(
            workspace_root,
            str(profile_id),
            anchor_type_id=requested_anchor_type_id,
            prompt_parent=self,
        )
        if resolution is None:
            return
        requested_active_node_id = None
        if (
            self._selected_recent_entry is not None
            and self._selected_recent_entry.workspace_root == workspace_root
            and self._selected_recent_entry.profile_id == resolution.profile_id
            and self._selected_recent_entry.anchor_type_id == resolution.anchor_type_id
        ):
            requested_active_node_id = self._selected_recent_entry.active_node_id
        try:
            self._host_window.set_workflow_context(
                workspace_root,
                resolution.profile_id,
                anchor_type_id=resolution.anchor_type_id,
                active_node_id=requested_active_node_id,
            )
        except Exception as exc:
            self._warning_label.setText(f"Could not load workflow: {exc}")
            return
        self._warning_label.setText(resolution.info_text)
        self.accept()

    def _sync_action_state(self) -> None:
        """Keep primary actions aligned with the current shell state."""

        has_loaded_workflow = bool(
            getattr(self._host_window.workflow_state_controller, "profile_id", None),
        )
        self._clear_button.setEnabled(has_loaded_workflow)
        self._load_button.setEnabled(
            bool(self._workspace_edit.text().strip())
            and self._profile_combo.currentIndex() >= 0
        )
