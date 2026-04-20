"""Explicit analysis-context preparation outside the UI layer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from .dataset_state import DatasetStateController, _normalize_path_metadata_payload
from .metrics_state import MetricsPipelineController
from .plugins.analysis import AnalysisContext, AnalysisRecord, AnalysisScopeNode


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
        elif mode == "roi_topk":
            means = metrics.roi_topk_means
            stds = metrics.roi_topk_stds
            sems = metrics.roi_topk_sems

        normalize_intensity = bool(metrics.normalize_intensity_values)
        scale = float(normalization_scale)
        if not np.isfinite(scale) or scale <= 0.0:
            scale = 1.0

        records: list[AnalysisRecord] = []
        metadata_fields: set[str] = set()
        for row, path in enumerate(dataset.paths):
            metadata = _normalize_path_metadata_payload(
                dataset.metadata_for_path(path),
            )
            if metrics.maxs is not None and row < len(metrics.maxs):
                metadata["max_pixel"] = float(metrics.maxs[row])
            if metrics.min_non_zero is not None and row < len(metrics.min_non_zero):
                metadata["min_non_zero"] = float(metrics.min_non_zero[row])
            if metrics.sat_counts is not None and row < len(metrics.sat_counts):
                metadata["sat_count"] = float(metrics.sat_counts[row])
            if metrics.roi_topk_means is not None and row < len(metrics.roi_topk_means):
                roi_topk_mean = float(metrics.roi_topk_means[row])
                if np.isfinite(roi_topk_mean):
                    metadata["roi_topk_mean"] = roi_topk_mean
            if (
                metrics.roi_topk_stds is not None
                and row < len(metrics.roi_topk_stds)
            ):
                roi_topk_std = float(metrics.roi_topk_stds[row])
                if np.isfinite(roi_topk_std):
                    metadata["roi_topk_std"] = roi_topk_std
            if (
                metrics.roi_topk_sems is not None
                and row < len(metrics.roi_topk_sems)
            ):
                roi_topk_sem = float(metrics.roi_topk_sems[row])
                if np.isfinite(roi_topk_sem):
                    metadata["roi_topk_sem"] = roi_topk_sem
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
            workflow_profile_id=dataset.scope_snapshot.workflow_profile_id,
            workflow_anchor_type_id=dataset.scope_snapshot.workflow_anchor_type_id,
            workflow_anchor_label=dataset.scope_snapshot.workflow_anchor_label,
            workflow_anchor_path=(
                str(dataset.scope_snapshot.workflow_anchor_path)
                if dataset.scope_snapshot.workflow_anchor_path is not None
                else None
            ),
            workflow_is_partial=dataset.scope_snapshot.workflow_is_partial,
            active_node_id=dataset.scope_snapshot.active_node_id,
            active_node_type=dataset.scope_snapshot.active_node_type,
            active_node_path=(
                str(dataset.scope_snapshot.active_node_path)
                if dataset.scope_snapshot.active_node_path is not None
                else None
            ),
            active_scope_kind=dataset.scope_snapshot.kind,
            active_scope_label=dataset.scope_snapshot.label,
            dataset_scope_root=(
                str(dataset.scope_snapshot.root)
                if dataset.scope_snapshot.root is not None
                else None
            ),
            dataset_scope_source=dataset.scope_snapshot.source,
            effective_metadata=dict(dataset.scope_effective_metadata),
            metadata_sources=dict(dataset.scope_metadata_sources),
            ancestor_chain=tuple(
                AnalysisScopeNode(
                    node_id=node.node_id,
                    type_id=node.type_id,
                    display_name=node.display_name,
                    folder_path=str(Path(node.folder_path)),
                )
                for node in dataset.scope_snapshot.ancestor_chain
            ),
        )
