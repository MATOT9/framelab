from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import tifffile

import framelab.workers as workers_module
from framelab.background import BackgroundConfig, BackgroundLibrary
from framelab.metrics_state import DynamicStatsResult, RoiApplyResult
from framelab.workers import DynamicStatsWorker, RoiApplyWorker


pytestmark = [pytest.mark.core]


@pytest.fixture
def write_tiff(tmp_path: Path):
    def _write_tiff(name: str, array: np.ndarray) -> str:
        path = tmp_path / name
        tifffile.imwrite(str(path), array)
        return str(path)

    return _write_tiff


def _run_dynamic_worker(worker: DynamicStatsWorker) -> DynamicStatsResult:
    finished: list[DynamicStatsResult] = []
    failed: list[tuple[object, ...]] = []
    worker.finished.connect(lambda result: finished.append(result))
    worker.failed.connect(lambda *args: failed.append(args))
    worker.run()
    assert not failed, f"worker failed unexpectedly: {failed}"
    assert len(finished) == 1
    return finished[0]


def _run_roi_worker(
    worker: RoiApplyWorker,
) -> tuple[list[tuple[int, int]], RoiApplyResult, list[tuple[object, ...]]]:
    progress: list[tuple[int, int]] = []
    finished: list[RoiApplyResult] = []
    failed: list[tuple[object, ...]] = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.finished.connect(lambda result: finished.append(result))
    worker.failed.connect(lambda *args: failed.append(args))
    worker.run()
    assert not failed, f"worker failed unexpectedly: {failed}"
    assert len(finished) == 1
    return (progress, finished[0], failed)


def test_dynamic_worker_computes_topk_stats_and_saturation_counts(
    qapp,
    write_tiff,
) -> None:
    path_a = write_tiff("a.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    path_b = write_tiff("b.tif", np.array([[0, 5], [1, 2]], dtype=np.uint16))
    worker = DynamicStatsWorker(
        job_id=11,
        paths=[path_a, path_b],
        threshold_value=3,
        mode="topk",
        avg_count_value=2,
    )
    result = _run_dynamic_worker(worker)

    assert result.job_id == 11
    assert tuple(result.failures) == ()
    np.testing.assert_array_equal(result.sat_counts, np.array([2, 1], dtype=np.int64))
    np.testing.assert_allclose(result.avg_topk, np.array([3.5, 3.5]))
    np.testing.assert_allclose(result.avg_topk_std, np.array([0.5, 1.5]))
    np.testing.assert_allclose(
        result.avg_topk_sem,
        np.array([0.5 / math.sqrt(2.0), 1.5 / math.sqrt(2.0)]),
    )
    np.testing.assert_array_equal(result.max_pixels, np.array([4, 5], dtype=np.int64))
    np.testing.assert_array_equal(result.min_non_zero, np.array([1, 1], dtype=np.int64))
    np.testing.assert_array_equal(result.bg_applied_mask, np.array([False, False]))


def test_dynamic_worker_handles_k_equals_one_and_k_larger_than_pixel_count(
    qapp,
    write_tiff,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))

    worker_k1 = DynamicStatsWorker(
        job_id=21,
        paths=[path],
        threshold_value=0,
        mode="topk",
        avg_count_value=1,
    )
    result_k1 = _run_dynamic_worker(worker_k1)

    worker_big_k = DynamicStatsWorker(
        job_id=22,
        paths=[path],
        threshold_value=0,
        mode="topk",
        avg_count_value=99,
    )
    result_big_k = _run_dynamic_worker(worker_big_k)

    np.testing.assert_allclose(result_k1.avg_topk, np.array([4.0]))
    np.testing.assert_allclose(result_k1.avg_topk_std, np.array([0.0]))
    np.testing.assert_allclose(result_k1.avg_topk_sem, np.array([0.0]))
    assert tuple(result_k1.failures) == ()

    expected = np.array([2.5])
    expected_std = np.array([np.std(np.array([1.0, 2.0, 3.0, 4.0]))])
    expected_sem = expected_std / math.sqrt(4.0)
    np.testing.assert_allclose(result_big_k.avg_topk, expected)
    np.testing.assert_allclose(result_big_k.avg_topk_std, expected_std)
    np.testing.assert_allclose(result_big_k.avg_topk_sem, expected_sem)
    assert tuple(result_big_k.failures) == ()


