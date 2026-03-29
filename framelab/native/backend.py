"""App-shaped native backend hook surface.

This module is the stable Python-facing boundary for optional native metrics.
TIFF decoding remains on the Python side for now. When the extension is not
available, or a native metric call fails, the wrapper falls back to the
existing Python implementations while recording lightweight diagnostics.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

try:
    from . import _native  # type: ignore
except Exception as exc:  # pragma: no cover - extension may not exist yet.
    _native = None
    _native_import_error = exc
else:
    _native_import_error = None

import numpy as np

from ..background import apply_background, validate_reference_shape
from ..metric_reducers import (
    compute_min_non_zero_and_max,
    compute_roi_stats,
    compute_topk_stats_inplace,
    count_at_or_above_threshold,
)
from ..roi_utils import normalize_roi_rect_like_numpy


class NativeBackendUnavailable(RuntimeError):
    """Raised when the optional native extension is not available."""


_metrics_backend_lock = Lock()
_metrics_native_enabled = _native is not None
_active_metrics_backend = "native" if _native is not None else "python"
_last_native_fallback_reason = (
    None
    if _native is not None
    else (
        "Native extension unavailable"
        if _native_import_error is None
        else f"Native extension unavailable: {_native_import_error}"
    )
)
_pending_backend_status_notice: str | None = None
_native_backend_notice_emitted = False


def native_available() -> bool:
    """Return whether the optional native extension module imported."""

    return _native is not None


def active_metrics_backend() -> str:
    """Return the metrics backend currently used by the wrapper."""

    with _metrics_backend_lock:
        return _active_metrics_backend


def last_native_fallback_reason() -> str | None:
    """Return the most recent reason native metrics fell back to Python."""

    with _metrics_backend_lock:
        return _last_native_fallback_reason


def consume_backend_status_notice() -> str | None:
    """Return and clear a one-shot user-facing backend status notice."""

    global _pending_backend_status_notice
    with _metrics_backend_lock:
        notice = _pending_backend_status_notice
        _pending_backend_status_notice = None
        return notice


def require_native() -> Any:
    """Return the loaded extension module or raise a clear error."""

    if _native is None:
        raise NativeBackendUnavailable(
            "FrameLab native backend is not available. Build and import the "
            "extension module before using native metric entry points.",
        )
    return _native


def _record_native_success() -> None:
    global _active_metrics_backend, _pending_backend_status_notice
    global _native_backend_notice_emitted

    with _metrics_backend_lock:
        _active_metrics_backend = "native"
        if not _native_backend_notice_emitted:
            _pending_backend_status_notice = "Using native metrics backend"
            _native_backend_notice_emitted = True


def _disable_native_metrics(reason: str) -> None:
    global _metrics_native_enabled, _active_metrics_backend
    global _last_native_fallback_reason

    with _metrics_backend_lock:
        _metrics_native_enabled = False
        _active_metrics_backend = "python"
        _last_native_fallback_reason = str(reason).strip() or "Native metrics failed"


def _native_metrics_enabled_now() -> bool:
    with _metrics_backend_lock:
        return bool(_metrics_native_enabled and _native is not None)


def _coerce_image(image) -> np.ndarray:
    return np.asarray(image)


def _compatible_background(image: np.ndarray, background) -> np.ndarray | None:
    if background is None:
        return None
    background_arr = np.asarray(background)
    if not validate_reference_shape(image.shape, background_arr.shape):
        return None
    return background_arr


def _python_compute_static_metrics(image) -> tuple[int, int]:
    return compute_min_non_zero_and_max(_coerce_image(image))


def _python_compute_dynamic_metrics(
    image,
    *,
    threshold_value: float,
    mode: str,
    avg_count_value: int,
    background=None,
    clip_negative: bool = True,
    threshold_only: bool = False,
) -> dict[str, object]:
    image_arr = _coerce_image(image)
    if mode not in {"none", "topk"}:
        raise ValueError("mode must be 'none' or 'topk'")

    background_arr = _compatible_background(image_arr, background)
    metric_img = (
        apply_background(image_arr, background_arr, clip_negative)
        if background_arr is not None
        else image_arr
    )
    min_non_zero, max_pixel = compute_min_non_zero_and_max(metric_img)
    sat_count, _scratch_mask = count_at_or_above_threshold(
        metric_img,
        float(threshold_value),
    )

    if mode == "topk" and not threshold_only:
        avg_topk, avg_topk_std, avg_topk_sem = compute_topk_stats_inplace(
            metric_img,
            avg_count_value,
        )
    else:
        avg_topk = None
        avg_topk_std = None
        avg_topk_sem = None

    return {
        "sat_count": int(sat_count),
        "min_non_zero": int(min_non_zero),
        "max_pixel": int(max_pixel),
        "avg_topk": avg_topk,
        "avg_topk_std": avg_topk_std,
        "avg_topk_sem": avg_topk_sem,
    }


def _python_compute_roi_metrics(
    image,
    *,
    roi_rect: tuple[int, int, int, int],
    background=None,
    clip_negative: bool = True,
) -> tuple[float, float, float, float]:
    image_arr = _coerce_image(image)
    background_arr = _compatible_background(image_arr, background)
    metric_img = (
        apply_background(image_arr, background_arr, clip_negative)
        if background_arr is not None
        else image_arr
    )
    x0, y0, x1, y1 = normalize_roi_rect_like_numpy(roi_rect, metric_img.shape)
    return compute_roi_stats(metric_img[y0:y1, x0:x1])


def compute_static_metrics(image, *, allow_native: bool = True):
    """Compute dataset-load static metrics for one 2D image.

    Expected native return contract:
        (min_non_zero: int, max_pixel: int)
    """
    if not allow_native or not _native_metrics_enabled_now():
        return _python_compute_static_metrics(image)
    try:
        result = require_native().compute_static_metrics(image)
    except Exception as exc:
        _disable_native_metrics(f"compute_static_metrics failed: {exc}")
        return _python_compute_static_metrics(image)
    _record_native_success()
    return result


def compute_dynamic_metrics(
    image,
    *,
    threshold_value: float,
    mode: str,
    avg_count_value: int,
    background=None,
    clip_negative: bool = True,
    threshold_only: bool = False,
):
    """Compute one image's dynamic metrics through the native backend.

    Expected native return keys:
        sat_count
        min_non_zero
        max_pixel
        avg_topk
        avg_topk_std
        avg_topk_sem
    """
    normalized_mode = "none" if mode == "roi" else mode
    if normalized_mode not in {"none", "topk"}:
        raise ValueError("mode must be 'none' or 'topk'")

    image_arr = _coerce_image(image)
    background_arr = _compatible_background(image_arr, background)
    native_mode = "none" if threshold_only else normalized_mode

    if not _native_metrics_enabled_now():
        return _python_compute_dynamic_metrics(
            image_arr,
            threshold_value=threshold_value,
            mode=normalized_mode,
            avg_count_value=avg_count_value,
            background=background_arr,
            clip_negative=clip_negative,
            threshold_only=threshold_only,
        )

    try:
        result = require_native().compute_dynamic_metrics(
            image_arr,
            threshold_value=threshold_value,
            mode=native_mode,
            avg_count_value=avg_count_value,
            background=background_arr,
            clip_negative=clip_negative,
        )
    except Exception as exc:
        _disable_native_metrics(f"compute_dynamic_metrics failed: {exc}")
        return _python_compute_dynamic_metrics(
            image_arr,
            threshold_value=threshold_value,
            mode=normalized_mode,
            avg_count_value=avg_count_value,
            background=background_arr,
            clip_negative=clip_negative,
            threshold_only=threshold_only,
        )
    _record_native_success()
    return result


def compute_roi_metrics(
    image,
    *,
    roi_rect: tuple[int, int, int, int],
    background=None,
    clip_negative: bool = True,
):
    """Compute one image's ROI statistics through the native backend."""
    image_arr = _coerce_image(image)
    normalized_roi = normalize_roi_rect_like_numpy(roi_rect, image_arr.shape)
    background_arr = _compatible_background(image_arr, background)

    if not _native_metrics_enabled_now():
        return _python_compute_roi_metrics(
            image_arr,
            roi_rect=normalized_roi,
            background=background_arr,
            clip_negative=clip_negative,
        )

    try:
        result = require_native().compute_roi_metrics(
            image_arr,
            roi_rect=normalized_roi,
            background=background_arr,
            clip_negative=clip_negative,
        )
    except Exception as exc:
        _disable_native_metrics(f"compute_roi_metrics failed: {exc}")
        return _python_compute_roi_metrics(
            image_arr,
            roi_rect=normalized_roi,
            background=background_arr,
            clip_negative=clip_negative,
        )
    _record_native_success()
    return result


def decode_raw_file(
    path: str,
    *,
    pixel_format: str,
    width: int,
    height: int,
    stride_bytes: int = 0,
    offset_bytes: int = 0,
):
    """Decode one raw image through the native backend and return a uint16 ndarray."""

    return require_native().decode_raw_file(
        path,
        pixel_format,
        width,
        height,
        stride_bytes=stride_bytes,
        offset_bytes=offset_bytes,
    )
