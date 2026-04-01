from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import framelab.native.backend as backend
from framelab.image_io import InvalidImageError
from framelab.raw_decode import RawDecodeSpec, RawDecodeSpecError
import tools.profile_metrics_backend as profile_module


pytestmark = [pytest.mark.core]


class _FakeNativeMetrics:
    @staticmethod
    def compute_static_metrics(image):
        arr = np.asarray(image)
        positive = arr[arr > 0]
        min_non_zero = int(np.min(positive)) if positive.size else 0
        max_pixel = int(np.max(arr)) if arr.size else 0
        return (min_non_zero, max_pixel)

    @staticmethod
    def compute_dynamic_metrics(image, **kwargs):
        arr = np.asarray(image, dtype=np.float64)
        background = kwargs.get("background")
        if background is not None:
            arr = arr - np.asarray(background, dtype=np.float64)
            arr = np.clip(arr, 0.0, None)
        flat = arr.ravel()
        sat_count = int(np.count_nonzero(flat >= float(kwargs["threshold_value"])))
        positive = flat[flat > 0]
        max_pixel = float(np.max(flat)) if flat.size else 0.0
        result = {
            "sat_count": sat_count,
            "min_non_zero": float(np.min(positive)) if positive.size else 0.0,
            "max_pixel": max_pixel,
            "avg_topk": None,
            "avg_topk_std": None,
            "avg_topk_sem": None,
        }
        if kwargs.get("mode") == "topk":
            count = max(1, int(kwargs.get("avg_count_value", 1)))
            top = np.sort(flat)[-count:]
            result["avg_topk"] = float(np.mean(top)) if top.size else 0.0
            result["avg_topk_std"] = float(np.std(top)) if top.size else 0.0
            result["avg_topk_sem"] = (
                float(np.std(top) / np.sqrt(top.size))
                if top.size
                else 0.0
            )
        return result

    @staticmethod
    def compute_roi_metrics(image, **kwargs):
        arr = np.asarray(image, dtype=np.float64)
        background = kwargs.get("background")
        if background is not None:
            arr = arr - np.asarray(background, dtype=np.float64)
            arr = np.clip(arr, 0.0, None)
        x0, y0, x1, y1 = kwargs["roi_rect"]
        roi = arr[y0:y1, x0:x1]
        if roi.size == 0:
            return (0.0, 0.0, 0.0, 0.0)
        std = float(np.std(roi))
        return (
            float(np.max(roi)),
            float(np.mean(roi)),
            std,
            float(std / np.sqrt(roi.size)),
        )

    @staticmethod
    def apply_background_f32(image, **kwargs):
        arr = np.asarray(image, dtype=np.float32)
        background = np.asarray(kwargs["background"], dtype=np.float32)
        corrected = arr - background
        if kwargs.get("clip_negative", True):
            corrected = np.maximum(corrected, 0.0)
        return corrected.astype(np.float32)

    @staticmethod
    def compute_value_range(image, **kwargs):
        arr = np.asarray(image, dtype=np.float64)
        background = kwargs.get("background")
        if background is not None:
            arr = arr - np.asarray(background, dtype=np.float64)
            if kwargs.get("clip_negative", True):
                arr = np.clip(arr, 0.0, None)
        if arr.size == 0:
            return (0.0, 0.0)
        return (float(np.min(arr)), float(np.max(arr)))

    @staticmethod
    def compute_histogram(image, **kwargs):
        arr = np.asarray(image, dtype=np.float64)
        background = kwargs.get("background")
        if background is not None:
            arr = arr - np.asarray(background, dtype=np.float64)
            if kwargs.get("clip_negative", True):
                arr = np.clip(arr, 0.0, None)
        counts, _edges = np.histogram(
            arr,
            bins=int(kwargs["bin_count"]),
            range=tuple(kwargs["value_range"]),
        )
        return counts.astype(np.uint64)


def _set_backend_state(monkeypatch, native_obj) -> None:
    monkeypatch.setattr(backend, "_native", native_obj, raising=False)
    monkeypatch.setattr(
        backend,
        "_metrics_native_enabled",
        native_obj is not None,
        raising=False,
    )
    monkeypatch.setattr(
        backend,
        "_active_metrics_backend",
        "native" if native_obj is not None else "python",
        raising=False,
    )
    monkeypatch.setattr(
        backend,
        "_last_native_fallback_reason",
        None if native_obj is not None else "Native extension unavailable",
        raising=False,
    )
    monkeypatch.setattr(
        backend,
        "_pending_backend_status_notice",
        None,
        raising=False,
    )
    monkeypatch.setattr(
        backend,
        "_native_backend_notice_emitted",
        False,
        raising=False,
    )


