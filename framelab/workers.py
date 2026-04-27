"""Background workers for metric computation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from fnmatch import fnmatch
import os
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from .background import (
    BackgroundConfig,
    BackgroundLibrary,
    apply_background,
    select_reference,
    validate_reference_shape,
)
from .image_io import is_supported_image, read_2d_image, source_kind_for_path
from .metadata import extract_path_metadata
from .metrics_cache import (
    FileMetricIdentity,
    MetricCacheWrite,
    MetricsCache,
    STATIC_METRIC_KIND,
    static_metric_signature_hash,
)
from .metric_reducers import (
    compute_min_non_zero_and_max,
    compute_topk_stats_inplace,
    count_at_or_above_threshold,
)
from .metrics_state import DynamicStatsResult, MetricFamily, RoiApplyResult
from .processing_failures import (
    ProcessingFailure,
    failure_reason_from_exception,
    make_processing_failure,
)
from .native import backend as native_backend
from .raw_decode import (
    RawDecodeResolverContext,
    build_image_metric_identity,
    resolve_raw_decode_spec,
)
from .roi_utils import normalize_roi_rect_like_numpy


class AnalysisPreparationWorker(QObject):
    """Background worker for plugin-owned immutable preparation."""

    finished = Signal(int, str, object)
    failed = Signal(int, str, str)

    def __init__(
        self,
        *,
        job_id: int,
        plugin_id: str,
        prepare: Callable[[], Any],
    ) -> None:
        super().__init__()
        self._job_id = int(job_id)
        self._plugin_id = str(plugin_id)
        self._prepare = prepare

    def run(self) -> None:
        """Run plugin preparation and emit the prepared payload."""

        try:
            result = self._prepare()
        except Exception as exc:
            self.failed.emit(self._job_id, self._plugin_id, str(exc))
            return
        self.finished.emit(self._job_id, self._plugin_id, result)


@dataclass(frozen=True, slots=True)
class DatasetLoadBatch:
    """One ordered batch of static scan rows emitted by the dataset loader."""

    job_id: int
    paths: tuple[str, ...]
    min_non_zero: np.ndarray
    max_pixels: np.ndarray
    metadata_by_path: dict[str, dict[str, object]]
    failures: tuple[ProcessingFailure, ...] = ()
    processed: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class DatasetLoadProgress:
    """Progress update emitted while discovering and scanning a dataset."""

    job_id: int
    phase: str
    processed: int
    total: int
    message: str


@dataclass(frozen=True, slots=True)
class DatasetLoadSummary:
    """Terminal summary for one dataset load job."""

    job_id: int
    dataset_root: str
    loaded_count: int
    total_candidates: int
    loaded_paths: tuple[str, ...] = ()
    min_non_zero: np.ndarray | None = None
    max_pixels: np.ndarray | None = None
    metadata_by_path: dict[str, dict[str, object]] = field(default_factory=dict)
    failures: tuple[ProcessingFailure, ...] = ()
    skipped_unreadable: int = 0
    pruned_dirs: int = 0
    skipped_files: int = 0
    no_files: bool = False
    was_cancelled: bool = False
    failed: bool = False
    failure_message: str = ""


def _skip_match(
    pattern: str,
    *,
    name: str,
    rel_path: str,
    abs_path: str,
) -> bool:
    """Return whether one configured skip pattern matches the entry."""

    token = pattern.strip().lower()
    if not token:
        return False

    entry_name = name.lower()
    rel = rel_path.lower().replace("\\", "/")
    absolute = abs_path.lower().replace("\\", "/")
    if "/" in token:
        return fnmatch(rel, token) or fnmatch(absolute, token)
    return fnmatch(entry_name, token) or fnmatch(rel, token)


def _is_path_skipped(
    patterns: tuple[str, ...],
    *,
    name: str,
    rel_path: str,
    abs_path: str,
) -> bool:
    """Return whether any configured skip pattern matches the entry."""

    return any(
        _skip_match(
            pattern,
            name=name,
            rel_path=rel_path,
            abs_path=abs_path,
        )
        for pattern in patterns
    )


def _find_supported_images(
    folder: Path,
    *,
    skip_patterns: tuple[str, ...] = (),
) -> tuple[list[Path], int, int]:
    """Recursively discover supported image files under one folder."""

    found: list[Path] = []
    root = folder.resolve()
    pruned_dirs = 0
    skipped_files = 0

    for current_root, dir_names, file_names in os.walk(root, topdown=True):
        current_path = Path(current_root)
        relative_root = current_path.relative_to(root)
        kept_dirs: list[str] = []
        for dirname in dir_names:
            candidate_path = current_path / dirname
            rel_path = (relative_root / dirname).as_posix()
            if _is_path_skipped(
                skip_patterns,
                name=dirname,
                rel_path=rel_path,
                abs_path=str(candidate_path),
            ):
                pruned_dirs += 1
                continue
            kept_dirs.append(dirname)
        dir_names[:] = kept_dirs

        for filename in file_names:
            candidate = current_path / filename
            if not is_supported_image(candidate):
                continue
            rel_file_path = (relative_root / filename).as_posix()
            if _is_path_skipped(
                skip_patterns,
                name=filename,
                rel_path=rel_file_path,
                abs_path=str(candidate),
            ):
                skipped_files += 1
                continue
            found.append(candidate)

    return (sorted(found), pruned_dirs, skipped_files)


def dataset_scan_worker_count(
    worker_count: int | None = None,
    *,
    cpu_count: int | None = None,
) -> int:
    """Return the effective worker count for large image scans."""

    return dataset_scan_worker_count_for_override(
        worker_count,
        cpu_count=cpu_count,
    )


def _normalize_scan_worker_count_override(worker_count: int | None) -> int | None:
    """Normalize persisted/manual scan-worker overrides."""

    if worker_count is None:
        return None
    try:
        resolved = int(worker_count)
    except (TypeError, ValueError):
        return None
    if resolved <= 0:
        return None
    return resolved


def auto_dataset_scan_worker_count(*, cpu_count: int | None = None) -> int:
    """Return the auto-detected worker count based on available CPU cores."""

    cpu = max(1, int(cpu_count or os.cpu_count() or 1))
    if cpu <= 2:
        return 1
    if cpu <= 4:
        return 2
    return min(8, max(2, (cpu + 1) // 2))


def dataset_scan_worker_count_for_override(
    worker_count: int | None,
    *,
    cpu_count: int | None = None,
) -> int:
    """Resolve a manual-or-auto dataset scan worker count."""

    normalized = _normalize_scan_worker_count_override(worker_count)
    if normalized is not None:
        return normalized
    return auto_dataset_scan_worker_count(cpu_count=cpu_count)


def dataset_scan_chunk_size(total_files: int) -> int:
    """Return static-scan chunk size for one dataset size."""

    if total_files <= 64:
        return 16
    if total_files <= 256:
        return 32
    return 64


def scan_single_static_image(
    path: Path | str,
    *,
    raw_resolver_context: RawDecodeResolverContext | None = None,
) -> tuple[tuple[str, int, int] | None, tuple[ProcessingFailure, ...]]:
    """Read one image and compute quick static metrics."""

    source_path = Path(path)
    source_kind = source_kind_for_path(source_path)
    try:
        if source_kind == "raw":
            spec = resolve_raw_decode_spec(
                source_path,
                context=raw_resolver_context,
            )
            min_non_zero, max_pixel = native_backend.compute_raw_static_metrics(
                source_path,
                spec=spec,
            )
        else:
            image = read_2d_image(
                source_path,
                raw_spec_resolver=resolve_raw_decode_spec,
                raw_resolver_context=raw_resolver_context,
            )
            min_non_zero, max_pixel = native_backend.compute_static_metrics(
                image,
                source_kind=source_kind,
            )
    except Exception as exc:
        return (
            None,
            (
                make_processing_failure(
                    stage="scan",
                    path=source_path,
                    reason=failure_reason_from_exception(exc),
                ),
            ),
        )

    return ((str(source_path), min_non_zero, max_pixel), ())


@dataclass(frozen=True, slots=True)
class MetricComputeRequest:
    """Explicit targeted metric-compute request for one worker run."""

    job_id: int
    paths: tuple[str, ...]
    source_indices: tuple[int, ...]
    result_length: int
    requested_families: tuple[MetricFamily, ...]
    threshold_value: float
    avg_count_value: int
    background_config: BackgroundConfig | None = None
    background_library: BackgroundLibrary | None = None
    path_metadata: dict[str, dict[str, object]] = field(default_factory=dict)
    raw_resolver_context: RawDecodeResolverContext | None = None
    family_signatures: dict[str, str] = field(default_factory=dict)
    existing_sat_counts: np.ndarray | None = None
    existing_avg_topk: np.ndarray | None = None
    existing_avg_topk_std: np.ndarray | None = None
    existing_avg_topk_sem: np.ndarray | None = None
    existing_max_pixels: np.ndarray | None = None
    existing_min_non_zero: np.ndarray | None = None
    existing_bg_applied_mask: np.ndarray | None = None


def _normalize_metric_families(
    families: tuple[MetricFamily | str, ...] | list[MetricFamily | str] | None,
) -> tuple[MetricFamily, ...]:
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


def _existing_or_default(
    values: np.ndarray | None,
    *,
    length: int,
    dtype: np.dtype,
    fill_value: object,
) -> np.ndarray:
    if values is not None and len(values) == length:
        return np.asarray(values, dtype=dtype).copy()
    result = np.empty(length, dtype=dtype)
    result.fill(fill_value)
    return result


class DynamicStatsWorker(QObject):
    """Background worker that computes requested metric families only."""

    finished = Signal(object)
    failed = Signal(int, str)

    def __init__(
        self,
        *,
        request: MetricComputeRequest | None = None,
        job_id: int,
        paths: list[str],
        source_indices: list[int] | None = None,
        result_length: int | None = None,
        threshold_value: float,
        mode: str,
        avg_count_value: int,
        update_kind: str = "full",
        requested_families: tuple[MetricFamily | str, ...] | None = None,
        family_signatures: dict[str, str] | None = None,
        background_config: Optional[BackgroundConfig] = None,
        background_library: Optional[BackgroundLibrary] = None,
        path_metadata: Optional[dict[str, dict[str, object]]] = None,
        raw_resolver_context: RawDecodeResolverContext | None = None,
        existing_sat_counts: Optional[np.ndarray] = None,
        existing_avg_topk: Optional[np.ndarray] = None,
        existing_avg_topk_std: Optional[np.ndarray] = None,
        existing_avg_topk_sem: Optional[np.ndarray] = None,
        existing_max_pixels: Optional[np.ndarray] = None,
        existing_min_non_zero: Optional[np.ndarray] = None,
        existing_bg_applied_mask: Optional[np.ndarray] = None,
    ) -> None:
        super().__init__()
        if request is None:
            source_index_tuple = tuple(source_indices or range(len(paths)))
            result_len = (
                int(result_length)
                if result_length is not None
                else len(source_index_tuple)
            )
            if requested_families is None:
                if update_kind == "threshold_only":
                    requested_families = (MetricFamily.SATURATION,)
                elif mode == "topk":
                    requested_families = (
                        MetricFamily.SATURATION,
                        MetricFamily.TOPK,
                        MetricFamily.BACKGROUND_APPLIED,
                    )
                else:
                    requested_families = (
                        MetricFamily.SATURATION,
                        MetricFamily.BACKGROUND_APPLIED,
                    )
            request = MetricComputeRequest(
                job_id=job_id,
                paths=tuple(paths),
                source_indices=source_index_tuple,
                result_length=result_len,
                requested_families=_normalize_metric_families(requested_families),
                threshold_value=float(threshold_value),
                avg_count_value=int(avg_count_value),
                background_config=background_config,
                background_library=background_library,
                path_metadata=dict(path_metadata or {}),
                raw_resolver_context=raw_resolver_context,
                family_signatures=dict(family_signatures or {}),
                existing_sat_counts=existing_sat_counts,
                existing_avg_topk=existing_avg_topk,
                existing_avg_topk_std=existing_avg_topk_std,
                existing_avg_topk_sem=existing_avg_topk_sem,
                existing_max_pixels=existing_max_pixels,
                existing_min_non_zero=existing_min_non_zero,
                existing_bg_applied_mask=existing_bg_applied_mask,
            )
        self._request = request
        self._job_id = int(request.job_id)
        self._paths = list(request.paths)
        self._source_indices = list(request.source_indices)
        self._result_length = int(request.result_length)
        self._requested_families = tuple(request.requested_families)
        self._threshold_value = float(request.threshold_value)
        self._avg_count_value = int(request.avg_count_value)
        self._background_config = request.background_config
        self._background_library = request.background_library
        self._path_metadata = request.path_metadata
        self._raw_resolver_context = request.raw_resolver_context

    @classmethod
    def from_request(cls, request: MetricComputeRequest) -> DynamicStatsWorker:
        """Construct a worker from an explicit request payload."""

        return cls(
            request=request,
            job_id=request.job_id,
            paths=list(request.paths),
            threshold_value=request.threshold_value,
            mode="topk" if MetricFamily.TOPK in request.requested_families else "none",
            avg_count_value=request.avg_count_value,
        )

    def _reference_for_path(self, path: str) -> Optional[np.ndarray]:
        config = self._background_config
        library = self._background_library
        if config is None or library is None:
            return None
        if not config.enabled or not library.has_any_reference():
            return None

        metadata = self._path_metadata.get(path, {})
        exposure_ms = metadata.get("exposure_ms")
        return select_reference(
            exposure_ms,
            library,
            config.exposure_policy,
        )

    def _metric_background(
        self,
        path: str,
        image: np.ndarray,
    ) -> tuple[np.ndarray | None, bool]:
        reference = self._reference_for_path(path)
        if reference is None:
            return (None, False)
        if not validate_reference_shape(image.shape, reference.shape):
            return (None, False)
        return (reference, True)

    def _metric_background_for_shape(
        self,
        path: str,
        shape: tuple[int, int],
    ) -> tuple[np.ndarray | None, bool]:
        reference = self._reference_for_path(path)
        if reference is None:
            return (None, False)
        if not validate_reference_shape(shape, reference.shape):
            return (None, False)
        return (reference, True)

    def run(self) -> None:
        """Compute requested per-image metric families."""
        n = max(0, self._result_length)
        failures = []
        requested = set(self._requested_families)
        request = self._request

        sat_counts = (
            _existing_or_default(
                request.existing_sat_counts,
                length=n,
                dtype=np.int64,
                fill_value=0,
            )
            if MetricFamily.SATURATION in requested
            else None
        )
        max_pixels = (
            _existing_or_default(
                request.existing_max_pixels,
                length=n,
                dtype=np.int64,
                fill_value=0,
            )
            if MetricFamily.BACKGROUND_APPLIED in requested
            else None
        )
        min_non_zero = (
            _existing_or_default(
                request.existing_min_non_zero,
                length=n,
                dtype=np.int64,
                fill_value=0,
            )
            if MetricFamily.BACKGROUND_APPLIED in requested
            else None
        )
        bg_applied_mask = (
            _existing_or_default(
                request.existing_bg_applied_mask,
                length=n,
                dtype=bool,
                fill_value=False,
            )
            if MetricFamily.BACKGROUND_APPLIED in requested
            else None
        )
        avg_topk = (
            _existing_or_default(
                request.existing_avg_topk,
                length=n,
                dtype=np.float64,
                fill_value=np.nan,
            )
            if MetricFamily.TOPK in requested
            else None
        )
        avg_topk_std = (
            _existing_or_default(
                request.existing_avg_topk_std,
                length=n,
                dtype=np.float64,
                fill_value=np.nan,
            )
            if MetricFamily.TOPK in requested
            else None
        )
        avg_topk_sem = (
            _existing_or_default(
                request.existing_avg_topk_sem,
                length=n,
                dtype=np.float64,
                fill_value=np.nan,
            )
            if MetricFamily.TOPK in requested
            else None
        )
        thread = QThread.currentThread()
        try:
            for source_index, path in zip(self._source_indices, self._paths):
                if thread.isInterruptionRequested():
                    return
                try:
                    img = read_2d_image(
                        path,
                        raw_spec_resolver=resolve_raw_decode_spec,
                        raw_resolver_context=self._raw_resolver_context,
                    )
                    background_img, bg_applied = self._metric_background(path, img)
                    clip_negative = (
                        True
                        if self._background_config is None
                        else self._background_config.clip_negative
                    )
                    metric_img = (
                        apply_background(img, background_img, clip_negative)
                        if background_img is not None
                        else img
                    )
                    if max_pixels is not None and min_non_zero is not None:
                        min_value, max_value = compute_min_non_zero_and_max(metric_img)
                        min_non_zero[source_index] = int(min_value)
                        max_pixels[source_index] = int(max_value)
                    if bg_applied_mask is not None:
                        bg_applied_mask[source_index] = bool(bg_applied)
                    if sat_counts is not None:
                        sat_count, _scratch = count_at_or_above_threshold(
                            metric_img,
                            self._threshold_value,
                        )
                        sat_counts[source_index] = int(sat_count)
                    if avg_topk is not None:
                        mean, std, sem = compute_topk_stats_inplace(
                            np.array(metric_img, copy=True, order="C"),
                            self._avg_count_value,
                        )
                        avg_topk[source_index] = float(mean)
                        if avg_topk_std is not None:
                            avg_topk_std[source_index] = float(std)
                        if avg_topk_sem is not None:
                            avg_topk_sem[source_index] = float(sem)
                except Exception as exc:
                    failures.append(
                        make_processing_failure(
                            stage="metrics",
                            path=path,
                            reason=(
                                "Metric computation failed: "
                                f"{failure_reason_from_exception(exc)}"
                            ),
                        ),
                    )
                    continue
        except Exception as exc:
            self.failed.emit(self._job_id, str(exc))
            return

        self.finished.emit(
            DynamicStatsResult(
                job_id=self._job_id,
                sat_counts=sat_counts,
                avg_topk=avg_topk,
                avg_topk_std=avg_topk_std,
                avg_topk_sem=avg_topk_sem,
                max_pixels=max_pixels,
                min_non_zero=min_non_zero,
                bg_applied_mask=bg_applied_mask,
                requested_families=tuple(self._requested_families),
                failures=tuple(failures),
            ),
        )


class RoiApplyWorker(QObject):
    """Background worker applying ROI statistics to all images."""

    progress = Signal(int, int)
    finished = Signal(object)
    cancelled = Signal(int)
    failed = Signal(int, str)

    def __init__(
        self,
        *,
        job_id: int,
        paths: list[str],
        source_indices: list[int] | None = None,
        result_length: int | None = None,
        roi_rect: tuple[int, int, int, int],
        background_config: Optional[BackgroundConfig] = None,
        background_library: Optional[BackgroundLibrary] = None,
        path_metadata: Optional[dict[str, dict[str, object]]] = None,
        raw_resolver_context: RawDecodeResolverContext | None = None,
        topk_count: int | None = None,
        requested_families: tuple[MetricFamily | str, ...] | None = None,
        existing_maxs: Optional[np.ndarray] = None,
        existing_sums: Optional[np.ndarray] = None,
        existing_means: Optional[np.ndarray] = None,
        existing_stds: Optional[np.ndarray] = None,
        existing_sems: Optional[np.ndarray] = None,
        existing_topk_means: Optional[np.ndarray] = None,
        existing_topk_stds: Optional[np.ndarray] = None,
        existing_topk_sems: Optional[np.ndarray] = None,
    ) -> None:
        super().__init__()
        self._job_id = job_id
        self._paths = paths
        self._source_indices = list(source_indices or range(len(paths)))
        self._result_length = (
            int(result_length)
            if result_length is not None
            else len(self._source_indices)
        )
        self._roi_rect = roi_rect
        self._background_config = background_config
        self._background_library = background_library
        self._path_metadata = path_metadata or {}
        self._raw_resolver_context = raw_resolver_context
        self._topk_count = None if topk_count is None else max(1, int(topk_count))
        self._requested_families = _normalize_metric_families(
            requested_families
            or (
                (MetricFamily.ROI, MetricFamily.ROI_TOPK)
                if self._topk_count is not None
                else (MetricFamily.ROI,)
            ),
        )
        self._existing_maxs = existing_maxs
        self._existing_sums = existing_sums
        self._existing_means = existing_means
        self._existing_stds = existing_stds
        self._existing_sems = existing_sems
        self._existing_topk_means = existing_topk_means
        self._existing_topk_stds = existing_topk_stds
        self._existing_topk_sems = existing_topk_sems

    def _reference_for_path(self, path: str) -> Optional[np.ndarray]:
        config = self._background_config
        library = self._background_library
        if config is None or library is None:
            return None
        if not config.enabled or not library.has_any_reference():
            return None

        metadata = self._path_metadata.get(path, {})
        exposure_ms = metadata.get("exposure_ms")
        return select_reference(
            exposure_ms,
            library,
            config.exposure_policy,
        )

    def _metric_background(
        self,
        path: str,
        image: np.ndarray,
    ) -> np.ndarray | None:
        reference = self._reference_for_path(path)
        if reference is None:
            return None
        if not validate_reference_shape(image.shape, reference.shape):
            return None
        return reference

    def run(self) -> None:
        """Compute ROI mean/std/stderr for each image."""
        n = max(0, self._result_length)
        maxs = (
            np.asarray(self._existing_maxs, dtype=np.float64).copy()
            if self._existing_maxs is not None and len(self._existing_maxs) == n
            else np.full(n, np.nan, dtype=np.float64)
        )
        sums = (
            np.asarray(self._existing_sums, dtype=np.float64).copy()
            if self._existing_sums is not None and len(self._existing_sums) == n
            else np.full(n, np.nan, dtype=np.float64)
        )
        means = (
            np.asarray(self._existing_means, dtype=np.float64).copy()
            if self._existing_means is not None and len(self._existing_means) == n
            else np.full(n, np.nan, dtype=np.float64)
        )
        stds = (
            np.asarray(self._existing_stds, dtype=np.float64).copy()
            if self._existing_stds is not None and len(self._existing_stds) == n
            else np.full(n, np.nan, dtype=np.float64)
        )
        sems = (
            np.asarray(self._existing_sems, dtype=np.float64).copy()
            if self._existing_sems is not None and len(self._existing_sems) == n
            else np.full(n, np.nan, dtype=np.float64)
        )
        topk_means = None
        topk_stds = None
        topk_sems = None
        if self._topk_count is not None:
            topk_means = (
                np.asarray(self._existing_topk_means, dtype=np.float64).copy()
                if self._existing_topk_means is not None
                and len(self._existing_topk_means) == n
                else np.full(n, np.nan, dtype=np.float64)
            )
            topk_stds = (
                np.asarray(self._existing_topk_stds, dtype=np.float64).copy()
                if self._existing_topk_stds is not None
                and len(self._existing_topk_stds) == n
                else np.full(n, np.nan, dtype=np.float64)
            )
            topk_sems = (
                np.asarray(self._existing_topk_sems, dtype=np.float64).copy()
                if self._existing_topk_sems is not None
                and len(self._existing_topk_sems) == n
                else np.full(n, np.nan, dtype=np.float64)
            )
        valid_count = int(np.count_nonzero(np.isfinite(means)))
        failures = []
        thread = QThread.currentThread()
        try:
            total = len(self._paths)
            for processed_index, (source_index, path) in enumerate(
                zip(self._source_indices, self._paths),
                start=1,
            ):
                if thread.isInterruptionRequested():
                    self.cancelled.emit(self._job_id)
                    return

                try:
                    img = read_2d_image(
                        path,
                        raw_spec_resolver=resolve_raw_decode_spec,
                        raw_resolver_context=self._raw_resolver_context,
                    )
                except Exception as exc:
                    failures.append(
                        make_processing_failure(
                            stage="roi",
                            path=path,
                            reason=failure_reason_from_exception(exc),
                        ),
                    )
                    self.progress.emit(processed_index, total)
                    continue

                try:
                    background_img = self._metric_background(path, img)
                    clip_negative = (
                        True
                        if self._background_config is None
                        else self._background_config.clip_negative
                    )
                    normalized_roi = normalize_roi_rect_like_numpy(
                        self._roi_rect,
                        img.shape,
                    )
                except Exception as exc:
                    failures.append(
                        make_processing_failure(
                            stage="roi",
                            path=path,
                            reason=(
                                "ROI preparation failed: "
                                f"{failure_reason_from_exception(exc)}"
                            ),
                        ),
                    )
                    self.progress.emit(processed_index, total)
                    continue
                try:
                    roi_result = native_backend.compute_roi_metrics_full(
                        img,
                        roi_rect=normalized_roi,
                        topk_count=self._topk_count,
                        background=background_img,
                        clip_negative=clip_negative,
                    )
                    maxs[source_index] = float(roi_result["roi_max"])
                    sums[source_index] = float(roi_result["roi_sum"])
                    means[source_index] = float(roi_result["roi_mean"])
                    stds[source_index] = float(roi_result["roi_std"])
                    sems[source_index] = float(roi_result["roi_sem"])
                    if topk_means is not None:
                        topk_means[source_index] = float(
                            roi_result["roi_topk_mean"],
                        )
                    if topk_stds is not None:
                        topk_stds[source_index] = float(
                            roi_result["roi_topk_std"],
                        )
                    if topk_sems is not None:
                        topk_sems[source_index] = float(
                            roi_result["roi_topk_sem"],
                        )
                except Exception as exc:
                    failures.append(
                        make_processing_failure(
                            stage="roi",
                            path=path,
                            reason=(
                                "ROI computation failed: "
                                f"{failure_reason_from_exception(exc)}"
                            ),
                        ),
                    )
                    self.progress.emit(processed_index, total)
                    continue
                if normalized_roi[0] < normalized_roi[2] and normalized_roi[1] < normalized_roi[3]:
                    valid_count += 1

                self.progress.emit(processed_index, total)
        except Exception as exc:
            self.failed.emit(self._job_id, str(exc))
            return

        self.finished.emit(
            RoiApplyResult(
                job_id=self._job_id,
                maxs=maxs,
                sums=sums,
                means=means,
                stds=stds,
                sems=sems,
                valid_count=valid_count,
                topk_means=topk_means,
                topk_stds=topk_stds,
                topk_sems=topk_sems,
                requested_families=tuple(self._requested_families),
                failures=tuple(failures),
            ),
        )


class DatasetLoadWorker(QObject):
    """Background worker that discovers files and emits static scan batches."""

    batch_ready = Signal(object)
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(int, str)

    def __init__(
        self,
        *,
        job_id: int,
        folder: str,
        skip_patterns: tuple[str, ...] = (),
        scan_worker_count_override: int | None = None,
        metadata_source: str = "json",
        metadata_boundary_root: str | None = None,
        scope_effective_metadata: dict[str, object] | None = None,
        raw_manual_overrides: dict[str, object] | None = None,
        cache_path: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        super().__init__()
        self._job_id = int(job_id)
        self._folder = str(folder)
        self._skip_patterns = tuple(
            str(pattern).strip()
            for pattern in skip_patterns
            if str(pattern).strip()
        )
        self._scan_worker_count_override = _normalize_scan_worker_count_override(
            scan_worker_count_override,
        )
        self._metadata_source = str(metadata_source or "path")
        self._metadata_boundary_root = (
            Path(metadata_boundary_root).expanduser().resolve()
            if metadata_boundary_root
            else None
        )
        self._scope_effective_metadata = dict(scope_effective_metadata or {})
        self._raw_manual_overrides = dict(raw_manual_overrides or {})
        self._cache_path = str(cache_path).strip() or None
        self._workspace_root = (
            Path(workspace_root).expanduser().resolve()
            if workspace_root
            else None
        )

    def _emit_progress(
        self,
        *,
        phase: str,
        processed: int,
        total: int,
        message: str,
    ) -> None:
        self.progress.emit(
            DatasetLoadProgress(
                job_id=self._job_id,
                phase=phase,
                processed=max(0, int(processed)),
                total=max(0, int(total)),
                message=str(message),
            ),
        )

    def _build_identity_map(
        self,
        paths: list[Path],
    ) -> dict[str, FileMetricIdentity]:
        dataset_root = Path(self._folder).expanduser().resolve()
        identities: dict[str, FileMetricIdentity] = {}
        for path in paths:
            try:
                identity = build_image_metric_identity(
                    path,
                    dataset_root=dataset_root,
                    workspace_root=self._workspace_root,
                    raw_resolver_context=self._raw_resolver_context(),
                )
            except Exception:
                continue
            identities[str(path.resolve())] = identity
        return identities

    def _raw_resolver_context(self) -> RawDecodeResolverContext:
        """Return the shared RAW spec resolution inputs for this load job."""

        return RawDecodeResolverContext(
            scope_metadata=self._scope_effective_metadata,
            manual_overrides=self._raw_manual_overrides,
            metadata_boundary_root=self._metadata_boundary_root,
        )

    def run(self) -> None:
        """Discover, statically scan, and emit dataset rows in ordered batches."""

        thread = QThread.currentThread()
        folder = Path(self._folder).expanduser().resolve()
        failures: list[ProcessingFailure] = []
        skipped_unreadable = 0
        loaded_count = 0
        all_loaded_paths: list[str] = []
        all_loaded_mins: list[int] = []
        all_loaded_maxs: list[int] = []
        all_loaded_metadata: dict[str, dict[str, object]] = {}
        raw_resolver_context = self._raw_resolver_context()

        try:
            self._emit_progress(
                phase="discover",
                processed=0,
                total=0,
                message="Discovering image files...",
            )
            files, pruned_dirs, skipped_files = _find_supported_images(
                folder,
                skip_patterns=self._skip_patterns,
            )
            if thread.isInterruptionRequested():
                self.finished.emit(
                    DatasetLoadSummary(
                        job_id=self._job_id,
                        dataset_root=str(folder),
                        loaded_count=0,
                        total_candidates=len(files),
                        pruned_dirs=pruned_dirs,
                        skipped_files=skipped_files,
                        was_cancelled=True,
                    ),
                )
                return

            if not files:
                self.finished.emit(
                    DatasetLoadSummary(
                        job_id=self._job_id,
                        dataset_root=str(folder),
                        loaded_count=0,
                        total_candidates=0,
                        pruned_dirs=pruned_dirs,
                        skipped_files=skipped_files,
                        no_files=True,
                    ),
                )
                return

            total_files = len(files)
            chunk_size = dataset_scan_chunk_size(total_files)
            max_workers = dataset_scan_worker_count(self._scan_worker_count_override)
            cache = MetricsCache(Path(self._cache_path)) if self._cache_path else None
            static_signature = static_metric_signature_hash()
            executor: ThreadPoolExecutor | None = None
            if max_workers > 1:
                executor = ThreadPoolExecutor(max_workers=max_workers)
            try:
                was_cancelled = False
                for start in range(0, total_files, chunk_size):
                    if thread.isInterruptionRequested():
                        was_cancelled = True
                        break

                    chunk = files[start:start + chunk_size]
                    identities = self._build_identity_map(chunk)
                    cached_payloads: dict[str, dict[str, object]] = {}
                    if cache is not None and identities:
                        cached_payloads = cache.fetch_entries(
                            identities.values(),
                            metric_kind=STATIC_METRIC_KIND,
                            signature_hash=static_signature,
                        )

                    computed_results: dict[
                        str,
                        tuple[tuple[str, int, int] | None, tuple[ProcessingFailure, ...]],
                    ] = {}
                    uncached_paths = [
                        path
                        for path in chunk
                        if str(path.resolve()) not in cached_payloads
                    ]
                    chunk_was_cancelled = False
                    if uncached_paths:
                        if executor is None:
                            for path in uncached_paths:
                                if thread.isInterruptionRequested():
                                    chunk_was_cancelled = True
                                    break
                                computed_results[str(path.resolve())] = scan_single_static_image(
                                    path,
                                    raw_resolver_context=raw_resolver_context,
                                )
                        else:
                            future_to_path = {
                                executor.submit(
                                    scan_single_static_image,
                                    path,
                                    raw_resolver_context=raw_resolver_context,
                                ): path
                                for path in uncached_paths
                            }
                            for future in as_completed(future_to_path):
                                if thread.isInterruptionRequested():
                                    chunk_was_cancelled = True
                                    for pending_future in future_to_path:
                                        if pending_future is not future:
                                            pending_future.cancel()
                                    break
                                path = future_to_path[future]
                                try:
                                    computed_results[str(path.resolve())] = future.result()
                                except Exception as exc:
                                    computed_results[str(path.resolve())] = (
                                        None,
                                        (
                                            make_processing_failure(
                                                stage="scan",
                                                path=path,
                                                reason=failure_reason_from_exception(exc),
                                            ),
                                        ),
                                    )
                    if chunk_was_cancelled or thread.isInterruptionRequested():
                        was_cancelled = True
                        break

                    batch_paths: list[str] = []
                    batch_mins: list[int] = []
                    batch_maxs: list[int] = []
                    batch_metadata: dict[str, dict[str, object]] = {}
                    cache_writes: list[MetricCacheWrite] = []
                    chunk_failures: list[ProcessingFailure] = []

                    for path in chunk:
                        resolved = str(path.resolve())
                        payload = cached_payloads.get(resolved)
                        if payload is not None:
                            min_non_zero = int(payload.get("min_non_zero", 0))
                            max_pixel = int(payload.get("max_pixel", 0))
                        else:
                            result, result_failures = computed_results.get(
                                resolved,
                                (None, ()),
                            )
                            chunk_failures.extend(result_failures)
                            if result is None:
                                skipped_unreadable += 1
                                continue
                            _path_str, min_non_zero, max_pixel = result
                            identity = identities.get(resolved)
                            if identity is not None and cache is not None:
                                cache_writes.append(
                                    MetricCacheWrite(
                                        identity=identity,
                                        payload={
                                            "min_non_zero": int(min_non_zero),
                                            "max_pixel": int(max_pixel),
                                        },
                                    ),
                                )

                        metadata = extract_path_metadata(
                            resolved,
                            metadata_source=self._metadata_source,
                            metadata_boundary_root=self._metadata_boundary_root,
                        )
                        batch_paths.append(resolved)
                        batch_mins.append(int(min_non_zero))
                        batch_maxs.append(int(max_pixel))
                        batch_metadata[resolved] = metadata

                    failures.extend(chunk_failures)
                    if cache is not None and cache_writes:
                        cache.store_entries(
                            cache_writes,
                            metric_kind=STATIC_METRIC_KIND,
                            signature_hash=static_signature,
                        )

                    loaded_count += len(batch_paths)
                    if batch_paths:
                        all_loaded_paths.extend(batch_paths)
                        all_loaded_mins.extend(int(value) for value in batch_mins)
                        all_loaded_maxs.extend(int(value) for value in batch_maxs)
                        all_loaded_metadata.update(batch_metadata)
                    if batch_paths:
                        self.batch_ready.emit(
                            DatasetLoadBatch(
                                job_id=self._job_id,
                                paths=tuple(batch_paths),
                                min_non_zero=np.asarray(batch_mins, dtype=np.int64),
                                max_pixels=np.asarray(batch_maxs, dtype=np.int64),
                                metadata_by_path=batch_metadata,
                                failures=tuple(chunk_failures),
                                processed=min(start + len(chunk), total_files),
                                total=total_files,
                            ),
                        )
                    self._emit_progress(
                        phase="scan",
                        processed=min(start + len(chunk), total_files),
                        total=total_files,
                        message=(
                            f"Loading images... "
                            f"{min(start + len(chunk), total_files)}/{total_files}"
                        ),
                    )
                if was_cancelled:
                    self.finished.emit(
                        DatasetLoadSummary(
                            job_id=self._job_id,
                            dataset_root=str(folder),
                            loaded_count=loaded_count,
                            total_candidates=total_files,
                            loaded_paths=tuple(all_loaded_paths),
                            min_non_zero=np.asarray(
                                all_loaded_mins,
                                dtype=np.int64,
                            ),
                            max_pixels=np.asarray(
                                all_loaded_maxs,
                                dtype=np.int64,
                            ),
                            metadata_by_path=dict(all_loaded_metadata),
                            failures=tuple(failures),
                            skipped_unreadable=skipped_unreadable,
                            pruned_dirs=pruned_dirs,
                            skipped_files=skipped_files,
                            was_cancelled=True,
                        ),
                    )
                    return
            finally:
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)

            self.finished.emit(
                DatasetLoadSummary(
                    job_id=self._job_id,
                    dataset_root=str(folder),
                    loaded_count=loaded_count,
                    total_candidates=total_files,
                    loaded_paths=tuple(all_loaded_paths),
                    min_non_zero=np.asarray(
                        all_loaded_mins,
                        dtype=np.int64,
                    ),
                    max_pixels=np.asarray(
                        all_loaded_maxs,
                        dtype=np.int64,
                    ),
                    metadata_by_path=dict(all_loaded_metadata),
                    failures=tuple(failures),
                    skipped_unreadable=skipped_unreadable,
                    pruned_dirs=pruned_dirs,
                    skipped_files=skipped_files,
                ),
            )
        except Exception as exc:
            self.failed.emit(self._job_id, str(exc))
