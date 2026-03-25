"""Explicit metric/background state ownership for the main window."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .background import BackgroundConfig, BackgroundLibrary
from .processing_failures import ProcessingFailure


@dataclass(frozen=True, slots=True)
class DynamicStatsResult:
    """Structured worker result for dynamic threshold/top-k statistics."""

    job_id: int
    sat_counts: np.ndarray
    avg_topk: np.ndarray | None
    avg_topk_std: np.ndarray | None
    avg_topk_sem: np.ndarray | None
    max_pixels: np.ndarray
    min_non_zero: np.ndarray
    bg_applied_mask: np.ndarray
    failures: tuple[ProcessingFailure, ...] = ()


@dataclass(frozen=True, slots=True)
class RoiApplyResult:
    """Structured worker result for dataset-wide ROI application."""

    job_id: int
    maxs: np.ndarray
    means: np.ndarray
    stds: np.ndarray
    sems: np.ndarray
    valid_count: int
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
        self.roi_means: np.ndarray | None = None
        self.roi_stds: np.ndarray | None = None
        self.roi_sems: np.ndarray | None = None
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
        self.threshold_value = 4095.0
        self.low_signal_threshold_value = 0.0
        self.avg_count_value = 32
        self.stats_job_id = 0
        self.stats_update_kind = "idle"
        self.stats_refresh_analysis = True
        self.is_stats_running = False
        self.roi_apply_job_id = 0
        self.is_roi_applying = False
        self.roi_apply_done = 0
        self.roi_apply_total = 0

    def clear_metric_results(self) -> None:
        """Clear dataset-dependent metric results while preserving settings."""
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
        self.roi_means = np.full(count, np.nan, dtype=np.float64)
        self.roi_stds = np.full(count, np.nan, dtype=np.float64)
        self.roi_sems = np.full(count, np.nan, dtype=np.float64)

    def initialize_loaded_dataset(self, path_count: int) -> None:
        """Initialize dataset-dependent state after a new dataset load."""
        count = max(0, int(path_count))
        self.roi_rect = None
        self.reset_roi_metrics(count)
        self.sat_counts = np.zeros(count, dtype=np.int64)
        self.avg_maxs = None
        self.avg_maxs_std = None
        self.avg_maxs_sem = None
        self.dn_per_ms_values = None
        self.dn_per_ms_stds = None
        self.dn_per_ms_sems = None
        self.bg_applied_mask = np.zeros(count, dtype=bool)
        self.bg_total_count = count
        self.bg_unmatched_count = (
            count if self.background_config.enabled else 0
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
        if self.roi_stds is None or len(self.roi_stds) != count:
            self.roi_stds = np.full(count, np.nan, dtype=np.float64)
        if self.roi_sems is None or len(self.roi_sems) != count:
            self.roi_sems = np.full(count, np.nan, dtype=np.float64)

    def apply_dynamic_stats_result(
        self,
        result: DynamicStatsResult,
        *,
        path_count: int,
    ) -> None:
        """Store one structured dynamic-stats worker result."""
        self.sat_counts = np.asarray(result.sat_counts, dtype=np.int64)
        self.avg_maxs = (
            np.asarray(result.avg_topk, dtype=np.float64)
            if result.avg_topk is not None
            else None
        )
        self.avg_maxs_std = (
            np.asarray(result.avg_topk_std, dtype=np.float64)
            if result.avg_topk_std is not None
            else None
        )
        self.avg_maxs_sem = (
            np.asarray(result.avg_topk_sem, dtype=np.float64)
            if result.avg_topk_sem is not None
            else None
        )
        self.maxs = np.asarray(result.max_pixels, dtype=np.int64)
        self.min_non_zero = np.asarray(result.min_non_zero, dtype=np.int64)
        self.bg_applied_mask = np.asarray(result.bg_applied_mask, dtype=bool)
        self.bg_total_count = max(0, int(path_count))
        self.bg_unmatched_count = int(
            self.bg_total_count - np.count_nonzero(self.bg_applied_mask),
        )

    def apply_roi_result(self, result: RoiApplyResult) -> None:
        """Store one structured ROI-apply worker result."""
        self.roi_applied_to_all = True
        self.roi_maxs = np.asarray(result.maxs, dtype=np.float64)
        self.roi_means = np.asarray(result.means, dtype=np.float64)
        self.roi_stds = np.asarray(result.stds, dtype=np.float64)
        self.roi_sems = np.asarray(result.sems, dtype=np.float64)

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
    ) -> int:
        """Advance and record one in-flight dynamic-stats job."""
        self.stats_job_id += 1
        self.stats_update_kind = (
            update_kind if update_kind in {"full", "threshold_only"} else "full"
        )
        self.stats_refresh_analysis = bool(refresh_analysis)
        self.is_stats_running = True
        return self.stats_job_id

    def finish_stats_job(self) -> None:
        """Clear dynamic-stats running state after completion or failure."""
        self.is_stats_running = False
        self.stats_update_kind = "idle"

    def begin_roi_apply(self, total: int) -> int:
        """Advance and record one in-flight dataset-wide ROI apply job."""
        self.roi_apply_job_id += 1
        self.is_roi_applying = True
        self.roi_apply_done = 0
        self.roi_apply_total = max(0, int(total))
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

    def cancel_roi_apply(self) -> int:
        """Invalidate the current ROI apply job and clear its running state."""
        self.roi_apply_job_id += 1
        self.finish_roi_apply()
        return self.roi_apply_job_id