def test_find_images_includes_bin_suffix(tmp_path: Path) -> None:
    tif_path = tmp_path / "img.tif"
    tiff_path = tmp_path / "img2.tiff"
    raw_path = tmp_path / "img3.bin"
    ignored = tmp_path / "notes.txt"
    nested = tmp_path / "nested"
    nested.mkdir()
    raw_nested = nested / "img4.bin"
    for path in (tif_path, tiff_path, raw_path, ignored, raw_nested):
        path.write_bytes(b"test")

    found = profile_module._find_images(tmp_path)

    assert found == sorted([tif_path, tiff_path, raw_path, raw_nested])


def test_parse_raw_overrides_coerces_strings_and_numbers() -> None:
    actual = profile_module._parse_raw_overrides(
        [
            "camera_settings.pixel_format=Mono12Packed",
            "camera_settings.resolution_x=128",
            "camera_settings.offset_bytes=12",
        ],
    )

    assert actual == {
        "camera_settings.pixel_format": "Mono12Packed",
        "camera_settings.resolution_x": 128,
        "camera_settings.offset_bytes": 12,
    }


def test_run_once_production_mode_reports_tiff_policy_routes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "img.tif"
    image = np.array([[1, 2], [3, 4]], dtype=np.uint16)

    class _FakeNative:
        @staticmethod
        def compute_dynamic_metrics(image, **kwargs):
            if kwargs["mode"] == "topk":
                return {
                    "sat_count": 2,
                    "min_non_zero": 1,
                    "max_pixel": 4,
                    "avg_topk": 3.5,
                    "avg_topk_std": 0.5,
                    "avg_topk_sem": 0.25,
                }
            raise AssertionError("production dynamic_none should not route native")

        @staticmethod
        def compute_roi_metrics(image, **kwargs):
            return (4.0, 2.5, 1.0, 0.5)

        @staticmethod
        def compute_histogram(image, **kwargs):
            return np.array([1, 1, 2], dtype=np.uint64)

    _set_backend_state(monkeypatch, _FakeNative())
    monkeypatch.setattr(profile_module, "_find_images", lambda root: [image_path])
    monkeypatch.setattr(
        profile_module,
        "read_2d_image",
        lambda path, **kwargs: image,
    )

    report = profile_module._run_once(
        dataset_root=tmp_path,
        background_path=None,
        backend_mode="production",
        threshold_value=3.0,
        avg_count_value=2,
        parity_check="none",
        parity_limit=1,
    )

    phases = {phase["phase"]: phase for phase in report["phases"]}

    assert report["forced_backend"] is None
    assert report["source_kind_counts"] == {"tiff": 1}
    assert phases["load_decode"]["images"] == 1
    assert phases["static_scan"]["route_used"] == "python"
    assert phases["static_scan"]["route_reason"] == "tiff_static_python"
    assert phases["dynamic_none"]["route_used"] == "python"
    assert phases["dynamic_none"]["route_reason"] == "tiff_dynamic_none_python"
    assert phases["dynamic_topk"]["route_used"] == "native"
    assert phases["dynamic_topk"]["route_reason"] == "topk_native"
    assert phases["roi_metrics"]["route_used"] == "native"
    assert phases["exact_histogram"]["route_used"] == "native"


