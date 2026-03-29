from __future__ import annotations

import math

import numpy as np
import pytest

import framelab.native.backend as backend
from framelab.raw_decode import RawDecodeSpec, RawDecodeSpecError


pytestmark = [pytest.mark.core]


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


def test_static_metrics_fall_back_cleanly_when_native_unavailable(monkeypatch) -> None:
    _set_backend_state(monkeypatch, None)

    result = backend.compute_static_metrics(
        np.array([[0, 2], [7, 1]], dtype=np.uint16),
    )

    assert result == (1, 7)
    assert backend.active_metrics_backend() == "python"
    assert backend.consume_backend_status_notice() is None


def test_describe_metric_route_uses_python_for_tiff_static_scan(monkeypatch) -> None:
    _set_backend_state(monkeypatch, object())

    decision = backend.describe_metric_route(
        "static_scan",
        source_kind="tiff",
    )

    assert decision["route_used"] == "python"
    assert decision["route_reason"] == "tiff_static_python"


def test_describe_metric_route_uses_python_for_tiff_dynamic_none(monkeypatch) -> None:
    _set_backend_state(monkeypatch, object())

    decision = backend.describe_metric_route(
        "dynamic_metrics",
        source_kind="tiff",
        mode="none",
    )

    assert decision["route_used"] == "python"
    assert decision["route_reason"] == "tiff_dynamic_none_python"
    assert decision["effective_mode"] == "none"


def test_describe_metric_route_uses_native_for_tiff_dynamic_topk(monkeypatch) -> None:
    _set_backend_state(monkeypatch, object())

    decision = backend.describe_metric_route(
        "dynamic_metrics",
        source_kind="tiff",
        mode="topk",
    )

    assert decision["route_used"] == "native"
    assert decision["route_reason"] == "topk_native"
    assert decision["effective_mode"] == "topk"


def test_describe_metric_route_uses_native_for_raw_static_scan(monkeypatch) -> None:
    _set_backend_state(monkeypatch, object())

    decision = backend.describe_metric_route(
        "static_scan",
        source_kind="raw",
    )

    assert decision["route_used"] == "native"
    assert decision["route_reason"] == "raw_native"


def test_dynamic_metrics_use_native_when_available_and_emit_one_shot_notice(
    monkeypatch,
) -> None:
    class _FakeNative:
        @staticmethod
        def compute_dynamic_metrics(image, **kwargs):
            assert kwargs["mode"] == "none"
            return {
                "sat_count": 12,
                "min_non_zero": 3,
                "max_pixel": 77,
                "avg_topk": None,
                "avg_topk_std": None,
                "avg_topk_sem": None,
            }

    _set_backend_state(monkeypatch, _FakeNative())

    result = backend.compute_dynamic_metrics(
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
        threshold_value=3,
        mode="topk",
        avg_count_value=2,
        threshold_only=True,
        backend_override="native",
    )

    assert result["sat_count"] == 12
    assert backend.active_metrics_backend() == "native"
    assert backend.consume_backend_status_notice() == "Using native metrics backend"
    assert backend.consume_backend_status_notice() is None


def test_backend_status_snapshot_reports_native_and_latched_failure(monkeypatch) -> None:
    class _FailingNative:
        @staticmethod
        def compute_histogram(image, **kwargs):
            raise RuntimeError("hist fail")

    _set_backend_state(monkeypatch, _FailingNative())

    initial = backend.backend_status_snapshot()
    assert initial["native_available"] is True
    assert initial["active_backend"] == "native"
    assert initial["native_latched_off"] is False

    result = backend.compute_histogram(
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
        value_range=(1.0, 4.0),
        bin_count=4,
    )

    assert int(np.sum(result)) == 4
    snapshot = backend.backend_status_snapshot()
    assert snapshot["native_available"] is True
    assert snapshot["active_backend"] == "python"
    assert snapshot["native_latched_off"] is True
    assert "compute_histogram failed" in str(snapshot["last_fallback_reason"])
    assert (
        backend.consume_backend_status_notice()
        == "Native metrics failed; using Python fallback"
    )


