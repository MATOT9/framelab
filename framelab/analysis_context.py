"""Explicit analysis-context preparation outside the UI layer."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .dataset_state import DatasetStateController
from .metrics_state import MetricsPipelineController
from .plugins.analysis import AnalysisContext, AnalysisRecord


class AnalysisContextController:
    """Build frozen analysis contexts from dataset and metric state."""

    def __init__(
        self,
        dataset_state: DatasetStateController,
        metrics_state: MetricsPipelineController,
        *,
        background_reference_label_resolver: Callable[[str], str],
    ) -> None:
        self._dataset_state = dataset_state
        self._metrics_state = metrics_state
        self._background_reference_label_resolver = (
            background_reference_label_resolver
        )

    def build_context(
        self,
        *,
        mode: str,
        normalization_scale: float,
    ) -> AnalysisContext:
        """Build an analysis context from the current dataset and metric state."""
        metrics = self._metrics_state
        dataset = self._dataset_state
        means: np.ndarray | None = None
        stds: np.ndarray | None = None
        sems: np.ndarray | None = None
        if mode == "topk":
            means = metrics.avg_maxs
            stds = metrics.avg_maxs_std
            sems = metrics.avg_maxs_sem
        elif mode == "roi":
            means = metrics.roi_means
            stds = metrics.roi_stds
            sems = metrics.roi_sems

        normalize_intensity = bool(metrics.normalize_intensity_values)
        scale = float(normalization_scale)
        if not np.isfinite(scale) or scale <= 0.0:
            scale = 1.0

        records: list[AnalysisRecord] = []
        metadata_fields: set[str] = set()
        for row, path in enumerate(dataset.paths):
            metadata = dict(dataset.metadata_for_path(path))
            if metrics.maxs is not None and row < len(metrics.maxs):
                metadata["max_pixel"] = float(metrics.maxs[row])
            if metrics.min_non_zero is not None and row < len(metrics.min_non_zero):
                metadata["min_non_zero"] = float(metrics.min_non_zero[row])
            if metrics.sat_counts is not None and row < len(metrics.sat_counts):
                metadata["sat_count"] = float(metrics.sat_counts[row])
            if (
                metrics.dn_per_ms_values is not None
                and row < len(metrics.dn_per_ms_values)
            ):
                dn_per_ms = float(metrics.dn_per_ms_values[row])
                dn_per_ms_std = (
                    float(metrics.dn_per_ms_stds[row])
                    if metrics.dn_per_ms_stds is not None
                    and row < len(metrics.dn_per_ms_stds)
                    else float(np.nan)
                )
                dn_per_ms_sem = (
                    float(metrics.dn_per_ms_sems[row])
                    if metrics.dn_per_ms_sems is not None
                    and row < len(metrics.dn_per_ms_sems)
                    else float(np.nan)
                )
                if normalize_intensity and scale > 0.0:
                    dn_per_ms /= scale
                    dn_per_ms_std /= scale
                    dn_per_ms_sem /= scale
                metadata["dn_per_ms"] = dn_per_ms
                metadata["dn_per_ms_std"] = dn_per_ms_std
                metadata["dn_per_ms_sem"] = dn_per_ms_sem

            background_applied = bool(
                metrics.bg_applied_mask is not None
                and row < len(metrics.bg_applied_mask)
                and metrics.bg_applied_mask[row]
            )
            metadata["background_enabled"] = bool(metrics.background_config.enabled)
            metadata["background_applied"] = background_applied
            if background_applied:
                metadata["background_reference"] = (
                    self._background_reference_label_resolver(path)
                )
            elif metrics.background_config.enabled:
                metadata["background_reference"] = "raw_fallback"
            else:
                metadata["background_reference"] = "disabled"

            mean = (
                float(means[row])
                if means is not None and row < len(means)
                else float(np.nan)
            )
            std = (
                float(stds[row])
                if stds is not None and row < len(stds)
                else float(np.nan)
            )
            sem = (
                float(sems[row])
                if sems is not None and row < len(sems)
                else float(np.nan)
            )
            if normalize_intensity and scale > 0.0:
                mean /= scale
                std /= scale
                sem /= scale

            metadata_fields.update(metadata.keys())
            records.append(
                AnalysisRecord(
                    path=path,
                    metadata=metadata,
                    mean=mean,
                    std=std,
                    sem=sem,
                )
            )

        return AnalysisContext(
            mode=mode,
            records=tuple(records),
            metadata_fields=tuple(sorted(metadata_fields)),
            normalization_enabled=normalize_intensity,
            normalization_scale=scale,
        )
