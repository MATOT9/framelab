"""Reason-coded refresh policy and lightweight diagnostics helpers."""

from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
import logging
from time import perf_counter
from typing import Iterator


class RefreshReason(str, Enum):
    """Named reasons for nontrivial refresh and compute paths."""

    SCAN_LOAD = "scan_load"
    APPLY_THRESHOLD = "apply_threshold"
    APPLY_TOPK = "apply_topk"
    APPLY_ROI = "apply_roi"
    PLUGIN_RUN = "plugin_run"
    BACKGROUND_CHANGE = "background_change"
    VIEW_REBIND = "view_rebind"
    TAB_SWITCH = "tab_switch"
    WORKFLOW_REMAP = "workflow_remap"
    WORKFLOW_SCOPE_CHANGE = "workflow_scope_change"
    METADATA_CHANGE = "metadata_change"
    WORKSPACE_RESTORE = "workspace_restore"


VIEW_ONLY_REASONS = frozenset(
    {
        RefreshReason.VIEW_REBIND,
        RefreshReason.TAB_SWITCH,
    },
)

logger = logging.getLogger("framelab.refresh")


def normalize_refresh_reason(reason: RefreshReason | str | None) -> RefreshReason:
    """Return a normalized refresh reason, rejecting missing or unknown values."""

    if isinstance(reason, RefreshReason):
        return reason
    if reason is None:
        raise ValueError("Refresh reason is required")
    try:
        return RefreshReason(str(reason))
    except ValueError as exc:
        raise ValueError(f"Unknown refresh reason: {reason!r}") from exc


def ensure_compute_reason(
    reason: RefreshReason | str | None,
    *,
    operation: str,
) -> RefreshReason:
    """Return a compute-safe reason or raise for missing/view-only reasons."""

    normalized = normalize_refresh_reason(reason)
    if normalized in VIEW_ONLY_REASONS:
        raise AssertionError(
            f"View-only refresh reason {normalized.value!r} reached compute path "
            f"{operation!r}",
        )
    return normalized


def is_view_only_reason(reason: RefreshReason | str | None) -> bool:
    """Return whether a reason is explicitly view-only."""

    return normalize_refresh_reason(reason) in VIEW_ONLY_REASONS


def _host_debug_context(host: object | None) -> dict[str, object]:
    """Extract compact host context for debug logs when available."""

    if host is None:
        return {}

    context: dict[str, object] = {}
    analysis_context = getattr(host, "_analysis_context_cache", None)
    data_signature = getattr(analysis_context, "data_signature", None)
    if data_signature:
        context["dataset_signature"] = data_signature

    dataset = getattr(host, "dataset_state", None)
    if dataset is not None:
        try:
            context["path_count"] = int(dataset.path_count())
        except Exception:
            pass
        scope_snapshot = getattr(dataset, "scope_snapshot", None)
        scope_root = getattr(scope_snapshot, "root", None)
        if scope_root is not None:
            context["scope_path"] = str(scope_root)

    return context


def log_refresh_event(
    event: str,
    *,
    reason: RefreshReason | str | None = None,
    host: object | None = None,
    family: object | None = None,
    plugin: object | None = None,
    **fields: object,
) -> None:
    """Emit one structured DEBUG refresh-policy event."""

    if not logger.isEnabledFor(logging.DEBUG):
        return
    payload = _host_debug_context(host)
    if reason is not None:
        payload["reason"] = normalize_refresh_reason(reason).value
    if family is not None:
        payload["family"] = getattr(family, "value", family)
    if plugin is not None:
        payload["plugin"] = str(plugin)
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.debug("%s %s", event, payload)


@contextmanager
def timed_refresh_event(
    event: str,
    *,
    reason: RefreshReason | str | None = None,
    host: object | None = None,
    family: object | None = None,
    plugin: object | None = None,
    **fields: object,
) -> Iterator[None]:
    """Log DEBUG start/end events with elapsed milliseconds."""

    if not logger.isEnabledFor(logging.DEBUG):
        yield
        return

    normalized_reason = (
        normalize_refresh_reason(reason)
        if reason is not None
        else None
    )
    log_refresh_event(
        event + ".start",
        reason=normalized_reason,
        host=host,
        family=family,
        plugin=plugin,
        **fields,
    )
    started = perf_counter()
    try:
        yield
    finally:
        duration_ms = (perf_counter() - started) * 1000.0
        log_refresh_event(
            event + ".end",
            reason=normalized_reason,
            host=host,
            family=family,
            plugin=plugin,
            duration_ms=round(duration_ms, 3),
            **fields,
        )
