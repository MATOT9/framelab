"""Background workers for metric computation."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from .background import (
    BackgroundConfig,
    BackgroundLibrary,
    apply_background,
    select_reference,
    validate_reference_shape,
)
from .image_io import read_2d_image
from .metrics_state import DynamicStatsResult, RoiApplyResult
from .processing_failures import (
    failure_reason_from_exception,
    make_processing_failure,
)


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
        self._existing_sat_counts = existing_sat_counts
        self._existing_avg_topk = existing_avg_topk
        self._existing_avg_topk_std = existing_avg_topk_std
        self._existing_avg_topk_sem = existing_avg_topk_sem
        self._existing_max_pixels = existing_max_pixels
        self._existing_min_non_zero = existing_min_non_zero
        self._existing_bg_applied_mask = existing_bg_applied_mask

    @staticmethod
    def _compute_min_non_zero_and_max(image: np.ndarray) -> tuple[int, int]:
        """Compute minimum non-zero and max pixel from metric image."""
        arr = np.asarray(image, dtype=np.float64)
        if arr.size == 0:
            return (0, 0)

        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return (0, 0)

        positive = finite[finite > 0.0]
        min_non_zero = (
            int(round(float(np.min(positive))))
            if positive.size > 0
            else 0
        )
        max_pixel = int(round(float(np.max(finite))))
        return (max(min_non_zero, 0), max(max_pixel, 0))

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

    def _metric_image(
        self,
        path: str,
        image: np.ndarray,
    ) -> tuple[np.ndarray, bool]:
        config = self._background_config
        reference = self._reference_for_path(path)
        if reference is None:
            return (image, False)
        if not validate_reference_shape(image.shape, reference.shape):
            return (image, False)
        clip_negative = True if config is None else config.clip_negative
        return (apply_background(image, reference, clip_negative), True)

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
                try:
                    img = read_2d_image(path)
                except Exception as exc:
                    failures.append(
                        make_processing_failure(
                            stage="metrics",
                            path=path,
                            reason=failure_reason_from_exception(exc),
                        ),
                    )
                    continue

                try:
                    metric_img, bg_applied = self._metric_image(path, img)
                except Exception as exc:
                    failures.append(
                        make_processing_failure(
                            stage="metrics",
                            path=path,
                            reason=(
                                "Background application failed: "
                                f"{failure_reason_from_exception(exc)}"
                            ),
                        ),
                    )
                    continue
                if not threshold_only:
                    bg_applied_mask[source_index] = bool(bg_applied)
                    min_nz, max_px = self._compute_min_non_zero_and_max(metric_img)
                    min_non_zero[source_index] = min_nz
                    max_pixels[source_index] = max_px
                sat_counts[source_index] = int(
                    np.count_nonzero(metric_img >= self._threshold_value),
                )

                if threshold_only or avg_topk is None:
                    continue
                flat = np.ravel(metric_img)
                if flat.size == 0:
                    continue
                k = min(self._avg_count_value, flat.size)
                split = flat.size - k
                top_k = np.partition(flat, split)[split:]
                if top_k.size == 0:
                    continue
                top_k_std = float(top_k.std())
                avg_topk[source_index] = float(top_k.mean())
                if avg_topk_std is not None:
                    avg_topk_std[source_index] = top_k_std
                if avg_topk_sem is not None:
                    avg_topk_sem[source_index] = top_k_std / math.sqrt(top_k.size)
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

    def _metric_image(self, path: str, image: np.ndarray) -> np.ndarray:
        reference = self._reference_for_path(path)
        config = self._background_config
        if reference is None:
            return image
        if not validate_reference_shape(image.shape, reference.shape):
            return image
        clip_negative = True if config is None else config.clip_negative
        return apply_background(image, reference, clip_negative)

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
        x0, y0, x1, y1 = self._roi_rect

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
                    img = read_2d_image(path)
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
                    metric_img = self._metric_image(path, img)
                except Exception as exc:
                    failures.append(
                        make_processing_failure(
                            stage="roi",
                            path=path,
                            reason=(
                                "Background application failed: "
                                f"{failure_reason_from_exception(exc)}"
                            ),
                        ),
                    )
                    self.progress.emit(processed_index, total)
                    continue
                roi = metric_img[y0:y1, x0:x1]
                if roi.size > 0:
                    roi_f = np.asarray(roi, dtype=np.float64)
                    maxs[source_index] = float(np.max(roi_f))
                    means[source_index] = float(roi_f.mean())
                    stds[source_index] = float(roi_f.std())
                    sems[source_index] = float(
                        stds[source_index] / math.sqrt(roi.size),
                    )
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
