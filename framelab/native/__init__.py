"""Python-facing native backend hooks."""

from .backend import (
    NativeBackendUnavailable,
    active_metrics_backend,
    apply_background_f32,
    backend_status_snapshot,
    consume_backend_status_notice,
    describe_metric_route,
    compute_histogram,
    compute_dynamic_metrics,
    compute_roi_metrics,
    compute_static_metrics,
    decode_raw_file,
    last_native_fallback_reason,
    native_available,
    require_native,
)

__all__ = [
    "NativeBackendUnavailable",
    "active_metrics_backend",
    "apply_background_f32",
    "backend_status_snapshot",
    "consume_backend_status_notice",
    "describe_metric_route",
    "compute_histogram",
    "compute_dynamic_metrics",
    "compute_roi_metrics",
    "compute_static_metrics",
    "decode_raw_file",
    "last_native_fallback_reason",
    "native_available",
    "require_native",
]
