"""Explicit metric/background state ownership for the main window."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from .background import BackgroundConfig, BackgroundLibrary
from .processing_failures import ProcessingFailure


class MetricFamily(str, Enum):
    """Named metric result families tracked by the pipeline controller."""

    STATIC_SCAN = "static_scan"
    SATURATION = "saturation"
    LOW_SIGNAL = "low_signal"
    TOPK = "topk"
    ROI = "roi"
    ROI_TOPK = "roi_topk"
    BACKGROUND_APPLIED = "background_applied"


class ScanMetricPreset(str, Enum):
    """Named scan-time metric setup presets."""

    MINIMAL = "minimal"
    THRESHOLD_REVIEW = "threshold_review"
    TOPK_STUDY = "topk_study"
    ROI_STUDY = "roi_study"
    CUSTOM = "custom"


class MetricFamilyState(str, Enum):
    """Readiness state for one metric family."""

    NOT_REQUESTED = "not_requested"
    PENDING_INPUTS = "pending_inputs"
    COMPUTING = "computing"
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MetricFamilyStatus:
    """Status payload for one metric family."""

    state: MetricFamilyState
    message: str = ""


SCAN_METRIC_FAMILY_ORDER = (
    MetricFamily.STATIC_SCAN,
    MetricFamily.SATURATION,
    MetricFamily.LOW_SIGNAL,
    MetricFamily.TOPK,
    MetricFamily.ROI,
    MetricFamily.ROI_TOPK,
)
SCAN_METRIC_OPTIONAL_FAMILIES = tuple(
    family for family in SCAN_METRIC_FAMILY_ORDER
    if family is not MetricFamily.STATIC_SCAN
)
SCAN_METRIC_PRESET_FAMILIES = {
    ScanMetricPreset.MINIMAL: (MetricFamily.STATIC_SCAN,),
    ScanMetricPreset.THRESHOLD_REVIEW: (
        MetricFamily.STATIC_SCAN,
        MetricFamily.SATURATION,
        MetricFamily.LOW_SIGNAL,
    ),
    ScanMetricPreset.TOPK_STUDY: (
        MetricFamily.STATIC_SCAN,
        MetricFamily.SATURATION,
        MetricFamily.TOPK,
    ),
    ScanMetricPreset.ROI_STUDY: (
        MetricFamily.STATIC_SCAN,
        MetricFamily.ROI,
    ),
}


@dataclass(frozen=True, slots=True)
class DynamicStatsResult:
    """Structured worker result for targeted dynamic metric families."""

    job_id: int
    sat_counts: np.ndarray | None = None
    avg_topk: np.ndarray | None = None
    avg_topk_std: np.ndarray | None = None
    avg_topk_sem: np.ndarray | None = None
    max_pixels: np.ndarray | None = None
    min_non_zero: np.ndarray | None = None
    bg_applied_mask: np.ndarray | None = None
    requested_families: tuple[MetricFamily, ...] = ()
    failures: tuple[ProcessingFailure, ...] = ()


@dataclass(frozen=True, slots=True)
class RoiApplyResult:
    """Structured worker result for dataset-wide ROI application."""

    job_id: int
    maxs: np.ndarray
    sums: np.ndarray
    means: np.ndarray
    stds: np.ndarray
    sems: np.ndarray
    valid_count: int
    topk_means: np.ndarray | None = None
    topk_stds: np.ndarray | None = None
    topk_sems: np.ndarray | None = None
    requested_families: tuple[MetricFamily, ...] = ()
    failures: tuple[ProcessingFailure, ...] = ()


class MetricsPipelineController:
    """Own metric settings, background state, and latest metric snapshots."""

    def __init__(self) -> None:
        self.min_non_zero: np.ndarray | None = None
        self.maxs: np.ndarray | None = None
        self.sat_counts: np.ndarray | None = None
        self.avg_maxs: np.ndarray | None = None
        self.avg_maxs_std: np.ndarray | None = None
        self.avg_maxs_sem: np.ndarray | None = None
        self.roi_maxs: np.ndarray | None = None
        self.roi_sums: np.ndarray | None = None
        self.roi_means: np.ndarray | None = None
        self.roi_stds: np.ndarray | None = None
        self.roi_sems: np.ndarray | None = None
        self.roi_topk_means: np.ndarray | None = None
        self.roi_topk_stds: np.ndarray | None = None
        self.roi_topk_sems: np.ndarray | None = None
        self.roi_applied_to_all = False
        self.dn_per_ms_values: np.ndarray | None = None
        self.dn_per_ms_stds: np.ndarray | None = None
        self.dn_per_ms_sems: np.ndarray | None = None
        self.roi_rect: tuple[int, int, int, int] | None = None
        self.rounding_mode = "off"
        self.normalize_intensity_values = False
        self.background_config = BackgroundConfig()
        self.background_library = BackgroundLibrary()
        self.background_signature = 0
        self.background_source_text = ""
        self.bg_applied_mask: np.ndarray | None = None
        self.bg_unmatched_count = 0
        self.bg_total_count = 0
        self.threshold_value = 65520.0
        self.low_signal_threshold_value = 0.0
        self.avg_count_value = 32
        self.pending_threshold_value = self.threshold_value
        self.pending_low_signal_threshold_value = self.low_signal_threshold_value
        self.pending_avg_count_value = self.avg_count_value
        self.scan_metric_preset = ScanMetricPreset.MINIMAL
        self.custom_scan_metric_families = (MetricFamily.STATIC_SCAN,)
        self.metric_family_statuses = {
            family.value: MetricFamilyStatus(MetricFamilyState.NOT_REQUESTED)
            for family in MetricFamily
        }
        self.stats_job_id = 0
        self.stats_update_kind = "idle"
        self.stats_refresh_analysis = True
        self.is_stats_running = False
        self.roi_apply_job_id = 0
        self.is_roi_applying = False
        self.roi_apply_done = 0
        self.roi_apply_total = 0
        self._clear_loaded_dataset_buffer_state()

    @staticmethod
    def _family_key(family: MetricFamily | str) -> str:
        key = family.value if isinstance(family, MetricFamily) else str(family)
        if key not in {entry.value for entry in MetricFamily}:
            raise ValueError(f"Unknown metric family: {family!r}")
        return key

    @staticmethod
    def _family_state(state: MetricFamilyState | str) -> MetricFamilyState:
        if isinstance(state, MetricFamilyState):
            return state
        return MetricFamilyState(str(state))

    def metric_family_status(
        self,
        family: MetricFamily | str,
    ) -> MetricFamilyStatus:
        """Return the current readiness status for one metric family."""

        key = self._family_key(family)
        return self.metric_family_statuses.get(
            key,
            MetricFamilyStatus(MetricFamilyState.NOT_REQUESTED),
        )

    def metric_family_state(self, family: MetricFamily | str) -> MetricFamilyState:
        """Return the current readiness state for one metric family."""

        return self.metric_family_status(family).state

    def set_metric_family_state(
        self,
        family: MetricFamily | str,
        state: MetricFamilyState | str,
        message: str = "",
    ) -> None:
        """Set the readiness state for one metric family."""

        self.metric_family_statuses[self._family_key(family)] = MetricFamilyStatus(
            self._family_state(state),
            str(message or ""),
        )

    def reset_metric_family_states(self) -> None:
        """Reset all metric families to their initial not-requested state."""

        for family in MetricFamily:
            self.set_metric_family_state(
                family,
                MetricFamilyState.NOT_REQUESTED,
            )

    @staticmethod
    def normalize_metric_families(
        families: list[MetricFamily | str] | tuple[MetricFamily | str, ...] | None,
    ) -> tuple[MetricFamily, ...]:
        """Return known metric families with duplicates removed in enum order."""

        selected: set[MetricFamily] = set()
        for family in families or ():
            try:
                selected.add(
                    family
                    if isinstance(family, MetricFamily)
                    else MetricFamily(str(family))
                )
            except ValueError:
                continue
        return tuple(family for family in MetricFamily if family in selected)

    @staticmethod
    def _scan_metric_preset(preset: ScanMetricPreset | str) -> ScanMetricPreset:
        if isinstance(preset, ScanMetricPreset):
            return preset
        try:
            return ScanMetricPreset(str(preset))
        except ValueError:
            return ScanMetricPreset.MINIMAL

    @staticmethod
    def _normalize_scan_metric_families(
        families: list[MetricFamily | str] | tuple[MetricFamily | str, ...] | None,
    ) -> tuple[MetricFamily, ...]:
        selected: set[MetricFamily] = {MetricFamily.STATIC_SCAN}
        for family in families or ():
            try:
                normalized = (
                    family
                    if isinstance(family, MetricFamily)
                    else MetricFamily(str(family))
                )
            except ValueError:
                continue
            if normalized in SCAN_METRIC_FAMILY_ORDER:
                selected.add(normalized)
        return tuple(
            family for family in SCAN_METRIC_FAMILY_ORDER
            if family in selected
        )

    def set_scan_metric_preset(self, preset: ScanMetricPreset | str) -> None:
        """Select one scan-time metric preset."""

        current_families = self.scan_metric_families()
        selected_preset = self._scan_metric_preset(preset)
        if (
            selected_preset == ScanMetricPreset.CUSTOM
            and self.scan_metric_preset != ScanMetricPreset.CUSTOM
        ):
            self.custom_scan_metric_families = current_families
        self.scan_metric_preset = selected_preset

    def set_custom_scan_metric_families(
        self,
        families: list[MetricFamily | str] | tuple[MetricFamily | str, ...] | None,
    ) -> None:
        """Store the family set used by the Custom scan preset."""

        self.custom_scan_metric_families = self._normalize_scan_metric_families(
            families,
        )
        self.scan_metric_preset = ScanMetricPreset.CUSTOM

    def restore_scan_metric_setup(
        self,
        *,
        preset: ScanMetricPreset | str,
        families: list[MetricFamily | str] | tuple[MetricFamily | str, ...] | None,
    ) -> None:
        """Restore scan setup from persisted workspace state."""

        self.scan_metric_preset = self._scan_metric_preset(preset)
        self.custom_scan_metric_families = self._normalize_scan_metric_families(
            families,
        )

    def scan_metric_families(self) -> tuple[MetricFamily, ...]:
        """Return the selected scan-time metric families."""

        if self.scan_metric_preset == ScanMetricPreset.CUSTOM:
            return self.custom_scan_metric_families
        return SCAN_METRIC_PRESET_FAMILIES.get(
            self.scan_metric_preset,
            SCAN_METRIC_PRESET_FAMILIES[ScanMetricPreset.MINIMAL],
        )

    def scan_metric_family_values(self) -> list[str]:
        """Return selected scan-time metric family ids for persistence."""

        return [family.value for family in self.scan_metric_families()]

    def threshold_inputs_pending(self) -> bool:
        """Return whether saturation threshold UI differs from applied state."""

        return float(self.pending_threshold_value) != float(self.threshold_value)

    def low_signal_inputs_pending(self) -> bool:
        """Return whether low-signal UI differs from applied state."""

        return (
            float(self.pending_low_signal_threshold_value)
            != float(self.low_signal_threshold_value)
        )

    def topk_inputs_pending(self) -> bool:
        """Return whether Top-K UI differs from applied state."""

        return int(self.pending_avg_count_value) != int(self.avg_count_value)

    def set_pending_threshold_value(self, value: float) -> None:
        """Store pending saturation threshold without applying it."""

        self.pending_threshold_value = float(value)
        self._sync_pending_input_family_states()

    def set_pending_low_signal_threshold_value(self, value: float) -> None:
        """Store pending low-signal threshold without applying it."""

        self.pending_low_signal_threshold_value = float(value)
        self._sync_pending_input_family_states()

    def set_pending_avg_count_value(self, value: int) -> None:
        """Store pending Top-K count without applying it."""

        self.pending_avg_count_value = max(1, int(value))
        self._sync_pending_input_family_states()

    def apply_pending_threshold_value(self) -> bool:
        """Make the pending saturation threshold the applied value."""

        changed = self.threshold_inputs_pending()
        self.threshold_value = float(self.pending_threshold_value)
        self._sync_pending_input_family_states()
        return changed

    def apply_pending_low_signal_threshold_value(self) -> bool:
        """Make the pending low-signal threshold the applied value."""

        changed = self.low_signal_inputs_pending()
        self.low_signal_threshold_value = float(
            self.pending_low_signal_threshold_value,
        )
        self.set_metric_family_state(
            MetricFamily.LOW_SIGNAL,
            (
                MetricFamilyState.NOT_REQUESTED
                if self.low_signal_threshold_value <= 0.0
                else MetricFamilyState.READY
            ),
        )
        self._sync_pending_input_family_states()
        return changed

    def apply_pending_avg_count_value(self) -> bool:
        """Make the pending Top-K count the applied value."""

        changed = self.topk_inputs_pending()
        self.avg_count_value = max(1, int(self.pending_avg_count_value))
        self._sync_pending_input_family_states()
        return changed

    def sync_pending_values_from_applied(self) -> None:
        """Reset pending UI values to the currently applied metric inputs."""

        self.pending_threshold_value = float(self.threshold_value)
        self.pending_low_signal_threshold_value = float(
            self.low_signal_threshold_value,
        )
        self.pending_avg_count_value = max(1, int(self.avg_count_value))
        self._sync_pending_input_family_states()

    def refresh_pending_input_family_states(self) -> None:
        """Refresh family states after external pending/applied restoration."""

        self._sync_pending_input_family_states()

    def _sync_pending_input_family_states(self) -> None:
        """Keep pending-input states explicit without clobbering active jobs."""

        pending_by_family = {
            MetricFamily.SATURATION: self.threshold_inputs_pending(),
            MetricFamily.LOW_SIGNAL: self.low_signal_inputs_pending(),
            MetricFamily.TOPK: self.topk_inputs_pending(),
            MetricFamily.ROI_TOPK: self.topk_inputs_pending(),
        }
        for family, pending in pending_by_family.items():
            state = self.metric_family_state(family)
            if pending:
                if state != MetricFamilyState.COMPUTING:
                    self.set_metric_family_state(
                        family,
                        MetricFamilyState.PENDING_INPUTS,
                    )
            elif state == MetricFamilyState.PENDING_INPUTS:
                self.set_metric_family_state(
                    family,
                    MetricFamilyState.NOT_REQUESTED,
                )

    def _clear_loaded_dataset_buffer_state(self) -> None:
        """Drop any reserved streaming buffers used during dataset loading."""

        self._loaded_dataset_capacity = 0
        self._loaded_dataset_count = 0
        self._loaded_min_non_zero_buffer: np.ndarray | None = None
        self._loaded_maxs_buffer: np.ndarray | None = None
        self._loaded_sat_counts_buffer: np.ndarray | None = None
        self._loaded_roi_maxs_buffer: np.ndarray | None = None
        self._loaded_roi_sums_buffer: np.ndarray | None = None
        self._loaded_roi_means_buffer: np.ndarray | None = None
        self._loaded_roi_stds_buffer: np.ndarray | None = None
        self._loaded_roi_sems_buffer: np.ndarray | None = None
        self._loaded_roi_topk_means_buffer: np.ndarray | None = None
        self._loaded_roi_topk_stds_buffer: np.ndarray | None = None
        self._loaded_roi_topk_sems_buffer: np.ndarray | None = None
        self._loaded_bg_applied_mask_buffer: np.ndarray | None = None

    def _current_loaded_dataset_count(self) -> int:
        """Return the current public row count tracked by dataset-sized arrays."""

        if self._loaded_min_non_zero_buffer is not None:
            return int(self._loaded_dataset_count)
        for values in (
            self.maxs,
            self.min_non_zero,
            self.sat_counts,
            self.roi_maxs,
            self.roi_sums,
        ):
            if values is not None:
                return int(len(values))
        return 0

    @staticmethod
    def _copy_prefix(
        target: np.ndarray,
        source: np.ndarray | None,
        count: int,
        *,
        dtype: np.dtype,
    ) -> None:
        """Copy one shared prefix into a resized streaming buffer."""

        if count <= 0 or source is None:
            return
        target[:count] = np.asarray(source, dtype=dtype)[:count]

    def _sync_loaded_dataset_views(self) -> None:
        """Expose the loaded prefix of reserved buffers through public arrays."""

        count = max(0, int(self._loaded_dataset_count))
        self.min_non_zero = (
            self._loaded_min_non_zero_buffer[:count]
            if self._loaded_min_non_zero_buffer is not None
            else None
        )
        self.maxs = (
            self._loaded_maxs_buffer[:count]
            if self._loaded_maxs_buffer is not None
            else None
        )
        self.sat_counts = (
            self._loaded_sat_counts_buffer[:count]
            if self._loaded_sat_counts_buffer is not None
            else None
        )
        self.roi_maxs = (
            self._loaded_roi_maxs_buffer[:count]
            if self._loaded_roi_maxs_buffer is not None
            else None
        )
        self.roi_sums = (
            self._loaded_roi_sums_buffer[:count]
            if self._loaded_roi_sums_buffer is not None
            else None
        )
        self.roi_means = (
            self._loaded_roi_means_buffer[:count]
            if self._loaded_roi_means_buffer is not None
            else None
        )
        self.roi_stds = (
            self._loaded_roi_stds_buffer[:count]
            if self._loaded_roi_stds_buffer is not None
            else None
        )
        self.roi_sems = (
            self._loaded_roi_sems_buffer[:count]
            if self._loaded_roi_sems_buffer is not None
            else None
        )
        self.roi_topk_means = (
            self._loaded_roi_topk_means_buffer[:count]
            if self._loaded_roi_topk_means_buffer is not None
            else None
        )
        self.roi_topk_stds = (
            self._loaded_roi_topk_stds_buffer[:count]
            if self._loaded_roi_topk_stds_buffer is not None
            else None
        )
        self.roi_topk_sems = (
            self._loaded_roi_topk_sems_buffer[:count]
            if self._loaded_roi_topk_sems_buffer is not None
            else None
        )
        self.bg_applied_mask = (
            self._loaded_bg_applied_mask_buffer[:count]
            if self._loaded_bg_applied_mask_buffer is not None
            else None
        )
        self.bg_total_count = count
        self.bg_unmatched_count = count if self.background_config.enabled else 0

    def clear_metric_results(self) -> None:
        """Clear dataset-dependent metric results while preserving settings."""
        self._clear_loaded_dataset_buffer_state()
        self.min_non_zero = None
        self.maxs = None
        self.sat_counts = None
        self.avg_maxs = None
        self.avg_maxs_std = None
        self.avg_maxs_sem = None
        self.dn_per_ms_values = None
        self.dn_per_ms_stds = None
        self.dn_per_ms_sems = None
        self.bg_applied_mask = None
        self.bg_unmatched_count = 0
        self.bg_total_count = 0
        self.reset_metric_family_states()

    def clear_dataset_state(self) -> None:
        """Clear metric and ROI state tied to the currently loaded dataset."""
        self.clear_metric_results()
        self.roi_rect = None
        self.reset_roi_metrics(0)

    def reset_roi_metrics(self, path_count: int) -> None:
        """Reset ROI-derived arrays to NaN-filled buffers for one dataset size."""
        count = max(0, int(path_count))
        self.roi_applied_to_all = False
        self.roi_maxs = np.full(count, np.nan, dtype=np.float64)
        self.roi_sums = np.full(count, np.nan, dtype=np.float64)
        self.roi_means = np.full(count, np.nan, dtype=np.float64)
        self.roi_stds = np.full(count, np.nan, dtype=np.float64)
        self.roi_sems = np.full(count, np.nan, dtype=np.float64)
        self.roi_topk_means = np.full(count, np.nan, dtype=np.float64)
        self.roi_topk_stds = np.full(count, np.nan, dtype=np.float64)
        self.roi_topk_sems = np.full(count, np.nan, dtype=np.float64)
        self.set_metric_family_state(MetricFamily.ROI, MetricFamilyState.NOT_REQUESTED)
        self.set_metric_family_state(
            MetricFamily.ROI_TOPK,
            (
                MetricFamilyState.PENDING_INPUTS
                if self.topk_inputs_pending()
                else MetricFamilyState.NOT_REQUESTED
            ),
        )

    def initialize_loaded_dataset(self, path_count: int) -> None:
        """Initialize dataset-dependent state after a new dataset load."""
        count = max(0, int(path_count))
        self._clear_loaded_dataset_buffer_state()
        self.roi_rect = None
        self.min_non_zero = (
            np.zeros(count, dtype=np.int64)
            if count > 0
            else None
        )
        self.maxs = (
            np.zeros(count, dtype=np.int64)
            if count > 0
            else None
        )
        self.reset_roi_metrics(count)
        self.sat_counts = None
        self.avg_maxs = None
        self.avg_maxs_std = None
        self.avg_maxs_sem = None
        self.dn_per_ms_values = None
        self.dn_per_ms_stds = None
        self.dn_per_ms_sems = None
        self.bg_applied_mask = None
        self.bg_total_count = 0
        self.bg_unmatched_count = 0
        self.reset_metric_family_states()
        if count > 0:
            self.set_metric_family_state(
                MetricFamily.STATIC_SCAN,
                MetricFamilyState.READY,
            )
        self._sync_pending_input_family_states()

    def reserve_loaded_dataset(self, total_candidates: int) -> None:
        """Reserve capacity for one incremental dataset load."""

        capacity = max(0, int(total_candidates))
        if capacity <= 0:
            return
        if (
            capacity <= self._loaded_dataset_capacity
            and self._loaded_min_non_zero_buffer is not None
        ):
            return

        loaded_count = min(self._current_loaded_dataset_count(), capacity)
        min_non_zero = np.zeros(capacity, dtype=np.int64)
        maxs = np.zeros(capacity, dtype=np.int64)
        sat_counts = np.zeros(capacity, dtype=np.int64)
        roi_maxs = np.full(capacity, np.nan, dtype=np.float64)
        roi_sums = np.full(capacity, np.nan, dtype=np.float64)
        roi_means = np.full(capacity, np.nan, dtype=np.float64)
        roi_stds = np.full(capacity, np.nan, dtype=np.float64)
        roi_sems = np.full(capacity, np.nan, dtype=np.float64)
        roi_topk_means = np.full(capacity, np.nan, dtype=np.float64)
        roi_topk_stds = np.full(capacity, np.nan, dtype=np.float64)
        roi_topk_sems = np.full(capacity, np.nan, dtype=np.float64)
        bg_applied_mask = np.zeros(capacity, dtype=bool)

        self._copy_prefix(
            min_non_zero,
            self.min_non_zero,
            loaded_count,
            dtype=np.int64,
        )
        self._copy_prefix(
            maxs,
            self.maxs,
            loaded_count,
            dtype=np.int64,
        )
        self._copy_prefix(
            sat_counts,
            self.sat_counts,
            loaded_count,
            dtype=np.int64,
        )
        self._copy_prefix(
            roi_maxs,
            self.roi_maxs,
            loaded_count,
            dtype=np.float64,
        )
        self._copy_prefix(
            roi_sums,
            self.roi_sums,
            loaded_count,
            dtype=np.float64,
        )
        self._copy_prefix(
            roi_means,
            self.roi_means,
            loaded_count,
            dtype=np.float64,
        )
        self._copy_prefix(
            roi_stds,
            self.roi_stds,
            loaded_count,
            dtype=np.float64,
        )
        self._copy_prefix(
            roi_topk_means,
            self.roi_topk_means,
            loaded_count,
            dtype=np.float64,
        )
        self._copy_prefix(
            roi_topk_stds,
            self.roi_topk_stds,
            loaded_count,
            dtype=np.float64,
        )
        self._copy_prefix(
            roi_topk_sems,
            self.roi_topk_sems,
            loaded_count,
            dtype=np.float64,
        )
        self._copy_prefix(
            roi_sems,
            self.roi_sems,
            loaded_count,
            dtype=np.float64,
        )
        self._copy_prefix(
            bg_applied_mask,
            self.bg_applied_mask,
            loaded_count,
            dtype=bool,
        )

        self._loaded_dataset_capacity = capacity
        self._loaded_dataset_count = loaded_count
        self._loaded_min_non_zero_buffer = min_non_zero
        self._loaded_maxs_buffer = maxs
        self._loaded_sat_counts_buffer = sat_counts
        self._loaded_roi_maxs_buffer = roi_maxs
        self._loaded_roi_sums_buffer = roi_sums
        self._loaded_roi_means_buffer = roi_means
        self._loaded_roi_stds_buffer = roi_stds
        self._loaded_roi_sems_buffer = roi_sems
        self._loaded_roi_topk_means_buffer = roi_topk_means
        self._loaded_roi_topk_stds_buffer = roi_topk_stds
        self._loaded_roi_topk_sems_buffer = roi_topk_sems
        self._loaded_bg_applied_mask_buffer = bg_applied_mask
        self._sync_loaded_dataset_views()

    def append_loaded_batch(
        self,
        min_non_zero: np.ndarray,
        maxs: np.ndarray,
    ) -> None:
        """Extend dataset-sized metric arrays for one incremental load batch."""

        mins_arr = np.asarray(min_non_zero, dtype=np.int64)
        maxs_arr = np.asarray(maxs, dtype=np.int64)
        if mins_arr.size != maxs_arr.size:
            raise ValueError("Loaded metric batches must have matching lengths")
        batch_count = int(maxs_arr.size)
        if batch_count <= 0:
            return
        required = self._current_loaded_dataset_count() + batch_count
        if (
            self._loaded_min_non_zero_buffer is None
            or required > self._loaded_dataset_capacity
        ):
            self.reserve_loaded_dataset(required)

        assert self._loaded_min_non_zero_buffer is not None
        assert self._loaded_maxs_buffer is not None
        assert self._loaded_sat_counts_buffer is not None
        assert self._loaded_roi_maxs_buffer is not None
        assert self._loaded_roi_sums_buffer is not None
        assert self._loaded_roi_means_buffer is not None
        assert self._loaded_roi_stds_buffer is not None
        assert self._loaded_roi_sems_buffer is not None
        assert self._loaded_roi_topk_means_buffer is not None
        assert self._loaded_roi_topk_stds_buffer is not None
        assert self._loaded_roi_topk_sems_buffer is not None
        assert self._loaded_bg_applied_mask_buffer is not None

        start = int(self._loaded_dataset_count)
        end = start + batch_count
        self._loaded_min_non_zero_buffer[start:end] = mins_arr
        self._loaded_maxs_buffer[start:end] = maxs_arr
        self._loaded_sat_counts_buffer[start:end] = 0
        self._loaded_roi_maxs_buffer[start:end].fill(np.nan)
        self._loaded_roi_sums_buffer[start:end].fill(np.nan)
        self._loaded_roi_means_buffer[start:end].fill(np.nan)
        self._loaded_roi_stds_buffer[start:end].fill(np.nan)
        self._loaded_roi_sems_buffer[start:end].fill(np.nan)
        self._loaded_roi_topk_means_buffer[start:end].fill(np.nan)
        self._loaded_roi_topk_stds_buffer[start:end].fill(np.nan)
        self._loaded_roi_topk_sems_buffer[start:end].fill(np.nan)
        self._loaded_bg_applied_mask_buffer[start:end] = False
        self._loaded_dataset_count = end
        self._sync_loaded_dataset_views()
        self.set_metric_family_state(
            MetricFamily.STATIC_SCAN,
            MetricFamilyState.READY,
        )

    def prepare_for_live_update(self, *, path_count: int, mode: str) -> None:
        """Ensure dataset-sized metric arrays exist for one recompute request."""
        count = max(0, int(path_count))
        self.bg_total_count = count
        if not self.background_config.enabled:
            self.bg_unmatched_count = 0
            self.bg_applied_mask = np.zeros(count, dtype=bool)
        elif not self.background_library.has_any_reference():
            self.bg_unmatched_count = count
            self.bg_applied_mask = np.zeros(count, dtype=bool)

        if self.sat_counts is None or len(self.sat_counts) != count:
            self.sat_counts = np.zeros(count, dtype=np.int64)

        if mode == "topk":
            if self.avg_maxs is None or len(self.avg_maxs) != count:
                self.avg_maxs = np.full(count, np.nan, dtype=np.float64)
            if self.avg_maxs_std is None or len(self.avg_maxs_std) != count:
                self.avg_maxs_std = np.full(count, np.nan, dtype=np.float64)
            if self.avg_maxs_sem is None or len(self.avg_maxs_sem) != count:
                self.avg_maxs_sem = np.full(count, np.nan, dtype=np.float64)
        else:
            self.avg_maxs = None
            self.avg_maxs_std = None
            self.avg_maxs_sem = None

        if self.roi_means is None or len(self.roi_means) != count:
            self.roi_means = np.full(count, np.nan, dtype=np.float64)
        if self.roi_maxs is None or len(self.roi_maxs) != count:
            self.roi_maxs = np.full(count, np.nan, dtype=np.float64)
        if self.roi_sums is None or len(self.roi_sums) != count:
            self.roi_sums = np.full(count, np.nan, dtype=np.float64)
        if self.roi_stds is None or len(self.roi_stds) != count:
            self.roi_stds = np.full(count, np.nan, dtype=np.float64)
        if self.roi_sems is None or len(self.roi_sems) != count:
            self.roi_sems = np.full(count, np.nan, dtype=np.float64)
        if self.roi_topk_means is None or len(self.roi_topk_means) != count:
            self.roi_topk_means = np.full(count, np.nan, dtype=np.float64)
        if self.roi_topk_stds is None or len(self.roi_topk_stds) != count:
            self.roi_topk_stds = np.full(count, np.nan, dtype=np.float64)
        if self.roi_topk_sems is None or len(self.roi_topk_sems) != count:
            self.roi_topk_sems = np.full(count, np.nan, dtype=np.float64)

    def apply_dynamic_stats_result(
        self,
        result: DynamicStatsResult,
        *,
        path_count: int,
    ) -> None:
        """Store one structured dynamic-stats worker result."""
        requested = self.normalize_metric_families(result.requested_families)
        if not requested:
            inferred: list[MetricFamily] = []
            if result.sat_counts is not None:
                inferred.append(MetricFamily.SATURATION)
            if result.avg_topk is not None:
                inferred.append(MetricFamily.TOPK)
            if result.max_pixels is not None or result.bg_applied_mask is not None:
                inferred.append(MetricFamily.BACKGROUND_APPLIED)
            requested = self.normalize_metric_families(tuple(inferred))

        self._clear_loaded_dataset_buffer_state()
        if MetricFamily.SATURATION in requested and result.sat_counts is not None:
            self.sat_counts = np.asarray(result.sat_counts, dtype=np.int64)
        if MetricFamily.TOPK in requested and result.avg_topk is not None:
            self.avg_maxs = np.asarray(result.avg_topk, dtype=np.float64)
            self.avg_maxs_std = (
                np.asarray(result.avg_topk_std, dtype=np.float64)
                if result.avg_topk_std is not None
                else np.full(max(0, int(path_count)), np.nan, dtype=np.float64)
            )
            self.avg_maxs_sem = (
                np.asarray(result.avg_topk_sem, dtype=np.float64)
                if result.avg_topk_sem is not None
                else np.full(max(0, int(path_count)), np.nan, dtype=np.float64)
            )
        if (
            MetricFamily.BACKGROUND_APPLIED in requested
            and result.max_pixels is not None
            and result.min_non_zero is not None
            and result.bg_applied_mask is not None
        ):
            self.maxs = np.asarray(result.max_pixels, dtype=np.int64)
            self.min_non_zero = np.asarray(result.min_non_zero, dtype=np.int64)
            self.bg_applied_mask = np.asarray(result.bg_applied_mask, dtype=bool)
            self.bg_total_count = max(0, int(path_count))
            self.bg_unmatched_count = int(
                self.bg_total_count - np.count_nonzero(self.bg_applied_mask),
            )
        self.set_metric_family_state(
            MetricFamily.STATIC_SCAN,
            MetricFamilyState.READY,
        )
        if MetricFamily.SATURATION in requested:
            self.set_metric_family_state(
                MetricFamily.SATURATION,
                (
                    MetricFamilyState.PENDING_INPUTS
                    if self.threshold_inputs_pending()
                    else MetricFamilyState.READY
                ),
            )
        if MetricFamily.BACKGROUND_APPLIED in requested:
            self.set_metric_family_state(
                MetricFamily.BACKGROUND_APPLIED,
                MetricFamilyState.READY,
            )
            self.set_metric_family_state(
                MetricFamily.LOW_SIGNAL,
                (
                    MetricFamilyState.PENDING_INPUTS
                    if self.low_signal_inputs_pending()
                    else (
                        MetricFamilyState.READY
                        if self.low_signal_threshold_value > 0.0
                        else MetricFamilyState.NOT_REQUESTED
                    )
                ),
            )
        if MetricFamily.TOPK in requested:
            self.set_metric_family_state(
                MetricFamily.TOPK,
                (
                    MetricFamilyState.PENDING_INPUTS
                    if self.topk_inputs_pending()
                    else MetricFamilyState.READY
                ),
            )

    def apply_roi_result(self, result: RoiApplyResult) -> None:
        """Store one structured ROI-apply worker result."""
        requested = self.normalize_metric_families(result.requested_families)
        if not requested:
            requested = (
                (MetricFamily.ROI, MetricFamily.ROI_TOPK)
                if result.topk_means is not None
                else (MetricFamily.ROI,)
            )
        self._clear_loaded_dataset_buffer_state()
        self.roi_applied_to_all = True
        self.roi_maxs = np.asarray(result.maxs, dtype=np.float64)
        self.roi_sums = np.asarray(result.sums, dtype=np.float64)
        self.roi_means = np.asarray(result.means, dtype=np.float64)
        self.roi_stds = np.asarray(result.stds, dtype=np.float64)
        self.roi_sems = np.asarray(result.sems, dtype=np.float64)
        self.roi_topk_means = (
            np.asarray(result.topk_means, dtype=np.float64)
            if result.topk_means is not None
            else None
        )
        self.roi_topk_stds = (
            np.asarray(result.topk_stds, dtype=np.float64)
            if result.topk_stds is not None
            else None
        )
        self.roi_topk_sems = (
            np.asarray(result.topk_sems, dtype=np.float64)
            if result.topk_sems is not None
            else None
        )
        if MetricFamily.ROI in requested:
            self.set_metric_family_state(
                MetricFamily.ROI,
                MetricFamilyState.READY,
            )
        if MetricFamily.ROI_TOPK in requested:
            self.set_metric_family_state(
                MetricFamily.ROI_TOPK,
                (
                    MetricFamilyState.PENDING_INPUTS
                    if self.topk_inputs_pending()
                    else MetricFamilyState.READY
                ),
            )
        elif self.metric_family_state(MetricFamily.ROI_TOPK) == MetricFamilyState.COMPUTING:
            self.set_metric_family_state(
                MetricFamily.ROI_TOPK,
                (
                    MetricFamilyState.PENDING_INPUTS
                    if self.topk_inputs_pending()
                    else MetricFamilyState.NOT_REQUESTED
                ),
            )

    def low_signal_mask(
        self,
        *,
        path_count: int | None = None,
    ) -> np.ndarray | None:
        """Return per-image low-signal flags for the applied threshold."""

        threshold = float(self.low_signal_threshold_value)
        if threshold <= 0.0 or self.maxs is None:
            return None
        mask = np.asarray(self.maxs, dtype=np.int64) <= int(threshold)
        if path_count is not None and len(mask) != max(0, int(path_count)):
            return None
        return mask

    def low_signal_image_count(
        self,
        *,
        path_count: int | None = None,
    ) -> int:
        """Return number of images flagged by the applied low-signal threshold."""

        mask = self.low_signal_mask(path_count=path_count)
        if mask is None:
            return 0
        return int(np.count_nonzero(mask))

    def begin_stats_job(
        self,
        *,
        update_kind: str,
        refresh_analysis: bool,
        requested_families: tuple[MetricFamily | str, ...] | None = None,
    ) -> int:
        """Advance and record one in-flight dynamic-stats job."""
        self.stats_job_id += 1
        self.stats_update_kind = (
            update_kind if update_kind in {"full", "threshold_only"} else "full"
        )
        self.stats_refresh_analysis = bool(refresh_analysis)
        self.is_stats_running = True
        requested = self.normalize_metric_families(
            requested_families
            or (
                (MetricFamily.SATURATION,)
                if self.stats_update_kind == "threshold_only"
                else (MetricFamily.SATURATION, MetricFamily.BACKGROUND_APPLIED)
            ),
        )
        for family in requested:
            self.set_metric_family_state(
                family,
                MetricFamilyState.COMPUTING,
            )
        return self.stats_job_id

    def finish_stats_job(self) -> None:
        """Clear dynamic-stats running state after completion or failure."""
        self.is_stats_running = False
        self.stats_update_kind = "idle"
        self._sync_pending_input_family_states()

    def cancel_stats_job(self) -> int:
        """Invalidate the current dynamic-stats job and clear running state."""

        self.stats_job_id += 1
        self.finish_stats_job()
        return self.stats_job_id

    def begin_roi_apply(
        self,
        total: int,
        *,
        requested_families: tuple[MetricFamily | str, ...] | None = None,
    ) -> int:
        """Advance and record one in-flight dataset-wide ROI apply job."""
        self.roi_apply_job_id += 1
        self.is_roi_applying = True
        self.roi_apply_done = 0
        self.roi_apply_total = max(0, int(total))
        requested = self.normalize_metric_families(
            requested_families or (MetricFamily.ROI,),
        )
        for family in requested:
            self.set_metric_family_state(
                family,
                MetricFamilyState.COMPUTING,
            )
        return self.roi_apply_job_id

    def update_roi_apply_progress(self, done: int, total: int) -> None:
        """Store current ROI-apply progress counts."""
        self.roi_apply_done = max(0, int(done))
        self.roi_apply_total = max(0, int(total))

    def finish_roi_apply(self) -> None:
        """Clear ROI-apply running state after finish, cancel, or failure."""
        self.is_roi_applying = False
        self.roi_apply_done = 0
        self.roi_apply_total = 0
        self._sync_pending_input_family_states()

    def cancel_roi_apply(self) -> int:
        """Invalidate the current ROI apply job and clear its running state."""
        self.roi_apply_job_id += 1
        self.finish_roi_apply()
        return self.roi_apply_job_id
