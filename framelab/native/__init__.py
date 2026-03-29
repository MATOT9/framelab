"""Python-facing native backend hooks."""

from .backend import (
    NativeBackendUnavailable,
    active_metrics_backend,
    consume_backend_status_notice,
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
    "consume_backend_status_notice",
    "compute_dynamic_metrics",
    "compute_roi_metrics",
    "compute_static_metrics",
    "decode_raw_file",
    "last_native_fallback_reason",
    "native_available",
    "require_native",
]
