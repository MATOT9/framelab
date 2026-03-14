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
        threshold_value: float,
        mode: str,
        avg_count_value: int,
        update_kind: str = "full",
        background_config: Optional[BackgroundConfig] = None,
        background_library: Optional[BackgroundLibrary] = None,
        path_metadata: Optional[dict[str, dict[str, object]]] = None,
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
        self._threshold_value = threshold_value
        self._mode = mode
        self._avg_count_value = avg_count_value
        self._update_kind = (
            update_kind if update_kind in {"full", "threshold_only"} else "full"
        )
        self._background_config = background_config
        self._background_library = background_library
        self._path_metadata = path_metadata or {}
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
        n = len(self._paths)
        sat_counts = np.zeros(n, dtype=np.int64)
        failures = []
        threshold_only = self._update_kind == "threshold_only"

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

        max_pixels = (
            existing_max_pixels.copy()
            if threshold_only and existing_max_pixels is not None
            else np.zeros(n, dtype=np.int64)
        )
        min_non_zero = (
            existing_min_non_zero.copy()
            if threshold_only and existing_min_non_zero is not None
            else np.zeros(n, dtype=np.int64)
        )
        bg_applied_mask = (
            existing_bg_applied_mask.copy()
            if threshold_only and existing_bg_applied_mask is not None
            else np.zeros(n, dtype=bool)
        )
        avg_topk = None
        avg_topk_std = None
        avg_topk_sem = None
        if self._mode == "topk":
            if threshold_only and existing_avg_topk is not None:
                avg_topk = existing_avg_topk.copy()
                avg_topk_std = existing_avg_topk_std.copy()
                avg_topk_sem = existing_avg_topk_sem.copy()
            else:
                avg_topk = np.full(n, np.nan, dtype=np.float64)
                avg_topk_std = np.full(n, np.nan, dtype=np.float64)
                avg_topk_sem = np.full(n, np.nan, dtype=np.float64)
        thread = QThread.currentThread()
        try:
            for i, path in enumerate(self._paths):
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
                    bg_applied_mask[i] = bool(bg_applied)
                    min_nz, max_px = self._compute_min_non_zero_and_max(metric_img)
                    min_non_zero[i] = min_nz
                    max_pixels[i] = max_px
                sat_counts[i] = int(
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
                avg_topk[i] = float(top_k.mean())
                if avg_topk_std is not None:
                    avg_topk_std[i] = top_k_std
                if avg_topk_sem is not None:
                    avg_topk_sem[i] = top_k_std / math.sqrt(top_k.size)
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
        roi_rect: tuple[int, int, int, int],
        background_config: Optional[BackgroundConfig] = None,
        background_library: Optional[BackgroundLibrary] = None,
        path_metadata: Optional[dict[str, dict[str, object]]] = None,
    ) -> None:
        super().__init__()
        self._job_id = job_id
        self._paths = paths
        self._roi_rect = roi_rect
        self._background_config = background_config
        self._background_library = background_library
        self._path_metadata = path_metadata or {}

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
        n = len(self._paths)
        means = np.full(n, np.nan, dtype=np.float64)
        stds = np.full(n, np.nan, dtype=np.float64)
        sems = np.full(n, np.nan, dtype=np.float64)
        valid_count = 0
        failures = []
        thread = QThread.currentThread()
        x0, y0, x1, y1 = self._roi_rect

        try:
            for i, path in enumerate(self._paths):
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
                    self.progress.emit(i + 1, n)
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
                    self.progress.emit(i + 1, n)
                    continue
                roi = metric_img[y0:y1, x0:x1]
                if roi.size > 0:
                    roi_f = np.asarray(roi, dtype=np.float64)
                    means[i] = float(roi_f.mean())
                    stds[i] = float(roi_f.std())
                    sems[i] = float(stds[i] / math.sqrt(roi.size))
                    valid_count += 1

                self.progress.emit(i + 1, n)
        except Exception as exc:
            self.failed.emit(self._job_id, str(exc))
            return

        self.finished.emit(
            RoiApplyResult(
                job_id=self._job_id,
                means=means,
                stds=stds,
                sems=sems,
                valid_count=valid_count,
                failures=tuple(failures),
            ),
        )
