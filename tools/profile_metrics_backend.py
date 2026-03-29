from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from framelab.image_io import read_2d_image, supported_suffixes
from framelab.native import backend as native_backend


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
    source_kind = "unknown"
    backend_override = None

    if operation in {"static_scan", "dynamic_metrics"}:
        source_kind = "tiff"
        if backend_mode == "native":
            backend_override = "native"
        elif backend_mode == "python":
            backend_override = "python"

    return {
        "allow_native": bool(allow_native),
        "source_kind": str(source_kind),
        "backend_override": backend_override,
    }


def _phase_route(
    *,
    backend_mode: str,
    operation: str,
    mode: str | None = None,
    threshold_only: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    options = _phase_backend_options(
        backend_mode=backend_mode,
        operation=operation,
    )
    decision = native_backend.describe_metric_route(
        operation,
        source_kind=str(options["source_kind"]),
        mode=mode,
        threshold_only=threshold_only,
        allow_native=bool(options["allow_native"]),
        backend_override=options["backend_override"],
    )
    return (dict(decision), options)


def _phase_summary(
    *,
    name: str,
    started_at: float,
    item_count: int,
    checksum: float,
    route_info: dict[str, object] | None = None,
    background_applied_images: int | None = None,
    raw_fallback_images: int | None = None,
    skipped_reason: str | None = None,
) -> dict[str, object]:
    elapsed = time.perf_counter() - started_at
    summary = {
        "phase": name,
        "images": int(item_count),
        "elapsed_s": round(elapsed, 6),
        "per_image_ms": round((elapsed * 1000.0 / item_count), 6) if item_count else 0.0,
        "checksum": float(checksum),
    }
    if route_info is not None:
        summary["route_used"] = str(route_info.get("route_used") or "")
        summary["route_reason"] = str(route_info.get("route_reason") or "")
        summary["source_kind"] = str(route_info.get("source_kind") or "")
        summary["effective_mode"] = route_info.get("effective_mode")
    if background_applied_images is not None:
        summary["background_applied_images"] = int(background_applied_images)
    if raw_fallback_images is not None:
        summary["raw_fallback_images"] = int(raw_fallback_images)
    if skipped_reason:
        summary["skipped_reason"] = str(skipped_reason)
    return summary


def _tuple_checksum(values: tuple[float, ...]) -> float:
    arr = np.asarray(values, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0
    return float(np.sum(finite, dtype=np.float64))


def _roi_parity_report(
    images: list[tuple[Path, np.ndarray]],
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

    for path, image in images:
        reference = _resolved_background(image, background)
        if reference is None:
            raw_fallback_images += 1
        else:
            background_applied_images += 1
        roi_rect = _default_roi_rect(tuple(np.asarray(image).shape))
        native_result = tuple(
            float(value)
            for value in native_backend.compute_roi_metrics(
                image,
                roi_rect=roi_rect,
                background=reference,
                allow_native=True,
            )
        )
        python_result = tuple(
            float(value)
            for value in native_backend.compute_roi_metrics(
                image,
                roi_rect=roi_rect,
                background=reference,
                allow_native=False,
            )
        )
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
                        "path": str(path),
                        "roi_rect": [int(v) for v in roi_rect],
                        "background_applied": bool(reference is not None),
                        "native": list(native_result),
                        "python": list(python_result),
                    },
                )

    return {
        "checked_images": len(images),
        "background_applied_images": background_applied_images,
        "raw_fallback_images": raw_fallback_images,
        "native_checksum": float(checksum_native),
        "python_checksum": float(checksum_python),
        "mismatch_count": mismatch_count,
        "mismatches": mismatches,
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
) -> dict[str, object]:
    image_paths = _find_images(dataset_root)
    if not image_paths:
        raise SystemExit(f"No supported TIFF images found under {dataset_root}")

    background = None
    if background_path is not None:
        background = np.asarray(read_2d_image(background_path))

    images = [(path, np.asarray(read_2d_image(path))) for path in image_paths]
    background_applicable_total = sum(
        1 for _path, image in images if _resolved_background(image, background) is not None
    )
    raw_fallback_total = len(images) - background_applicable_total
    phases: list[dict[str, object]] = []

    static_route, static_options = _phase_route(
        backend_mode=backend_mode,
        operation="static_scan",
    )
    started = time.perf_counter()
    checksum = 0.0
    for _path, image in images:
        min_non_zero, max_pixel = native_backend.compute_static_metrics(
            image,
            source_kind=str(static_options["source_kind"]),
            allow_native=bool(static_options["allow_native"]),
            backend_override=static_options["backend_override"],
        )
        checksum += float(min_non_zero) + float(max_pixel)
    phases.append(
        _phase_summary(
            name="static_scan",
            started_at=started,
            item_count=len(images),
            checksum=checksum,
            route_info=static_route,
        ),
    )

    dynamic_none_route, dynamic_none_options = _phase_route(
        backend_mode=backend_mode,
        operation="dynamic_metrics",
        mode="none",
    )
    started = time.perf_counter()
    checksum = 0.0
    for _path, image in images:
        reference = _resolved_background(image, background)
        result = native_backend.compute_dynamic_metrics(
            image,
            threshold_value=threshold_value,
            mode="none",
            avg_count_value=avg_count_value,
            background=reference,
            source_kind=str(dynamic_none_options["source_kind"]),
            allow_native=bool(dynamic_none_options["allow_native"]),
            backend_override=dynamic_none_options["backend_override"],
        )
        checksum += (
            float(result["sat_count"])
            + float(result["min_non_zero"])
            + float(result["max_pixel"])
        )
    phases.append(
        _phase_summary(
            name="dynamic_none",
            started_at=started,
            item_count=len(images),
            checksum=checksum,
            route_info=dynamic_none_route,
            background_applied_images=background_applicable_total,
            raw_fallback_images=raw_fallback_total,
            skipped_reason=(
                "No matching background shape found"
                if background is not None and background_applicable_total == 0
                else None
            ),
        ),
    )

    dynamic_topk_route, dynamic_topk_options = _phase_route(
        backend_mode=backend_mode,
        operation="dynamic_metrics",
        mode="topk",
    )
    started = time.perf_counter()
    checksum = 0.0
    for _path, image in images:
        reference = _resolved_background(image, background)
        result = native_backend.compute_dynamic_metrics(
            image,
            threshold_value=threshold_value,
            mode="topk",
            avg_count_value=avg_count_value,
            background=reference,
            source_kind=str(dynamic_topk_options["source_kind"]),
            allow_native=bool(dynamic_topk_options["allow_native"]),
            backend_override=dynamic_topk_options["backend_override"],
        )
        checksum += (
            float(result["sat_count"])
            + float(result["min_non_zero"])
            + float(result["max_pixel"])
            + float(result["avg_topk"] or 0.0)
        )
    phases.append(
        _phase_summary(
            name="dynamic_topk",
            started_at=started,
            item_count=len(images),
            checksum=checksum,
            route_info=dynamic_topk_route,
            background_applied_images=background_applicable_total,
            raw_fallback_images=raw_fallback_total,
            skipped_reason=(
                "No matching background shape found"
                if background is not None and background_applicable_total == 0
                else None
            ),
        ),
    )

    roi_route, roi_options = _phase_route(
        backend_mode=backend_mode,
        operation="roi_metrics",
    )
    started = time.perf_counter()
    checksum = 0.0
    for _path, image in images:
        reference = _resolved_background(image, background)
        roi_max, roi_mean, roi_std, roi_sem = native_backend.compute_roi_metrics(
            image,
            roi_rect=_default_roi_rect(tuple(np.asarray(image).shape)),
            background=reference,
            allow_native=bool(roi_options["allow_native"]),
        )
        checksum += float(roi_max) + float(roi_mean) + float(roi_std) + float(roi_sem)
    phases.append(
        _phase_summary(
            name="roi_metrics",
            started_at=started,
            item_count=len(images),
            checksum=checksum,
            route_info=roi_route,
            background_applied_images=background_applicable_total,
            raw_fallback_images=raw_fallback_total,
            skipped_reason=(
                "No matching background shape found"
                if background is not None and background_applicable_total == 0
                else None
            ),
        ),
    )

    preview_route, preview_options = _phase_route(
        backend_mode=backend_mode,
        operation="apply_background_f32",
    )
    corrected_ready = 0
    started = time.perf_counter()
    checksum = 0.0
    for _path, image in images:
        reference = _resolved_background(image, background)
        if reference is None:
            continue
        corrected = native_backend.apply_background_f32(
            image,
            background=reference,
            allow_native=bool(preview_options["allow_native"]),
        )
        checksum += float(np.sum(corrected, dtype=np.float64))
        corrected_ready += 1
    phases.append(
        _phase_summary(
            name="exact_corrected_preview",
            started_at=started,
            item_count=corrected_ready,
            checksum=checksum,
            route_info=preview_route,
            background_applied_images=background_applicable_total,
            raw_fallback_images=raw_fallback_total,
            skipped_reason=(
                "No background file provided"
                if background is None
                else (
                    "No matching background shape found"
                    if corrected_ready == 0
                    else None
                )
            ),
        ),
    )

    histogram_route, histogram_options = _phase_route(
        backend_mode=backend_mode,
        operation="compute_histogram",
    )
    range_options = _phase_backend_options(
        backend_mode=backend_mode,
        operation="compute_value_range",
    )
    started = time.perf_counter()
    checksum = 0.0
    histogram_count = 0
    for _path, image in images:
        reference = _resolved_background(image, background)
        if reference is None:
            data_min, data_max = _finite_min_max(image)
        else:
            data_min, data_max = native_backend.compute_value_range(
                image,
                background=reference,
                allow_native=bool(range_options["allow_native"]),
            )
        range_min, range_max = _histogram_range(data_min, data_max)
        bin_count = _histogram_bins(
            image,
            range_min=range_min,
            range_max=range_max,
            background_used=reference is not None,
        )
        counts = native_backend.compute_histogram(
            image,
            value_range=(range_min, range_max),
            bin_count=bin_count,
            background=reference,
            allow_native=bool(histogram_options["allow_native"]),
        )
        checksum += float(np.sum(counts, dtype=np.float64))
        histogram_count += 1
    phases.append(
        _phase_summary(
            name="exact_histogram",
            started_at=started,
            item_count=histogram_count,
            checksum=checksum,
            route_info=histogram_route,
            background_applied_images=background_applicable_total,
            raw_fallback_images=raw_fallback_total,
            skipped_reason=(
                "No background file provided"
                if background is None
                else (
                    "No matching background shape found"
                    if background_applicable_total == 0
                    else None
                )
            ),
        ),
    )

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
        "image_count": len(images),
        "phases": phases,
        "backend_status": native_backend.backend_status_snapshot(),
        "background_applicable_images": background_applicable_total,
        "background_raw_fallback_images": raw_fallback_total,
    }
    if parity_check == "roi":
        report["roi_parity"] = _roi_parity_report(
            images,
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
        f" images={int(report.get('image_count', 0))}"
        f" background_applicable={int(report.get('background_applicable_images', 0))}"
        f" raw_fallback={int(report.get('background_raw_fallback_images', 0))}",
    )

    phase_headers = [
        ("phase", "Phase"),
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

    notes = [
        f"{phase.get('phase')}: {phase.get('skipped_reason')}"
        for phase in report["phases"]
        if phase.get("skipped_reason")
    ]
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
        description="Profile FrameLab native metrics wrappers on TIFF workloads.",
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

    if args.run_once:
        report = _run_once(
            dataset_root=dataset_root,
            background_path=background_path,
            backend_mode=str(args.backend),
            threshold_value=float(args.threshold),
            avg_count_value=int(args.avg_count),
            parity_check=str(args.parity_check),
            parity_limit=int(args.parity_limit),
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
