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


_VALID_SOURCE_KINDS = {"tiff", "raw", "unknown"}
_VALID_BACKEND_OVERRIDES = {None, "python", "native"}
_VALID_ROUTE_OPERATIONS = {
    "static_scan",
    "dynamic_metrics",
    "roi_metrics",
    "apply_background_f32",
    "compute_value_range",
    "compute_histogram",
}

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


def _backend_status_snapshot_locked() -> dict[str, object]:
    native_is_available = _native is not None
    return {
        "native_available": native_is_available,
        "active_backend": _active_metrics_backend,
        "native_latched_off": bool(native_is_available and not _metrics_native_enabled),
        "last_fallback_reason": _last_native_fallback_reason,
    }


def backend_status_snapshot() -> dict[str, object]:
    """Return the current process-wide metrics backend status."""

    with _metrics_backend_lock:
        return dict(_backend_status_snapshot_locked())


def native_available() -> bool:
    """Return whether the optional native extension module imported."""

    return bool(backend_status_snapshot()["native_available"])


def active_metrics_backend() -> str:
    """Return the metrics backend currently used by the wrapper."""

    return str(backend_status_snapshot()["active_backend"])


def last_native_fallback_reason() -> str | None:
    """Return the most recent reason native metrics fell back to Python."""

    reason = backend_status_snapshot()["last_fallback_reason"]
    return None if reason is None else str(reason)


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
    global _last_native_fallback_reason
    global _native_backend_notice_emitted

    with _metrics_backend_lock:
        if not _metrics_native_enabled or _native is None:
            return
        _active_metrics_backend = "native"
        _last_native_fallback_reason = None
        if not _native_backend_notice_emitted:
            _pending_backend_status_notice = "Using native metrics backend"
            _native_backend_notice_emitted = True


def _disable_native_metrics(reason: str) -> None:
    global _metrics_native_enabled, _active_metrics_backend
    global _last_native_fallback_reason, _pending_backend_status_notice

    with _metrics_backend_lock:
        was_enabled = bool(_metrics_native_enabled and _native is not None)
        _metrics_native_enabled = False
        _active_metrics_backend = "python"
        _last_native_fallback_reason = str(reason).strip() or "Native metrics failed"
        if was_enabled:
            _pending_backend_status_notice = "Native metrics failed; using Python fallback"


def _native_metrics_enabled_now() -> bool:
    with _metrics_backend_lock:
        return bool(_metrics_native_enabled and _native is not None)


def _normalize_source_kind(source_kind: str | None) -> str:
    value = str(source_kind or "unknown").strip().lower()
    return value if value in _VALID_SOURCE_KINDS else "unknown"


def _normalize_backend_override(backend_override: str | None) -> str | None:
    if backend_override is None:
        return None
    value = str(backend_override).strip().lower()
    if value not in _VALID_BACKEND_OVERRIDES:
        raise ValueError("backend_override must be None, 'python', or 'native'")
    return value


def _native_route_block_reason(*, allow_native: bool) -> str | None:
    with _metrics_backend_lock:
        if _native is None:
            return "native_unavailable"
        if not allow_native:
            return "allow_native_false"
        if not _metrics_native_enabled:
            return "native_latched_off"
    return None


def describe_metric_route(
    operation: str,
    *,
    source_kind: str = "unknown",
    mode: str | None = None,
    threshold_only: bool = False,
    allow_native: bool = True,
    backend_override: str | None = None,
) -> dict[str, object]:
    """Describe the backend route that should be used for one metric operation."""

    normalized_operation = str(operation).strip().lower()
    if normalized_operation not in _VALID_ROUTE_OPERATIONS:
        raise ValueError(f"Unsupported metric routing operation: {operation!r}")
    normalized_source_kind = _normalize_source_kind(source_kind)
    normalized_override = _normalize_backend_override(backend_override)
    effective_mode: str | None = None

    if normalized_operation == "dynamic_metrics":
        normalized_mode = "none" if mode == "roi" else str(mode or "").strip().lower()
        if normalized_mode not in {"none", "topk"}:
            raise ValueError("mode must be 'none' or 'topk'")
        effective_mode = "none" if threshold_only else normalized_mode

    def _decision(route_used: str, route_reason: str) -> dict[str, object]:
        return {
            "operation": normalized_operation,
            "route_used": route_used,
            "route_reason": route_reason,
            "source_kind": normalized_source_kind,
            "effective_mode": effective_mode,
        }

    if normalized_override == "python":
        return _decision("python", "override_python")

    if normalized_override == "native":
        block_reason = _native_route_block_reason(allow_native=True)
        if block_reason is not None:
            return _decision("python", block_reason)
        return _decision("native", "override_native")

    block_reason = _native_route_block_reason(allow_native=allow_native)
    if block_reason is not None:
        return _decision("python", block_reason)

    if normalized_operation == "static_scan":
        if normalized_source_kind == "raw":
            return _decision("native", "raw_native")
        if normalized_source_kind == "tiff":
            return _decision("python", "tiff_static_python")
        return _decision("python", "unknown_python")

    if normalized_operation == "dynamic_metrics":
        assert effective_mode is not None
        if effective_mode == "topk":
            return _decision("native", "topk_native")
        if normalized_source_kind == "raw":
            return _decision("native", "raw_native")
        if normalized_source_kind == "tiff":
            return _decision("python", "tiff_dynamic_none_python")
        return _decision("python", "unknown_python")

    return _decision("native", "native_default")


