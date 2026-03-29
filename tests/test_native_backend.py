from __future__ import annotations

import math

import numpy as np
import pytest

import framelab.native.backend as backend


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
    )

    assert result["sat_count"] == 12
    assert backend.active_metrics_backend() == "native"
    assert backend.consume_backend_status_notice() == "Using native metrics backend"
    assert backend.consume_backend_status_notice() is None


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


@pytest.mark.skipif(
    not backend.native_available(),
    reason="native extension not built in this environment",
)
def test_native_and_python_static_metrics_match_when_extension_is_present(monkeypatch) -> None:
    image = np.array([[0, 5], [7, 1]], dtype=np.uint16)

    monkeypatch.setattr(backend, "_metrics_native_enabled", True, raising=False)
    native_result = backend.compute_static_metrics(image)

    monkeypatch.setattr(backend, "_metrics_native_enabled", False, raising=False)
    monkeypatch.setattr(backend, "_active_metrics_backend", "python", raising=False)
    python_result = backend.compute_static_metrics(image)

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
    )

    monkeypatch.setattr(backend, "_metrics_native_enabled", False, raising=False)
    monkeypatch.setattr(backend, "_active_metrics_backend", "python", raising=False)
    python_result = backend.compute_dynamic_metrics(
        image,
        threshold_value=2,
        mode="topk",
        avg_count_value=2,
        background=background,
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
