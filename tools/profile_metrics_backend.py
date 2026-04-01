from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from framelab.image_io import read_2d_image, source_kind_for_path, supported_suffixes
from framelab.native import backend as native_backend
from framelab.processing_failures import (
    ProcessingFailure,
    failure_reason_from_exception,
    make_processing_failure,
)
from framelab.raw_decode import (
    RawDecodeResolverContext,
    RawDecodeSpec,
    resolve_raw_decode_spec,
)


@dataclass(slots=True)
class BenchmarkInputRecord:
    """One discovered benchmark input with optional decoded image data."""

    path: Path
    source_kind: str
    load_status: str
    image: np.ndarray | None = None
    raw_spec: RawDecodeSpec | None = None
    failure: ProcessingFailure | None = None


def _find_images(root: Path) -> list[Path]:
    suffixes = {suffix.lower() for suffix in supported_suffixes()}
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    )


def _finite_min_max(image: np.ndarray) -> tuple[float, float]:
    flat = np.ravel(np.asarray(image))
    if np.issubdtype(flat.dtype, np.floating):
        flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return (0.0, 0.0)
    return (float(np.min(flat)), float(np.max(flat)))


def _histogram_range(data_min: float, data_max: float) -> tuple[float, float]:
    if data_max <= data_min:
        return (data_min - 0.5, data_max + 0.5)
    range_min = data_min
    range_max = data_max
    if data_min <= 0.0 <= data_max:
        range_min = min(range_min, 0.0)
    if range_max <= range_min:
        range_max = range_min + 1.0
    return (range_min, range_max)


def _histogram_bins(
    image: np.ndarray,
    *,
    range_min: float,
    range_max: float,
    background_used: bool,
) -> int:
    arr = np.asarray(image)
    bins = int(max(32, min(144, np.sqrt(float(arr.size)) * 0.45)))
    if not background_used and np.issubdtype(arr.dtype, np.integer):
        span_int = int(round(range_max - range_min))
        if span_int > 0:
            bins = min(bins, span_int + 1)
            bins = max(24, bins)
    return bins


def _resolved_background(
    image: np.ndarray,
    background: np.ndarray | None,
) -> np.ndarray | None:
    if background is None:
        return None
    if tuple(np.asarray(image).shape) != tuple(np.asarray(background).shape):
        return None
    return background


