"""Main application window for FrameLab."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Optional
from collections import OrderedDict

import numpy as np
from PySide6 import QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt, QThread, QTimer

from .analysis_context import AnalysisContextController
from .datacard_labels import label_for_metadata_field
from .dataset_state import DatasetStateController
from .main_window import (
    AnalysisPageMixin,
    DataPageMixin,
    DatasetLoadingMixin,
    InspectPageMixin,
    MetricsRuntimeMixin,
    WindowChromeMixin,
    WindowActionsMixin,
)
from .metrics_state import MetricsPipelineController
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
from .ui_settings import UiStateSnapshot, UiStateStore
from .workers import DynamicStatsWorker, RoiApplyWorker


def _controller_property(controller_name: str, state_name: str, doc: str) -> property:
    """Build a simple compatibility proxy onto one controller attribute."""

    def getter(self):
        return getattr(getattr(self, controller_name), state_name)

    def setter(self, value):
        setattr(getattr(self, controller_name), state_name, value)

    return property(getter, setter, doc=doc)


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
        self._analysis_plugins: list[AnalysisPlugin] = []
        self._enabled_plugin_ids = resolve_enabled_plugin_ids(enabled_plugin_ids)
        self._page_plugin_classes: dict[str, list[type[object]]] = {
            page: [] for page in PAGE_IDS
        }
        self._page_plugin_manifests: dict[str, list[PluginManifest]] = {
            page: [] for page in PAGE_IDS
        }
        self._image_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._image_cache_capacity = 24
        self._corrected_cache: OrderedDict[
            tuple[str, int], np.ndarray
        ] = OrderedDict()
        self._corrected_cache_capacity = 24
        self._load_ui_state()
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