def _coerce_image(image) -> np.ndarray:
    return np.asarray(image)


def _compatible_background(image: np.ndarray, background) -> np.ndarray | None:
    if background is None:
        return None
    background_arr = np.asarray(background)
    if not validate_reference_shape(image.shape, background_arr.shape):
        return None
    return background_arr


def _native_row_contiguous(array: np.ndarray | None) -> np.ndarray | None:
    """Return one row-contiguous array for native histogram/value-range calls."""

    if array is None:
        return None
    return np.ascontiguousarray(array)


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
            np.array(metric_img, copy=True, order="C"),
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


def _python_apply_background_f32(
    image,
    *,
    background=None,
    clip_negative: bool = True,
) -> np.ndarray:
    image_arr = _coerce_image(image)
    background_arr = _compatible_background(image_arr, background)
    metric_img = (
        apply_background(image_arr, background_arr, clip_negative)
        if background_arr is not None
        else image_arr
    )
    return np.asarray(metric_img, dtype=np.float32, order="C")


def _python_compute_value_range(
    image,
    *,
    background=None,
    clip_negative: bool = True,
) -> tuple[float, float]:
    metric_img = _python_apply_background_f32(
        image,
        background=background,
        clip_negative=clip_negative,
    )
    flat = np.ravel(metric_img)
    if np.issubdtype(flat.dtype, np.floating):
        flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return (0.0, 0.0)
    return (float(np.min(flat)), float(np.max(flat)))


def _python_compute_histogram(
    image,
    *,
    value_range: tuple[float, float],
    bin_count: int,
    background=None,
    clip_negative: bool = True,
) -> np.ndarray:
    metric_img = _python_apply_background_f32(
        image,
        background=background,
        clip_negative=clip_negative,
    )
    flat = np.ravel(metric_img)
    if np.issubdtype(flat.dtype, np.floating):
        flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return np.zeros(int(bin_count), dtype=np.uint64)
    counts, _edges = np.histogram(
        flat,
        bins=int(bin_count),
        range=tuple(float(v) for v in value_range),
    )
    return np.asarray(counts, dtype=np.uint64)


def _execute_routed_metric(
    *,
    decision: dict[str, object],
    python_fn,
    native_fn,
    failure_label: str,
):
    if str(decision["route_used"]) != "native":
        return python_fn()
    try:
        result = native_fn()
    except Exception as exc:
        _disable_native_metrics(f"{failure_label} failed: {exc}")
        return python_fn()
    _record_native_success()
    return result


def compute_static_metrics(
    image,
    *,
    source_kind: str = "unknown",
    allow_native: bool = True,
    backend_override: str | None = None,
):
    """Compute dataset-load static metrics for one 2D image.

    Expected native return contract:
        (min_non_zero: int, max_pixel: int)
    """
    decision = describe_metric_route(
        "static_scan",
        source_kind=source_kind,
        allow_native=allow_native,
        backend_override=backend_override,
    )
    image_arr = _coerce_image(image)
    return _execute_routed_metric(
        decision=decision,
        python_fn=lambda: _python_compute_static_metrics(image_arr),
        native_fn=lambda: require_native().compute_static_metrics(image_arr),
        failure_label="compute_static_metrics",
    )