def test_dynamic_metrics_treat_roi_mode_as_none(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _FakeNative:
        @staticmethod
        def compute_dynamic_metrics(image, **kwargs):
            calls.append(dict(kwargs))
            return {
                "sat_count": 4,
                "min_non_zero": 1,
                "max_pixel": 9,
                "avg_topk": None,
                "avg_topk_std": None,
                "avg_topk_sem": None,
            }

    _set_backend_state(monkeypatch, _FakeNative())

    result = backend.compute_dynamic_metrics(
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
        threshold_value=2,
        mode="roi",
        avg_count_value=8,
        backend_override="native",
    )

    assert result["sat_count"] == 4
    assert len(calls) == 1
    assert calls[0]["mode"] == "none"


def test_roi_metrics_disable_native_after_failure_and_fall_back(monkeypatch) -> None:
    class _FailingNative:
        @staticmethod
        def compute_roi_metrics(image, **kwargs):
            raise RuntimeError("boom")

    _set_backend_state(monkeypatch, _FailingNative())

    result = backend.compute_roi_metrics(
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
        roi_rect=(0, 0, 2, 2),
    )

    assert result[0] == pytest.approx(4.0)
    assert result[1] == pytest.approx(2.5)
    assert result[2] == pytest.approx(np.std(np.array([1.0, 2.0, 3.0, 4.0])))
    assert result[3] == pytest.approx(result[2] / math.sqrt(4.0))
    assert backend.active_metrics_backend() == "python"
    assert "compute_roi_metrics failed" in str(backend.last_native_fallback_reason())


def test_apply_background_f32_returns_float32_and_supports_force_python(
    monkeypatch,
) -> None:
    class _FakeNative:
        @staticmethod
        def apply_background_f32(image, **kwargs):
            return np.full_like(np.asarray(image, dtype=np.float32), 7.0)

    image = np.array([[5, 6], [7, 8]], dtype=np.uint16)
    background = np.array([[1, 2], [3, 4]], dtype=np.uint16)
    _set_backend_state(monkeypatch, _FakeNative())

    native_result = backend.apply_background_f32(
        image,
        background=background,
    )
    python_result = backend.apply_background_f32(
        image,
        background=background,
        allow_native=False,
    )

    assert native_result.dtype == np.float32
    np.testing.assert_allclose(native_result, np.full((2, 2), 7.0, dtype=np.float32))
    np.testing.assert_allclose(
        python_result,
        np.array([[4.0, 4.0], [4.0, 4.0]], dtype=np.float32),
    )


def test_compute_histogram_uses_python_policy_but_can_force_python(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _FakeNative:
        @staticmethod
        def compute_histogram(image, **kwargs):
            calls.append(dict(kwargs))
            return np.array([1, 2, 3], dtype=np.uint64)

        @staticmethod
        def compute_value_range(image, **kwargs):
            return (0.0, 5.0)

    _set_backend_state(monkeypatch, _FakeNative())
    image = np.array([[0, 1], [2, 3]], dtype=np.uint16)

    native_counts = backend.compute_histogram(
        image,
        value_range=(0.0, 3.0),
        bin_count=3,
    )
    python_counts = backend.compute_histogram(
        image,
        value_range=(0.0, 3.0),
        bin_count=3,
        allow_native=False,
    )

    assert len(calls) == 1
    assert calls[0]["bin_count"] == 3
    np.testing.assert_array_equal(native_counts, np.array([1, 2, 3], dtype=np.uint64))
    np.testing.assert_array_equal(
        python_counts,
        np.array([1, 1, 2], dtype=np.uint64),
    )


def test_histogram_native_paths_coerce_non_contiguous_inputs(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _FakeNative:
        @staticmethod
        def compute_value_range(image, **kwargs):
            image_arr = np.asarray(image)
            background_arr = np.asarray(kwargs["background"])
            calls.append(
                {
                    "kind": "range",
                    "image_contiguous": bool(image_arr.flags.c_contiguous),
                    "background_contiguous": bool(background_arr.flags.c_contiguous),
                },
            )
            return (float(np.min(image_arr)), float(np.max(image_arr)))

        @staticmethod
        def compute_histogram(image, **kwargs):
            image_arr = np.asarray(image)
            background_arr = np.asarray(kwargs["background"])
            calls.append(
                {
                    "kind": "hist",
                    "image_contiguous": bool(image_arr.flags.c_contiguous),
                    "background_contiguous": bool(background_arr.flags.c_contiguous),
                },
            )
            return np.array([1, 1, 2], dtype=np.uint64)

    _set_backend_state(monkeypatch, _FakeNative())
    image = np.arange(64, dtype=np.float32).reshape(8, 8)[:, ::2]
    background = np.ones_like(image)

    value_range = backend.compute_value_range(
        image,
        background=background,
    )
    counts = backend.compute_histogram(
        image,
        value_range=value_range,
        bin_count=3,
        background=background,
    )

    assert calls == [
        {
            "kind": "range",
            "image_contiguous": True,
            "background_contiguous": True,
        },
        {
            "kind": "hist",
            "image_contiguous": True,
            "background_contiguous": True,
        },
    ]
    np.testing.assert_array_equal(counts, np.array([1, 1, 2], dtype=np.uint64))


def test_decode_raw_file_accepts_validated_spec_and_calls_native(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "frame.raw"
    path.write_bytes(b"\x00" * 16)
    calls: list[dict[str, object]] = []

    class _FakeNative:
        @staticmethod
        def decode_raw_file(
            candidate,
            pixel_format,
            width,
            height,
            *,
            stride_bytes,
            offset_bytes,
        ):
            calls.append(
                {
                    "path": candidate,
                    "pixel_format": pixel_format,
                    "width": width,
                    "height": height,
                    "stride_bytes": stride_bytes,
                    "offset_bytes": offset_bytes,
                },
            )
            return np.arange(width * height, dtype=np.uint16).reshape(height, width)

    monkeypatch.setattr(backend, "_native", _FakeNative(), raising=False)

    result = backend.decode_raw_file(
        str(path),
        spec=RawDecodeSpec(
            source_kind="raw",
            pixel_format=" MONO8 ",
            width=4,
            height=2,
            stride_bytes=0,
            offset_bytes=6,
        ),
    )

    assert calls == [
        {
            "path": str(path),
            "pixel_format": "mono8",
            "width": 4,
            "height": 2,
            "stride_bytes": 0,
            "offset_bytes": 6,
        },
    ]
    np.testing.assert_array_equal(result, np.arange(8, dtype=np.uint16).reshape(2, 4))


def test_decode_raw_file_rejects_mixed_spec_and_explicit_fields(
    tmp_path,
) -> None:
    path = tmp_path / "mixed.raw"
    path.write_bytes(b"\x00" * 8)

    with pytest.raises(ValueError, match="Provide either spec=RawDecodeSpec"):
        backend.decode_raw_file(
            str(path),
            pixel_format="mono8",
            width=2,
            height=2,
            spec=RawDecodeSpec(
                source_kind="raw",
                pixel_format="mono8",
                width=2,
                height=2,
            ),
        )


def test_decode_raw_file_validates_python_side_spec_before_native(tmp_path) -> None:
    path = tmp_path / "bad.raw"
    path.write_bytes(b"\x00" * 8)

    with pytest.raises(RawDecodeSpecError, match="Unsupported RAW pixel format"):
        backend.decode_raw_file(
            str(path),
            pixel_format="rgb8",
            width=2,
            height=2,
        )
    assert backend.backend_status_snapshot()["native_latched_off"] is False


def test_compute_static_metrics_obeys_describe_metric_route(monkeypatch) -> None:
    class _FakeNative:
        @staticmethod
        def compute_static_metrics(image):
            raise AssertionError("native path should not be called")

    _set_backend_state(monkeypatch, _FakeNative())
    monkeypatch.setattr(
        backend,
        "describe_metric_route",
        lambda *args, **kwargs: {
            "operation": "static_scan",
            "route_used": "python",
            "route_reason": "override_python",
            "source_kind": "tiff",
            "effective_mode": None,
        },
    )
    monkeypatch.setattr(
        backend,
        "_python_compute_static_metrics",
        lambda image: (4, 9),
    )

    result = backend.compute_static_metrics(
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
        source_kind="tiff",
    )

    assert result == (4, 9)


def test_static_metrics_backend_override_can_force_native_or_python(monkeypatch) -> None:
    native_calls = 0
    python_calls = 0

    class _FakeNative:
        @staticmethod
        def compute_static_metrics(image):
            nonlocal native_calls
            native_calls += 1
            return (8, 77)

    def _fake_python(image):
        nonlocal python_calls
        python_calls += 1
        return (1, 4)

    _set_backend_state(monkeypatch, _FakeNative())
    monkeypatch.setattr(backend, "_python_compute_static_metrics", _fake_python)
    image = np.array([[0, 1], [4, 8]], dtype=np.uint16)

    native_result = backend.compute_static_metrics(
        image,
        source_kind="tiff",
        backend_override="native",
    )
    python_result = backend.compute_static_metrics(
        image,
        source_kind="raw",
        backend_override="python",
    )

    assert native_result == (8, 77)
    assert python_result == (1, 4)
    assert native_calls == 1
    assert python_calls == 1


def test_threshold_only_routes_like_effective_none(monkeypatch) -> None:
    _set_backend_state(monkeypatch, object())

    decision = backend.describe_metric_route(
        "dynamic_metrics",
        source_kind="tiff",
        mode="topk",
        threshold_only=True,
    )

    assert decision["route_used"] == "python"
    assert decision["route_reason"] == "tiff_dynamic_none_python"
    assert decision["effective_mode"] == "none"


def test_native_failure_stays_latched_for_subsequent_calls(monkeypatch) -> None:
    call_count = 0

    class _FlakyNative:
        @staticmethod
        def compute_value_range(image, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("range boom")

    _set_backend_state(monkeypatch, _FlakyNative())
    image = np.array([[1, 2], [3, 4]], dtype=np.uint16)
    background = np.array([[0, 0], [0, 0]], dtype=np.uint16)

    first = backend.compute_value_range(image, background=background)
    second = backend.compute_value_range(image, background=background)

    assert first == pytest.approx((1.0, 4.0))
    assert second == pytest.approx((1.0, 4.0))
    assert call_count == 1
    assert backend.backend_status_snapshot()["native_latched_off"] is True
    decision = backend.describe_metric_route(
        "dynamic_metrics",
        source_kind="raw",
        mode="topk",
    )
    assert decision["route_used"] == "python"
    assert decision["route_reason"] == "native_latched_off"


@pytest.mark.skipif(
    not backend.native_available(),
    reason="native extension not built in this environment",
)
def test_native_and_python_static_metrics_match_when_extension_is_present(monkeypatch) -> None:
    image = np.array([[0, 5], [7, 1]], dtype=np.uint16)

    monkeypatch.setattr(backend, "_metrics_native_enabled", True, raising=False)
    native_result = backend.compute_static_metrics(
        image,
        source_kind="tiff",
        backend_override="native",
    )

    monkeypatch.setattr(backend, "_metrics_native_enabled", False, raising=False)
    monkeypatch.setattr(backend, "_active_metrics_backend", "python", raising=False)
    python_result = backend.compute_static_metrics(
        image,
        source_kind="tiff",
        backend_override="python",
    )

    assert native_result == python_result


@pytest.mark.skipif(
    not backend.native_available(),
    reason="native extension not built in this environment",
)
def test_native_and_python_dynamic_metrics_match_when_extension_is_present(
    monkeypatch,
) -> None:
    image = np.array([[1, 2], [3, 4]], dtype=np.uint16)
    background = np.array([[0, 1], [1, 0]], dtype=np.uint16)

    monkeypatch.setattr(backend, "_metrics_native_enabled", True, raising=False)
    native_result = backend.compute_dynamic_metrics(
        image,
        threshold_value=2,
        mode="topk",
        avg_count_value=2,
        background=background,
        source_kind="tiff",
        backend_override="native",
    )

    monkeypatch.setattr(backend, "_metrics_native_enabled", False, raising=False)
    monkeypatch.setattr(backend, "_active_metrics_backend", "python", raising=False)
    python_result = backend.compute_dynamic_metrics(
        image,
        threshold_value=2,
        mode="topk",
        avg_count_value=2,
        background=background,
        source_kind="tiff",
        backend_override="python",
    )

    assert native_result["sat_count"] == python_result["sat_count"]
    assert native_result["min_non_zero"] == python_result["min_non_zero"]
    assert native_result["max_pixel"] == python_result["max_pixel"]
    assert native_result["avg_topk"] == pytest.approx(python_result["avg_topk"])
    assert native_result["avg_topk_std"] == pytest.approx(
        python_result["avg_topk_std"],
    )
    assert native_result["avg_topk_sem"] == pytest.approx(
        python_result["avg_topk_sem"],
    )


@pytest.mark.skipif(
    not backend.native_available(),
    reason="native extension not built in this environment",
)
def test_native_and_python_roi_metrics_match_when_extension_is_present(monkeypatch) -> None:
    image = np.array([[1, 2], [3, 4]], dtype=np.uint16)

    monkeypatch.setattr(backend, "_metrics_native_enabled", True, raising=False)
    native_result = backend.compute_roi_metrics(
        image,
        roi_rect=(1, 1, 5, 5),
    )

    monkeypatch.setattr(backend, "_metrics_native_enabled", False, raising=False)
    monkeypatch.setattr(backend, "_active_metrics_backend", "python", raising=False)
    python_result = backend.compute_roi_metrics(
        image,
        roi_rect=(1, 1, 5, 5),
    )

    assert native_result[0] == pytest.approx(python_result[0])
    assert native_result[1] == pytest.approx(python_result[1])
    assert native_result[2] == pytest.approx(python_result[2])
    assert native_result[3] == pytest.approx(python_result[3])
