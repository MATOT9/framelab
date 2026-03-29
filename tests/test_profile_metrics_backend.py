from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import framelab.native.backend as backend
import tools.profile_metrics_backend as profile_module


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
        lambda path: image,
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
    assert phases["static_scan"]["route_used"] == "python"
    assert phases["static_scan"]["route_reason"] == "tiff_static_python"
    assert phases["dynamic_none"]["route_used"] == "python"
    assert phases["dynamic_none"]["route_reason"] == "tiff_dynamic_none_python"
    assert phases["dynamic_topk"]["route_used"] == "native"
    assert phases["dynamic_topk"]["route_reason"] == "topk_native"
    assert phases["roi_metrics"]["route_used"] == "native"
    assert phases["exact_histogram"]["route_used"] == "native"


def test_render_summary_includes_route_and_reason_columns() -> None:
    report = {
        "requested_backend": "python",
        "forced_backend": "python",
        "image_count": 65,
        "background_applicable_images": 0,
        "background_raw_fallback_images": 65,
        "backend_status": {
            "active_backend": "native",
            "native_available": True,
            "native_latched_off": False,
            "last_fallback_reason": None,
        },
        "phases": [
            {
                "phase": "static_scan",
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
    assert "Route" in rendered
    assert "Reason" in rendered
    assert "static_scan" in rendered
    assert "override_python" in rendered