def test_dynamic_worker_threshold_only_reuses_existing_static_and_topk_outputs(
    qapp,
    write_tiff,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 4], [5, 0]], dtype=np.uint16))
    worker = DynamicStatsWorker(
        job_id=31,
        paths=[path],
        threshold_value=4,
        mode="topk",
        avg_count_value=2,
        update_kind="threshold_only",
        existing_avg_topk=np.array([12.5]),
        existing_avg_topk_std=np.array([1.25]),
        existing_avg_topk_sem=np.array([0.625]),
        existing_max_pixels=np.array([99], dtype=np.int64),
        existing_min_non_zero=np.array([7], dtype=np.int64),
        existing_bg_applied_mask=np.array([True]),
    )
    result = _run_dynamic_worker(worker)

    np.testing.assert_array_equal(result.sat_counts, np.array([2], dtype=np.int64))
    np.testing.assert_allclose(result.avg_topk, np.array([12.5]))
    np.testing.assert_allclose(result.avg_topk_std, np.array([1.25]))
    np.testing.assert_allclose(result.avg_topk_sem, np.array([0.625]))
    np.testing.assert_array_equal(result.max_pixels, np.array([99], dtype=np.int64))
    np.testing.assert_array_equal(result.min_non_zero, np.array([7], dtype=np.int64))
    np.testing.assert_array_equal(result.bg_applied_mask, np.array([True]))
    assert tuple(result.failures) == ()


def test_dynamic_worker_applies_exposure_matched_background_with_raw_fallback(
    qapp,
    write_tiff,
) -> None:
    path_a = write_tiff("a.tif", np.full((2, 2), 2, dtype=np.uint16))
    path_b = write_tiff("b.tif", np.array([[5, 0], [0, 0]], dtype=np.uint16))
    library = BackgroundLibrary(
        refs_by_exposure_ms={10.0: np.ones((2, 2), dtype=np.float64)},
        label_by_exposure_ms={10.0: "10 ms"},
    )
    worker = DynamicStatsWorker(
        job_id=41,
        paths=[path_a, path_b],
        threshold_value=1,
        mode="none",
        avg_count_value=2,
        background_config=BackgroundConfig(enabled=True),
        background_library=library,
        path_metadata={
            path_a: {"exposure_ms": 10.0},
            path_b: {"exposure_ms": 20.0},
        },
    )
    result = _run_dynamic_worker(worker)

    assert result.avg_topk is None
    assert result.avg_topk_std is None
    assert result.avg_topk_sem is None
    np.testing.assert_array_equal(result.bg_applied_mask, np.array([True, False]))
    np.testing.assert_array_equal(result.max_pixels, np.array([1, 5], dtype=np.int64))
    np.testing.assert_array_equal(result.min_non_zero, np.array([1, 5], dtype=np.int64))
    np.testing.assert_array_equal(result.sat_counts, np.array([4, 1], dtype=np.int64))
    assert tuple(result.failures) == ()


def test_dynamic_worker_reports_unreadable_images_and_continues(
    qapp,
    write_tiff,
    tmp_path: Path,
) -> None:
    valid_path = write_tiff("valid.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    missing_path = str(tmp_path / "missing.tif")
    worker = DynamicStatsWorker(
        job_id=51,
        paths=[valid_path, missing_path],
        threshold_value=3,
        mode="topk",
        avg_count_value=2,
    )
    result = _run_dynamic_worker(worker)

    np.testing.assert_array_equal(result.sat_counts, np.array([2, 0], dtype=np.int64))
    assert np.isfinite(result.avg_topk[0])
    assert np.isnan(result.avg_topk[1])
    assert np.isnan(result.avg_topk_std[1])
    assert np.isnan(result.avg_topk_sem[1])
    np.testing.assert_array_equal(result.max_pixels, np.array([4, 0], dtype=np.int64))
    np.testing.assert_array_equal(result.min_non_zero, np.array([1, 0], dtype=np.int64))
    np.testing.assert_array_equal(result.bg_applied_mask, np.array([False, False]))
    assert len(result.failures) == 1
    assert result.failures[0].stage == "metrics"
    assert result.failures[0].path == missing_path
    assert "InvalidImageError" in result.failures[0].reason


def test_dynamic_worker_fills_only_missing_source_indices(
    qapp,
    write_tiff,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 4], [5, 0]], dtype=np.uint16))
    worker = DynamicStatsWorker(
        job_id=56,
        paths=[path],
        source_indices=[1],
        result_length=3,
        threshold_value=4,
        mode="topk",
        avg_count_value=2,
        existing_sat_counts=np.array([7, 0, 9], dtype=np.int64),
        existing_avg_topk=np.array([10.0, np.nan, 30.0]),
        existing_avg_topk_std=np.array([1.0, np.nan, 3.0]),
        existing_avg_topk_sem=np.array([0.5, np.nan, 1.5]),
        existing_max_pixels=np.array([11, 0, 33], dtype=np.int64),
        existing_min_non_zero=np.array([2, 0, 4], dtype=np.int64),
        existing_bg_applied_mask=np.array([True, False, True]),
    )
    result = _run_dynamic_worker(worker)

    np.testing.assert_array_equal(result.sat_counts, np.array([7, 2, 9], dtype=np.int64))
    np.testing.assert_allclose(result.avg_topk, np.array([10.0, 4.5, 30.0]))
    np.testing.assert_allclose(result.avg_topk_std, np.array([1.0, 0.5, 3.0]))
    np.testing.assert_allclose(
        result.avg_topk_sem,
        np.array([0.5, 0.5 / math.sqrt(2.0), 1.5]),
    )
    np.testing.assert_array_equal(result.max_pixels, np.array([11, 5, 33], dtype=np.int64))
    np.testing.assert_array_equal(result.min_non_zero, np.array([2, 1, 4], dtype=np.int64))
    np.testing.assert_array_equal(result.bg_applied_mask, np.array([True, False, True]))
    assert tuple(result.failures) == ()


