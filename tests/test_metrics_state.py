from __future__ import annotations

import unittest

import numpy as np

from framelab.metrics_state import (
    DynamicStatsResult,
    MetricsPipelineController,
    RoiApplyResult,
)


class MetricsStateControllerTests(unittest.TestCase):
    def test_initialize_loaded_dataset_resets_dataset_dependent_arrays(self) -> None:
        state = MetricsPipelineController()
        state.background_config.enabled = True
        state.initialize_loaded_dataset(3)

        self.assertIsNone(state.avg_maxs)
        self.assertIsNone(state.dn_per_ms_values)
        self.assertIsNone(state.roi_rect)
        np.testing.assert_array_equal(state.sat_counts, np.zeros(3, dtype=np.int64))
        np.testing.assert_array_equal(state.bg_applied_mask, np.zeros(3, dtype=bool))
        self.assertEqual(state.bg_total_count, 3)
        self.assertEqual(state.bg_unmatched_count, 3)
        self.assertEqual(state.roi_means.shape, (3,))
        self.assertTrue(np.isnan(state.roi_means).all())

    def test_prepare_for_live_update_sizes_topk_roi_and_background_arrays(self) -> None:
        state = MetricsPipelineController()
        state.background_config.enabled = True

        state.prepare_for_live_update(path_count=2, mode="topk")

        np.testing.assert_array_equal(state.sat_counts, np.zeros(2, dtype=np.int64))
        np.testing.assert_array_equal(state.bg_applied_mask, np.zeros(2, dtype=bool))
        self.assertEqual(state.bg_unmatched_count, 2)
        self.assertEqual(state.avg_maxs.shape, (2,))
        self.assertEqual(state.avg_maxs_std.shape, (2,))
        self.assertEqual(state.avg_maxs_sem.shape, (2,))
        self.assertEqual(state.roi_means.shape, (2,))

        state.prepare_for_live_update(path_count=2, mode="none")

        self.assertIsNone(state.avg_maxs)
        self.assertIsNone(state.avg_maxs_std)
        self.assertIsNone(state.avg_maxs_sem)

    def test_apply_dynamic_stats_result_updates_latest_metric_snapshot(self) -> None:
        state = MetricsPipelineController()
        result = DynamicStatsResult(
            job_id=7,
            sat_counts=np.array([1, 0], dtype=np.int64),
            avg_topk=np.array([5.0, np.nan]),
            avg_topk_std=np.array([1.0, np.nan]),
            avg_topk_sem=np.array([0.5, np.nan]),
            max_pixels=np.array([9, 2], dtype=np.int64),
            min_non_zero=np.array([1, 0], dtype=np.int64),
            bg_applied_mask=np.array([True, False], dtype=bool),
        )

        state.apply_dynamic_stats_result(result, path_count=2)

        np.testing.assert_array_equal(state.sat_counts, np.array([1, 0]))
        np.testing.assert_array_equal(state.maxs, np.array([9, 2]))
        np.testing.assert_array_equal(state.min_non_zero, np.array([1, 0]))
        np.testing.assert_array_equal(state.bg_applied_mask, np.array([True, False]))
        self.assertEqual(state.bg_total_count, 2)
        self.assertEqual(state.bg_unmatched_count, 1)

    def test_apply_roi_result_updates_roi_arrays(self) -> None:
        state = MetricsPipelineController()
        result = RoiApplyResult(
            job_id=9,
            means=np.array([2.0, np.nan]),
            stds=np.array([1.0, np.nan]),
            sems=np.array([0.5, np.nan]),
            valid_count=1,
        )

        state.apply_roi_result(result)

        np.testing.assert_allclose(state.roi_means[:1], np.array([2.0]))
        self.assertTrue(np.isnan(state.roi_means[1]))
        np.testing.assert_allclose(state.roi_stds[:1], np.array([1.0]))
        np.testing.assert_allclose(state.roi_sems[:1], np.array([0.5]))

    def test_job_state_helpers_track_stats_and_roi_lifecycle(self) -> None:
        state = MetricsPipelineController()

        stats_job_id = state.begin_stats_job(
            update_kind="threshold_only",
            refresh_analysis=False,
        )
        self.assertEqual(stats_job_id, 1)
        self.assertTrue(state.is_stats_running)
        self.assertEqual(state.stats_update_kind, "threshold_only")
        self.assertFalse(state.stats_refresh_analysis)

        state.finish_stats_job()
        self.assertFalse(state.is_stats_running)
        self.assertEqual(state.stats_update_kind, "idle")

        roi_job_id = state.begin_roi_apply(13)
        self.assertEqual(roi_job_id, 1)
        self.assertTrue(state.is_roi_applying)
        self.assertEqual(state.roi_apply_total, 13)
        self.assertEqual(state.roi_apply_done, 0)

        state.update_roi_apply_progress(4, 13)
        self.assertEqual(state.roi_apply_done, 4)
        self.assertEqual(state.roi_apply_total, 13)

        cancelled_job_id = state.cancel_roi_apply()
        self.assertEqual(cancelled_job_id, 2)
        self.assertFalse(state.is_roi_applying)
        self.assertEqual(state.roi_apply_done, 0)
        self.assertEqual(state.roi_apply_total, 0)


if __name__ == "__main__":
    unittest.main()