def compute_dynamic_metrics(
    image,
    *,
    threshold_value: float,
    mode: str,
    avg_count_value: int,
    background=None,
    clip_negative: bool = True,
    threshold_only: bool = False,
    source_kind: str = "unknown",
    allow_native: bool = True,
    backend_override: str | None = None,
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
    decision = describe_metric_route(
        "dynamic_metrics",
        source_kind=source_kind,
        mode=mode,
        threshold_only=threshold_only,
        allow_native=allow_native,
        backend_override=backend_override,
    )
    resolved_mode = str(decision["effective_mode"] or "none")
    image_arr = _coerce_image(image)
    background_arr = _compatible_background(image_arr, background)
    return _execute_routed_metric(
        decision=decision,
        python_fn=lambda: _python_compute_dynamic_metrics(
            image_arr,
            threshold_value=threshold_value,
            mode=resolved_mode,
            avg_count_value=avg_count_value,
            background=background_arr,
            clip_negative=clip_negative,
            threshold_only=threshold_only,
        ),
        native_fn=lambda: require_native().compute_dynamic_metrics(
            image_arr,
            threshold_value=threshold_value,
            mode=resolved_mode,
            avg_count_value=avg_count_value,
            background=background_arr,
            clip_negative=clip_negative,
        ),
        failure_label="compute_dynamic_metrics",
    )


def compute_roi_metrics(
    image,
    *,
    roi_rect: tuple[int, int, int, int],
    background=None,
    clip_negative: bool = True,
    allow_native: bool = True,
):
    """Compute one image's ROI statistics through the native backend."""
    decision = describe_metric_route(
        "roi_metrics",
        allow_native=allow_native,
    )
    image_arr = _coerce_image(image)
    normalized_roi = normalize_roi_rect_like_numpy(roi_rect, image_arr.shape)
    background_arr = _compatible_background(image_arr, background)
    return _execute_routed_metric(
        decision=decision,
        python_fn=lambda: _python_compute_roi_metrics(
            image_arr,
            roi_rect=normalized_roi,
            background=background_arr,
            clip_negative=clip_negative,
        ),
        native_fn=lambda: require_native().compute_roi_metrics(
            image_arr,
            roi_rect=normalized_roi,
            background=background_arr,
            clip_negative=clip_negative,
        ),
        failure_label="compute_roi_metrics",
    )


def apply_background_f32(
    image,
    *,
    background,
    clip_negative: bool = True,
    allow_native: bool = True,
) -> np.ndarray:
    """Return the metric/preview corrected-image buffer as float32."""

    decision = describe_metric_route(
        "apply_background_f32",
        allow_native=allow_native,
    )
    image_arr = _coerce_image(image)
    background_arr = _compatible_background(image_arr, background)
    if background_arr is None:
        return np.asarray(image_arr, dtype=np.float32, order="C")
    result = _execute_routed_metric(
        decision=decision,
        python_fn=lambda: _python_apply_background_f32(
            image_arr,
            background=background_arr,
            clip_negative=clip_negative,
        ),
        native_fn=lambda: require_native().apply_background_f32(
            image_arr,
            background=background_arr,
            clip_negative=clip_negative,
        ),
        failure_label="apply_background_f32",
    )
    return np.asarray(result, dtype=np.float32, order="C")


def compute_value_range(
    image,
    *,
    background=None,
    clip_negative: bool = True,
    allow_native: bool = True,
) -> tuple[float, float]:
    """Return min/max values for histogram policy selection."""

    decision = describe_metric_route(
        "compute_value_range",
        allow_native=allow_native,
    )
    image_arr = _coerce_image(image)
    background_arr = _compatible_background(image_arr, background)
    native_image_arr = (
        _native_row_contiguous(image_arr)
        if str(decision["route_used"]) == "native"
        else image_arr
    )
    native_background_arr = (
        _native_row_contiguous(background_arr)
        if str(decision["route_used"]) == "native"
        else background_arr
    )
    result = _execute_routed_metric(
        decision=decision,
        python_fn=lambda: _python_compute_value_range(
            image_arr,
            background=background_arr,
            clip_negative=clip_negative,
        ),
        native_fn=lambda: require_native().compute_value_range(
            native_image_arr,
            background=native_background_arr,
            clip_negative=clip_negative,
        ),
        failure_label="compute_value_range",
    )
    return (float(result[0]), float(result[1]))


def compute_histogram(
    image,
    *,
    value_range: tuple[float, float],
    bin_count: int,
    background=None,
    clip_negative: bool = True,
    allow_native: bool = True,
) -> np.ndarray:
    """Count histogram bins for one chosen numeric policy."""

    decision = describe_metric_route(
        "compute_histogram",
        allow_native=allow_native,
    )
    range_min, range_max = (float(value_range[0]), float(value_range[1]))
    resolved_bin_count = int(bin_count)
    if resolved_bin_count <= 0:
        raise ValueError("bin_count must be a positive integer")
    if not np.isfinite(range_min) or not np.isfinite(range_max) or not (range_max > range_min):
        raise ValueError("value_range must contain finite increasing bounds")

    image_arr = _coerce_image(image)
    background_arr = _compatible_background(image_arr, background)
    native_image_arr = (
        _native_row_contiguous(image_arr)
        if str(decision["route_used"]) == "native"
        else image_arr
    )
    native_background_arr = (
        _native_row_contiguous(background_arr)
        if str(decision["route_used"]) == "native"
        else background_arr
    )
    result = _execute_routed_metric(
        decision=decision,
        python_fn=lambda: _python_compute_histogram(
            image_arr,
            value_range=(range_min, range_max),
            bin_count=resolved_bin_count,
            background=background_arr,
            clip_negative=clip_negative,
        ),
        native_fn=lambda: require_native().compute_histogram(
            native_image_arr,
            value_range=(range_min, range_max),
            bin_count=resolved_bin_count,
            background=native_background_arr,
            clip_negative=clip_negative,
        ),
        failure_label="compute_histogram",
    )
    return np.asarray(result, dtype=np.uint64)


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