def test_run_once_reports_raw_load_failures_and_mixed_routing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tiff_path = tmp_path / "img.tif"
    raw_good_path = tmp_path / "good.bin"
    raw_bad_spec_path = tmp_path / "bad-spec.bin"
    raw_bad_decode_path = tmp_path / "bad-decode.bin"
    tiff_image = np.array([[1, 2], [3, 4]], dtype=np.uint16)
    raw_image = np.array([[10, 20], [30, 40]], dtype=np.uint16)

    _set_backend_state(monkeypatch, _FakeNativeMetrics())
    monkeypatch.setattr(
        profile_module,
        "_find_images",
        lambda root: [
            tiff_path,
            raw_good_path,
            raw_bad_spec_path,
            raw_bad_decode_path,
        ],
    )

    good_spec = RawDecodeSpec(
        source_kind="raw",
        pixel_format="mono12packed",
        width=2,
        height=2,
        stride_bytes=None,
        offset_bytes=0,
    )

    def _resolve_raw(path, *, context=None):
        resolved = Path(path)
        if resolved == raw_bad_spec_path:
            raise RawDecodeSpecError(
                "Missing RAW decode spec fields: pixel_format, width, height",
            )
        if resolved.suffix.lower() == ".bin":
            return good_spec
        raise AssertionError("unexpected non-raw resolution request")

    read_calls: list[dict[str, object]] = []

    def _read(path, **kwargs):
        resolved = Path(path)
        read_calls.append(
            {
                "path": resolved,
                "raw_spec_resolver": kwargs.get("raw_spec_resolver"),
                "raw_resolver_context": kwargs.get("raw_resolver_context"),
            },
        )
        if resolved.suffix.lower() == ".bin":
            assert callable(kwargs["raw_spec_resolver"])
            assert kwargs["raw_resolver_context"] is not None
            spec = kwargs["raw_spec_resolver"](
                resolved,
                context=kwargs["raw_resolver_context"],
            )
            assert spec.pixel_format == "mono12packed"
        if resolved == tiff_path:
            return tiff_image
        if resolved == raw_good_path:
            return raw_image
        if resolved == raw_bad_decode_path:
            raise InvalidImageError("native decode error")
        raise AssertionError(f"unexpected path {resolved}")

    monkeypatch.setattr(profile_module, "resolve_raw_decode_spec", _resolve_raw)
    monkeypatch.setattr(profile_module, "read_2d_image", _read)

    report = profile_module._run_once(
        dataset_root=tmp_path,
        background_path=None,
        backend_mode="production",
        threshold_value=3.0,
        avg_count_value=2,
        parity_check="none",
        parity_limit=1,
        verbose_files=True,
    )

    phases = {phase["phase"]: phase for phase in report["phases"]}

    assert report["discovered_file_count"] == 4
    assert report["image_count"] == 2
    assert report["successful_file_count"] == 2
    assert report["failed_file_count"] == 2
    assert report["source_kinds_seen"] == ["raw", "tiff"]
    assert report["source_kind_counts"] == {"raw": 3, "tiff": 1}
    assert report["benchmarked_source_kind_counts"] == {"raw": 1, "tiff": 1}
    assert report["raw_files_total"] == 3
    assert report["raw_files_decoded"] == 1
    assert report["raw_files_failed_spec"] == 1
    assert report["raw_files_failed_decode"] == 1
    assert report["raw_decode_summary"]["pixel_formats_seen"] == ["mono12packed"]
    assert phases["load_decode"]["images"] == 2
    assert phases["load_decode"]["failed_images"] == 2
    assert phases["static_scan"]["route_used"] == "mixed"
    assert phases["static_scan"]["route_reason"] == "mixed"
    assert phases["static_scan"]["source_kind"] == "mixed"
    assert phases["static_scan"]["source_kind_counts"] == {"raw": 1, "tiff": 1}
    assert phases["static_scan"]["route_breakdown"] == [
        {
            "source_kind": "raw",
            "route_used": "native",
            "route_reason": "raw_native",
            "count": 1,
            "effective_mode": None,
        },
        {
            "source_kind": "tiff",
            "route_used": "python",
            "route_reason": "tiff_static_python",
            "count": 1,
            "effective_mode": None,
        },
    ]
    assert [item["load_status"] for item in report["files"]] == [
        "loaded",
        "loaded",
        "failed_spec",
        "failed_decode",
    ]
    assert report["files"][1]["raw_spec"]["pixel_format"] == "mono12packed"
    assert report["files"][2]["raw_spec_resolved"] is False
    assert report["files"][3]["raw_spec_resolved"] is True
    assert all(
        call["raw_spec_resolver"] is not None
        for call in read_calls
        if call["path"].suffix.lower() == ".bin"
    )


