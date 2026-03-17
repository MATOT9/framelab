"""Main application window for FrameLab."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Optional
import shutil

import numpy as np
from PySide6 import QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt, QSignalBlocker, QThread, QTimer

from .analysis_context import AnalysisContextController
from .byte_budget_cache import ByteBudgetCache
from .datacard_labels import label_for_metadata_field
from .dataset_state import DatasetScopeNode, DatasetStateController
from .main_window import (
    AnalysisPageMixin,
    DataPageMixin,
    DatasetLoadingMixin,
    InspectPageMixin,
    MetricsRuntimeMixin,
    WindowChromeMixin,
    WindowActionsMixin,
)
from .metrics_cache import MetricsCache
from .metrics_state import MetricsPipelineController
from .metadata import clear_metadata_cache, invalidate_metadata_cache
from .metadata_state import MetadataStateController
from .plugins import (
    PAGE_IDS,
    PluginManifest,
    enabled_plugin_manifests,
    load_enabled_plugins,
    resolve_enabled_plugin_ids,
)
from .plugins.analysis import AnalysisPlugin
from .ui_density import AdaptiveUiContext, UiDensityResolver
from .scan_settings import load_skip_patterns, skip_config_path
from .ui_settings import RecentWorkflowEntry, UiStateSnapshot, UiStateStore
from .workflow import WorkflowStateController
from .workers import DynamicStatsWorker, RoiApplyWorker


def _controller_property(controller_name: str, state_name: str, doc: str) -> property:
    """Build a simple compatibility proxy onto one controller attribute."""

    def getter(self):
        return getattr(getattr(self, controller_name), state_name)

    def setter(self, value):
        setattr(getattr(self, controller_name), state_name, value)

    return property(getter, setter, doc=doc)


@dataclass(frozen=True)
class WorkflowTreeMutationResult:
    """Filesystem mutation summary for workflow-node create/delete actions."""

    created_path: Path | None = None
    created_paths: tuple[Path, ...] = ()
    deleted_paths: tuple[Path, ...] = ()
    renamed_paths: tuple[tuple[Path, Path], ...] = ()


class FrameLabWindow(
    WindowChromeMixin,
    DataPageMixin,
    InspectPageMixin,
    AnalysisPageMixin,
    DatasetLoadingMixin,
    MetricsRuntimeMixin,
    WindowActionsMixin,
    qtw.QMainWindow,
):
    """Main application window for image measurement and analysis."""

    RAW_IMAGE_CACHE_BUDGET_BYTES = 256 * 1024 * 1024
    CORRECTED_IMAGE_CACHE_BUDGET_BYTES = 256 * 1024 * 1024

    DATA_COLUMN_INDEX = {
        "path": 0,
        "parent": 1,
        "grandparent": 2,
        "iris_pos": 3,
        "exposure_ms": 4,
        "exposure_source": 5,
        "group": 6,
    }
    MEASURE_COLUMN_INDEX = {
        "row": 0,
        "path": 1,
        "iris_pos": 2,
        "exposure_ms": 3,
        "max_pixel": 4,
        "min_non_zero": 5,
        "sat_count": 6,
        "avg": 7,
        "std": 8,
        "sem": 9,
        "dn_per_ms": 10,
    }
    BASE_VISIBLE_DATA_COLUMNS = {"path", "parent", "grandparent"}
    BASE_VISIBLE_MEASURE_COLUMNS = {
        "row",
        "path",
        "max_pixel",
        "min_non_zero",
        "sat_count",
    }
    MODE_MEASURE_COLUMNS = {"avg", "std", "sem", "dn_per_ms"}
    DATA_OPTIONAL_COLUMNS = (
        ("iris_pos", label_for_metadata_field("iris_position")),
        ("exposure_ms", label_for_metadata_field("exposure_ms")),
        ("exposure_source", label_for_metadata_field("exposure_source")),
        ("group", label_for_metadata_field("group_index")),
    )
    MEASURE_OPTIONAL_COLUMNS = (
        ("iris_pos", label_for_metadata_field("iris_position")),
        ("exposure_ms", label_for_metadata_field("exposure_ms")),
        ("max_pixel", "Max Pixel"),
        ("min_non_zero", "Min > 0"),
        ("sat_count", "# Saturated"),
        ("avg", "Average Metric"),
        ("std", "Std"),
        ("sem", "Std Err"),
        ("dn_per_ms", "DN/ms"),
    )
    BASE_METADATA_GROUP_FIELDS = (
        ("None", None),
        ("Parent Folder", "parent_folder"),
        ("Grandparent Folder", "grandparent_folder"),
    )
    EXTRA_METADATA_GROUP_FIELD_LABELS = {
        "iris_position": label_for_metadata_field("iris_position"),
        "exposure_ms": label_for_metadata_field("exposure_ms"),
    }

    def __init__(self, enabled_plugin_ids: Iterable[str] = ()) -> None:
        super().__init__()
        self.setWindowTitle("FrameLab")
        app = qtw.QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())
        self.resize(1480, 900)
        self.setMinimumSize(1120, 720)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

        self.dataset_state = DatasetStateController()
        self.metrics_state = MetricsPipelineController()
        self.analysis_context_controller = AnalysisContextController(
            self.dataset_state,
            self.metrics_state,
            background_reference_label_resolver=self._background_reference_label_for_path,
        )
        self._analysis_context_cache = None
        self._analysis_context_generation = 0
        self._analysis_context_dirty = True
        self._analysis_context_delivered_generation_by_plugin: dict[str, int] = {}
        self._analysis_context_refresh_timer = QTimer(self)
        self._analysis_context_refresh_timer.setSingleShot(True)
        self._analysis_context_refresh_timer.setInterval(0)
        self._analysis_context_refresh_timer.timeout.connect(
            self._flush_dirty_analysis_context_if_visible,
        )
        self._analysis_plugins: list[AnalysisPlugin] = []
        self.metrics_cache = MetricsCache()
        self._dynamic_cache_pending: dict[str, object] | None = None
        self._roi_cache_pending: dict[str, object] | None = None
        self._enabled_plugin_ids = resolve_enabled_plugin_ids(enabled_plugin_ids)
        self._page_plugin_classes: dict[str, list[type[object]]] = {
            page: [] for page in PAGE_IDS
        }
        self._page_plugin_manifests: dict[str, list[PluginManifest]] = {
            page: [] for page in PAGE_IDS
        }
        self._image_cache = ByteBudgetCache[str](
            self.RAW_IMAGE_CACHE_BUDGET_BYTES,
        )
        self._corrected_cache = ByteBudgetCache[tuple[str, int]](
            self.CORRECTED_IMAGE_CACHE_BUDGET_BYTES,
        )
        self._load_ui_state()
        self.workflow_state_controller = WorkflowStateController()
        self.metadata_state_controller = MetadataStateController(
            self.workflow_state_controller,
        )
        self._restore_persisted_workflow_state()
        self.show_image_preview = self.ui_preferences.show_image_preview
        self.show_histogram_preview = self.ui_preferences.show_histogram_preview
        self._density_resolver = UiDensityResolver()
        self._density_refresh_timer = QTimer(self)
        self._density_refresh_timer.setSingleShot(True)
        self._density_refresh_timer.setInterval(90)
        self._density_refresh_timer.timeout.connect(
            self._apply_dynamic_visibility_policy,
        )
        initial_context = AdaptiveUiContext(
            usable_height=max(self.height(), 0),
            active_page="data",
            has_processing_banner=False,
            has_loaded_data=False,
        )
        self._active_density_tokens = self._density_resolver.tokens_for_mode(
            self.ui_preferences.density_mode,
            initial_context,
        )
        self._active_visibility_policy = self._density_resolver.visibility_policy(
            self.ui_preferences.density_mode,
            initial_context,
            preferences=self.ui_preferences,
        )
        self._analysis_plugin_engaged = False
        self._session_panel_overrides: dict[str, bool] = {}
        self._manual_data_column_visibility: dict[str, bool] = {}
        self._manual_measure_column_visibility: dict[str, bool] = {}
        self._data_column_actions: dict[str, QtGui.QAction] = {}
        self._measure_column_actions: dict[str, QtGui.QAction] = {}
        self._stats_thread: Optional[QThread] = None
        self._stats_worker: Optional[DynamicStatsWorker] = None
        self._threshold_summary_anim_phase = 0
        self._threshold_summary_timer = QTimer(self)
        self._threshold_summary_timer.setInterval(320)
        self._threshold_summary_timer.timeout.connect(
            self._advance_threshold_summary_animation,
        )
        self._roi_apply_thread: Optional[QThread] = None
        self._roi_apply_worker: Optional[RoiApplyWorker] = None
        self._pause_preview_updates = False
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder
        self._theme_mode = self.ui_preferences.theme_mode
        self._processing_failures = []
        self._processing_failure_banners: list[qtw.QWidget] = []
        self._processing_failure_banner_labels: list[qtw.QLabel] = []
        self._processing_failure_banner_layouts: list[qtw.QHBoxLayout] = []

        self.base_status = "Select a folder."
        self.context_hint = "Step 1: choose a dataset folder, then scan."
        self.skip_patterns = load_skip_patterns()
        self.skip_pattern_config_path = skip_config_path()
        self._last_scan_pruned_dirs = 0
        self._last_scan_skipped_files = 0

        self._page_plugin_manifests = enabled_plugin_manifests(self._enabled_plugin_ids)
        self._page_plugin_classes = load_enabled_plugins(self._enabled_plugin_ids)
        self._apply_base_font()
        self._build_ui()
        self._sync_dataset_scope_to_workflow(
            update_folder_edit=True,
            unload_mismatched_dataset=False,
        )
        self._apply_theme(self.ui_preferences.theme_mode)
        self._restore_persisted_ui_state()
        self._set_status()

    def _load_ui_state(self) -> None:
        """Load persisted UI preferences and last-session workspace state."""

        self.ui_state_store = UiStateStore()
        try:
            self.ui_state_snapshot = self.ui_state_store.load()
        except Exception:
            self.ui_state_snapshot = UiStateSnapshot()
        self.ui_preferences = self.ui_state_snapshot.preferences

    def _restore_persisted_ui_state(self) -> None:
        """Restore last tab/plugin selection once widgets exist."""

        if (
            self.ui_preferences.restore_last_tab
            and hasattr(self, "workflow_tabs")
            and self.ui_state_snapshot.last_tab_index is not None
        ):
            index = self.ui_state_snapshot.last_tab_index
            if 0 <= index < self.workflow_tabs.count():
                self.workflow_tabs.setCurrentIndex(index)

        plugin_id = self.ui_state_snapshot.last_analysis_plugin_id
        if not plugin_id or not hasattr(self, "analysis_profile_combo"):
            return
        plugin_index = self.analysis_profile_combo.findData(plugin_id)
        if plugin_index >= 0:
            self.analysis_profile_combo.setCurrentIndex(plugin_index)
        if hasattr(self, "_apply_dynamic_visibility_policy"):
            self._apply_dynamic_visibility_policy()

    def _restore_persisted_workflow_state(self) -> None:
        """Restore persisted workflow workspace selection when available."""

        root = self.ui_state_snapshot.workflow_workspace_root
        profile_id = self.ui_state_snapshot.workflow_profile_id
        if not root or not profile_id:
            self.workflow_state_controller.clear()
            self.metadata_state_controller.clear_cache()
            return
        try:
            self.workflow_state_controller.load_workspace(
                root,
                profile_id,
                anchor_type_id=self.ui_state_snapshot.workflow_anchor_type_id,
                active_node_id=self.ui_state_snapshot.workflow_active_node_id,
            )
            self.metadata_state_controller.clear_cache()
            self._remember_recent_workflow_context(
                root,
                profile_id,
                self.workflow_state_controller.anchor_type_id,
                self.workflow_state_controller.active_node_id,
            )
        except Exception:
            self.workflow_state_controller.clear()
            self.metadata_state_controller.clear_cache()

    def _set_folder_edit_text(self, path: str | None) -> None:
        """Update the dataset-folder editor without emitting user-change noise."""

        if not hasattr(self, "folder_edit"):
            return
        text = str(path).strip() if path else ""
        blocker = QSignalBlocker(self.folder_edit)
        self.folder_edit.setText(text)
        del blocker

    def _sync_dataset_scope_to_workflow(
        self,
        *,
        update_folder_edit: bool,
        unload_mismatched_dataset: bool,
    ) -> None:
        """Mirror the active workflow node into dataset-scope state."""

        active_node = self.workflow_state_controller.active_node()
        if active_node is None:
            if not getattr(self.workflow_state_controller, "profile_id", None):
                self.dataset_state.clear_scope()
            return

        metadata_snapshot = self.metadata_state_controller.resolve_active_node_metadata()
        ancestry = self.workflow_state_controller.ancestry_for(active_node.node_id)
        self.dataset_state.set_workflow_scope(
            root=active_node.folder_path,
            kind=active_node.type_id,
            label=active_node.display_name,
            workflow_profile_id=self.workflow_state_controller.profile_id,
            workflow_anchor_type_id=self.workflow_state_controller.anchor_type_id,
            workflow_anchor_label=self.workflow_state_controller.anchor_summary_label(),
            workflow_anchor_path=self.workflow_state_controller.workspace_root,
            workflow_is_partial=self.workflow_state_controller.is_partial_workspace(),
            active_node_id=active_node.node_id,
            active_node_type=active_node.type_id,
            active_node_path=active_node.folder_path,
            ancestor_chain=tuple(
                DatasetScopeNode(
                    node_id=node.node_id,
                    type_id=node.type_id,
                    display_name=node.display_name,
                    folder_path=node.folder_path,
                )
                for node in ancestry
            ),
            effective_metadata=(
                dict(metadata_snapshot.flat_metadata)
                if metadata_snapshot is not None
                else {}
            ),
            metadata_sources=(
                {
                    key: source.provenance
                    for key, source in metadata_snapshot.field_sources.items()
                }
                if metadata_snapshot is not None
                else {}
            ),
        )
        if update_folder_edit:
            self._set_folder_edit_text(str(active_node.folder_path))
        loaded_root = self.dataset_state.dataset_root
        if (
            unload_mismatched_dataset
            and loaded_root is not None
            and loaded_root.resolve() != active_node.folder_path.resolve()
            and hasattr(self, "unload_folder")
        ):
            self.unload_folder(clear_folder_edit=False)

    def _refresh_manager_dialogs(self) -> None:
        """Refresh open workflow surfaces after host-state changes."""

        for attr_name in (
            "_workflow_manager_dialog",
            "_metadata_manager_dialog",
            "_workflow_explorer_dock",
            "_metadata_inspector_dock",
        ):
            dialog = getattr(self, attr_name, None)
            refresh = getattr(dialog, "sync_from_host", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    continue

    def _notify_workflow_scope_changed(self) -> None:
        """Refresh page summaries and dialogs after the active workflow node changes."""

        if hasattr(self, "_refresh_workflow_shell_context"):
            self._refresh_workflow_shell_context()
        if hasattr(self, "_refresh_data_header_state"):
            self._refresh_data_header_state()
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()
        if hasattr(self, "_refresh_analysis_summary"):
            self._refresh_analysis_summary()
        if hasattr(self, "_invalidate_analysis_context"):
            self._invalidate_analysis_context(refresh_visible_plugin=True)
        elif hasattr(self, "_refresh_analysis_summary"):
            self._refresh_analysis_summary()
        if hasattr(self, "_apply_dynamic_visibility_policy"):
            self._apply_dynamic_visibility_policy()
        if hasattr(self, "_set_status"):
            self._set_status()
        self._refresh_manager_dialogs()

    def _notify_metadata_context_changed(
        self,
        changed_root: str | Path | None = None,
    ) -> None:
        """Refresh derived metadata state after node metadata is edited."""

        if changed_root is None:
            self.metadata_state_controller.clear_cache()
            clear_metadata_cache()
            affected_paths: list[str] | None = None
        else:
            self.metadata_state_controller.invalidate_paths((changed_root,))
            invalidate_metadata_cache((changed_root,))
            affected_paths = self.dataset_state.paths_within_root(changed_root)
        if self.workflow_state_controller.active_node() is not None:
            self._sync_dataset_scope_to_workflow(
                update_folder_edit=False,
                unload_mismatched_dataset=False,
            )
        if self.dataset_state.has_loaded_data():
            if hasattr(self, "_refresh_metadata_cache"):
                self._refresh_metadata_cache(
                    paths=affected_paths,
                    invalidate_roots=(),
                )
            if hasattr(self, "_refresh_metadata_table"):
                self._refresh_metadata_table()
            if hasattr(self, "_refresh_table"):
                self._refresh_table()
        self._notify_workflow_scope_changed()

    def _set_manual_dataset_scope(self, folder: Path | None) -> None:
        """Store a manual folder-driven scope when workflow resolution is not used."""

        if folder is None:
            self.dataset_state.clear_scope()
            return
        self.dataset_state.set_manual_scope(folder)

    def _resolve_requested_dataset_scope_folder(self, folder: Path) -> Path:
        """Resolve the effective scan root from manual input and workflow state."""

        candidate = folder.expanduser()
        workflow = self.workflow_state_controller
        active_node = workflow.active_node()
        if active_node is None:
            return candidate

        node_id = workflow.resolve_node_id_for_path(candidate)
        if node_id is not None:
            self.set_active_workflow_node(
                node_id,
                sync_scope=True,
                unload_mismatched_dataset=False,
            )
            resolved_node = workflow.active_node()
            if resolved_node is not None:
                return resolved_node.folder_path

        # LEGACY_COMPAT[manual_folder_scope_override]: Preserve folder-edit driven scans outside the active workflow tree while legacy Open Folder and Session Manager entry points still coexist with workflow scope. Remove after: workflow explorer owns scope changes and manual folder-loading paths are retired or explicitly redesigned.
        return candidate

    def set_workflow_context(
        self,
        workspace_root: str | None,
        profile_id: str | None,
        *,
        anchor_type_id: str | None = None,
        active_node_id: str | None = None,
    ) -> str | None:
        """Load or clear the current workflow context."""

        if not workspace_root or not profile_id:
            self.workflow_state_controller.clear()
            self.metadata_state_controller.clear_cache()
            self.ui_state_snapshot.workflow_workspace_root = None
            self.ui_state_snapshot.workflow_profile_id = None
            self.ui_state_snapshot.workflow_anchor_type_id = None
            self.ui_state_snapshot.workflow_active_node_id = None
            current_folder = (
                Path(self.folder_edit.text().strip()).expanduser()
                if hasattr(self, "folder_edit") and self.folder_edit.text().strip()
                else None
            )
            self._set_manual_dataset_scope(current_folder)
            self._notify_workflow_scope_changed()
            return None

        load_result = self.workflow_state_controller.load_workspace(
            workspace_root,
            profile_id,
            anchor_type_id=anchor_type_id,
            active_node_id=active_node_id,
        )
        self.metadata_state_controller.clear_cache()
        self.ui_state_snapshot.workflow_workspace_root = str(load_result.workspace_root)
        self.ui_state_snapshot.workflow_profile_id = load_result.profile_id
        self.ui_state_snapshot.workflow_anchor_type_id = load_result.anchor_type_id
        self.ui_state_snapshot.workflow_active_node_id = load_result.active_node_id
        self._remember_recent_workflow_context(
            load_result.workspace_root,
            load_result.profile_id,
            load_result.anchor_type_id,
            load_result.active_node_id,
        )
        if hasattr(self, "folder_edit"):
            self._sync_dataset_scope_to_workflow(
                update_folder_edit=True,
                unload_mismatched_dataset=True,
            )
        self._notify_workflow_scope_changed()
        return load_result.active_node_id

    def set_active_workflow_node(
        self,
        node_id: str | None,
        *,
        sync_scope: bool = True,
        unload_mismatched_dataset: bool = True,
    ) -> str | None:
        """Update the active workflow node inside the loaded controller state."""

        node = self.workflow_state_controller.set_active_node(node_id)
        self.metadata_state_controller.clear_cache()
        self.ui_state_snapshot.workflow_active_node_id = (
            node.node_id if node is not None else None
        )
        if self.workflow_state_controller.workspace_root is not None:
            self._remember_recent_workflow_context(
                self.workflow_state_controller.workspace_root,
                self.workflow_state_controller.profile_id,
                self.workflow_state_controller.anchor_type_id,
                self.ui_state_snapshot.workflow_active_node_id,
            )
        if sync_scope and hasattr(self, "folder_edit"):
            self._sync_dataset_scope_to_workflow(
                update_folder_edit=True,
                unload_mismatched_dataset=unload_mismatched_dataset,
            )
        self._notify_workflow_scope_changed()
        return self.ui_state_snapshot.workflow_active_node_id

    def recent_workflow_entries(self) -> tuple[RecentWorkflowEntry, ...]:
        """Return recent workflow contexts in most-recent-first order."""

        return tuple(self.ui_state_snapshot.recent_workflows)

    def _workflow_selected_folder(self) -> Path | None:
        """Return the current folder-edit path when present."""

        if not hasattr(self, "folder_edit"):
            return None
        text = self.folder_edit.text().strip()
        if not text:
            return None
        return Path(text).expanduser()

    def _workflow_node_and_session_context(
        self,
        node_id: str | None = None,
    ):
        """Return selected node plus nearest session/acquisition workflow context."""

        controller = self.workflow_state_controller
        node = controller.node(node_id) if node_id else controller.active_node()
        if node is None:
            return (None, None, None, None)
        if node.type_id == "session":
            from .session_manager import inspect_session

            session_index = inspect_session(node.folder_path)
            return (node, node, session_index, None)
        if node.type_id == "acquisition":
            ancestry = controller.ancestry_for(node.node_id)
            session_node = next(
                (entry for entry in reversed(ancestry) if entry.type_id == "session"),
                None,
            )
            session_index = None
            if session_node is not None:
                from .session_manager import inspect_session

                session_index = inspect_session(session_node.folder_path)
            selected_entry = None
            if session_index is not None:
                selected_entry = next(
                    (entry for entry in session_index.entries if entry.path == node.folder_path),
                    None,
                )
            return (node, session_node, session_index, selected_entry)
        return (node, None, None, None)

    def _workflow_structure_action_state(
        self,
        node_id: str | None = None,
    ) -> dict[str, object]:
        """Return structure-authoring capabilities for one workflow selection."""

        node, session_node, session_index, selected_entry = self._workflow_node_and_session_context(
            node_id,
        )
        numbering_valid = session_index.numbering_valid if session_index is not None else False
        create_parent_node, create_child_type_id = self._workflow_create_target(
            node_id,
        )
        can_create_child = create_parent_node is not None and create_child_type_id is not None
        if create_child_type_id == "acquisition":
            can_create_child = session_node is not None and numbering_valid
        can_delete_node = node is not None and node.type_id != "root"
        if node is not None and node.type_id == "acquisition":
            can_delete_node = selected_entry is not None and numbering_valid
        return {
            "node": node,
            "session_node": session_node,
            "session_index": session_index,
            "selected_entry": selected_entry,
            "can_create_session": node is not None and node.type_id == "campaign",
            "can_delete_session": node is not None and node.type_id == "session",
            "can_create": session_node is not None and numbering_valid,
            "can_batch_create": session_node is not None and numbering_valid,
            "can_rename": selected_entry is not None,
            "can_delete": selected_entry is not None and numbering_valid,
            "can_reindex": session_index is not None and bool(session_index.entries),
            "can_create_child": can_create_child,
            "create_action_text": (
                f"New {self._workflow_node_type_label(create_child_type_id)}..."
                if create_child_type_id
                else "New..."
            ),
            "create_child_type_id": create_child_type_id,
            "can_delete_node": can_delete_node,
            "delete_action_text": (
                f"Delete {self._workflow_node_type_label(node.type_id)}..."
                if node is not None
                else "Delete..."
            ),
            "can_open_folder": node is not None,
            "warning_text": session_index.warning_text if session_index is not None else "",
        }

    def _workflow_node_type_label(self, type_id: str | None) -> str:
        """Return a human label for one workflow node type."""

        clean = str(type_id or "").strip().lower()
        if not clean:
            return "Node"
        profile = self.workflow_state_controller.profile
        if profile is not None:
            try:
                return profile.node_type(clean).display_name
            except KeyError:
                pass
        return clean.replace("_", " ").title()

    def _workflow_create_target(
        self,
        node_id: str | None = None,
    ) -> tuple[object | None, str | None]:
        """Return the parent node and child type used for generic create actions."""

        node, session_node, _session_index, _selected_entry = self._workflow_node_and_session_context(
            node_id,
        )
        profile = self.workflow_state_controller.profile
        if node is None or profile is None:
            return (None, None)
        if node.type_id == "acquisition":
            return (session_node, "acquisition") if session_node is not None else (None, None)
        try:
            child_type_ids = profile.node_type(node.type_id).child_type_ids
        except KeyError:
            return (None, None)
        if not child_type_ids:
            return (None, None)
        return (node, child_type_ids[0])

    @staticmethod
    def _clean_workflow_folder_label(
        folder_label: str,
        entity_label: str,
    ) -> str:
        """Validate and normalize one new workflow folder label."""

        clean_label = str(folder_label).strip()
        if not clean_label:
            raise ValueError(f"{entity_label} folder label cannot be empty.")
        if clean_label in {".", ".."} or "/" in clean_label or "\\" in clean_label:
            raise ValueError(f"{entity_label} folder label cannot contain path separators.")
        return clean_label

    def _apply_loaded_dataset_path_mutation(
        self,
        result: object,
        *,
        force_refresh_if_loaded: bool = False,
    ) -> None:
        """Apply acquisition-path mutations to the currently loaded dataset view."""

        if not hasattr(result, "deleted_paths") or not hasattr(result, "renamed_paths"):
            return
        loaded_folder = self._workflow_selected_folder()
        if loaded_folder is None:
            return
        unloaded = False
        deleted_paths = tuple(getattr(result, "deleted_paths", ()))
        renamed_paths = tuple(getattr(result, "renamed_paths", ()))
        for deleted_path in deleted_paths:
            if loaded_folder == deleted_path or deleted_path in loaded_folder.parents:
                if hasattr(self, "unload_folder"):
                    self.unload_folder(clear_folder_edit=True)
                unloaded = True
                break
        if unloaded:
            return

        for old_path, new_path in renamed_paths:
            if loaded_folder == old_path or old_path in loaded_folder.parents:
                relative = loaded_folder.relative_to(old_path)
                new_loaded_path = new_path.joinpath(relative)
                self._set_folder_edit_text(str(new_loaded_path))
                if hasattr(self, "load_folder"):
                    self.load_folder()
                return

        if deleted_paths and force_refresh_if_loaded and self.dataset_state.has_loaded_data():
            if hasattr(self, "load_folder"):
                self.load_folder()
            return

        created_paths = tuple(getattr(result, "created_paths", ()))
        if created_paths and self.dataset_state.has_loaded_data():
            for created_path in created_paths:
                if loaded_folder == created_path or loaded_folder in created_path.parents:
                    if hasattr(self, "load_folder"):
                        self.load_folder()
                    return

    def _map_path_through_workflow_mutation(
        self,
        path: Path | None,
        result: object,
    ) -> Path | None:
        """Map one workflow path through acquisition create/rename/delete changes."""

        if path is None:
            return None
        deleted_paths = tuple(getattr(result, "deleted_paths", ()))
        renamed_paths = tuple(getattr(result, "renamed_paths", ()))
        for deleted_path in deleted_paths:
            if path == deleted_path or deleted_path in path.parents:
                return None
        mapped = path
        for old_path, new_path in renamed_paths:
            if mapped == old_path or old_path in mapped.parents:
                relative = mapped.relative_to(old_path)
                mapped = new_path.joinpath(relative)
        return mapped

    def _refresh_workflow_after_structure_mutation(
        self,
        result: object,
        *,
        preferred_active_path: Path | None = None,
        force_refresh_if_loaded: bool = False,
    ) -> None:
        """Refresh workflow and dataset state after session/acquisition edits."""

        self._apply_loaded_dataset_path_mutation(
            result,
            force_refresh_if_loaded=force_refresh_if_loaded,
        )
        controller = self.workflow_state_controller
        if controller.workspace_root is None or controller.profile_id is None:
            return

        target_path = preferred_active_path
        if target_path is None:
            active_node = controller.active_node()
            target_path = active_node.folder_path if active_node is not None else None
        target_path = self._map_path_through_workflow_mutation(target_path, result)
        workspace_root = self._map_path_through_workflow_mutation(
            controller.workspace_root,
            result,
        )
        anchor_type_id = controller.anchor_type_id
        if workspace_root is None:
            workspace_root = target_path
            anchor_type_id = None
        if workspace_root is None:
            self.set_workflow_context(None, None)
            return

        self.set_workflow_context(
            str(workspace_root),
            controller.profile_id,
            anchor_type_id=anchor_type_id,
        )
        if target_path is not None:
            node_id = self.workflow_state_controller.resolve_node_id_for_path(target_path)
            if node_id is not None:
                self.set_active_workflow_node(
                    node_id,
                    unload_mismatched_dataset=False,
                )

    def _open_workflow_acquisition_creation_dialog(
        self,
        node_id: str | None = None,
        *,
        batch: bool = False,
    ) -> None:
        """Create one or more acquisitions under the selected workflow session."""

        _node, session_node, session_index, _selected_entry = self._workflow_node_and_session_context(
            node_id,
        )
        if session_node is None or session_index is None:
            return
        from .acquisition_authoring_dialog import AcquisitionAuthoringDialog

        dialog = AcquisitionAuthoringDialog(
            session_node.folder_path,
            self,
            initial_mode="batch" if batch else "next",
        )
        if dialog.exec() != qtw.QDialog.Accepted or not dialog.created_paths:
            return
        preferred_path = (
            session_node.folder_path
            if batch and len(dialog.created_paths) > 1
            else dialog.created_paths[-1]
        )
        self._refresh_workflow_after_structure_mutation(
            dialog,
            preferred_active_path=preferred_path,
            force_refresh_if_loaded=False,
        )

    def _rename_workflow_acquisition(
        self,
        node_id: str | None = None,
    ) -> None:
        """Rename the selected acquisition label from the workflow shell."""

        _node, _session_node, _session_index, selected_entry = self._workflow_node_and_session_context(
            node_id,
        )
        if selected_entry is None:
            return
        label, accepted = qtw.QInputDialog.getText(
            self,
            "Rename Acquisition",
            "Name (leave blank for no __name suffix):",
            text=selected_entry.label or "",
        )
        if not accepted:
            return
        from .session_manager import rename_acquisition_label

        try:
            result = rename_acquisition_label(selected_entry.path, label.strip() or None)
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Rename Acquisition", str(exc))
            return
        preferred = (
            result.renamed_paths[0][1]
            if result.renamed_paths
            else selected_entry.path
        )
        self._refresh_workflow_after_structure_mutation(
            result,
            preferred_active_path=preferred,
            force_refresh_if_loaded=True,
        )

    def _workflow_delete_confirmation_text(self, entry_path: Path, folder_name: str) -> str:
        """Return confirmation copy for a workflow-driven acquisition delete."""

        loaded_folder = self._workflow_selected_folder()
        loaded_note = ""
        if loaded_folder is not None:
            loaded_note = (
                "\n\nA dataset is currently loaded. Confirming will trigger a full refresh."
            )
            if entry_path in loaded_folder.parents or loaded_folder == entry_path:
                loaded_note = (
                    "\n\nThe currently loaded dataset is inside this acquisition. "
                    "Confirming will unload it and refresh the UI."
                )
        return (
            f"Delete acquisition folder '{folder_name}'?\n"
            "Later acquisitions will be renumbered to close the gap."
            f"{loaded_note}"
        )

    def _delete_workflow_acquisition(
        self,
        node_id: str | None = None,
    ) -> None:
        """Delete the selected acquisition from the workflow shell."""

        _node, session_node, _session_index, selected_entry = self._workflow_node_and_session_context(
            node_id,
        )
        if session_node is None or selected_entry is None:
            return
        answer = qtw.QMessageBox.question(
            self,
            "Delete Acquisition",
            self._workflow_delete_confirmation_text(
                selected_entry.path,
                selected_entry.folder_name,
            ),
            qtw.QMessageBox.Yes | qtw.QMessageBox.No,
            qtw.QMessageBox.No,
        )
        if answer != qtw.QMessageBox.Yes:
            return
        from .session_manager import delete_acquisition

        try:
            result = delete_acquisition(session_node.folder_path, selected_entry.path)
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Delete Acquisition", str(exc))
            return
        self._refresh_workflow_after_structure_mutation(
            result,
            preferred_active_path=session_node.folder_path,
            force_refresh_if_loaded=True,
        )

    def _workflow_session_delete_confirmation_text(
        self,
        session_path: Path,
        folder_name: str,
    ) -> str:
        """Return confirmation copy for a workflow-driven session delete."""

        loaded_folder = self._workflow_selected_folder()
        loaded_note = ""
        if loaded_folder is not None:
            loaded_note = (
                "\n\nA dataset is currently loaded. Confirming will trigger a full refresh."
            )
            if session_path in loaded_folder.parents or loaded_folder == session_path:
                loaded_note = (
                    "\n\nThe currently loaded dataset is inside this session. "
                    "Confirming will unload it and refresh the UI."
                )
        return (
            f"Delete session folder '{folder_name}'?\n"
            "This removes the entire session directory and all acquisitions inside it."
            f"{loaded_note}"
        )

    def _workflow_node_delete_confirmation_text(
        self,
        node_path: Path,
        *,
        node_label: str,
        folder_name: str,
    ) -> str:
        """Return confirmation copy for a workflow subtree delete."""

        loaded_folder = self._workflow_selected_folder()
        loaded_note = ""
        if loaded_folder is not None:
            loaded_note = (
                "\n\nA dataset is currently loaded. Confirming will trigger a full refresh."
            )
            if node_path in loaded_folder.parents or loaded_folder == node_path:
                loaded_note = (
                    "\n\nThe currently loaded dataset is inside this subtree. "
                    "Confirming will unload it and refresh the UI."
                )
        node_text = node_label.lower()
        return (
            f"Delete {node_text} folder '{folder_name}'?\n"
            f"This removes the entire {node_text} subtree and all descendants."
            f"{loaded_note}"
        )

    def _create_workflow_session(
        self,
        node_id: str | None,
        folder_label: str,
    ) -> Path | None:
        """Create a session under the selected workflow campaign."""

        controller = self.workflow_state_controller
        node = controller.node(node_id) if node_id else controller.active_node()
        if node is None or node.type_id != "campaign":
            return None
        from .session_manager import create_session

        result = create_session(node.folder_path, folder_label)
        preferred_path = result.created_path or node.folder_path
        self._refresh_workflow_after_structure_mutation(
            result,
            preferred_active_path=preferred_path,
            force_refresh_if_loaded=False,
        )
        return result.created_path

    def _create_workflow_child_node(
        self,
        node_id: str | None,
        folder_label: str,
    ) -> Path | None:
        """Create a direct workflow child under the selected node."""

        parent_node, child_type_id = self._workflow_create_target(node_id)
        if parent_node is None or child_type_id is None:
            return None
        if child_type_id == "session":
            return self._create_workflow_session(
                getattr(parent_node, "node_id", None),
                folder_label,
            )
        if child_type_id == "acquisition":
            self._open_workflow_acquisition_creation_dialog(
                getattr(parent_node, "node_id", None),
                batch=False,
            )
            return None

        child_label = self._workflow_node_type_label(child_type_id)
        clean_label = self._clean_workflow_folder_label(folder_label, child_label)
        parent_path = Path(getattr(parent_node, "folder_path")).resolve()
        created_path = parent_path.joinpath(clean_label)
        if created_path.exists():
            raise FileExistsError(f"{child_label} folder already exists: {created_path.name}")

        created_path.mkdir(parents=True, exist_ok=False)
        if child_type_id == "campaign":
            created_path.joinpath("01_sessions").mkdir(parents=True, exist_ok=True)

        result = WorkflowTreeMutationResult(
            created_path=created_path,
            created_paths=(created_path,),
        )
        self._refresh_workflow_after_structure_mutation(
            result,
            preferred_active_path=created_path,
            force_refresh_if_loaded=False,
        )
        return created_path

    def _delete_workflow_session(
        self,
        node_id: str | None = None,
    ) -> None:
        """Delete the selected workflow session."""

        controller = self.workflow_state_controller
        node = controller.node(node_id) if node_id else controller.active_node()
        if node is None or node.type_id != "session":
            return

        answer = qtw.QMessageBox.question(
            self,
            "Delete Session",
            self._workflow_session_delete_confirmation_text(
                node.folder_path,
                node.folder_path.name,
            ),
            qtw.QMessageBox.Yes | qtw.QMessageBox.No,
            qtw.QMessageBox.No,
        )
        if answer != qtw.QMessageBox.Yes:
            return

        from .session_manager import delete_session

        try:
            result = delete_session(node.folder_path)
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Delete Session", str(exc))
            return

        preferred_path = None
        ancestry = controller.ancestry_for(node.node_id)
        campaign_node = next(
            (entry for entry in reversed(ancestry) if entry.type_id == "campaign"),
            None,
        )
        if campaign_node is not None:
            preferred_path = campaign_node.folder_path
        elif node.folder_path.parent.name.lower() in {"01_sessions", "sessions"}:
            preferred_path = node.folder_path.parent.parent
        else:
            preferred_path = node.folder_path.parent
        self._refresh_workflow_after_structure_mutation(
            result,
            preferred_active_path=preferred_path,
            force_refresh_if_loaded=True,
        )

    def _delete_workflow_node(
        self,
        node_id: str | None = None,
    ) -> None:
        """Delete the selected workflow node, dispatching by node type."""

        controller = self.workflow_state_controller
        node = controller.node(node_id) if node_id else controller.active_node()
        if node is None or node.type_id == "root":
            return
        if node.type_id == "session":
            self._delete_workflow_session(node.node_id)
            return
        if node.type_id == "acquisition":
            self._delete_workflow_acquisition(node.node_id)
            return

        answer = qtw.QMessageBox.question(
            self,
            f"Delete {self._workflow_node_type_label(node.type_id)}",
            self._workflow_node_delete_confirmation_text(
                node.folder_path,
                node_label=self._workflow_node_type_label(node.type_id),
                folder_name=node.folder_path.name,
            ),
            qtw.QMessageBox.Yes | qtw.QMessageBox.No,
            qtw.QMessageBox.No,
        )
        if answer != qtw.QMessageBox.Yes:
            return

        try:
            shutil.rmtree(node.folder_path)
        except Exception as exc:
            qtw.QMessageBox.warning(
                self,
                f"Delete {self._workflow_node_type_label(node.type_id)}",
                str(exc),
            )
            return

        parent_node = controller.node(node.parent_id) if node.parent_id is not None else None
        preferred_path = (
            parent_node.folder_path
            if parent_node is not None
            else node.folder_path.parent
        )
        result = WorkflowTreeMutationResult(
            deleted_paths=(node.folder_path,),
        )
        self._refresh_workflow_after_structure_mutation(
            result,
            preferred_active_path=preferred_path,
            force_refresh_if_loaded=True,
        )

    def _reindex_workflow_session(
        self,
        node_id: str | None = None,
    ) -> None:
        """Normalize acquisition numbering for the selected workflow session."""

        _node, session_node, session_index, _selected_entry = self._workflow_node_and_session_context(
            node_id,
        )
        if session_node is None or session_index is None:
            return
        starting_number, accepted = qtw.QInputDialog.getInt(
            self,
            "Normalize/Reindex",
            "Starting number:",
            value=session_index.starting_number,
            minValue=0,
            maxValue=999999,
        )
        if not accepted:
            return
        answer = qtw.QMessageBox.question(
            self,
            "Normalize/Reindex",
            (
                f"Renumber acquisitions contiguously from {starting_number}?\n"
                "Acquisition folder names will change and loaded datasets may be reloaded."
            ),
            qtw.QMessageBox.Yes | qtw.QMessageBox.No,
            qtw.QMessageBox.No,
        )
        if answer != qtw.QMessageBox.Yes:
            return
        from .session_manager import reindex_acquisitions

        try:
            result = reindex_acquisitions(
                session_node.folder_path,
                starting_number=starting_number,
            )
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Normalize/Reindex", str(exc))
            return
        self._refresh_workflow_after_structure_mutation(
            result,
            preferred_active_path=session_node.folder_path,
            force_refresh_if_loaded=True,
        )

    def _remember_recent_workflow_context(
        self,
        workspace_root: str | Path | None,
        profile_id: str | None,
        anchor_type_id: str | None,
        active_node_id: str | None,
    ) -> None:
        """Track one workflow context for later quick selection."""

        if workspace_root is None or not profile_id:
            return
        try:
            normalized_root = str(Path(workspace_root).expanduser().resolve())
        except Exception:
            normalized_root = str(workspace_root).strip()
        normalized_profile = str(profile_id).strip().lower()
        if not normalized_root or not normalized_profile:
            return

        current = RecentWorkflowEntry(
            workspace_root=normalized_root,
            profile_id=normalized_profile,
            anchor_type_id=str(anchor_type_id).strip().lower() or None,
            active_node_id=str(active_node_id).strip() or None,
        )
        updated = [current]
        for entry in self.ui_state_snapshot.recent_workflows:
            same_root = entry.workspace_root == current.workspace_root
            same_profile = entry.profile_id == current.profile_id
            same_anchor = entry.anchor_type_id == current.anchor_type_id
            if same_root and same_profile and same_anchor:
                continue
            updated.append(entry)
        self.ui_state_snapshot.recent_workflows = updated[:8]

    def _current_analysis_plugin_id(self) -> str | None:
        """Return the active analysis plugin id if one is selected."""

        if not hasattr(self, "analysis_profile_combo"):
            return None
        plugin_id = self.analysis_profile_combo.currentData()
        if plugin_id is None:
            return None
        text = str(plugin_id).strip()
        if not text or text == "none":
            return None
        return text

    def _save_ui_state(self) -> None:
        """Persist current UI preferences and workspace selection state."""

        preferences = replace(
            self.ui_preferences,
            theme_mode=self._theme_mode,
            show_image_preview=bool(self.show_image_preview),
            show_histogram_preview=bool(self.show_histogram_preview),
        )
        snapshot = UiStateSnapshot(
            preferences=preferences,
            panel_states=dict(self.ui_state_snapshot.panel_states),
            splitter_sizes={
                key: list(value)
                for key, value in self.ui_state_snapshot.splitter_sizes.items()
            },
            last_tab_index=(
                self.workflow_tabs.currentIndex()
                if hasattr(self, "workflow_tabs")
                else self.ui_state_snapshot.last_tab_index
            ),
            last_analysis_plugin_id=self._current_analysis_plugin_id(),
            workflow_workspace_root=(
                str(self.workflow_state_controller.workspace_root)
                if self.workflow_state_controller.workspace_root is not None
                else None
            ),
            workflow_profile_id=self.workflow_state_controller.profile_id,
            workflow_anchor_type_id=self.workflow_state_controller.anchor_type_id,
            workflow_active_node_id=self.workflow_state_controller.active_node_id,
            recent_workflows=list(self.ui_state_snapshot.recent_workflows),
        )
        self.ui_state_store.save(snapshot)
        self.ui_state_snapshot = snapshot
        self.ui_preferences = snapshot.preferences

    def _current_active_page_id(self) -> str:
        """Return the active workflow page id."""

        if not hasattr(self, "workflow_tabs"):
            return "data"
        current_widget = self.workflow_tabs.currentWidget()
        if current_widget is getattr(self, "analysis_page", None):
            return "analysis"
        index = self.workflow_tabs.currentIndex()
        if index <= 0:
            return "data"
        return "measure"

    def _current_adaptive_ui_context(self) -> AdaptiveUiContext:
        """Build runtime context used by the density resolver."""

        central = self.centralWidget()
        usable_height = central.height() if central is not None else self.height()
        if usable_height <= 0:
            usable_height = self.height()
        return AdaptiveUiContext(
            usable_height=max(int(usable_height), 0),
            active_page=self._current_active_page_id(),
            has_processing_banner=bool(getattr(self, "_processing_failures", [])),
            has_loaded_data=bool(
                self._has_loaded_data()
                if hasattr(self, "_has_loaded_data")
                else False
            ),
        )

    def _visibility_user_overrides(self) -> dict[str, bool | None]:
        """Return persisted disclosure states when restore is enabled."""

        overrides: dict[str, bool] = {}
        if self.ui_preferences.restore_panel_states:
            overrides.update(
                {
                    str(key).strip().lower(): bool(value)
                    for key, value in self.ui_state_snapshot.panel_states.items()
                    if str(key).strip()
                }
            )
        overrides.update(
            {
                str(key).strip().lower(): bool(value)
                for key, value in self._session_panel_overrides.items()
                if str(key).strip()
            }
        )
        return overrides

    def _remember_panel_state(self, key: str, expanded: bool) -> None:
        """Store a panel disclosure override for the current session."""

        clean_key = str(key).strip().lower()
        if not clean_key:
            return
        value = bool(expanded)
        self._session_panel_overrides[clean_key] = value
        self.ui_state_snapshot.panel_states[clean_key] = value

    def _persist_splitter_state(self, key: str, splitter: object | None) -> None:
        """Store the latest splitter sizes in the current UI snapshot."""

        clean_key = str(key).strip().lower()
        if not clean_key or splitter is None or not hasattr(splitter, "sizes"):
            return
        try:
            raw_sizes = splitter.sizes()
        except Exception:
            return
        sizes = [max(0, int(size)) for size in raw_sizes]
        if not sizes:
            return
        self.ui_state_snapshot.splitter_sizes[clean_key] = sizes

    def _restore_splitter_state(self, key: str, splitter: object | None) -> None:
        """Apply persisted splitter sizes when restore behavior is enabled."""

        clean_key = str(key).strip().lower()
        if (
            not clean_key
            or splitter is None
            or not self.ui_preferences.restore_panel_states
            or not hasattr(splitter, "setSizes")
            or not hasattr(splitter, "count")
        ):
            return
        sizes = self.ui_state_snapshot.splitter_sizes.get(clean_key)
        if not sizes:
            return
        normalized = [max(0, int(size)) for size in sizes]
        try:
            expected_count = int(splitter.count())
        except Exception:
            expected_count = len(normalized)
        if expected_count > 0 and len(normalized) != expected_count:
            return
        if sum(normalized) <= 0:
            return
        try:
            splitter.setSizes(normalized)
        except Exception:
            return

    def _policy_for_page(self, page_id: str):
        """Resolve policy for one page using the current global context."""

        context = replace(
            self._current_adaptive_ui_context(),
            active_page=page_id,
        )
        return self._density_resolver.visibility_policy(
            self.ui_preferences.density_mode,
            context,
            preferences=self.ui_preferences,
            user_overrides=self._visibility_user_overrides(),
        )

    def _apply_density_policy(self) -> None:
        """Resolve and store active density tokens and visibility policy."""

        context = self._current_adaptive_ui_context()
        previous_tokens = getattr(self, "_active_density_tokens", None)
        self._active_density_tokens = self._density_resolver.tokens_for_mode(
            self.ui_preferences.density_mode,
            context,
        )
        self._active_visibility_policy = self._density_resolver.visibility_policy(
            self.ui_preferences.density_mode,
            context,
            preferences=self.ui_preferences,
            user_overrides=self._visibility_user_overrides(),
        )
        if previous_tokens != self._active_density_tokens and hasattr(
            self,
            "_apply_density",
        ):
            self._apply_density()

    @staticmethod
    def _set_header_subtitle_visible(
        header: object | None,
        visible: bool,
    ) -> None:
        """Show or hide one header subtitle while preserving empty-state logic."""

        if header is not None and hasattr(header, "set_subtitle_visible"):
            header.set_subtitle_visible(bool(visible))
            return
        subtitle_label = getattr(header, "subtitle_label", None)
        if subtitle_label is None:
            return
        subtitle_label.setVisible(
            bool(visible) and bool(subtitle_label.text().strip()),
        )

    def _apply_visibility_policy(self) -> None:
        """Apply the currently resolved visibility policy to existing widgets."""

        self._set_header_subtitle_visible(
            getattr(self, "_data_header", None),
            self._policy_for_page("data").show_subtitles,
        )
        if hasattr(self, "_apply_data_page_visibility_policy"):
            self._apply_data_page_visibility_policy(
                self._policy_for_page("data"),
            )
        self._set_header_subtitle_visible(
            getattr(self, "_measure_header", None),
            self._policy_for_page("measure").show_subtitles,
        )
        if hasattr(self, "_apply_measure_page_visibility_policy"):
            self._apply_measure_page_visibility_policy(
                self._policy_for_page("measure"),
            )
        self._set_header_subtitle_visible(
            getattr(self, "_analysis_header", None),
            self._policy_for_page("analysis").show_subtitles,
        )
        if hasattr(self, "_apply_analysis_page_visibility_policy"):
            self._apply_analysis_page_visibility_policy(
                self._policy_for_page("analysis"),
            )

    def _schedule_density_refresh(self) -> None:
        """Debounce resize-driven density recomputation."""

        self._density_refresh_timer.start()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """Refresh density-dependent policy after the window is resized."""

        super().resizeEvent(event)
        self._schedule_density_refresh()

    @property
    def paths(self) -> list[str]:
        """Compatibility proxy for controller-owned dataset paths."""
        return self.dataset_state.paths

    @paths.setter
    def paths(self, value: Iterable[str]) -> None:
        self.dataset_state.paths = [str(path) for path in value]

    @property
    def path_metadata(self) -> dict[str, dict[str, object]]:
        """Compatibility proxy for controller-owned metadata cache."""
        return self.dataset_state.path_metadata

    @path_metadata.setter
    def path_metadata(self, value: dict[str, dict[str, object]]) -> None:
        self.dataset_state.set_path_metadata(value)

    @property
    def metadata_source_mode(self) -> str:
        """Compatibility proxy for controller-owned active metadata source."""
        return self.dataset_state.metadata_source_mode

    @metadata_source_mode.setter
    def metadata_source_mode(self, value: str) -> None:
        self.dataset_state.metadata_source_mode = str(value)

    @property
    def _preferred_metadata_source_mode(self) -> str:
        """Compatibility proxy for controller-owned preferred metadata source."""
        return self.dataset_state.preferred_metadata_source_mode

    @_preferred_metadata_source_mode.setter
    def _preferred_metadata_source_mode(self, value: str) -> None:
        self.dataset_state.preferred_metadata_source_mode = str(value)

    @property
    def _has_json_metadata_source(self) -> bool:
        """Compatibility proxy for controller-owned JSON availability state."""
        return self.dataset_state.has_json_metadata_source

    @_has_json_metadata_source.setter
    def _has_json_metadata_source(self, value: bool) -> None:
        self.dataset_state.has_json_metadata_source = bool(value)

    @property
    def _metadata_visible_paths(self) -> list[str]:
        """Compatibility proxy for controller-owned metadata row ordering."""
        return self.dataset_state.metadata_visible_paths

    @_metadata_visible_paths.setter
    def _metadata_visible_paths(self, value: Iterable[str]) -> None:
        self.dataset_state.set_metadata_visible_paths(value)

    @property
    def selected_index(self) -> Optional[int]:
        """Compatibility proxy for controller-owned current row selection."""
        return self.dataset_state.selected_index

    @selected_index.setter
    def selected_index(self, value: Optional[int]) -> None:
        self.dataset_state.set_selected_index(value)

    min_non_zero = _controller_property(
        "metrics_state",
        "min_non_zero",
        "Compatibility proxy for controller-owned min-non-zero metrics.",
    )
    maxs = _controller_property(
        "metrics_state",
        "maxs",
        "Compatibility proxy for controller-owned max-pixel metrics.",
    )
    sat_counts = _controller_property(
        "metrics_state",
        "sat_counts",
        "Compatibility proxy for controller-owned saturation counts.",
    )
    avg_maxs = _controller_property(
        "metrics_state",
        "avg_maxs",
        "Compatibility proxy for controller-owned Top-K means.",
    )
    avg_maxs_std = _controller_property(
        "metrics_state",
        "avg_maxs_std",
        "Compatibility proxy for controller-owned Top-K std values.",
    )
    avg_maxs_sem = _controller_property(
        "metrics_state",
        "avg_maxs_sem",
        "Compatibility proxy for controller-owned Top-K std err values.",
    )
    roi_means = _controller_property(
        "metrics_state",
        "roi_means",
        "Compatibility proxy for controller-owned ROI means.",
    )
    roi_stds = _controller_property(
        "metrics_state",
        "roi_stds",
        "Compatibility proxy for controller-owned ROI std values.",
    )
    roi_sems = _controller_property(
        "metrics_state",
        "roi_sems",
        "Compatibility proxy for controller-owned ROI std err values.",
    )
    dn_per_ms_values = _controller_property(
        "metrics_state",
        "dn_per_ms_values",
        "Compatibility proxy for controller-owned DN/ms means.",
    )
    dn_per_ms_stds = _controller_property(
        "metrics_state",
        "dn_per_ms_stds",
        "Compatibility proxy for controller-owned DN/ms std values.",
    )
    dn_per_ms_sems = _controller_property(
        "metrics_state",
        "dn_per_ms_sems",
        "Compatibility proxy for controller-owned DN/ms std err values.",
    )
    roi_rect = _controller_property(
        "metrics_state",
        "roi_rect",
        "Compatibility proxy for controller-owned ROI rectangle.",
    )
    rounding_mode = _controller_property(
        "metrics_state",
        "rounding_mode",
        "Compatibility proxy for controller-owned display rounding mode.",
    )
    normalize_intensity_values = _controller_property(
        "metrics_state",
        "normalize_intensity_values",
        "Compatibility proxy for controller-owned normalization flag.",
    )
    background_config = _controller_property(
        "metrics_state",
        "background_config",
        "Compatibility proxy for controller-owned background config.",
    )
    background_library = _controller_property(
        "metrics_state",
        "background_library",
        "Compatibility proxy for controller-owned background library.",
    )
    background_signature = _controller_property(
        "metrics_state",
        "background_signature",
        "Compatibility proxy for controller-owned background signature.",
    )
    _background_source_text = _controller_property(
        "metrics_state",
        "background_source_text",
        "Compatibility proxy for controller-owned background source text.",
    )
    _bg_applied_mask = _controller_property(
        "metrics_state",
        "bg_applied_mask",
        "Compatibility proxy for controller-owned background applied mask.",
    )
    _bg_unmatched_count = _controller_property(
        "metrics_state",
        "bg_unmatched_count",
        "Compatibility proxy for controller-owned background unmatched count.",
    )
    _bg_total_count = _controller_property(
        "metrics_state",
        "bg_total_count",
        "Compatibility proxy for controller-owned background total count.",
    )
    threshold_value = _controller_property(
        "metrics_state",
        "threshold_value",
        "Compatibility proxy for controller-owned saturation threshold.",
    )
    avg_count_value = _controller_property(
        "metrics_state",
        "avg_count_value",
        "Compatibility proxy for controller-owned Top-K count.",
    )
    _stats_job_id = _controller_property(
        "metrics_state",
        "stats_job_id",
        "Compatibility proxy for controller-owned dynamic-stats job id.",
    )
    _stats_update_kind = _controller_property(
        "metrics_state",
        "stats_update_kind",
        "Compatibility proxy for controller-owned dynamic-stats update kind.",
    )
    _stats_refresh_analysis = _controller_property(
        "metrics_state",
        "stats_refresh_analysis",
        "Compatibility proxy for controller-owned analysis-refresh flag.",
    )
    _is_stats_running = _controller_property(
        "metrics_state",
        "is_stats_running",
        "Compatibility proxy for controller-owned dynamic-stats running flag.",
    )
    _roi_apply_job_id = _controller_property(
        "metrics_state",
        "roi_apply_job_id",
        "Compatibility proxy for controller-owned ROI-apply job id.",
    )
    _is_roi_applying = _controller_property(
        "metrics_state",
        "is_roi_applying",
        "Compatibility proxy for controller-owned ROI-apply running flag.",
    )
    _roi_apply_done = _controller_property(
        "metrics_state",
        "roi_apply_done",
        "Compatibility proxy for controller-owned ROI-apply progress.",
    )
    _roi_apply_total = _controller_property(
        "metrics_state",
        "roi_apply_total",
        "Compatibility proxy for controller-owned ROI-apply total count.",
    )
