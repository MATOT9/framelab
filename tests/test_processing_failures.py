from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

import framelab.main_window.dataset_loading as dataset_loading_module
from framelab.background import freeze_background_array
from framelab.byte_budget_cache import ByteBudgetCache
from framelab.dataset_state import DatasetStateController
from framelab.image_io import read_2d_image
from framelab.main_window.dataset_loading import DatasetLoadingMixin
from framelab.metrics_cache import MetricsCache
from framelab.metrics_state import MetricsPipelineController
from framelab.processing_failures import (
    ProcessingFailure,
    format_processing_failure_details,
    make_processing_failure,
    merge_processing_failures,
    summarize_processing_failures,
)


pytestmark = [pytest.mark.data, pytest.mark.core]


class _DatasetScanHarness(DatasetLoadingMixin):
    def __init__(self, *, metrics_cache: MetricsCache | None = None) -> None:
        self.cached: dict[str, np.ndarray] = {}
        self.metrics_cache = metrics_cache
        self.read_calls = 0

    def _read_2d_image(self, path: Path) -> np.ndarray:
        self.read_calls += 1
        return read_2d_image(path)

    def _cache_image(self, path: str, image: np.ndarray) -> None:
        self.cached[path] = image


class _MetricPreviewHarness(DatasetLoadingMixin):
    def __init__(self, image: np.ndarray, reference: np.ndarray) -> None:
        self._image = np.asarray(image)
        self.dataset_state = DatasetStateController()
        self.metrics_state = MetricsPipelineController()
        self.metrics_state.background_config.enabled = True
        self.metrics_state.background_signature = 17
        self.metrics_state.background_library.global_ref = freeze_background_array(
            np.asarray(reference),
        )
        self._image_cache = ByteBudgetCache[str](1_000_000)
        self._corrected_cache = ByteBudgetCache[tuple[str, int]](1_000_000)
        self._path = "/tmp/preview-0.tif"
        self.dataset_state.set_loaded_dataset(None, [self._path])
        self.dataset_state.set_path_metadata({self._path: {}})

    def _read_2d_image(self, path: Path) -> np.ndarray:
        return self._image


def test_merge_processing_failures_dedupes_and_replaces_stage() -> None:
    scan_failure = make_processing_failure(
        stage="scan",
        path="a.tif",
        reason="InvalidImageError: unreadable",
    )
    roi_failure = make_processing_failure(
        stage="roi",
        path="b.tif",
        reason="InvalidImageError: missing",
    )
    merged = merge_processing_failures(
        [scan_failure],
        [scan_failure, roi_failure],
    )
    assert merged == [scan_failure, roi_failure]

    replaced = merge_processing_failures(
        merged,
        [
            make_processing_failure(
                stage="scan",
                path="c.tif",
                reason="InvalidImageError: bad header",
            ),
        ],
        replace_stage="scan",
    )
    assert len(replaced) == 2
    assert [failure.stage for failure in replaced] == ["roi", "scan"]


def test_failure_summary_and_details_are_human_readable() -> None:
    failures = [
        ProcessingFailure("scan", "a.tif", "InvalidImageError: unreadable"),
        ProcessingFailure("scan", "b.tif", "InvalidImageError: missing"),
        ProcessingFailure("metrics", "", "Worker crashed"),
    ]
    summary = summarize_processing_failures(failures)
    details = format_processing_failure_details(failures)
    assert summary == "Scan 2, Metrics 1"
    assert "3 processing issue(s)" in details
    assert "[Scan] a.tif" in details
    assert "[Metrics] <operation>" in details


def test_scan_tiffs_chunked_parallel_returns_structured_failures(
    tmp_path: Path,
) -> None:
    valid_path = tmp_path / "valid.tif"
    invalid_path = tmp_path / "broken.tif"
    tifffile.imwrite(
        str(valid_path),
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
    )
    invalid_path.write_text("not a tiff", encoding="utf-8")

    harness = _DatasetScanHarness()
    paths, mins, maxs, skipped, failures = harness._scan_tiffs_chunked_parallel(
        [valid_path, invalid_path],
        update_status=False,
    )

    assert paths == [str(valid_path)]
    assert mins == [1]
    assert maxs == [4]
    assert skipped == 1
    assert harness.cached == {}
    assert len(failures) == 1
    assert failures[0].stage == "scan"
    assert failures[0].path == str(invalid_path)
    assert "InvalidImageError" in failures[0].reason


def test_scan_tiffs_chunked_parallel_reuses_persisted_static_cache(
    tmp_path: Path,
) -> None:
    valid_path = tmp_path / "valid.tif"
    tifffile.imwrite(
        str(valid_path),
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
    )
    cache = MetricsCache(tmp_path / "metrics.sqlite")

    first = _DatasetScanHarness(metrics_cache=cache)
    first_paths, first_mins, first_maxs, first_skipped, first_failures = (
        first._scan_tiffs_chunked_parallel(
            [valid_path],
            update_status=False,
            dataset_root=tmp_path,
        )
    )

    second = _DatasetScanHarness(metrics_cache=cache)
    second_paths, second_mins, second_maxs, second_skipped, second_failures = (
        second._scan_tiffs_chunked_parallel(
            [valid_path],
            update_status=False,
            dataset_root=tmp_path,
        )
    )

    assert first.read_calls == 1
    assert second.read_calls == 0
    assert first_paths == second_paths == [str(valid_path.resolve())]
    assert first_mins == second_mins == [1]
    assert first_maxs == second_maxs == [4]
    assert first_skipped == second_skipped == 0
    assert first_failures == second_failures == []


def test_get_metric_image_by_index_uses_backend_corrected_cache(monkeypatch) -> None:
    harness = _MetricPreviewHarness(
        np.array([[5, 6], [7, 8]], dtype=np.uint16),
        np.array([[1, 2], [3, 4]], dtype=np.uint16),
    )
    calls = 0

    def _fake_apply_background_f32(image, **kwargs):
        nonlocal calls
        calls += 1
        return np.full_like(np.asarray(image, dtype=np.float32), 9.0)

    monkeypatch.setattr(
        dataset_loading_module.native_backend,
        "apply_background_f32",
        _fake_apply_background_f32,
    )

    first, first_bg = harness._get_metric_image_by_index(0)
    second, second_bg = harness._get_metric_image_by_index(0)

    assert first_bg is True
    assert second_bg is True
    assert calls == 1
    np.testing.assert_allclose(first, np.full((2, 2), 9.0, dtype=np.float32))
    np.testing.assert_allclose(second, first)