def test_run_once_uses_shared_raw_loader_for_background_and_manual_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "frame.bin"
    background_path = tmp_path / "background.bin"
    image = np.array([[5, 6], [7, 8]], dtype=np.uint16)
    background = np.array([[1, 1], [1, 1]], dtype=np.uint16)
    override_payload = {
        "camera_settings.pixel_format": "mono8",
        "camera_settings.resolution_x": 2,
        "camera_settings.resolution_y": 2,
    }

    monkeypatch.setattr(profile_module, "_find_images", lambda root: [raw_path])

    def _resolve_raw(path, *, context=None):
        assert context is not None
        assert dict(context.manual_overrides or {}) == override_payload
        return RawDecodeSpec(
            source_kind="raw",
            pixel_format=str(context.manual_overrides["camera_settings.pixel_format"]),
            width=int(context.manual_overrides["camera_settings.resolution_x"]),
            height=int(context.manual_overrides["camera_settings.resolution_y"]),
            stride_bytes=None,
            offset_bytes=0,
        )

    read_calls: list[dict[str, object]] = []

    def _read(path, **kwargs):
        resolved = Path(path)
        read_calls.append(
            {
                "path": resolved,
                "raw_spec_resolver": kwargs.get("raw_spec_resolver"),
                "raw_resolver_context": kwargs.get("raw_resolver_context"),
            },
        )
        spec = kwargs["raw_spec_resolver"](
            resolved,
            context=kwargs["raw_resolver_context"],
        )
        assert spec.pixel_format == "mono8"
        if resolved == background_path:
            return background
        return image

    monkeypatch.setattr(profile_module, "resolve_raw_decode_spec", _resolve_raw)
    monkeypatch.setattr(profile_module, "read_2d_image", _read)

    report = profile_module._run_once(
        dataset_root=tmp_path,
        background_path=background_path,
        backend_mode="python",
        threshold_value=3.0,
        avg_count_value=2,
        parity_check="none",
        parity_limit=1,
        raw_manual_overrides=override_payload,
    )

    assert report["background_source_kind"] == "raw"
    assert report["raw_files_total"] == 1
    assert report["background_applicable_images"] == 1
    assert [call["path"] for call in read_calls] == [background_path, raw_path]
    assert all(call["raw_spec_resolver"] is not None for call in read_calls)
    assert all(call["raw_resolver_context"] is not None for call in read_calls)


def test_run_once_phase_failures_do_not_abort_other_images(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tiff_path = tmp_path / "img.tif"
    raw_path = tmp_path / "frame.bin"
    tiff_image = np.array([[1, 2], [3, 4]], dtype=np.uint16)
    raw_image = np.array([[9, 9], [9, 9]], dtype=np.uint16)

    monkeypatch.setattr(profile_module, "_find_images", lambda root: [tiff_path, raw_path])
    monkeypatch.setattr(
        profile_module,
        "resolve_raw_decode_spec",
        lambda path, *, context=None: RawDecodeSpec(
            source_kind="raw",
            pixel_format="mono8",
            width=2,
            height=2,
            stride_bytes=None,
            offset_bytes=0,
        ),
    )
    monkeypatch.setattr(
        profile_module,
        "read_2d_image",
        lambda path, **kwargs: raw_image if Path(path) == raw_path else tiff_image,
    )

    def _compute_dynamic_metrics(image, **kwargs):
        if int(np.asarray(image)[0, 0]) == 9:
            raise ValueError("metric blew up")
        return {
            "sat_count": 1,
            "min_non_zero": 1,
            "max_pixel": 4,
            "avg_topk": 4.0,
            "avg_topk_std": 0.0,
            "avg_topk_sem": 0.0,
        }

    monkeypatch.setattr(
        profile_module.native_backend,
        "compute_dynamic_metrics",
        _compute_dynamic_metrics,
    )

    report = profile_module._run_once(
        dataset_root=tmp_path,
        background_path=None,
        backend_mode="python",
        threshold_value=3.0,
        avg_count_value=2,
        parity_check="none",
        parity_limit=1,
    )

    phases = {phase["phase"]: phase for phase in report["phases"]}

    assert report["image_count"] == 2
    assert phases["dynamic_none"]["images"] == 1
    assert phases["dynamic_none"]["failed_images"] == 1
    assert phases["dynamic_none"]["failures_by_reason"] == {
        "ValueError: metric blew up": 1,
    }
    assert phases["roi_metrics"]["images"] == 2
    assert phases["exact_histogram"]["images"] == 2


def test_render_summary_includes_route_and_reason_columns() -> None:
    report = {
        "requested_backend": "python",
        "forced_backend": "python",
        "discovered_file_count": 65,
        "image_count": 65,
        "failed_file_count": 0,
        "background_applicable_images": 0,
        "background_raw_fallback_images": 65,
        "source_kinds_seen": ["tiff"],
        "backend_status": {
            "active_backend": "native",
            "native_available": True,
            "native_latched_off": False,
            "last_fallback_reason": None,
        },
        "phases": [
            {
                "phase": "static_scan",
                "source_kind": "tiff",
                "route_used": "python",
                "route_reason": "override_python",
                "images": 65,
                "elapsed_s": 4.3,
                "per_image_ms": 66.2,
                "checksum": 826432.0,
            },
        ],
    }

    rendered = profile_module._render_summary(report)

    assert "[python] forced=python" in rendered
    assert "wrapper_active=native" in rendered
    assert "Phase" in rendered
    assert "Source" in rendered
    assert "Route" in rendered
    assert "Reason" in rendered
    assert "static_scan" in rendered
    assert "override_python" in rendered
