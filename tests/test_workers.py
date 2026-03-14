from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import tifffile
from PySide6 import QtCore

from framelab.background import BackgroundConfig, BackgroundLibrary
from framelab.metrics_state import DynamicStatsResult, RoiApplyResult
from framelab.workers import DynamicStatsWorker, RoiApplyWorker


class WorkerBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def _write_tiff(self, root: Path, name: str, array: np.ndarray) -> str:
        path = root / name
        tifffile.imwrite(str(path), array)
        return str(path)

    def _run_dynamic_worker(
        self,
        worker: DynamicStatsWorker,
    ) -> DynamicStatsResult:
        finished: list[DynamicStatsResult] = []
        failed: list[tuple[object, ...]] = []
        worker.finished.connect(lambda result: finished.append(result))
        worker.failed.connect(lambda *args: failed.append(args))
        worker.run()
        self.assertFalse(failed, f"worker failed unexpectedly: {failed}")
        self.assertEqual(len(finished), 1)
        return finished[0]

    def _run_roi_worker(
        self,
        worker: RoiApplyWorker,
    ) -> tuple[list[tuple[int, int]], RoiApplyResult, list[tuple[object, ...]]]:
        progress: list[tuple[int, int]] = []
        finished: list[RoiApplyResult] = []
        failed: list[tuple[object, ...]] = []
        worker.progress.connect(lambda done, total: progress.append((done, total)))
        worker.finished.connect(lambda result: finished.append(result))
        worker.failed.connect(lambda *args: failed.append(args))
        worker.run()
        self.assertFalse(failed, f"worker failed unexpectedly: {failed}")
        self.assertEqual(len(finished), 1)
        return (progress, finished[0], failed)

    def test_dynamic_worker_computes_topk_stats_and_saturation_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path_a = self._write_tiff(
                root,
                "a.tif",
                np.array([[1, 2], [3, 4]], dtype=np.uint16),
            )
            path_b = self._write_tiff(
                root,
                "b.tif",
                np.array([[0, 5], [1, 2]], dtype=np.uint16),
            )
            worker = DynamicStatsWorker(
                job_id=11,
                paths=[path_a, path_b],
                threshold_value=3,
                mode="topk",
                avg_count_value=2,
            )
            result = self._run_dynamic_worker(worker)

        self.assertEqual(result.job_id, 11)
        self.assertEqual(tuple(result.failures), ())
        np.testing.assert_array_equal(
            result.sat_counts,
            np.array([2, 1], dtype=np.int64),
        )
        np.testing.assert_allclose(result.avg_topk, np.array([3.5, 3.5]))
        np.testing.assert_allclose(result.avg_topk_std, np.array([0.5, 1.5]))
        np.testing.assert_allclose(
            result.avg_topk_sem,
            np.array([0.5 / math.sqrt(2.0), 1.5 / math.sqrt(2.0)]),
        )
        np.testing.assert_array_equal(
            result.max_pixels,
            np.array([4, 5], dtype=np.int64),
        )
        np.testing.assert_array_equal(
            result.min_non_zero,
            np.array([1, 1], dtype=np.int64),
        )
        np.testing.assert_array_equal(
            result.bg_applied_mask,
            np.array([False, False]),
        )

    def test_dynamic_worker_handles_k_equals_one_and_k_larger_than_pixel_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = self._write_tiff(
                root,
                "img.tif",
                np.array([[1, 2], [3, 4]], dtype=np.uint16),
            )

            worker_k1 = DynamicStatsWorker(
                job_id=21,
                paths=[path],
                threshold_value=0,
                mode="topk",
                avg_count_value=1,
            )
            result_k1 = self._run_dynamic_worker(worker_k1)

            worker_big_k = DynamicStatsWorker(
                job_id=22,
                paths=[path],
                threshold_value=0,
                mode="topk",
                avg_count_value=99,
            )
            result_big_k = self._run_dynamic_worker(worker_big_k)

        np.testing.assert_allclose(result_k1.avg_topk, np.array([4.0]))
        np.testing.assert_allclose(result_k1.avg_topk_std, np.array([0.0]))
        np.testing.assert_allclose(result_k1.avg_topk_sem, np.array([0.0]))
        self.assertEqual(tuple(result_k1.failures), ())

        expected = np.array([2.5])
        expected_std = np.array([np.std(np.array([1.0, 2.0, 3.0, 4.0]))])
        expected_sem = expected_std / math.sqrt(4.0)
        np.testing.assert_allclose(result_big_k.avg_topk, expected)
        np.testing.assert_allclose(result_big_k.avg_topk_std, expected_std)
        np.testing.assert_allclose(result_big_k.avg_topk_sem, expected_sem)
        self.assertEqual(tuple(result_big_k.failures), ())

    def test_dynamic_worker_threshold_only_reuses_existing_static_and_topk_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = self._write_tiff(
                root,
                "img.tif",
                np.array([[1, 4], [5, 0]], dtype=np.uint16),
            )
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
            result = self._run_dynamic_worker(worker)

        np.testing.assert_array_equal(result.sat_counts, np.array([2], dtype=np.int64))
        np.testing.assert_allclose(result.avg_topk, np.array([12.5]))
        np.testing.assert_allclose(result.avg_topk_std, np.array([1.25]))
        np.testing.assert_allclose(result.avg_topk_sem, np.array([0.625]))
        np.testing.assert_array_equal(result.max_pixels, np.array([99], dtype=np.int64))
        np.testing.assert_array_equal(result.min_non_zero, np.array([7], dtype=np.int64))
        np.testing.assert_array_equal(result.bg_applied_mask, np.array([True]))
        self.assertEqual(tuple(result.failures), ())

    def test_dynamic_worker_applies_exposure_matched_background_with_raw_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path_a = self._write_tiff(
                root,
                "a.tif",
                np.full((2, 2), 2, dtype=np.uint16),
            )
            path_b = self._write_tiff(
                root,
                "b.tif",
                np.array([[5, 0], [0, 0]], dtype=np.uint16),
            )
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
            result = self._run_dynamic_worker(worker)

        self.assertIsNone(result.avg_topk)
        self.assertIsNone(result.avg_topk_std)
        self.assertIsNone(result.avg_topk_sem)
        np.testing.assert_array_equal(result.bg_applied_mask, np.array([True, False]))
        np.testing.assert_array_equal(result.max_pixels, np.array([1, 5], dtype=np.int64))
        np.testing.assert_array_equal(result.min_non_zero, np.array([1, 5], dtype=np.int64))
        np.testing.assert_array_equal(result.sat_counts, np.array([4, 1], dtype=np.int64))
        self.assertEqual(tuple(result.failures), ())

    def test_dynamic_worker_reports_unreadable_images_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            valid_path = self._write_tiff(
                root,
                "valid.tif",
                np.array([[1, 2], [3, 4]], dtype=np.uint16),
            )
            missing_path = str(root / "missing.tif")
            worker = DynamicStatsWorker(
                job_id=51,
                paths=[valid_path, missing_path],
                threshold_value=3,
                mode="topk",
                avg_count_value=2,
            )
            result = self._run_dynamic_worker(worker)

        np.testing.assert_array_equal(result.sat_counts, np.array([2, 0], dtype=np.int64))
        self.assertTrue(np.isfinite(result.avg_topk[0]))
        self.assertTrue(np.isnan(result.avg_topk[1]))
        self.assertTrue(np.isnan(result.avg_topk_std[1]))
        self.assertTrue(np.isnan(result.avg_topk_sem[1]))
        np.testing.assert_array_equal(result.max_pixels, np.array([4, 0], dtype=np.int64))
        np.testing.assert_array_equal(result.min_non_zero, np.array([1, 0], dtype=np.int64))
        np.testing.assert_array_equal(result.bg_applied_mask, np.array([False, False]))
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "metrics")
        self.assertEqual(result.failures[0].path, missing_path)
        self.assertIn("InvalidImageError", result.failures[0].reason)

    def test_roi_worker_computes_mean_std_and_sem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = self._write_tiff(
                root,
                "img.tif",
                np.array([[1, 2], [3, 4]], dtype=np.uint16),
            )
            worker = RoiApplyWorker(
                job_id=61,
                paths=[path],
                roi_rect=(0, 0, 2, 2),
            )
            progress, finished, _failed = self._run_roi_worker(worker)

        self.assertEqual(progress, [(1, 1)])
        self.assertEqual(finished.job_id, 61)
        self.assertEqual(finished.valid_count, 1)
        self.assertEqual(tuple(finished.failures), ())
        np.testing.assert_allclose(finished.means, np.array([2.5]))
        np.testing.assert_allclose(
            finished.stds,
            np.array([np.std(np.array([1.0, 2.0, 3.0, 4.0]))]),
        )
        np.testing.assert_allclose(
            finished.sems,
            np.array([np.std(np.array([1.0, 2.0, 3.0, 4.0])) / math.sqrt(4.0)]),
        )

    def test_roi_worker_empty_roi_returns_nan_and_zero_valid_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = self._write_tiff(
                root,
                "img.tif",
                np.array([[1, 2], [3, 4]], dtype=np.uint16),
            )
            worker = RoiApplyWorker(
                job_id=71,
                paths=[path],
                roi_rect=(1, 1, 1, 1),
            )
            _progress, finished, _failed = self._run_roi_worker(worker)

        self.assertEqual(finished.valid_count, 0)
        self.assertEqual(tuple(finished.failures), ())
        self.assertTrue(np.isnan(finished.means[0]))
        self.assertTrue(np.isnan(finished.stds[0]))
        self.assertTrue(np.isnan(finished.sems[0]))

    def test_roi_worker_uses_current_numpy_slicing_contract_for_out_of_bounds_roi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = self._write_tiff(
                root,
                "img.tif",
                np.array([[1, 2], [3, 4]], dtype=np.uint16),
            )
            worker = RoiApplyWorker(
                job_id=81,
                paths=[path],
                roi_rect=(1, 1, 5, 5),
            )
            _progress, finished, _failed = self._run_roi_worker(worker)

        self.assertEqual(finished.valid_count, 1)
        self.assertEqual(tuple(finished.failures), ())
        np.testing.assert_allclose(finished.means, np.array([4.0]))
        np.testing.assert_allclose(finished.stds, np.array([0.0]))
        np.testing.assert_allclose(finished.sems, np.array([0.0]))

    def test_roi_worker_reports_unreadable_images_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            valid_path = self._write_tiff(
                root,
                "valid.tif",
                np.array([[1, 2], [3, 4]], dtype=np.uint16),
            )
            missing_path = str(root / "missing.tif")
            worker = RoiApplyWorker(
                job_id=91,
                paths=[valid_path, missing_path],
                roi_rect=(0, 0, 2, 2),
            )
            progress, finished, _failed = self._run_roi_worker(worker)

        self.assertEqual(progress, [(1, 2), (2, 2)])
        self.assertEqual(finished.valid_count, 1)
        np.testing.assert_allclose(finished.means[:1], np.array([2.5]))
        self.assertTrue(np.isnan(finished.means[1]))
        self.assertTrue(np.isnan(finished.stds[1]))
        self.assertTrue(np.isnan(finished.sems[1]))
        self.assertEqual(len(finished.failures), 1)
        self.assertEqual(finished.failures[0].stage, "roi")
        self.assertEqual(finished.failures[0].path, missing_path)
        self.assertIn("InvalidImageError", finished.failures[0].reason)


if __name__ == "__main__":
    unittest.main()
