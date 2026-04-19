"""Main application window for FrameLab."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
import sys
from typing import Iterable, Optional
import shutil

import numpy as np
from PySide6 import QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt, QSignalBlocker, QThread, QTimer, Signal

from .analysis_context import AnalysisContextController
from .acquisition_datacard import (
    resolve_campaign_datacard_path,
    resolve_session_datacard_path,
)
from .byte_budget_cache import ByteBudgetCache
from .datacard_authoring.mapping import load_field_mapping
from .datacard_authoring.service import (
    load_acquisition_datacard,
    save_acquisition_datacard,
)
from .datacard_labels import label_for_metadata_field
from .dataset_state import DatasetScopeNode, DatasetStateController
from .file_dialogs import choose_open_file, choose_save_file
from .icons import apply_app_identity
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
from .node_metadata import load_nodecard, save_nodecard
from .payload_utils import (
    delete_dot_path,
    flatten_payload_dict,
    read_json_dict,
    set_dot_path,
    write_json_dict,
)
from .plugins import (
    PAGE_IDS,
    PluginManifest,
    enabled_plugin_manifests,
    load_enabled_plugins,
    resolve_enabled_plugin_ids,
)
from .plugins.analysis import AnalysisPlugin
from .ui_density import AdaptiveUiContext, UiDensityResolver
from .ui_settings import RecentWorkflowEntry, UiStateSnapshot, UiStateStore
from .workspace_document import (
    WorkspaceDocumentBackgroundState,
    WorkspaceDocumentDatasetState,
    WorkspaceDocumentMeasureState,
    WorkspaceDocumentSnapshot,
    WorkspaceDocumentStore,
    WorkspaceDocumentUiState,
    WorkspaceDocumentWorkflowState,
)
from .window_drag import apply_secondary_window_geometry
from .workflow import WorkflowStateController, workflow_profile_by_id
from .workers import DynamicStatsWorker, RoiApplyWorker, DatasetLoadWorker
from .native import backend as native_backend


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


@dataclass(frozen=True)
class WorkflowLoadResolution:
    """Resolved workflow load request after prompt-driven fallback decisions."""

    profile_id: str
    anchor_type_id: str | None = None
    info_text: str = ""


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

    datasetLoadCompleted = Signal(object)

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
        "roi_max": 5,
        "min_non_zero": 6,
        "sat_count": 7,
        "avg": 8,
        "std": 9,
        "sem": 10,
        "dn_per_ms": 11,
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
    ROI_MODE_MEASURE_COLUMNS = {"roi_max"}
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
        ("roi_max", "ROI Max"),
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
        self._density_refresh_ready = False
        self._density_refresh_timer: QTimer | None = None
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
        self._workflow_tab_settle_timer = QTimer(self)
        self._workflow_tab_settle_timer.setSingleShot(True)
        self._workflow_tab_settle_timer.setInterval(150)
        self._workflow_tab_settle_timer.timeout.connect(
            self._flush_pending_workflow_tab_change,
        )
        self._pending_workflow_tab_index: int | None = None
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
        self._image_cache = ByteBudgetCache[object](
            self.RAW_IMAGE_CACHE_BUDGET_BYTES,
        )
        self._corrected_cache = ByteBudgetCache[tuple[object, int]](
            self.CORRECTED_IMAGE_CACHE_BUDGET_BYTES,
        )
        self.workspace_document_store = WorkspaceDocumentStore()
        self._workspace_document_path: Path | None = None
        self._workspace_document_reference_payload: dict[str, object] | None = None
        self._workspace_document_dirty = False
        self._workspace_document_tracking_enabled = False
        self._workspace_document_restore_depth = 0
        self._load_ui_state()
        native_backend.configure_raw_runtime(
            use_mmap_for_raw=self.ui_preferences.use_mmap_for_raw,
            enable_raw_simd=self.ui_preferences.enable_raw_simd,
        )
        self.workflow_state_controller = WorkflowStateController()
        self.metadata_state_controller = MetadataStateController(
            self.workflow_state_controller,
        )
        self._restore_persisted_workflow_state()
        self.show_image_preview = self.ui_preferences.show_image_preview
        self.show_histogram_preview = self.ui_preferences.show_histogram_preview
        self._density_resolver = UiDensityResolver()
        density_refresh_timer = QTimer(self)
        density_refresh_timer.setSingleShot(True)
        density_refresh_timer.setInterval(90)
        density_refresh_timer.timeout.connect(
            self._apply_dynamic_visibility_policy,
        )
        self._density_refresh_timer = density_refresh_timer
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
        self._dataset_load_thread: Optional[QThread] = None
        self._dataset_load_worker: Optional[DatasetLoadWorker] = None
        self._dataset_load_job_id = 0
        self._dataset_load_callbacks: dict[int, list[object]] = {}
        self._dataset_load_auto_metrics: dict[int, bool] = {}
        self._dataset_load_workflow_notices: dict[int, str] = {}
        self._dataset_load_start_pending = False
        self._dataset_load_batch_applying = False
        self._dataset_load_refresh_timer = QTimer(self)
        self._dataset_load_refresh_timer.setSingleShot(True)
        self._dataset_load_refresh_timer.setInterval(60)
        self._dataset_load_refresh_timer.timeout.connect(
            self._flush_dataset_load_table_refresh,
        )
        self._threshold_summary_anim_phase = 0
        self._threshold_summary_timer = QTimer(self)
        self._threshold_summary_timer.setInterval(320)
        self._threshold_summary_timer.timeout.connect(
            self._advance_threshold_summary_animation,
        )
        self._roi_apply_thread: Optional[QThread] = None
        self._roi_apply_worker: Optional[RoiApplyWorker] = None
        self._preview_selection_timer = QTimer(self)
        self._preview_selection_timer.setSingleShot(True)
        self._preview_selection_timer.setInterval(150)
        self._preview_selection_timer.timeout.connect(
            self._flush_pending_selection_preview,
        )
        self._pending_selection_preview_index: int | None = None
        self._pending_selection_preview_generation = 0
        self._preview_generation = 0
        self._pause_preview_updates = False
        self._workflow_scope_refresh_timer = QTimer(self)
        self._workflow_scope_refresh_timer.setSingleShot(True)
        self._workflow_scope_refresh_timer.setInterval(0)
        self._workflow_scope_refresh_timer.timeout.connect(
            self._flush_pending_workflow_scope_refresh,
        )
        self._pending_workflow_scope_refresh_origin: str | None = None
        self._scan_selected_scope_timer = QTimer(self)
        self._scan_selected_scope_timer.setSingleShot(True)
        self._scan_selected_scope_timer.setInterval(25)
        self._scan_selected_scope_timer.timeout.connect(
            self._flush_pending_scan_selected_scope,
        )
        self._pending_scan_selected_scope = False
        self._workspace_document_dirty_timer = QTimer(self)
        self._workspace_document_dirty_timer.setSingleShot(True)
        self._workspace_document_dirty_timer.setInterval(200)
        self._workspace_document_dirty_timer.timeout.connect(
            self._refresh_workspace_document_dirty_state,
        )
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder
        self._theme_mode = self.ui_preferences.theme_mode
        self._processing_failures = []
        self._processing_failure_banners: list[qtw.QWidget] = []
        self._processing_failure_banner_labels: list[qtw.QLabel] = []
        self._processing_failure_banner_layouts: list[qtw.QHBoxLayout] = []

        self.base_status = "Select a folder."
        self.context_hint = "Step 1: choose a dataset folder, then scan."
        self.skip_patterns: list[str] = []
        self.skip_pattern_config_path = None
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
        self._initialize_workspace_document_tracking()
        self._density_refresh_ready = True
        self._schedule_density_refresh()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """Re-apply app identity once the main window is a native top level."""

        super().showEvent(event)
        if sys.platform == "win32":
            return
        app = qtw.QApplication.instance()
        if not isinstance(app, qtw.QApplication):
            return
        QTimer.singleShot(
            0,
            lambda app=app, window=self: apply_app_identity(app, window),
        )

    def _load_ui_state(self) -> None:
        """Load persisted UI preferences and initialize empty launch state."""

        self.ui_state_store = UiStateStore()
        try:
            self.ui_state_snapshot = self.ui_state_store.load()
        except Exception:
            self.ui_state_snapshot = UiStateSnapshot()
        self.ui_preferences = self.ui_state_snapshot.preferences

    def _restore_persisted_ui_state(self) -> None:
        """Apply any launch-time UI snapshot state once widgets exist."""

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
        """Apply any launch-time workflow snapshot state when available."""

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
        scope_kind = (
            "custom"
            if self.workflow_state_controller.is_custom_workspace()
            else active_node.type_id
        )
        self.dataset_state.set_workflow_scope(
            root=active_node.folder_path,
            kind=scope_kind,
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

    def _refresh_manager_dialogs(
        self,
        *,
        origin: str | None = None,
    ) -> None:
        """Refresh open workflow surfaces after host-state changes."""

        for attr_name in (
            "_workflow_manager_dialog",
            "_metadata_manager_dialog",
            "_workflow_explorer_dock",
            "_metadata_inspector_dock",
        ):
            dialog = getattr(self, attr_name, None)
            if dialog is None:
                continue
            if origin == "workflow_explorer" and attr_name == "_workflow_explorer_dock":
                continue
            if isinstance(dialog, qtw.QWidget) and not dialog.isVisible():
                mark_dirty = getattr(dialog, "mark_dirty", None)
                if callable(mark_dirty):
                    try:
                        mark_dirty()
                    except Exception:
                        pass
                continue
            schedule_refresh = getattr(dialog, "schedule_sync_from_host", None)
            if callable(schedule_refresh):
                try:
                    schedule_refresh()
                except Exception:
                    continue
                continue
            refresh = getattr(dialog, "sync_from_host", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    continue

    def _schedule_workflow_scope_refresh(
        self,
        *,
        origin: str | None = None,
    ) -> None:
        """Coalesce expensive scope-change refreshes onto the next event-loop turn."""

        self._pending_workflow_scope_refresh_origin = origin
        self._workflow_scope_refresh_timer.start()

    def _flush_pending_workflow_scope_refresh(self) -> None:
        """Apply deferred scope-change fanout after the UI selection settles."""

        origin = self._pending_workflow_scope_refresh_origin
        self._pending_workflow_scope_refresh_origin = None

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
        self._refresh_manager_dialogs(origin=origin)

    def _notify_workflow_scope_changed(
        self,
        *,
        origin: str | None = None,
    ) -> None:
        """Refresh cheap scope UI immediately, then defer heavier fanout."""

        if hasattr(self, "_refresh_workflow_shell_context"):
            self._refresh_workflow_shell_context()
        explorer = getattr(self, "_workflow_explorer_dock", None)
        refresh = getattr(explorer, "sync_from_host", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass
        self._schedule_workflow_scope_refresh(origin=origin)

    def _request_scan_selected_scope(self) -> None:
        """Switch to Data, then start scanning after scope activation settles."""

        explorer = getattr(self, "_workflow_explorer_dock", None)
        flush_pending = getattr(explorer, "flush_pending_activation", None)
        if callable(flush_pending):
            try:
                flush_pending()
            except Exception:
                pass
        if hasattr(self, "workflow_tabs"):
            self.workflow_tabs.setCurrentIndex(0)
        self._pending_scan_selected_scope = True
        self._scan_selected_scope_timer.start()

    def _flush_pending_scan_selected_scope(self) -> None:
        """Kick off one pending scope scan after tab switching has settled."""

        if not self._pending_scan_selected_scope:
            return
        self._pending_scan_selected_scope = False
        if hasattr(self, "load_folder"):
            self.load_folder()

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

    def _move_metadata_field_to_workflow_node_payload(
        self,
        payload: dict[str, object],
        target_node_id: str,
    ) -> bool:
        """Move one metadata field from its current storage onto another node."""

        workflow = self.workflow_state_controller
        target_node = workflow.node(target_node_id)
        if target_node is None:
            return False

        key = str(payload.get("key", "") or "").strip()
        label = str(payload.get("label", "") or key).strip() or key
        source_path_text = str(payload.get("source_path", "") or "").strip()
        source_storage_kind = str(payload.get("storage_kind", "") or "nodecard").strip()
        source_value = deepcopy(payload.get("value"))
        if not key or not source_path_text:
            return False
        if source_storage_kind == "acquisition_datacard_override":
            raise ValueError(
                f"'{label}' varies by frame in acquisition override rows and cannot "
                "be moved as one single field value.",
            )

        source_path = Path(source_path_text).expanduser().resolve()
        target_storage_kind = self._metadata_target_storage_kind(
            key,
            target_node.type_id,
        )
        if (
            source_path == target_node.folder_path.resolve()
            and source_storage_kind == target_storage_kind
        ):
            return False

        self._remove_metadata_field_from_storage(
            source_path,
            key,
            source_storage_kind,
        )
        self._write_metadata_field_to_storage(
            target_node.folder_path,
            target_node.profile_id,
            target_node.type_id,
            key,
            source_value,
            target_storage_kind,
        )
        self._notify_metadata_context_changed()
        self.statusBar().showMessage(
            (
                f"Moved '{label}' to "
                f"{self._workflow_node_type_label(target_node.type_id)} "
                f"'{target_node.display_name}'."
            ),
            5000,
        )
        return True

    def _remove_metadata_field_payload(
        self,
        payload: dict[str, object],
    ) -> bool:
        """Remove one metadata field from the storage owned by its current node."""

        key = str(payload.get("key", "") or "").strip()
        label = str(payload.get("label", "") or key).strip() or key
        source_path_text = str(payload.get("source_path", "") or "").strip()
        source_storage_kind = str(payload.get("storage_kind", "") or "nodecard").strip()
        if not key or not source_path_text:
            return False

        source_path = Path(source_path_text).expanduser().resolve()
        self._remove_metadata_field_from_storage(
            source_path,
            key,
            source_storage_kind,
        )
        self._notify_metadata_context_changed(changed_root=source_path)
        self.statusBar().showMessage(
            f"Removed '{label}' from {source_path.name}.",
            5000,
        )
        return True

    def _metadata_target_storage_kind(
        self,
        key: str,
        node_type_id: str,
    ) -> str:
        """Return the preferred storage backend for a field on one node type."""

        clean_key = str(key).strip()
        if str(node_type_id).strip().lower() != "acquisition":
            return "nodecard"
        try:
            mapping = load_field_mapping()
        except Exception:
            mapping = None
        if mapping is not None and clean_key in mapping.by_key():
            return "acquisition_datacard_defaults"
        return "nodecard"

    def _remove_metadata_field_from_storage(
        self,
        node_path: Path,
        key: str,
        storage_kind: str,
    ) -> None:
        """Remove one metadata key from its current backing storage."""

        clean_storage = str(storage_kind).strip().lower()
        if clean_storage == "acquisition_datacard_override":
            model = load_acquisition_datacard(node_path)
            delete_dot_path(model.defaults, key)
            filtered_rows = []
            for row in model.overrides:
                if not isinstance(row.changes, dict):
                    continue
                row.changes.pop(key, None)
                if row.changes:
                    filtered_rows.append(row)
            model.overrides = filtered_rows
            save_acquisition_datacard(node_path, model)
            return
        if clean_storage == "acquisition_datacard_defaults":
            model = load_acquisition_datacard(node_path)
            delete_dot_path(model.defaults, key)
            save_acquisition_datacard(node_path, model)
            return

        existing_card = self.metadata_state_controller.load_node_metadata(node_path)
        updated_metadata = deepcopy(existing_card.metadata)
        delete_dot_path(updated_metadata, key)
        self.metadata_state_controller.save_node_metadata(
            node_path,
            updated_metadata,
            profile_id=existing_card.profile_id,
            node_type_id=existing_card.node_type_id,
            extra_top_level=dict(existing_card.extra_top_level),
        )

    def _write_metadata_field_to_storage(
        self,
        node_path: Path,
        profile_id: str | None,
        node_type_id: str | None,
        key: str,
        value: object,
        storage_kind: str,
    ) -> None:
        """Write one metadata key into the requested target storage backend."""

        clean_storage = str(storage_kind).strip().lower()
        if clean_storage == "acquisition_datacard_defaults":
            model = load_acquisition_datacard(node_path)
            set_dot_path(model.defaults, key, deepcopy(value))
            save_acquisition_datacard(node_path, model)
            existing_card = self.metadata_state_controller.load_node_metadata(node_path)
            existing_flat = deepcopy(existing_card.metadata)
            if existing_card.source_exists and key in flatten_payload_dict(existing_flat):
                delete_dot_path(existing_flat, key)
                self.metadata_state_controller.save_node_metadata(
                    node_path,
                    existing_flat,
                    profile_id=existing_card.profile_id or profile_id,
                    node_type_id=existing_card.node_type_id or node_type_id,
                    extra_top_level=dict(existing_card.extra_top_level),
                )
            return

        existing_card = self.metadata_state_controller.load_node_metadata(node_path)
        updated_metadata = deepcopy(existing_card.metadata)
        set_dot_path(updated_metadata, key, deepcopy(value))
        self.metadata_state_controller.save_node_metadata(
            node_path,
            updated_metadata,
            profile_id=existing_card.profile_id or profile_id,
            node_type_id=existing_card.node_type_id or node_type_id,
            extra_top_level=dict(existing_card.extra_top_level),
        )

    def _set_manual_dataset_scope(self, folder: Path | None) -> None:
        """Store a manual folder-driven scope when workflow resolution is not used."""

        if folder is None:
            self.dataset_state.clear_scope()
            return
        self.dataset_state.set_manual_scope(folder)

    def _try_switch_custom_workflow_context(
        self,
        folder: Path,
    ) -> Path | None:
        """Detect and switch from Custom mode to a structured workflow when possible."""

        workflow = self.workflow_state_controller
        detection = workflow.detect_supported_workspace(folder)
        if detection is None:
            return None

        self.set_workflow_context(
            str(detection.workspace_root),
            detection.profile_id,
            anchor_type_id=detection.anchor_type_id,
        )
        profile = workflow_profile_by_id(detection.profile_id)
        display_name = (
            profile.display_name
            if profile is not None
            else detection.profile_id.replace("_", " ").title()
        )
        self._workflow_scope_transition_message = (
            f"Detected {display_name} workflow and switched out of Custom mode."
        )
        resolved_node = self.workflow_state_controller.active_node()
        if resolved_node is not None:
            return resolved_node.folder_path
        return detection.workspace_root

    def _scaffold_structured_workflow_root(
        self,
        workspace_root: str | Path,
        profile_id: str,
    ) -> Path:
        """Register one folder as an empty structured workflow root in place."""

        root = Path(workspace_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        existing = load_nodecard(root)
        save_nodecard(
            root,
            existing.metadata,
            profile_id=profile_id,
            node_type_id="root",
            extra_top_level=existing.extra_top_level,
        )
        profile = workflow_profile_by_id(profile_id)
        display_name = (
            profile.display_name
            if profile is not None
            else profile_id.replace("_", " ").title()
        )
        if hasattr(self, "statusBar"):
            self.statusBar().showMessage(
                f"Registered {display_name} workflow root at {root}.",
                5000,
            )
        return root

    def _prompt_for_unsupported_workflow_resolution(
        self,
        workspace_root: str | Path,
        requested_profile_id: str,
        warning_text: str,
        *,
        parent: qtw.QWidget | None = None,
    ) -> str | None:
        """Ask how an unsupported folder should be opened or scaffolded."""

        profile = workflow_profile_by_id(requested_profile_id)
        display_name = (
            profile.display_name
            if profile is not None
            else requested_profile_id.replace("_", " ").title()
        )
        dialog = qtw.QMessageBox(parent or self)
        dialog.setOption(qtw.QMessageBox.DontUseNativeDialog, True)
        dialog.setIcon(qtw.QMessageBox.Warning)
        dialog.setWindowTitle("Unsupported Workflow Level")
        dialog.setText(warning_text)
        dialog.setInformativeText(
            (
                f"You can still open this folder in Custom mode, or register "
                f"this folder itself as a new empty Calibration or Trials "
                f"workspace. Choosing a structured option writes a root "
                f"nodecard here so FrameLab recognizes it later even before "
                f"any child nodes exist.\n\nSelected profile: {display_name}\n"
                f"Folder: {Path(workspace_root).expanduser()}"
            ),
        )
        custom_button = dialog.addButton(
            "Open as Custom",
            qtw.QMessageBox.AcceptRole,
        )
        calibration_button = dialog.addButton(
            "Create Calibration Here",
            qtw.QMessageBox.ActionRole,
        )
        trials_button = dialog.addButton(
            "Create Trials Here",
            qtw.QMessageBox.ActionRole,
        )
        cancel_button = dialog.addButton(qtw.QMessageBox.Cancel)
        dialog.setDefaultButton(custom_button)
        apply_secondary_window_geometry(
            dialog,
            preferred_size=dialog.sizeHint(),
            host_window=parent or self,
        )
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is calibration_button:
            return "calibration"
        if clicked is trials_button:
            return "trials"
        if clicked is custom_button:
            return "custom"
        if clicked is cancel_button:
            return None
        return None

    def _resolve_workflow_load_request(
        self,
        workspace_root: str | Path,
        requested_profile_id: str,
        *,
        anchor_type_id: str | None = None,
        prompt_parent: qtw.QWidget | None = None,
    ) -> WorkflowLoadResolution | None:
        """Resolve one workflow-load request, including unsupported-folder prompts."""

        clean_profile_id = str(requested_profile_id).strip().lower()
        clean_anchor_type = (
            str(anchor_type_id).strip().lower()
            if anchor_type_id is not None and str(anchor_type_id).strip()
            else None
        )
        controller = self.workflow_state_controller
        warning_text = controller.unsupported_load_message(
            workspace_root,
            clean_profile_id,
            anchor_type_id=clean_anchor_type,
        )
        if not warning_text:
            return WorkflowLoadResolution(
                profile_id=clean_profile_id,
                anchor_type_id=clean_anchor_type,
            )

        choice = self._prompt_for_unsupported_workflow_resolution(
            workspace_root,
            clean_profile_id,
            warning_text,
            parent=prompt_parent,
        )
        if choice is None:
            return None
        if choice == "custom":
            return WorkflowLoadResolution(
                profile_id="custom",
                anchor_type_id="root",
                info_text=warning_text,
            )

        scaffold_root = self._scaffold_structured_workflow_root(
            workspace_root,
            choice,
        )
        display_name = choice.replace("_", " ").title()
        return WorkflowLoadResolution(
            profile_id=choice,
            anchor_type_id="root",
            info_text=(
                f"Created an empty {display_name} workflow root at "
                f"{scaffold_root}."
            ),
        )

    def _resolve_requested_dataset_scope_folder(self, folder: Path) -> Path:
        """Resolve the effective scan root from manual input and workflow state."""

        candidate = folder.expanduser()
        workflow = self.workflow_state_controller
        active_node = workflow.active_node()
        if active_node is None:
            return candidate

        if workflow.is_custom_workspace():
            detected_root = self._try_switch_custom_workflow_context(candidate)
            if detected_root is not None:
                candidate = detected_root
                workflow = self.workflow_state_controller
                active_node = workflow.active_node()
                if active_node is None:
                    return candidate
            elif candidate.resolve(strict=False) != active_node.folder_path.resolve():
                self._set_manual_dataset_scope(candidate)
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
            self._schedule_workspace_document_dirty_state_refresh()
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
        self._schedule_workspace_document_dirty_state_refresh()
        return load_result.active_node_id

    def set_active_workflow_node(
        self,
        node_id: str | None,
        *,
        sync_scope: bool = True,
        unload_mismatched_dataset: bool = True,
        notify_origin: str | None = None,
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
        self._notify_workflow_scope_changed(origin=notify_origin)
        self._schedule_workspace_document_dirty_state_refresh()
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
        can_rename_node = False
        rename_action_text = "Rename..."
        if node is not None and node.type_id != "root":
            can_rename_node = node.type_id != "acquisition" or selected_entry is not None
            rename_action_text = (
                "Rename / Relabel..."
                if node.type_id == "acquisition"
                else f"Rename {self._workflow_node_type_label(node.type_id)}..."
            )
        return {
            "node": node,
            "session_node": session_node,
            "session_index": session_index,
            "selected_entry": selected_entry,
            "can_create_session": create_child_type_id == "session",
            "can_delete_session": node is not None and node.type_id == "session",
            "can_create": session_node is not None and numbering_valid,
            "can_batch_create": session_node is not None and numbering_valid,
            "can_rename": selected_entry is not None,
            "can_rename_node": can_rename_node,
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
            "rename_action_text": rename_action_text,
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

    @staticmethod
    def _update_workflow_folder_identity_label(
        payload_path: Path,
        *,
        folder_name: str,
    ) -> None:
        """Keep structural datacard labels aligned with renamed workflow folders."""

        payload = read_json_dict(payload_path)
        if not isinstance(payload, dict):
            return
        identity = payload.get("identity")
        if not isinstance(identity, dict):
            identity = {}
        identity["label"] = folder_name
        payload["identity"] = identity
        write_json_dict(payload_path, payload)

    def _rename_workflow_node(
        self,
        node_id: str | None = None,
    ) -> None:
        """Rename the selected workflow node from the workflow shell."""

        controller = self.workflow_state_controller
        node = controller.node(node_id) if node_id else controller.active_node()
        if node is None or node.type_id == "root":
            return
        if node.type_id == "acquisition":
            self._rename_workflow_acquisition(node.node_id)
            return

        node_label = self._workflow_node_type_label(node.type_id)
        folder_label, accepted = qtw.QInputDialog.getText(
            self,
            f"Rename {node_label}",
            f"{node_label} folder name:",
            text=node.folder_path.name,
        )
        if not accepted:
            return

        try:
            clean_label = self._clean_workflow_folder_label(folder_label, node_label)
            new_path = node.folder_path.with_name(clean_label)
            if new_path != node.folder_path and new_path.exists():
                raise FileExistsError(
                    f"{node_label} folder already exists: {new_path.name}",
                )
            if new_path != node.folder_path:
                node.folder_path.rename(new_path)
                if node.type_id == "session":
                    self._update_workflow_folder_identity_label(
                        resolve_session_datacard_path(new_path),
                        folder_name=new_path.name,
                    )
                elif node.type_id == "campaign":
                    self._update_workflow_folder_identity_label(
                        resolve_campaign_datacard_path(new_path),
                        folder_name=new_path.name,
                    )
        except Exception as exc:
            qtw.QMessageBox.warning(
                self,
                f"Rename {node_label}",
                str(exc),
            )
            return

        result = WorkflowTreeMutationResult(
            renamed_paths=((node.folder_path, new_path),)
            if new_path != node.folder_path
            else (),
        )
        self._refresh_workflow_after_structure_mutation(
            result,
            preferred_active_path=new_path,
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
        """Create a session under the selected workflow parent node."""

        parent_node, child_type_id = self._workflow_create_target(node_id)
        if parent_node is None or child_type_id != "session":
            return None
        from .session_manager import create_session

        result = create_session(parent_node.folder_path, folder_label)
        preferred_path = result.created_path or parent_node.folder_path
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

        controller = self.workflow_state_controller
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
        profile_id = str(getattr(controller.profile, "profile_id", "") or "").strip().lower()
        if profile_id == "calibration" and child_type_id == "campaign":
            created_path.joinpath("01_sessions").mkdir(parents=True, exist_ok=True)
        if profile_id and child_type_id not in {"session", "acquisition"}:
            save_nodecard(
                created_path,
                {},
                profile_id=profile_id,
                node_type_id=child_type_id,
            )

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
        profile = controller.profile
        session_parent_node = next(
            (
                entry
                for entry in reversed(ancestry[:-1])
                if profile is not None
                and "session" in getattr(
                    profile.node_type(entry.type_id),
                    "child_type_ids",
                    (),
                )
            ),
            None,
        )
        if session_parent_node is not None:
            preferred_path = session_parent_node.folder_path
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

    def _initialize_workspace_document_tracking(self) -> None:
        """Start document tracking from the current live session state."""

        self._workspace_document_tracking_enabled = False
        self._workspace_document_path = None
        try:
            self._workspace_document_reference_payload = (
                self._capture_workspace_document_snapshot().to_payload()
            )
        except Exception:
            self._workspace_document_reference_payload = None
        self._workspace_document_dirty = False
        self._workspace_document_tracking_enabled = True
        self._update_workspace_document_window_title()

    def _workspace_document_restore_active(self) -> bool:
        """Return whether document restore is currently mutating live state."""

        return self._workspace_document_restore_depth > 0

    @staticmethod
    def _sanitize_workspace_document_label(label: object | None) -> str:
        """Return a filesystem-safe base name for suggested document paths."""

        text = str(label or "").strip()
        if not text:
            return "workspace"
        safe = "".join(
            character
            if character.isalnum() or character in {"-", "_", "."}
            else "_"
            for character in text
        ).strip("._")
        while "__" in safe:
            safe = safe.replace("__", "_")
        return safe or "workspace"

    def _suggest_workspace_document_path(self) -> Path:
        """Return a reasonable default path for Save Workspace As."""

        if self._workspace_document_path is not None:
            return self._workspace_document_path

        workflow_root = self.workflow_state_controller.workspace_root
        dataset_root = self.dataset_state.dataset_root
        active_node = self.workflow_state_controller.active_node()
        scope_label = (
            active_node.display_name
            if active_node is not None
            else self.dataset_state.scope_snapshot.label
        )
        base_name = self._sanitize_workspace_document_label(
            scope_label
            or (workflow_root.name if workflow_root is not None else None)
            or (dataset_root.name if dataset_root is not None else None)
            or "workspace",
        )
        directory = (
            workflow_root
            or dataset_root
            or Path.home()
        )
        return Path(directory).expanduser() / f"{base_name}.framelab"

    def _update_workspace_document_window_title(self) -> None:
        """Refresh the main window title from the active document state."""

        label = (
            self._workspace_document_path.name
            if self._workspace_document_path is not None
            else "Untitled"
        )
        modified = "*" if self._workspace_document_dirty else ""
        self.setWindowTitle(f"FrameLab - {label}{modified}")

    def _refresh_workspace_document_dirty_state(self) -> None:
        """Recompute the modified flag from the current serialized session."""

        if (
            not self._workspace_document_tracking_enabled
            or self._workspace_document_restore_active()
            or self._workspace_document_reference_payload is None
        ):
            return
        try:
            current_payload = self._capture_workspace_document_snapshot().to_payload()
        except Exception:
            return
        dirty = current_payload != self._workspace_document_reference_payload
        if dirty == self._workspace_document_dirty:
            return
        self._workspace_document_dirty = dirty
        self._update_workspace_document_window_title()

    def _schedule_workspace_document_dirty_state_refresh(self) -> None:
        """Coalesce expensive dirty-state recomputation after transient UI changes."""

        timer = getattr(self, "_workspace_document_dirty_timer", None)
        if timer is None:
            self._refresh_workspace_document_dirty_state()
            return
        timer.start()

    def _capture_workspace_document_snapshot(self) -> WorkspaceDocumentSnapshot:
        """Capture the current reopenable session as one workspace document."""

        workflow = self.workflow_state_controller
        dataset = self.dataset_state
        metrics = self.metrics_state
        selected_image_path: str | None = None
        if (
            dataset.selected_index is not None
            and 0 <= dataset.selected_index < dataset.path_count()
        ):
            selected_image_path = dataset.paths[dataset.selected_index]

        panel_states = {
            str(key).strip().lower(): bool(value)
            for key, value in self.ui_state_snapshot.panel_states.items()
            if str(key).strip()
        }
        workflow_dock = getattr(self, "_workflow_explorer_dock", None)
        if workflow_dock is not None:
            panel_states["workflow.explorer_dock"] = workflow_dock.isVisible()
        metadata_dock = getattr(self, "_metadata_inspector_dock", None)
        if metadata_dock is not None:
            panel_states["metadata.inspector_dock"] = metadata_dock.isVisible()
        data_toggle = getattr(self, "data_advanced_toggle", None)
        if data_toggle is not None:
            panel_states["data.advanced_row"] = bool(data_toggle.isChecked())
        analysis_toggle = getattr(self, "analysis_plugin_controls_toggle", None)
        if analysis_toggle is not None:
            panel_states["analysis.plugin_controls"] = bool(
                analysis_toggle.isChecked(),
            )

        splitter_sizes = {
            str(key).strip().lower(): [int(size) for size in value]
            for key, value in self.ui_state_snapshot.splitter_sizes.items()
            if str(key).strip()
        }
        measure_splitter = getattr(self, "measure_main_splitter", None)
        if measure_splitter is not None and hasattr(measure_splitter, "sizes"):
            splitter_sizes["measure.main_splitter"] = [
                int(size) for size in measure_splitter.sizes()
            ]
        analysis_splitter = getattr(self, "analysis_main_splitter", None)
        if analysis_splitter is not None and hasattr(analysis_splitter, "sizes"):
            splitter_sizes[self._analysis_main_splitter_key()] = [
                int(size) for size in analysis_splitter.sizes()
            ]
        analysis_plugin = self._current_analysis_plugin()
        if analysis_plugin is not None:
            workspace_splitter = analysis_plugin.workspace_splitter()
            if workspace_splitter is not None and hasattr(workspace_splitter, "sizes"):
                splitter_sizes[self._analysis_workspace_splitter_key(analysis_plugin)] = [
                    int(size) for size in workspace_splitter.sizes()
                ]

        metadata_panel = getattr(getattr(self, "_metadata_inspector_dock", None), "_panel", None)
        metadata_splitter = getattr(metadata_panel, "_splitter", None)
        if metadata_splitter is not None and hasattr(metadata_splitter, "sizes"):
            splitter_sizes["metadata.inspector_splitter.v1"] = [
                int(size) for size in metadata_splitter.sizes()
            ]

        scan_root = (
            str(dataset.dataset_root)
            if dataset.dataset_root is not None
            else None
        )
        scope_source = dataset.scope_snapshot.source
        if not scan_root and dataset.scope_snapshot.root is None:
            scope_source = None

        return WorkspaceDocumentSnapshot(
            workflow=WorkspaceDocumentWorkflowState(
                workspace_root=(
                    str(workflow.workspace_root)
                    if workflow.workspace_root is not None
                    else None
                ),
                profile_id=workflow.profile_id,
                anchor_type_id=workflow.anchor_type_id,
                active_node_id=workflow.active_node_id,
            ),
            dataset=WorkspaceDocumentDatasetState(
                scope_source=scope_source,
                scan_root=scan_root,
                selected_image_path=selected_image_path,
                skip_patterns=[str(pattern) for pattern in self.skip_patterns],
            ),
            measure=WorkspaceDocumentMeasureState(
                average_mode=self._current_average_mode(),
                threshold_value=float(
                    self.threshold_spin.value()
                    if hasattr(self, "threshold_spin")
                    else metrics.threshold_value
                ),
                low_signal_threshold_value=float(
                    self.low_signal_spin.value()
                    if hasattr(self, "low_signal_spin")
                    else metrics.low_signal_threshold_value
                ),
                avg_count_value=int(
                    self.avg_spin.value()
                    if hasattr(self, "avg_spin")
                    else metrics.avg_count_value
                ),
                rounding_mode=str(metrics.rounding_mode or "off"),
                normalize_intensity_values=bool(metrics.normalize_intensity_values),
                roi_rect=(
                    tuple(int(value) for value in metrics.roi_rect)
                    if metrics.roi_rect is not None
                    else None
                ),
                roi_applied_to_all=bool(metrics.roi_applied_to_all),
            ),
            background=WorkspaceDocumentBackgroundState(
                enabled=bool(metrics.background_config.enabled),
                source_mode=str(metrics.background_config.source_mode),
                clip_negative=bool(metrics.background_config.clip_negative),
                exposure_policy=str(metrics.background_config.exposure_policy),
                no_match_policy=str(metrics.background_config.no_match_policy),
                source_path=str(metrics.background_source_text).strip() or None,
            ),
            ui=WorkspaceDocumentUiState(
                active_page=self._current_active_page_id(),
                analysis_plugin_id=self._current_analysis_plugin_id(),
                show_image_preview=bool(self.show_image_preview),
                show_histogram_preview=bool(self.show_histogram_preview),
                panel_states=panel_states,
                splitter_sizes=splitter_sizes,
            ),
        )

    def _apply_workspace_document_panel_states(
        self,
        panel_states: dict[str, bool],
    ) -> None:
        """Apply saved dock and disclosure states from a workspace document."""

        if not self.ui_preferences.restore_panel_states:
            return

        workflow_dock = getattr(self, "_workflow_explorer_dock", None)
        if workflow_dock is not None and "workflow.explorer_dock" in panel_states:
            blocker = QSignalBlocker(workflow_dock)
            workflow_dock.setVisible(bool(panel_states["workflow.explorer_dock"]))
            del blocker
            toggle_action = getattr(self, "view_workflow_explorer_action", None)
            if toggle_action is not None:
                toggle_action.setChecked(bool(panel_states["workflow.explorer_dock"]))

        metadata_dock = getattr(self, "_metadata_inspector_dock", None)
        if metadata_dock is not None and "metadata.inspector_dock" in panel_states:
            blocker = QSignalBlocker(metadata_dock)
            metadata_dock.setVisible(bool(panel_states["metadata.inspector_dock"]))
            del blocker
            toggle_action = getattr(self, "view_metadata_inspector_action", None)
            if toggle_action is not None:
                toggle_action.setChecked(bool(panel_states["metadata.inspector_dock"]))

        if "data.advanced_row" in panel_states:
            self._set_data_advanced_row_expanded(bool(panel_states["data.advanced_row"]))
        if "analysis.plugin_controls" in panel_states:
            self._set_analysis_plugin_controls_expanded(
                bool(panel_states["analysis.plugin_controls"]),
            )

    def _apply_workspace_document_splitter_states(self) -> None:
        """Restore splitter sizes after document panel state has been loaded."""

        if hasattr(self, "_restore_splitter_state"):
            self._restore_splitter_state(
                "measure.main_splitter",
                getattr(self, "measure_main_splitter", None),
            )
        if hasattr(self, "_restore_visible_analysis_layout"):
            self._restore_visible_analysis_layout()
        metadata_panel = getattr(getattr(self, "_metadata_inspector_dock", None), "_panel", None)
        restore_metadata_splitter = getattr(
            metadata_panel,
            "_restore_splitter_state_if_needed",
            None,
        )
        if callable(restore_metadata_splitter):
            restore_metadata_splitter()

    def _restore_workspace_document_selection(
        self,
        selected_image_path: str | None,
        warnings: list[str],
    ) -> None:
        """Restore the selected image by persisted path."""

        dataset = self.dataset_state
        if not self._has_loaded_data() or not selected_image_path:
            return
        normalized = str(Path(selected_image_path).expanduser())
        index = -1
        for candidate_index, candidate_path in enumerate(dataset.paths):
            if str(Path(candidate_path).expanduser()) == normalized:
                index = candidate_index
                break
        if index < 0:
            warnings.append(
                "Selected image path is no longer present in the restored dataset: "
                f"{selected_image_path}",
            )
            return
        dataset.set_selected_index(index, path_count=dataset.path_count())
        self._set_table_current_source_row(index)
        self._display_image(index)

    def _finalize_workspace_document_open(
        self,
        path: Path,
        snapshot: WorkspaceDocumentSnapshot,
        warnings: list[str],
    ) -> None:
        """Record one fully restored workspace document as the active session."""

        try:
            reference_payload = self._capture_workspace_document_snapshot().to_payload()
        except Exception:
            reference_payload = snapshot.to_payload()
        self._workspace_document_path = path.expanduser()
        self._workspace_document_reference_payload = reference_payload
        self._workspace_document_dirty = False
        self._update_workspace_document_window_title()
        self._set_status(f"Opened workspace file {self._workspace_document_path.name}")
        if warnings:
            self._show_info(
                "Workspace File Opened With Warnings",
                "\n".join(warnings),
            )

    def _continue_workspace_document_restore(
        self,
        snapshot: WorkspaceDocumentSnapshot,
        warnings: list[str],
        *,
        document_path: Path | None = None,
        load_summary=None,
    ) -> None:
        """Apply the post-load portion of workspace restore, then finalize open."""

        try:
            if load_summary is not None and (
                getattr(load_summary, "failed", False)
                or getattr(load_summary, "no_files", False)
                or (
                    getattr(snapshot.dataset, "scan_root", None)
                    and not self._has_loaded_data()
                )
            ):
                scan_root_text = (snapshot.dataset.scan_root or "").strip()
                if scan_root_text:
                    warnings.append(
                        f"Dataset scan root could not be loaded: {scan_root_text}",
                    )

            background_state = snapshot.background
            metrics = self.metrics_state
            metrics.background_library.clear()
            self._invalidate_background_cache()
            metrics.background_config.enabled = bool(background_state.enabled)
            metrics.background_config.source_mode = str(background_state.source_mode)
            metrics.background_config.clip_negative = bool(
                background_state.clip_negative,
            )
            metrics.background_config.exposure_policy = str(
                background_state.exposure_policy,
            )
            metrics.background_config.no_match_policy = str(
                background_state.no_match_policy,
            )
            metrics.background_source_text = background_state.source_path or ""
            if background_state.source_path:
                source_path = Path(background_state.source_path).expanduser()
                if source_path.exists():
                    loaded = self._load_background_reference(
                        source_text=str(source_path),
                        mode=background_state.source_mode,
                        quiet=True,
                    )
                    if not loaded:
                        warnings.append(
                            "Background source could not be loaded: "
                            f"{background_state.source_path}",
                        )
                else:
                    warnings.append(
                        "Background source is missing: "
                        f"{background_state.source_path}",
                    )
            else:
                self._update_background_status_label()

            measure_state = snapshot.measure
            if hasattr(self, "avg_mode_combo"):
                blocker = QSignalBlocker(self.avg_mode_combo)
                mode_index = self.avg_mode_combo.findData(measure_state.average_mode)
                self.avg_mode_combo.setCurrentIndex(max(0, mode_index))
                del blocker
            if hasattr(self, "threshold_spin"):
                blocker = QSignalBlocker(self.threshold_spin)
                self.threshold_spin.setValue(float(measure_state.threshold_value))
                del blocker
            if hasattr(self, "low_signal_spin"):
                blocker = QSignalBlocker(self.low_signal_spin)
                self.low_signal_spin.setValue(
                    float(measure_state.low_signal_threshold_value),
                )
                del blocker
            if hasattr(self, "avg_spin"):
                blocker = QSignalBlocker(self.avg_spin)
                self.avg_spin.setValue(max(1, int(measure_state.avg_count_value)))
                del blocker
            metrics.threshold_value = float(measure_state.threshold_value)
            metrics.low_signal_threshold_value = float(
                measure_state.low_signal_threshold_value,
            )
            metrics.avg_count_value = max(1, int(measure_state.avg_count_value))
            metrics.rounding_mode = str(measure_state.rounding_mode)
            metrics.normalize_intensity_values = bool(
                measure_state.normalize_intensity_values,
            )
            if hasattr(self, "table_model"):
                self.table_model.set_rounding_mode(metrics.rounding_mode)
            if hasattr(self, "_sync_measure_display_menu_state"):
                self._sync_measure_display_menu_state()
            if self._has_loaded_data():
                self._apply_live_update()

            roi_rect = measure_state.roi_rect
            if roi_rect is not None:
                applied = self._apply_roi_rect_to_current_dataset(
                    roi_rect,
                    status_message=None,
                )
                if not applied:
                    warnings.append(
                        "Saved ROI no longer fits the restored dataset image bounds.",
                    )
            else:
                metrics.roi_rect = None
                if hasattr(self, "image_preview"):
                    self.image_preview.set_roi_rect(None)
                self._reset_roi_metrics()

            metrics.roi_applied_to_all = bool(measure_state.roi_applied_to_all)
            if (
                self._has_loaded_data()
                and measure_state.average_mode == "roi"
                and metrics.roi_rect is not None
                and metrics.roi_applied_to_all
            ):
                self._start_roi_apply_job()

            self.show_image_preview = bool(snapshot.ui.show_image_preview)
            self.show_histogram_preview = bool(snapshot.ui.show_histogram_preview)
            self._on_preview_visibility_changed()

            analysis_plugin_id = snapshot.ui.analysis_plugin_id
            if analysis_plugin_id and hasattr(self, "analysis_profile_combo"):
                index = self.analysis_profile_combo.findData(analysis_plugin_id)
                if index >= 0:
                    self.analysis_profile_combo.setCurrentIndex(index)
                else:
                    warnings.append(
                        "Saved analysis plugin is not currently available: "
                        f"{analysis_plugin_id}",
                    )

            page_id = snapshot.ui.active_page
            if self.ui_preferences.restore_last_tab and hasattr(self, "workflow_tabs"):
                target_index = 0
                if page_id == "measure":
                    target_index = 1 if self.workflow_tabs.count() > 1 else 0
                elif page_id == "analysis":
                    target_index = self.workflow_tabs.indexOf(
                        getattr(self, "analysis_page", None),
                    )
                if target_index >= 0:
                    self.workflow_tabs.setCurrentIndex(target_index)
                elif page_id == "analysis":
                    warnings.append(
                        "Saved Analyze tab could not be restored because no "
                        "analysis page is available.",
                    )

            self._apply_dynamic_visibility_policy()
            self._apply_workspace_document_panel_states(snapshot.ui.panel_states)
            self._apply_workspace_document_splitter_states()
            self._restore_workspace_document_selection(
                snapshot.dataset.selected_image_path,
                warnings,
            )
            self._refresh_manager_dialogs()
            self._set_status()
            if document_path is not None:
                self._finalize_workspace_document_open(
                    document_path,
                    snapshot,
                    warnings,
                )
        finally:
            self._workspace_document_restore_depth = max(
                0,
                self._workspace_document_restore_depth - 1,
            )

    def _restore_workspace_document_snapshot(
        self,
        snapshot: WorkspaceDocumentSnapshot,
        *,
        document_path: Path | None = None,
    ) -> list[str]:
        """Apply one workspace-document snapshot to the live window state."""

        warnings: list[str] = []
        self._workspace_document_restore_depth += 1
        async_pending = False
        try:
            self._session_panel_overrides.clear()
            self.ui_state_snapshot.panel_states = {
                str(key).strip().lower(): bool(value)
                for key, value in snapshot.ui.panel_states.items()
                if str(key).strip()
            }
            self.ui_state_snapshot.splitter_sizes = {
                str(key).strip().lower(): [max(0, int(size)) for size in value]
                for key, value in snapshot.ui.splitter_sizes.items()
                if str(key).strip() and value
            }
            self._set_skip_patterns(snapshot.dataset.skip_patterns, persist=False)

            workflow_state = snapshot.workflow
            workflow_loaded = False
            if workflow_state.workspace_root and workflow_state.profile_id:
                workflow_root = Path(workflow_state.workspace_root).expanduser()
                if workflow_root.exists():
                    self.set_workflow_context(
                        str(workflow_root),
                        workflow_state.profile_id,
                        anchor_type_id=workflow_state.anchor_type_id,
                        active_node_id=workflow_state.active_node_id,
                    )
                    workflow_loaded = True
                else:
                    warnings.append(
                        f"Workflow root is missing: {workflow_state.workspace_root}",
                    )
                    self.set_workflow_context(None, None)
            else:
                self.set_workflow_context(None, None)

            dataset_state = snapshot.dataset
            scan_root_text = (dataset_state.scan_root or "").strip()
            scan_root = Path(scan_root_text).expanduser() if scan_root_text else None
            if not scan_root_text:
                if self._has_loaded_data():
                    self.unload_folder(clear_folder_edit=False)
                if workflow_loaded:
                    self._sync_dataset_scope_to_workflow(
                        update_folder_edit=True,
                        unload_mismatched_dataset=False,
                    )
            else:
                if dataset_state.scope_source == "manual":
                    self._set_manual_dataset_scope(scan_root)
                if hasattr(self, "_set_folder_edit_text"):
                    self._set_folder_edit_text(str(scan_root))
                if scan_root is not None and scan_root.is_dir():
                    async_pending = True
                    self.load_folder(
                        after_load=(
                            lambda summary, snapshot=snapshot, warnings=warnings, document_path=document_path:
                            self._continue_workspace_document_restore(
                                snapshot,
                                warnings,
                                document_path=document_path,
                                load_summary=summary,
                            )
                        ),
                        suppress_auto_metrics=True,
                    )
                else:
                    warnings.append(
                        f"Dataset scan root is missing: {scan_root_text}",
                    )
                    if self._has_loaded_data():
                        self.unload_folder(clear_folder_edit=False)
            if not async_pending:
                self._continue_workspace_document_restore(
                    snapshot,
                    warnings,
                    document_path=document_path,
                )
        finally:
            if not async_pending:
                self._workspace_document_restore_depth = max(
                    0,
                    self._workspace_document_restore_depth - 1,
                )
        return warnings

    def _select_workspace_document_path_to_open(self) -> Path | None:
        """Prompt for one workspace-document path to open."""

        initial_dir = (
            str(self._workspace_document_path.parent)
            if self._workspace_document_path is not None
            else str(self._suggest_workspace_document_path().parent)
        )
        selected_path = choose_open_file(
            self,
            "Open Workspace File",
            initial_dir,
            name_filters=("FrameLab Workspace (*.framelab)", "All files (*)"),
            selected_name_filter="FrameLab Workspace (*.framelab)",
        )
        if not selected_path:
            return None
        return Path(selected_path).expanduser()

    def _select_workspace_document_path_to_save(self) -> Path | None:
        """Prompt for one workspace-document path to save."""

        initial_path = self._suggest_workspace_document_path()
        selected_path, _selected_filter = choose_save_file(
            self,
            "Save Workspace File",
            initial_path,
            name_filters=("FrameLab Workspace (*.framelab)", "All files (*)"),
            selected_name_filter="FrameLab Workspace (*.framelab)",
        )
        if not selected_path:
            return None
        candidate = Path(selected_path).expanduser()
        if candidate.suffix.lower() != ".framelab":
            candidate = candidate.with_suffix(".framelab")
        return candidate

    def _save_workspace_document_to_path(self, path: Path | str) -> bool:
        """Write the current session to one workspace-document path."""

        try:
            snapshot = self._capture_workspace_document_snapshot()
            final_path = self.workspace_document_store.save(path, snapshot)
        except Exception as exc:
            self._show_error("Save Workspace failed", str(exc))
            return False

        self._workspace_document_path = final_path
        self._workspace_document_reference_payload = snapshot.to_payload()
        self._workspace_document_dirty = False
        self._update_workspace_document_window_title()
        self._set_status(f"Saved workspace file to {final_path.name}")
        return True

    def _save_workspace_document(self) -> bool:
        """Save the current workspace document, prompting for a path if needed."""

        if self._workspace_document_path is None:
            return self._save_workspace_document_as()
        return self._save_workspace_document_to_path(self._workspace_document_path)

    def _save_workspace_document_as(self) -> bool:
        """Prompt for a destination and save the current workspace document."""

        selected_path = self._select_workspace_document_path_to_save()
        if selected_path is None:
            return False
        return self._save_workspace_document_to_path(selected_path)

    def _maybe_save_workspace_document_before_destructive_action(self) -> bool:
        """Prompt to save the current document before open/close when dirty."""

        app = qtw.QApplication.instance()
        if (
            not self._workspace_document_dirty
            or not self.isVisible()
            or (
                isinstance(app, qtw.QApplication)
                and app.platformName().strip().lower() == "offscreen"
            )
        ):
            return True

        dialog = qtw.QMessageBox(self)
        dialog.setOption(qtw.QMessageBox.DontUseNativeDialog, True)
        dialog.setIcon(qtw.QMessageBox.Warning)
        dialog.setWindowTitle("Unsaved Workspace Changes")
        dialog.setText(
            "Save changes to the current workspace document before continuing?",
        )
        dialog.setInformativeText(
            "Workflow, scan, ROI, background, and UI-state changes will be lost "
            "if you discard them.",
        )
        dialog.setStandardButtons(
            qtw.QMessageBox.Save
            | qtw.QMessageBox.Discard
            | qtw.QMessageBox.Cancel,
        )
        dialog.setDefaultButton(qtw.QMessageBox.Save)
        theme_sheet = (
            self._current_theme_stylesheet()
            if hasattr(self, "_current_theme_stylesheet")
            else ""
        )
        if theme_sheet:
            dialog.setStyleSheet(theme_sheet)
        apply_secondary_window_geometry(
            dialog,
            preferred_size=dialog.sizeHint(),
            host_window=self,
        )
        answer = dialog.exec()
        if answer == qtw.QMessageBox.Cancel:
            return False
        if answer == qtw.QMessageBox.Discard:
            return True
        return self._save_workspace_document()

    def _open_workspace_document(self, path: Path | str) -> bool:
        """Load and restore one workspace document from disk."""

        document_path = Path(path).expanduser()
        try:
            snapshot = self.workspace_document_store.load(document_path)
        except Exception as exc:
            self._show_error("Open Workspace failed", str(exc))
            return False

        try:
            self._restore_workspace_document_snapshot(
                snapshot,
                document_path=document_path,
            )
        except Exception as exc:
            self._show_error("Open Workspace failed", str(exc))
            return False
        return True

    def _open_workspace_document_from_dialog(self) -> None:
        """Prompt for and open a workspace document."""

        if not self._maybe_save_workspace_document_before_destructive_action():
            return
        selected_path = self._select_workspace_document_path_to_open()
        if selected_path is None:
            return
        self._open_workspace_document(selected_path)

    def _save_ui_state(self) -> None:
        """Persist current UI preferences and keep the runtime snapshot in sync."""

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
        self._refresh_workspace_document_dirty_state()

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
        self._refresh_workspace_document_dirty_state()

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

        if not bool(getattr(self, "_density_refresh_ready", False)):
            return
        timer = getattr(self, "_density_refresh_timer", None)
        start = getattr(timer, "start", None)
        if callable(start):
            start()

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
    roi_maxs = _controller_property(
        "metrics_state",
        "roi_maxs",
        "Compatibility proxy for controller-owned ROI max values.",
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
    low_signal_threshold_value = _controller_property(
        "metrics_state",
        "low_signal_threshold_value",
        "Compatibility proxy for controller-owned low-signal threshold.",
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
