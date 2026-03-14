"""Main application window for FrameLab."""

from __future__ import annotations

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
from .scan_settings import load_skip_patterns, skip_config_path
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
        self.show_image_preview = True
        self.show_histogram_preview = False
        self._analysis_plugin_engaged = False
        self._metadata_controls_auto_expanded = False
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
        self._theme_mode = "dark"
        self._processing_failures = []
        self._processing_failure_banners: list[qtw.QWidget] = []
        self._processing_failure_banner_labels: list[qtw.QLabel] = []

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
        self._apply_theme("dark")
        self._set_status()

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
