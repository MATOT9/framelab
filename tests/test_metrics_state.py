from __future__ import annotations

import numpy as np
import pytest

from framelab.metrics_state import (
    DynamicStatsResult,
    MetricsPipelineController,
    RoiApplyResult,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


@pytest.fixture
def state() -> MetricsPipelineController:
    return MetricsPipelineController()


def test_initialize_loaded_dataset_resets_dataset_dependent_arrays(
    state: MetricsPipelineController,
) -> None:
    state.background_config.enabled = True
    state.initialize_loaded_dataset(3)

    assert state.avg_maxs is None
    assert state.dn_per_ms_values is None
    assert state.roi_rect is None
    np.testing.assert_array_equal(state.sat_counts, np.zeros(3, dtype=np.int64))
    np.testing.assert_array_equal(state.bg_applied_mask, np.zeros(3, dtype=bool))
    assert state.bg_total_count == 3
    assert state.bg_unmatched_count == 3
    assert state.roi_means.shape == (3,)
    assert np.isnan(state.roi_means).all()


def test_prepare_for_live_update_sizes_topk_roi_and_background_arrays(
    state: MetricsPipelineController,
) -> None:
    state.background_config.enabled = True

    state.prepare_for_live_update(path_count=2, mode="topk")

    np.testing.assert_array_equal(state.sat_counts, np.zeros(2, dtype=np.int64))
    np.testing.assert_array_equal(state.bg_applied_mask, np.zeros(2, dtype=bool))
    assert state.bg_unmatched_count == 2
    assert state.avg_maxs.shape == (2,)
    assert state.avg_maxs_std.shape == (2,)
    assert state.avg_maxs_sem.shape == (2,)
    assert state.roi_means.shape == (2,)

    state.prepare_for_live_update(path_count=2, mode="none")

    assert state.avg_maxs is None
    assert state.avg_maxs_std is None
    assert state.avg_maxs_sem is None


def test_apply_dynamic_stats_result_updates_latest_metric_snapshot(
    state: MetricsPipelineController,
) -> None:
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
    assert state.bg_total_count == 2
    assert state.bg_unmatched_count == 1


def test_apply_roi_result_updates_roi_arrays(state: MetricsPipelineController) -> None:
    result = RoiApplyResult(
        job_id=9,
        means=np.array([2.0, np.nan]),
        stds=np.array([1.0, np.nan]),
        sems=np.array([0.5, np.nan]),
        valid_count=1,
    )

    state.apply_roi_result(result)

    np.testing.assert_allclose(state.roi_means[:1], np.array([2.0]))
    assert np.isnan(state.roi_means[1])
    np.testing.assert_allclose(state.roi_stds[:1], np.array([1.0]))
    np.testing.assert_allclose(state.roi_sems[:1], np.array([0.5]))


def test_job_state_helpers_track_stats_and_roi_lifecycle(
    state: MetricsPipelineController,
) -> None:
    stats_job_id = state.begin_stats_job(
        update_kind="threshold_only",
        refresh_analysis=False,
    )
    assert stats_job_id == 1
    assert state.is_stats_running
    assert state.stats_update_kind == "threshold_only"
    assert not state.stats_refresh_analysis

    state.finish_stats_job()
    assert not state.is_stats_running
    assert state.stats_update_kind == "idle"

    roi_job_id = state.begin_roi_apply(13)
    assert roi_job_id == 1
    assert state.is_roi_applying
    assert state.roi_apply_total == 13
    assert state.roi_apply_done == 0

    state.update_roi_apply_progress(4, 13)
    assert state.roi_apply_done == 4
    assert state.roi_apply_total == 13

    cancelled_job_id = state.cancel_roi_apply()
    assert cancelled_job_id == 2
    assert not state.is_roi_applying
    assert state.roi_apply_done == 0
    assert state.roi_apply_total == 0