def test_scan_single_static_image_uses_backend_wrapper(
    write_tiff,
    monkeypatch,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))

    monkeypatch.setattr(
        workers_module.native_backend,
        "compute_static_metrics",
        lambda image, **kwargs: (7, 99),
    )

    result, failures = workers_module.scan_single_static_image(path)

    assert failures == ()
    assert result == (path, 7, 99)


def test_dynamic_worker_uses_backend_wrapper(
    qapp,
    write_tiff,
    monkeypatch,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    calls: list[dict[str, object]] = []

    def _fake_compute(image, **kwargs):
        calls.append(dict(kwargs))
        return {
            "sat_count": 13,
            "min_non_zero": 5,
            "max_pixel": 42,
            "avg_topk": 11.5,
            "avg_topk_std": 1.25,
            "avg_topk_sem": 0.625,
        }

    monkeypatch.setattr(
        workers_module.native_backend,
        "compute_dynamic_metrics",
        _fake_compute,
    )

    worker = DynamicStatsWorker(
        job_id=58,
        paths=[path],
        threshold_value=4,
        mode="topk",
        avg_count_value=2,
    )
    result = _run_dynamic_worker(worker)

    assert len(calls) == 1
    assert calls[0]["threshold_only"] is False
    np.testing.assert_array_equal(result.sat_counts, np.array([13], dtype=np.int64))
    np.testing.assert_array_equal(result.min_non_zero, np.array([5], dtype=np.int64))
    np.testing.assert_array_equal(result.max_pixels, np.array([42], dtype=np.int64))
    np.testing.assert_allclose(result.avg_topk, np.array([11.5]))
    np.testing.assert_allclose(result.avg_topk_std, np.array([1.25]))
    np.testing.assert_allclose(result.avg_topk_sem, np.array([0.625]))


def test_roi_worker_computes_mean_std_and_sem(qapp, write_tiff) -> None:
    path = write_tiff("img.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    worker = RoiApplyWorker(
        job_id=61,
        paths=[path],
        roi_rect=(0, 0, 2, 2),
    )
    progress, finished, _failed = _run_roi_worker(worker)

    assert progress == [(1, 1)]
    assert finished.job_id == 61
    assert finished.valid_count == 1
    assert tuple(finished.failures) == ()
    np.testing.assert_allclose(finished.maxs, np.array([4.0]))
    np.testing.assert_allclose(finished.means, np.array([2.5]))
    np.testing.assert_allclose(
        finished.stds,
        np.array([np.std(np.array([1.0, 2.0, 3.0, 4.0]))]),
    )
    np.testing.assert_allclose(
        finished.sems,
        np.array([np.std(np.array([1.0, 2.0, 3.0, 4.0])) / math.sqrt(4.0)]),
    )


def test_roi_worker_empty_roi_returns_nan_and_zero_valid_count(
    qapp,
    write_tiff,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    worker = RoiApplyWorker(
        job_id=71,
        paths=[path],
        roi_rect=(1, 1, 1, 1),
    )
    _progress, finished, _failed = _run_roi_worker(worker)

    assert finished.valid_count == 0
    assert tuple(finished.failures) == ()
    assert np.isnan(finished.maxs[0])
    assert np.isnan(finished.means[0])
    assert np.isnan(finished.stds[0])
    assert np.isnan(finished.sems[0])


def test_roi_worker_uses_current_numpy_slicing_contract_for_out_of_bounds_roi(
    qapp,
    write_tiff,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    worker = RoiApplyWorker(
        job_id=81,
        paths=[path],
        roi_rect=(1, 1, 5, 5),
    )
    _progress, finished, _failed = _run_roi_worker(worker)

    assert finished.valid_count == 1
    assert tuple(finished.failures) == ()
    np.testing.assert_allclose(finished.maxs, np.array([4.0]))
    np.testing.assert_allclose(finished.means, np.array([4.0]))
    np.testing.assert_allclose(finished.stds, np.array([0.0]))
    np.testing.assert_allclose(finished.sems, np.array([0.0]))


def test_roi_worker_reports_unreadable_images_and_continues(
    qapp,
    write_tiff,
    tmp_path: Path,
) -> None:
    valid_path = write_tiff("valid.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    missing_path = str(tmp_path / "missing.tif")
    worker = RoiApplyWorker(
        job_id=91,
        paths=[valid_path, missing_path],
        roi_rect=(0, 0, 2, 2),
    )
    progress, finished, _failed = _run_roi_worker(worker)

    assert progress == [(1, 2), (2, 2)]
    assert finished.valid_count == 1
    np.testing.assert_allclose(finished.maxs[:1], np.array([4.0]))
    assert np.isnan(finished.maxs[1])
    np.testing.assert_allclose(finished.means[:1], np.array([2.5]))
    assert np.isnan(finished.means[1])
    assert np.isnan(finished.stds[1])
    assert np.isnan(finished.sems[1])
    assert len(finished.failures) == 1
    assert finished.failures[0].stage == "roi"
    assert finished.failures[0].path == missing_path
    assert "InvalidImageError" in finished.failures[0].reason


def test_roi_worker_fills_only_missing_source_indices(
    qapp,
    write_tiff,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    worker = RoiApplyWorker(
        job_id=96,
        paths=[path],
        source_indices=[1],
        result_length=3,
        roi_rect=(0, 0, 2, 2),
        existing_maxs=np.array([20.0, np.nan, 40.0]),
        existing_means=np.array([10.0, np.nan, 30.0]),
        existing_stds=np.array([1.0, np.nan, 3.0]),
        existing_sems=np.array([0.5, np.nan, 1.5]),
    )
    progress, finished, _failed = _run_roi_worker(worker)

    assert progress == [(1, 1)]
    assert finished.valid_count == 3
    np.testing.assert_allclose(finished.maxs, np.array([20.0, 4.0, 40.0]))
    np.testing.assert_allclose(finished.means, np.array([10.0, 2.5, 30.0]))
    np.testing.assert_allclose(
        finished.stds,
        np.array([1.0, np.std(np.array([1.0, 2.0, 3.0, 4.0])), 3.0]),
    )
    np.testing.assert_allclose(
        finished.sems,
        np.array(
            [
                0.5,
                np.std(np.array([1.0, 2.0, 3.0, 4.0])) / math.sqrt(4.0),
                1.5,
            ],
        ),
    )
    assert tuple(finished.failures) == ()


def test_roi_worker_uses_backend_wrapper(
    qapp,
    write_tiff,
    monkeypatch,
) -> None:
    path = write_tiff("img.tif", np.array([[1, 2], [3, 4]], dtype=np.uint16))
    calls: list[dict[str, object]] = []

    def _fake_compute(image, **kwargs):
        calls.append(dict(kwargs))
        return (9.0, 8.0, 7.0, 6.0)

    monkeypatch.setattr(
        workers_module.native_backend,
        "compute_roi_metrics",
        _fake_compute,
    )

    worker = RoiApplyWorker(
        job_id=97,
        paths=[path],
        roi_rect=(0, 0, 2, 2),
    )
    progress, finished, _failed = _run_roi_worker(worker)

    assert progress == [(1, 1)]
    assert len(calls) == 1
    assert calls[0]["roi_rect"] == (0, 0, 2, 2)
    np.testing.assert_allclose(finished.maxs, np.array([9.0]))
    np.testing.assert_allclose(finished.means, np.array([8.0]))
    np.testing.assert_allclose(finished.stds, np.array([7.0]))
    np.testing.assert_allclose(finished.sems, np.array([6.0]))
