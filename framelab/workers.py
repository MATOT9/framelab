"""Background workers for metric computation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from fnmatch import fnmatch
import os
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from .background import (
    BackgroundConfig,
    BackgroundLibrary,
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
from .metrics_state import DynamicStatsResult, RoiApplyResult
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


class DynamicStatsWorker(QObject):
    """Background worker that computes threshold and top-k statistics."""

    finished = Signal(object)
    failed = Signal(int, str)

    def __init__(
        self,
        *,
        job_id: int,
        paths: list[str],
        source_indices: list[int] | None = None,
        result_length: int | None = None,
        threshold_value: float,
        mode: str,
        avg_count_value: int,
        update_kind: str = "full",
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
        self._job_id = job_id
        self._paths = paths
        self._source_indices = list(source_indices or range(len(paths)))
        self._result_length = (
            int(result_length)
            if result_length is not None
            else len(self._source_indices)
        )
        self._threshold_value = threshold_value
        self._mode = mode
        self._avg_count_value = avg_count_value
        self._update_kind = (
            update_kind if update_kind in {"full", "threshold_only"} else "full"
        )
        self._background_config = background_config
        self._background_library = background_library
        self._path_metadata = path_metadata or {}
        self._raw_resolver_context = raw_resolver_context
        self._existing_sat_counts = existing_sat_counts
        self._existing_avg_topk = existing_avg_topk
        self._existing_avg_topk_std = existing_avg_topk_std
        self._existing_avg_topk_sem = existing_avg_topk_sem
        self._existing_max_pixels = existing_max_pixels
        self._existing_min_non_zero = existing_min_non_zero
        self._existing_bg_applied_mask = existing_bg_applied_mask

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
        """Compute dynamic per-image stats (threshold/top-k/static)."""
        n = max(0, self._result_length)
        failures = []
        threshold_only = self._update_kind == "threshold_only"

        existing_sat_counts = (
            np.asarray(self._existing_sat_counts, dtype=np.int64)
            if self._existing_sat_counts is not None
            else None
        )
        existing_max_pixels = (
            np.asarray(self._existing_max_pixels, dtype=np.int64)
            if self._existing_max_pixels is not None
            else None
        )
        existing_min_non_zero = (
            np.asarray(self._existing_min_non_zero, dtype=np.int64)
            if self._existing_min_non_zero is not None
            else None
        )
        existing_bg_applied_mask = (
            np.asarray(self._existing_bg_applied_mask, dtype=bool)
            if self._existing_bg_applied_mask is not None
            else None
        )
        existing_avg_topk = (
            np.asarray(self._existing_avg_topk, dtype=np.float64)
            if self._existing_avg_topk is not None
            else None
        )
        existing_avg_topk_std = (
            np.asarray(self._existing_avg_topk_std, dtype=np.float64)
            if self._existing_avg_topk_std is not None
            else None
        )
        existing_avg_topk_sem = (
            np.asarray(self._existing_avg_topk_sem, dtype=np.float64)
            if self._existing_avg_topk_sem is not None
            else None
        )

        if threshold_only:
            static_ready = (
                existing_max_pixels is not None
                and len(existing_max_pixels) == n
                and existing_min_non_zero is not None
                and len(existing_min_non_zero) == n
                and existing_bg_applied_mask is not None
                and len(existing_bg_applied_mask) == n
            )
            topk_ready = (
                self._mode != "topk"
                or (
                    existing_avg_topk is not None
                    and len(existing_avg_topk) == n
                    and existing_avg_topk_std is not None
                    and len(existing_avg_topk_std) == n
                    and existing_avg_topk_sem is not None
                    and len(existing_avg_topk_sem) == n
                )
            )
            threshold_only = static_ready and topk_ready

        sat_counts = (
            existing_sat_counts.copy()
            if existing_sat_counts is not None and len(existing_sat_counts) == n
            else np.zeros(n, dtype=np.int64)
        )
        max_pixels = (
            existing_max_pixels.copy()
            if existing_max_pixels is not None and len(existing_max_pixels) == n
            else np.zeros(n, dtype=np.int64)
        )
        min_non_zero = (
            existing_min_non_zero.copy()
            if existing_min_non_zero is not None and len(existing_min_non_zero) == n
            else np.zeros(n, dtype=np.int64)
        )
        bg_applied_mask = (
            existing_bg_applied_mask.copy()
            if existing_bg_applied_mask is not None and len(existing_bg_applied_mask) == n
            else np.zeros(n, dtype=bool)
        )
        avg_topk = None
        avg_topk_std = None
        avg_topk_sem = None
        if self._mode == "topk":
            if existing_avg_topk is not None and len(existing_avg_topk) == n:
                avg_topk = existing_avg_topk.copy()
                avg_topk_std = (
                    existing_avg_topk_std.copy()
                    if existing_avg_topk_std is not None
                    and len(existing_avg_topk_std) == n
                    else np.full(n, np.nan, dtype=np.float64)
                )
                avg_topk_sem = (
                    existing_avg_topk_sem.copy()
                    if existing_avg_topk_sem is not None
                    and len(existing_avg_topk_sem) == n
                    else np.full(n, np.nan, dtype=np.float64)
                )
            else:
                avg_topk = np.full(n, np.nan, dtype=np.float64)
                avg_topk_std = np.full(n, np.nan, dtype=np.float64)
                avg_topk_sem = np.full(n, np.nan, dtype=np.float64)
        thread = QThread.currentThread()
        try:
            for source_index, path in zip(self._source_indices, self._paths):
                if thread.isInterruptionRequested():
                    return
                source_kind = source_kind_for_path(path)
                try:
                    clip_negative = (
                        True
                        if self._background_config is None
                        else self._background_config.clip_negative
                    )
                    if source_kind == "raw":
                        spec = resolve_raw_decode_spec(
                            path,
                            context=self._raw_resolver_context,
                        )
                        background_img, bg_applied = self._metric_background_for_shape(
                            path,
                            (spec.height, spec.width),
                        )
                        metric_result = native_backend.compute_raw_dynamic_metrics(
                            path,
                            spec=spec,
                            threshold_value=self._threshold_value,
                            mode="none" if threshold_only else self._mode,
                            avg_count_value=self._avg_count_value,
                            background=background_img,
                            clip_negative=clip_negative,
                        )
                    else:
                        img = read_2d_image(
                            path,
                            raw_spec_resolver=resolve_raw_decode_spec,
                            raw_resolver_context=self._raw_resolver_context,
                        )
                        background_img, bg_applied = self._metric_background(path, img)
                        metric_result = native_backend.compute_dynamic_metrics(
                            img,
                            threshold_value=self._threshold_value,
                            mode=self._mode,
                            avg_count_value=self._avg_count_value,
                            background=background_img,
                            clip_negative=clip_negative,
                            threshold_only=threshold_only,
                            source_kind=source_kind,
                        )
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
                if not threshold_only:
                    bg_applied_mask[source_index] = bool(bg_applied)
                    min_non_zero[source_index] = int(metric_result["min_non_zero"])
                    max_pixels[source_index] = int(metric_result["max_pixel"])
                sat_counts[source_index] = int(metric_result["sat_count"])

                if threshold_only or avg_topk is None:
                    continue
                avg_topk[source_index] = float(metric_result["avg_topk"])
                if avg_topk_std is not None:
                    avg_topk_std[source_index] = float(metric_result["avg_topk_std"])
                if avg_topk_sem is not None:
                    avg_topk_sem[source_index] = float(metric_result["avg_topk_sem"])
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
        existing_maxs: Optional[np.ndarray] = None,
        existing_means: Optional[np.ndarray] = None,
        existing_stds: Optional[np.ndarray] = None,
        existing_sems: Optional[np.ndarray] = None,
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
        self._existing_maxs = existing_maxs
        self._existing_means = existing_means
        self._existing_stds = existing_stds
        self._existing_sems = existing_sems

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
                    (
                        maxs[source_index],
                        means[source_index],
                        stds[source_index],
                        sems[source_index],
                    ) = native_backend.compute_roi_metrics(
                        img,
                        roi_rect=normalized_roi,
                        background=background_img,
                        clip_negative=clip_negative,
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
                means=means,
                stds=stds,
                sems=sems,
                valid_count=valid_count,
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
                for start in range(0, total_files, chunk_size):
                    if thread.isInterruptionRequested():
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
                    if uncached_paths:
                        if executor is None:
                            for path in uncached_paths:
                                computed_results[str(path.resolve())] = scan_single_static_image(
                                    path,
                                    raw_resolver_context=self._raw_resolver_context(),
                                )
                        else:
                            future_to_path = {
                                executor.submit(
                                    scan_single_static_image,
                                    path,
                                    raw_resolver_context=self._raw_resolver_context(),
                                ): path
                                for path in uncached_paths
                            }
                            for future in as_completed(future_to_path):
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
            finally:
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=False)

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