def _default_roi_rect(shape: tuple[int, int]) -> tuple[int, int, int, int]:
    height, width = int(shape[0]), int(shape[1])
    x0 = max(0, width // 4)
    y0 = max(0, height // 4)
    x1 = min(width, max(x0 + 1, width - x0))
    y1 = min(height, max(y0 + 1, height - y0))
    return (x0, y0, x1, y1)


def _phase_backend_options(
    *,
    backend_mode: str,
    operation: str,
) -> dict[str, object]:
    if backend_mode not in {"native", "python", "production"}:
        raise ValueError(f"Unsupported backend mode: {backend_mode!r}")

    allow_native = backend_mode != "python"
    backend_override = None

    if operation in {"static_scan", "dynamic_metrics"}:
        if backend_mode == "native":
            backend_override = "native"
        elif backend_mode == "python":
            backend_override = "python"

    return {
        "allow_native": bool(allow_native),
        "backend_override": backend_override,
    }


def _phase_route_for_input(
    *,
    backend_mode: str,
    operation: str,
    source_kind: str,
    mode: str | None = None,
    threshold_only: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    options = _phase_backend_options(
        backend_mode=backend_mode,
        operation=operation,
    )
    decision = native_backend.describe_metric_route(
        operation,
        source_kind=source_kind,
        mode=mode,
        threshold_only=threshold_only,
        allow_native=bool(options["allow_native"]),
        backend_override=options["backend_override"],
    )
    return (dict(decision), options)


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return {
        key: int(counter[key])
        for key in sorted(counter)
    }


def _unique_or_mixed(values: list[object], *, mixed_label: str = "mixed") -> object:
    unique: list[object] = []
    for value in values:
        if value in unique:
            continue
        unique.append(value)
    if not unique:
        return ""
    if len(unique) == 1:
        return unique[0]
    return mixed_label


def _aggregate_route_info(
    route_infos: list[dict[str, object]],
) -> dict[str, object] | None:
    if not route_infos:
        return None

    source_kind_counts: Counter[str] = Counter()
    breakdown_counter: Counter[tuple[str, str, str, str]] = Counter()
    for route in route_infos:
        source_kind = str(route.get("source_kind") or "unknown")
        route_used = str(route.get("route_used") or "")
        route_reason = str(route.get("route_reason") or "")
        effective_mode = str(route.get("effective_mode") or "")
        source_kind_counts[source_kind] += 1
        breakdown_counter[(source_kind, route_used, route_reason, effective_mode)] += 1

    route_breakdown: list[dict[str, object]] = []
    for (
        source_kind,
        route_used,
        route_reason,
        effective_mode,
    ), count in sorted(
        breakdown_counter.items(),
        key=lambda item: item[0],
    ):
        entry: dict[str, object] = {
            "source_kind": source_kind,
            "route_used": route_used,
            "route_reason": route_reason,
            "count": int(count),
        }
        entry["effective_mode"] = effective_mode or None
        route_breakdown.append(entry)

    return {
        "route_used": str(
            _unique_or_mixed([route.get("route_used") for route in route_infos]),
        ),
        "route_reason": str(
            _unique_or_mixed([route.get("route_reason") for route in route_infos]),
        ),
        "source_kind": str(
            _unique_or_mixed([route.get("source_kind") for route in route_infos]),
        ),
        "effective_mode": _unique_or_mixed(
            [route.get("effective_mode") for route in route_infos],
        ),
        "source_kind_counts": _sorted_counter(source_kind_counts),
        "route_breakdown": route_breakdown,
    }


def _phase_summary(
    *,
    name: str,
    started_at: float,
    item_count: int,
    checksum: float,
    attempted_images: int | None = None,
    failed_images: int | None = None,
    route_info: dict[str, object] | None = None,
    source_kind_counts: dict[str, int] | None = None,
    background_applied_images: int | None = None,
    raw_fallback_images: int | None = None,
    skipped_reason: str | None = None,
    failures: list[ProcessingFailure] | None = None,
) -> dict[str, object]:
    elapsed = time.perf_counter() - started_at
    summary = {
        "phase": name,
        "images": int(item_count),
        "elapsed_s": round(elapsed, 6),
        "per_image_ms": round((elapsed * 1000.0 / item_count), 6) if item_count else 0.0,
        "checksum": float(checksum),
    }
    if attempted_images is not None:
        summary["attempted_images"] = int(attempted_images)
    if failed_images is not None:
        summary["failed_images"] = int(failed_images)
    if route_info is not None:
        summary["route_used"] = str(route_info.get("route_used") or "")
        summary["route_reason"] = str(route_info.get("route_reason") or "")
        summary["source_kind"] = str(route_info.get("source_kind") or "")
        summary["effective_mode"] = route_info.get("effective_mode")
        if "source_kind_counts" in route_info:
            summary["source_kind_counts"] = dict(route_info["source_kind_counts"])
        if "route_breakdown" in route_info:
            summary["route_breakdown"] = list(route_info["route_breakdown"])
    elif source_kind_counts is not None:
        summary["source_kind_counts"] = dict(source_kind_counts)
    if background_applied_images is not None:
        summary["background_applied_images"] = int(background_applied_images)
    if raw_fallback_images is not None:
        summary["raw_fallback_images"] = int(raw_fallback_images)
    if skipped_reason:
        summary["skipped_reason"] = str(skipped_reason)
    if failures:
        summary["failures_by_reason"] = _sorted_counter(
            Counter(failure.reason for failure in failures),
        )
    return summary


def _tuple_checksum(values: tuple[float, ...]) -> float:
    arr = np.asarray(values, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0
    return float(np.sum(finite, dtype=np.float64))


def _serialize_raw_spec(spec: RawDecodeSpec | None) -> dict[str, object] | None:
    if spec is None:
        return None
    return {
        "source_kind": str(spec.source_kind),
        "pixel_format": str(spec.pixel_format),
        "width": int(spec.width),
        "height": int(spec.height),
        "stride_bytes": (
            0
            if spec.stride_bytes in {None, 0}
            else int(spec.stride_bytes)
        ),
        "offset_bytes": int(spec.offset_bytes),
    }


def _serialize_input_record(record: BenchmarkInputRecord) -> dict[str, object]:
    payload = {
        "path": str(record.path),
        "source_kind": str(record.source_kind),
        "load_status": str(record.load_status),
        "failure_reason": None if record.failure is None else str(record.failure.reason),
        "raw_spec_resolved": bool(record.raw_spec is not None),
        "raw_spec": _serialize_raw_spec(record.raw_spec),
    }
    if record.image is not None:
        payload["shape"] = [int(dim) for dim in np.asarray(record.image).shape]
    return payload


def _phase_failure_stage(phase_name: str) -> str:
    if phase_name == "roi_metrics":
        return "roi"
    if phase_name == "exact_corrected_preview":
        return "preview"
    return "metrics"


def _override_value(value: str) -> object:
    text = str(value).strip()
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(text)
    except Exception:
        pass
    try:
        return float(text)
    except Exception:
        return text


def _parse_raw_overrides(items: list[str] | tuple[str, ...]) -> dict[str, object]:
    overrides: dict[str, object] = {}
    for item in items:
        raw = str(item).strip()
        if not raw or "=" not in raw:
            raise ValueError(
                "RAW override entries must use KEY=VALUE syntax",
            )
        key, value = raw.split("=", 1)
        clean_key = str(key).strip()
        clean_value = str(value).strip()
        if not clean_key or not clean_value:
            raise ValueError(
                "RAW override entries must use non-empty KEY=VALUE syntax",
            )
        overrides[clean_key] = _override_value(clean_value)
    return overrides


def _build_raw_resolver_context(
    *,
    raw_manual_overrides: dict[str, object] | None = None,
) -> RawDecodeResolverContext:
    return RawDecodeResolverContext(
        manual_overrides=dict(raw_manual_overrides or {}),
    )


def _build_cached_raw_spec_resolver() -> Callable[..., RawDecodeSpec]:
    cache: dict[str, RawDecodeSpec] = {}

    def _resolve(
        path: str | Path,
        *,
        context: RawDecodeResolverContext | None = None,
    ) -> RawDecodeSpec:
        resolved = str(Path(path).expanduser().resolve())
        cached = cache.get(resolved)
        if cached is not None:
            return cached
        spec = resolve_raw_decode_spec(path, context=context)
        cache[resolved] = spec
        return spec

    return _resolve


def _load_background(
    path: Path | None,
    *,
    raw_spec_resolver: Callable[..., RawDecodeSpec],
    raw_resolver_context: RawDecodeResolverContext,
) -> np.ndarray | None:
    if path is None:
        return None
    try:
        return np.asarray(
            read_2d_image(
                path,
                raw_spec_resolver=raw_spec_resolver,
                raw_resolver_context=raw_resolver_context,
            ),
        )
    except Exception as exc:
        reason = failure_reason_from_exception(exc)
        raise SystemExit(f"Background load failed for {path}: {reason}") from exc


def _load_inputs(
    image_paths: list[Path],
    *,
    raw_spec_resolver: Callable[..., RawDecodeSpec],
    raw_resolver_context: RawDecodeResolverContext,
) -> tuple[list[BenchmarkInputRecord], float]:
    records: list[BenchmarkInputRecord] = []
    started = time.perf_counter()

    for path in image_paths:
        source_kind = source_kind_for_path(path)
        raw_spec: RawDecodeSpec | None = None
        spec_resolved = False
        try:
            if source_kind == "raw":
                raw_spec = raw_spec_resolver(
                    path,
                    context=raw_resolver_context,
                )
                spec_resolved = True
            image = np.asarray(
                read_2d_image(
                    path,
                    raw_spec_resolver=raw_spec_resolver,
                    raw_resolver_context=raw_resolver_context,
                ),
            )
        except Exception as exc:
            failure = make_processing_failure(
                stage="scan",
                path=path,
                reason=failure_reason_from_exception(exc),
            )
            load_status = "failed"
            if source_kind == "raw":
                load_status = "failed_decode" if spec_resolved else "failed_spec"
            records.append(
                BenchmarkInputRecord(
                    path=path,
                    source_kind=source_kind,
                    load_status=load_status,
                    raw_spec=raw_spec,
                    failure=failure,
                ),
            )
            continue

        records.append(
            BenchmarkInputRecord(
                path=path,
                source_kind=source_kind,
                load_status="loaded",
                image=image,
                raw_spec=raw_spec,
            ),
        )

    return (records, time.perf_counter() - started)


def _successful_inputs(
    records: list[BenchmarkInputRecord],
) -> list[BenchmarkInputRecord]:
    return [record for record in records if record.image is not None]


def _load_failures(
    records: list[BenchmarkInputRecord],
) -> list[ProcessingFailure]:
    return [
        record.failure
        for record in records
        if record.failure is not None
    ]


def _raw_report_fields(records: list[BenchmarkInputRecord]) -> dict[str, object]:
    raw_records = [record for record in records if record.source_kind == "raw"]
    raw_specs = [record.raw_spec for record in raw_records if record.raw_spec is not None]
    serialized_specs = [
        spec_payload
        for spec_payload in (_serialize_raw_spec(spec) for spec in raw_specs)
        if spec_payload is not None
    ]
    raw_failures = [
        record.failure
        for record in raw_records
        if record.failure is not None
    ]

    return {
        "raw_files_total": len(raw_records),
        "raw_files_decoded": sum(
            1 for record in raw_records if record.load_status == "loaded"
        ),
        "raw_files_failed_spec": sum(
            1 for record in raw_records if record.load_status == "failed_spec"
        ),
        "raw_files_failed_decode": sum(
            1 for record in raw_records if record.load_status == "failed_decode"
        ),
        "raw_failures_by_reason": _sorted_counter(
            Counter(failure.reason for failure in raw_failures),
        ),
        "raw_decode_summary": {
            "resolved_specs": len(serialized_specs),
            "pixel_formats_seen": sorted(
                {str(spec["pixel_format"]) for spec in serialized_specs},
            ),
            "widths_seen": sorted({int(spec["width"]) for spec in serialized_specs}),
            "heights_seen": sorted({int(spec["height"]) for spec in serialized_specs}),
            "stride_bytes_seen": sorted(
                {int(spec["stride_bytes"]) for spec in serialized_specs},
            ),
            "offset_bytes_seen": sorted(
                {int(spec["offset_bytes"]) for spec in serialized_specs},
            ),
        },
    }


def _source_kind_counts(
    records: list[BenchmarkInputRecord],
) -> dict[str, int]:
    return _sorted_counter(
        Counter(record.source_kind for record in records),
    )


def _load_phase_summary(
    records: list[BenchmarkInputRecord],
    *,
    load_elapsed_s: float,
) -> dict[str, object]:
    loaded = _successful_inputs(records)
    failures = _load_failures(records)
    source_kind_counts = _source_kind_counts(records)
    attempted = len(records)
    loaded_count = len(loaded)
    checksum = float(
        sum(
            int(np.asarray(record.image).size)
            for record in loaded
            if record.image is not None
        ),
    )
    summary = {
        "phase": "load_decode",
        "images": int(loaded_count),
        "attempted_images": int(attempted),
        "failed_images": int(attempted - loaded_count),
        "elapsed_s": round(load_elapsed_s, 6),
        "per_image_ms": round((load_elapsed_s * 1000.0 / loaded_count), 6)
        if loaded_count
        else 0.0,
        "checksum": checksum,
        "source_kind_counts": source_kind_counts,
    }
    if failures:
        summary["failures_by_reason"] = _sorted_counter(
            Counter(failure.reason for failure in failures),
        )
    if loaded_count == 0:
        summary["skipped_reason"] = "No successfully loaded images"
    return summary


def _run_static_phase(
    inputs: list[BenchmarkInputRecord],
    *,
    backend_mode: str,
) -> dict[str, object]:
    started = time.perf_counter()
    checksum = 0.0
    attempted = 0
    succeeded = 0
    route_infos: list[dict[str, object]] = []
    failures: list[ProcessingFailure] = []

    for item in inputs:
        assert item.image is not None
        route_info, route_options = _phase_route_for_input(
            backend_mode=backend_mode,
            operation="static_scan",
            source_kind=item.source_kind,
        )
        route_infos.append(route_info)
        attempted += 1
        try:
            min_non_zero, max_pixel = native_backend.compute_static_metrics(
                item.image,
                source_kind=item.source_kind,
                allow_native=bool(route_options["allow_native"]),
                backend_override=route_options["backend_override"],
            )
        except Exception as exc:
            failures.append(
                make_processing_failure(
                    stage="metrics",
                    path=item.path,
                    reason=failure_reason_from_exception(exc),
                ),
            )
            continue
        checksum += float(min_non_zero) + float(max_pixel)
        succeeded += 1

    return _phase_summary(
        name="static_scan",
        started_at=started,
        item_count=succeeded,
        checksum=checksum,
        attempted_images=attempted,
        failed_images=attempted - succeeded,
        route_info=_aggregate_route_info(route_infos),
        skipped_reason=(
            "No successfully loaded images"
            if attempted == 0
            else None
        ),
        failures=failures,
    )


def _run_dynamic_phase(
    inputs: list[BenchmarkInputRecord],
    *,
    backend_mode: str,
    threshold_value: float,
    avg_count_value: int,
    background: np.ndarray | None,
    mode: str,
) -> dict[str, object]:
    phase_name = "dynamic_topk" if mode == "topk" else "dynamic_none"
    started = time.perf_counter()
    checksum = 0.0
    attempted = 0
    succeeded = 0
    route_infos: list[dict[str, object]] = []
    failures: list[ProcessingFailure] = []
    background_applied_images = 0
    raw_fallback_images = 0

    for item in inputs:
        assert item.image is not None
        route_info, route_options = _phase_route_for_input(
            backend_mode=backend_mode,
            operation="dynamic_metrics",
            source_kind=item.source_kind,
            mode=mode,
        )
        route_infos.append(route_info)
        reference = _resolved_background(item.image, background)
        if reference is None:
            raw_fallback_images += 1
        else:
            background_applied_images += 1
        attempted += 1
        try:
            result = native_backend.compute_dynamic_metrics(
                item.image,
                threshold_value=threshold_value,
                mode=mode,
                avg_count_value=avg_count_value,
                background=reference,
                source_kind=item.source_kind,
                allow_native=bool(route_options["allow_native"]),
                backend_override=route_options["backend_override"],
            )
        except Exception as exc:
            failures.append(
                make_processing_failure(
                    stage="metrics",
                    path=item.path,
                    reason=failure_reason_from_exception(exc),
                ),
            )
            continue
        checksum += (
            float(result["sat_count"])
            + float(result["min_non_zero"])
            + float(result["max_pixel"])
        )
        if mode == "topk":
            checksum += float(result["avg_topk"] or 0.0)
        succeeded += 1

    skipped_reason = None
    if attempted == 0:
        skipped_reason = "No successfully loaded images"
    elif background is not None and background_applied_images == 0:
        skipped_reason = "No matching background shape found"

    return _phase_summary(
        name=phase_name,
        started_at=started,
        item_count=succeeded,
        checksum=checksum,
        attempted_images=attempted,
        failed_images=attempted - succeeded,
        route_info=_aggregate_route_info(route_infos),
        background_applied_images=background_applied_images,
        raw_fallback_images=raw_fallback_images,
        skipped_reason=skipped_reason,
        failures=failures,
    )


def _run_roi_phase(
    inputs: list[BenchmarkInputRecord],
    *,
    backend_mode: str,
    background: np.ndarray | None,
) -> dict[str, object]:
    started = time.perf_counter()
    checksum = 0.0
    attempted = 0
    succeeded = 0
    route_infos: list[dict[str, object]] = []
    failures: list[ProcessingFailure] = []
    background_applied_images = 0
    raw_fallback_images = 0

    for item in inputs:
        assert item.image is not None
        route_info, route_options = _phase_route_for_input(
            backend_mode=backend_mode,
            operation="roi_metrics",
            source_kind=item.source_kind,
        )
        route_infos.append(route_info)
        reference = _resolved_background(item.image, background)
        if reference is None:
            raw_fallback_images += 1
        else:
            background_applied_images += 1
        attempted += 1
        try:
            roi_max, roi_mean, roi_std, roi_sem = native_backend.compute_roi_metrics(
                item.image,
                roi_rect=_default_roi_rect(tuple(np.asarray(item.image).shape)),
                background=reference,
                allow_native=bool(route_options["allow_native"]),
            )
        except Exception as exc:
            failures.append(
                make_processing_failure(
                    stage="roi",
                    path=item.path,
                    reason=failure_reason_from_exception(exc),
                ),
            )
            continue
        checksum += float(roi_max) + float(roi_mean) + float(roi_std) + float(roi_sem)
        succeeded += 1

    skipped_reason = None
    if attempted == 0:
        skipped_reason = "No successfully loaded images"
    elif background is not None and background_applied_images == 0:
        skipped_reason = "No matching background shape found"

    return _phase_summary(
        name="roi_metrics",
        started_at=started,
        item_count=succeeded,
        checksum=checksum,
        attempted_images=attempted,
        failed_images=attempted - succeeded,
        route_info=_aggregate_route_info(route_infos),
        background_applied_images=background_applied_images,
        raw_fallback_images=raw_fallback_images,
        skipped_reason=skipped_reason,
        failures=failures,
    )


def _run_preview_phase(
    inputs: list[BenchmarkInputRecord],
    *,
    backend_mode: str,
    background: np.ndarray | None,
) -> dict[str, object]:
    started = time.perf_counter()
    checksum = 0.0
    attempted = 0
    succeeded = 0
    route_infos: list[dict[str, object]] = []
    failures: list[ProcessingFailure] = []
    background_applied_images = 0
    raw_fallback_images = 0

    for item in inputs:
        assert item.image is not None
        reference = _resolved_background(item.image, background)
        if reference is None:
            raw_fallback_images += 1
            continue
        background_applied_images += 1
        route_info, route_options = _phase_route_for_input(
            backend_mode=backend_mode,
            operation="apply_background_f32",
            source_kind=item.source_kind,
        )
        route_infos.append(route_info)
        attempted += 1
        try:
            corrected = native_backend.apply_background_f32(
                item.image,
                background=reference,
                allow_native=bool(route_options["allow_native"]),
            )
        except Exception as exc:
            failures.append(
                make_processing_failure(
                    stage="preview",
                    path=item.path,
                    reason=failure_reason_from_exception(exc),
                ),
            )
            continue
        checksum += float(np.sum(corrected, dtype=np.float64))
        succeeded += 1

    if not inputs:
        skipped_reason = "No successfully loaded images"
    elif background is None:
        skipped_reason = "No background file provided"
    elif attempted == 0:
        skipped_reason = "No matching background shape found"
    else:
        skipped_reason = None

    return _phase_summary(
        name="exact_corrected_preview",
        started_at=started,
        item_count=succeeded,
        checksum=checksum,
        attempted_images=attempted,
        failed_images=attempted - succeeded,
        route_info=_aggregate_route_info(route_infos),
        background_applied_images=background_applied_images,
        raw_fallback_images=raw_fallback_images,
        skipped_reason=skipped_reason,
        failures=failures,
    )


def _run_histogram_phase(
    inputs: list[BenchmarkInputRecord],
    *,
    backend_mode: str,
    background: np.ndarray | None,
) -> dict[str, object]:
    started = time.perf_counter()
    checksum = 0.0
    attempted = 0
    succeeded = 0
    route_infos: list[dict[str, object]] = []
    failures: list[ProcessingFailure] = []
    background_applied_images = 0
    raw_fallback_images = 0

    for item in inputs:
        assert item.image is not None
        reference = _resolved_background(item.image, background)
        if reference is None:
            raw_fallback_images += 1
        else:
            background_applied_images += 1
        route_info, route_options = _phase_route_for_input(
            backend_mode=backend_mode,
            operation="compute_histogram",
            source_kind=item.source_kind,
        )
        route_infos.append(route_info)
        value_range_route, value_range_options = _phase_route_for_input(
            backend_mode=backend_mode,
            operation="compute_value_range",
            source_kind=item.source_kind,
        )
        attempted += 1
        try:
            if reference is None:
                data_min, data_max = _finite_min_max(item.image)
            else:
                _ = value_range_route
                data_min, data_max = native_backend.compute_value_range(
                    item.image,
                    background=reference,
                    allow_native=bool(value_range_options["allow_native"]),
                )
            range_min, range_max = _histogram_range(data_min, data_max)
            bin_count = _histogram_bins(
                item.image,
                range_min=range_min,
                range_max=range_max,
                background_used=reference is not None,
            )
            counts = native_backend.compute_histogram(
                item.image,
                value_range=(range_min, range_max),
                bin_count=bin_count,
                background=reference,
                allow_native=bool(route_options["allow_native"]),
            )
        except Exception as exc:
            failures.append(
                make_processing_failure(
                    stage="metrics",
                    path=item.path,
                    reason=failure_reason_from_exception(exc),
                ),
            )
            continue
        checksum += float(np.sum(counts, dtype=np.float64))
        succeeded += 1

    skipped_reason = None
    if attempted == 0:
        skipped_reason = "No successfully loaded images"
    elif background is not None and background_applied_images == 0:
        skipped_reason = "No matching background shape found"

    return _phase_summary(
        name="exact_histogram",
        started_at=started,
        item_count=succeeded,
        checksum=checksum,
        attempted_images=attempted,
        failed_images=attempted - succeeded,
        route_info=_aggregate_route_info(route_infos),
        background_applied_images=background_applied_images,
        raw_fallback_images=raw_fallback_images,
        skipped_reason=skipped_reason,
        failures=failures,
    )


def _roi_parity_report(
    inputs: list[BenchmarkInputRecord],
    *,
    background: np.ndarray | None,
    mismatch_limit: int,
) -> dict[str, object]:
    mismatches: list[dict[str, object]] = []
    mismatch_count = 0
    checksum_native = 0.0
    checksum_python = 0.0
    background_applied_images = 0
    raw_fallback_images = 0
    attempted = 0
    failures: list[ProcessingFailure] = []

    for item in inputs:
        assert item.image is not None
        reference = _resolved_background(item.image, background)
        if reference is None:
            raw_fallback_images += 1
        else:
            background_applied_images += 1
        roi_rect = _default_roi_rect(tuple(np.asarray(item.image).shape))
        attempted += 1
        try:
            native_result = tuple(
                float(value)
                for value in native_backend.compute_roi_metrics(
                    item.image,
                    roi_rect=roi_rect,
                    background=reference,
                    allow_native=True,
                )
            )
            python_result = tuple(
                float(value)
                for value in native_backend.compute_roi_metrics(
                    item.image,
                    roi_rect=roi_rect,
                    background=reference,
                    allow_native=False,
                )
            )
        except Exception as exc:
            failures.append(
                make_processing_failure(
                    stage="roi",
                    path=item.path,
                    reason=failure_reason_from_exception(exc),
                ),
            )
            continue

        checksum_native += _tuple_checksum(native_result)
        checksum_python += _tuple_checksum(python_result)
        if not np.allclose(
            np.asarray(native_result, dtype=np.float64),
            np.asarray(python_result, dtype=np.float64),
            rtol=1e-6,
            atol=1e-6,
            equal_nan=True,
        ):
            mismatch_count += 1
            if len(mismatches) < mismatch_limit:
                mismatches.append(
                    {
                        "path": str(item.path),
                        "source_kind": str(item.source_kind),
                        "roi_rect": [int(v) for v in roi_rect],
                        "background_applied": bool(reference is not None),
                        "native": list(native_result),
                        "python": list(python_result),
                    },
                )

    return {
        "checked_images": attempted - len(failures),
        "background_applied_images": background_applied_images,
        "raw_fallback_images": raw_fallback_images,
        "native_checksum": float(checksum_native),
        "python_checksum": float(checksum_python),
        "mismatch_count": mismatch_count,
        "mismatches": mismatches,
        "failures_by_reason": _sorted_counter(
            Counter(failure.reason for failure in failures),
        ),
    }


def _run_once(
    *,
    dataset_root: Path,
    background_path: Path | None,
    backend_mode: str,
    threshold_value: float,
    avg_count_value: int,
    parity_check: str,
    parity_limit: int,
    raw_manual_overrides: dict[str, object] | None = None,
    verbose_files: bool = False,
) -> dict[str, object]:
    image_paths = _find_images(dataset_root)
    if not image_paths:
        raise SystemExit(f"No supported image files found under {dataset_root}")

    raw_resolver_context = _build_raw_resolver_context(
        raw_manual_overrides=raw_manual_overrides,
    )
    raw_spec_resolver = _build_cached_raw_spec_resolver()

    background = _load_background(
        background_path,
        raw_spec_resolver=raw_spec_resolver,
        raw_resolver_context=raw_resolver_context,
    )

    records, load_elapsed_s = _load_inputs(
        image_paths,
        raw_spec_resolver=raw_spec_resolver,
        raw_resolver_context=raw_resolver_context,
    )
    loaded_inputs = _successful_inputs(records)
    background_applicable_total = sum(
        1
        for record in loaded_inputs
        if record.image is not None
        and _resolved_background(record.image, background) is not None
    )
    raw_fallback_total = len(loaded_inputs) - background_applicable_total
    phases: list[dict[str, object]] = [
        _load_phase_summary(records, load_elapsed_s=load_elapsed_s),
    ]

    phases.append(
        _run_static_phase(
            loaded_inputs,
            backend_mode=backend_mode,
        ),
    )
    phases.append(
        _run_dynamic_phase(
            loaded_inputs,
            backend_mode=backend_mode,
            threshold_value=threshold_value,
            avg_count_value=avg_count_value,
            background=background,
            mode="none",
        ),
    )
    phases.append(
        _run_dynamic_phase(
            loaded_inputs,
            backend_mode=backend_mode,
            threshold_value=threshold_value,
            avg_count_value=avg_count_value,
            background=background,
            mode="topk",
        ),
    )
    phases.append(
        _run_roi_phase(
            loaded_inputs,
            backend_mode=backend_mode,
            background=background,
        ),
    )
    phases.append(
        _run_preview_phase(
            loaded_inputs,
            backend_mode=backend_mode,
            background=background,
        ),
    )
    phases.append(
        _run_histogram_phase(
            loaded_inputs,
            backend_mode=backend_mode,
            background=background,
        ),
    )

    load_failures = _load_failures(records)
    report = {
        "requested_backend": backend_mode,
        "forced_backend": (
            backend_mode
            if backend_mode in {"native", "python"}
            else None
        ),
        "allow_native": bool(backend_mode != "python"),
        "dataset_root": str(dataset_root),
        "background_path": None if background_path is None else str(background_path),
        "background_source_kind": (
            None
            if background_path is None
            else source_kind_for_path(background_path)
        ),
        "discovered_file_count": len(records),
        "image_count": len(loaded_inputs),
        "successful_file_count": len(loaded_inputs),
        "failed_file_count": len(load_failures),
        "source_kinds_seen": sorted(
            {
                str(record.source_kind)
                for record in records
            },
        ),
        "source_kind_counts": _source_kind_counts(records),
        "benchmarked_source_kind_counts": _source_kind_counts(loaded_inputs),
        "phases": phases,
        "backend_status": native_backend.backend_status_snapshot(),
        "background_applicable_images": background_applicable_total,
        "background_raw_fallback_images": raw_fallback_total,
        "load_failures_by_reason": _sorted_counter(
            Counter(failure.reason for failure in load_failures),
        ),
    }
    report.update(_raw_report_fields(records))
    if verbose_files:
        report["files"] = [
            _serialize_input_record(record)
            for record in records
        ]
    if parity_check == "roi":
        report["roi_parity"] = _roi_parity_report(
            loaded_inputs,
            background=background,
            mismatch_limit=max(1, int(parity_limit)),
        )
    return report


def _run_subprocess(
    *,
    script_path: Path,
    dataset_root: Path,
    background_path: Path | None,
    backend_mode: str,
    threshold_value: float,
    avg_count_value: int,
    parity_check: str,
    parity_limit: int,
    raw_overrides: tuple[str, ...],
    verbose_files: bool,
) -> dict[str, object]:
    command = [
        sys.executable,
        str(script_path),
        "--run-once",
        "--dataset-root",
        str(dataset_root),
        "--backend",
        backend_mode,
        "--threshold",
        str(threshold_value),
        "--avg-count",
        str(avg_count_value),
        "--parity-check",
        parity_check,
        "--parity-limit",
        str(parity_limit),
    ]
    if background_path is not None:
        command.extend(["--background", str(background_path)])
    for item in raw_overrides:
        command.extend(["--raw-override", str(item)])
    if verbose_files:
        command.append("--verbose-files")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail_parts: list[str] = [
            f"Profile subprocess failed for backend '{backend_mode}'",
            f"Command: {' '.join(command)}",
        ]
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        if stderr:
            detail_parts.append(f"stderr:\n{stderr}")
        if stdout:
            detail_parts.append(f"stdout:\n{stdout}")
        raise SystemExit("\n\n".join(detail_parts))
    return json.loads(completed.stdout)


def _render_summary(report: dict[str, object]) -> str:
    status = dict(report["backend_status"])
    lines: list[str] = []
    requested_backend = str(report.get("requested_backend") or "unknown")
    forced_backend = report.get("forced_backend")
    header = f"[{requested_backend}]"
    if forced_backend:
        header += f" forced={forced_backend}"
    else:
        header += " forced=policy"
    header += (
        f" wrapper_active={status.get('active_backend')}"
        f" native_available={status.get('native_available')}"
        f" latched={status.get('native_latched_off')}"
    )
    lines.append(header)
    reason = status.get("last_fallback_reason")
    if reason:
        lines.append(f"  reason: {reason}")
    lines.append(
        "  dataset:"
        f" discovered={int(report.get('discovered_file_count', 0))}"
        f" loaded={int(report.get('image_count', 0))}"
        f" failed={int(report.get('failed_file_count', 0))}"
        f" source_kinds={','.join(report.get('source_kinds_seen', [])) or '-'}"
        f" background_applicable={int(report.get('background_applicable_images', 0))}"
        f" raw_fallback={int(report.get('background_raw_fallback_images', 0))}",
    )
    if int(report.get("raw_files_total", 0)) > 0:
        raw_decode_summary = dict(report.get("raw_decode_summary") or {})
        lines.append(
            "  raw_decode:"
            f" total={int(report.get('raw_files_total', 0))}"
            f" decoded={int(report.get('raw_files_decoded', 0))}"
            f" failed_spec={int(report.get('raw_files_failed_spec', 0))}"
            f" failed_decode={int(report.get('raw_files_failed_decode', 0))}",
        )
        pixel_formats_seen = list(raw_decode_summary.get("pixel_formats_seen") or [])
        if pixel_formats_seen:
            lines.append(
                "    pixel_formats="
                + ",".join(str(value) for value in pixel_formats_seen),
            )
        raw_failures_by_reason = dict(report.get("raw_failures_by_reason") or {})
        for reason_text, count in raw_failures_by_reason.items():
            lines.append(f"    raw_failure[{count}] {reason_text}")

    phase_headers = [
        ("phase", "Phase"),
        ("source_kind", "Source"),
        ("route_used", "Route"),
        ("route_reason", "Reason"),
        ("images", "Images"),
        ("elapsed_s", "Total(s)"),
        ("per_image_ms", "ms/img"),
        ("checksum", "Checksum"),
    ]
    formatted_rows: list[dict[str, str]] = []
    for phase in report["phases"]:
        formatted_rows.append(
            {
                "phase": str(phase.get("phase") or ""),
                "source_kind": str(phase.get("source_kind") or "-"),
                "route_used": str(phase.get("route_used") or "-"),
                "route_reason": str(phase.get("route_reason") or "-"),
                "images": str(int(phase.get("images") or 0)),
                "elapsed_s": str(phase.get("elapsed_s")),
                "per_image_ms": str(phase.get("per_image_ms")),
                "checksum": str(phase.get("checksum")),
            },
        )

    widths: dict[str, int] = {}
    for key, label in phase_headers:
        widths[key] = max(
            len(label),
            *(len(row[key]) for row in formatted_rows),
        )

    lines.append("  phases:")
    lines.append(
        "    "
        + "  ".join(label.ljust(widths[key]) for key, label in phase_headers),
    )
    lines.append(
        "    "
        + "  ".join("-" * widths[key] for key, _label in phase_headers),
    )
    for row in formatted_rows:
        lines.append(
            "    "
            + "  ".join(row[key].ljust(widths[key]) for key, _label in phase_headers),
        )

    notes: list[str] = []
    load_failures_by_reason = dict(report.get("load_failures_by_reason") or {})
    if load_failures_by_reason:
        for reason_text, count in load_failures_by_reason.items():
            notes.append(f"load_decode: {reason_text} ({count})")
    for phase in report["phases"]:
        if phase.get("skipped_reason"):
            notes.append(f"{phase.get('phase')}: {phase.get('skipped_reason')}")
        failures_by_reason = dict(phase.get("failures_by_reason") or {})
        for reason_text, count in failures_by_reason.items():
            notes.append(f"{phase.get('phase')}: {reason_text} ({count})")
    if notes:
        lines.append("  notes:")
        for note in notes:
            lines.append(f"    - {note}")

    roi_parity = report.get("roi_parity")
    if isinstance(roi_parity, dict):
        lines.append(
            "  roi_parity:"
            f" checked={roi_parity.get('checked_images', 0)}"
            f" mismatches={roi_parity.get('mismatch_count', 0)}"
            f" native_checksum={roi_parity.get('native_checksum', 0.0)}"
            f" python_checksum={roi_parity.get('python_checksum', 0.0)}",
        )
        mismatches = roi_parity.get("mismatches") or []
        if mismatches:
            first = mismatches[0]
            lines.append(f"    first_mismatch_path={first.get('path')}")
            lines.append(f"    roi_rect={first.get('roi_rect')}")
            lines.append(f"    background_applied={first.get('background_applied')}")
            lines.append(f"    native={first.get('native')}")
            lines.append(f"    python={first.get('python')}")
    return "\n".join(lines)


def _print_summary(report: dict[str, object]) -> None:
    print(_render_summary(report))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Profile FrameLab metrics wrappers on TIFF/RAW workloads.",
    )
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--background", type=Path, default=None)
    parser.add_argument(
        "--backend",
        choices=("native", "python", "both", "production"),
        default="both",
    )
    parser.add_argument("--threshold", type=float, default=65520.0)
    parser.add_argument("--avg-count", type=int, default=32)
    parser.add_argument(
        "--parity-check",
        choices=("none", "roi"),
        default="none",
    )
    parser.add_argument("--parity-limit", type=int, default=1)
    parser.add_argument(
        "--raw-override",
        action="append",
        default=[],
        help="Manual RAW decode fallback override using KEY=VALUE syntax.",
    )
    parser.add_argument(
        "--verbose-files",
        action="store_true",
        help="Include per-file load/decode details in JSON output.",
    )
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args(argv)

    dataset_root = args.dataset_root.resolve()
    background_path = None if args.background is None else args.background.resolve()
    if not dataset_root.exists():
        raise SystemExit(f"Dataset root does not exist: {dataset_root}")
    if not dataset_root.is_dir():
        raise SystemExit(f"Dataset root is not a directory: {dataset_root}")
    if background_path is not None and not background_path.exists():
        raise SystemExit(f"Background file does not exist: {background_path}")
    if background_path is not None and not background_path.is_file():
        raise SystemExit(f"Background path is not a file: {background_path}")

    try:
        raw_manual_overrides = _parse_raw_overrides(tuple(args.raw_override))
    except ValueError as exc:
        parser.error(str(exc))

    if args.run_once:
        report = _run_once(
            dataset_root=dataset_root,
            background_path=background_path,
            backend_mode=str(args.backend),
            threshold_value=float(args.threshold),
            avg_count_value=int(args.avg_count),
            parity_check=str(args.parity_check),
            parity_limit=int(args.parity_limit),
            raw_manual_overrides=raw_manual_overrides,
            verbose_files=bool(args.verbose_files),
        )
        print(json.dumps(report))
        return 0

    backends = ["native", "python"] if args.backend == "both" else [str(args.backend)]
    for backend_mode in backends:
        report = _run_subprocess(
            script_path=Path(__file__).resolve(),
            dataset_root=dataset_root,
            background_path=background_path,
            backend_mode=backend_mode,
            threshold_value=float(args.threshold),
            avg_count_value=int(args.avg_count),
            parity_check=(
                str(args.parity_check)
                if len(backends) == 1
                else "none"
            ),
            parity_limit=int(args.parity_limit),
            raw_overrides=tuple(args.raw_override),
            verbose_files=bool(args.verbose_files),
        )
        _print_summary(report)
    if str(args.parity_check) == "roi" and len(backends) > 1:
        parity_report = _run_once(
            dataset_root=dataset_root,
            background_path=background_path,
            backend_mode="production",
            threshold_value=float(args.threshold),
            avg_count_value=int(args.avg_count),
            parity_check="roi",
            parity_limit=int(args.parity_limit),
            raw_manual_overrides=raw_manual_overrides,
            verbose_files=bool(args.verbose_files),
        )
        _print_summary(
            {
                **parity_report,
                "requested_backend": "roi-parity",
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
