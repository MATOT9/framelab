from __future__ import annotations

import numpy as np
import pytest

from framelab.metrics_state import (
    DynamicStatsResult,
    MetricFamily,
    MetricFamilyState,
    MetricsPipelineController,
    RoiApplyResult,
    ScanMetricPreset,
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
    assert state.sat_counts is None
    assert state.bg_applied_mask is None
    assert state.bg_total_count == 0
    assert state.bg_unmatched_count == 0
    assert (
        state.metric_family_state(MetricFamily.STATIC_SCAN)
        == MetricFamilyState.READY
    )
    assert (
        state.metric_family_state(MetricFamily.SATURATION)
        == MetricFamilyState.NOT_REQUESTED
    )
    assert state.roi_maxs.shape == (3,)
    assert np.isnan(state.roi_maxs).all()
    assert state.roi_sums.shape == (3,)
    assert np.isnan(state.roi_sums).all()
    assert state.roi_means.shape == (3,)
    assert np.isnan(state.roi_means).all()
    assert state.roi_topk_means.shape == (3,)
    assert np.isnan(state.roi_topk_means).all()


def test_pending_inputs_are_separate_from_applied_values(
    state: MetricsPipelineController,
) -> None:
    state.set_pending_threshold_value(42)
    state.set_pending_low_signal_threshold_value(7)
    state.set_pending_avg_count_value(5)

    assert state.threshold_value == pytest.approx(65520.0)
    assert state.low_signal_threshold_value == pytest.approx(0.0)
    assert state.avg_count_value == 32
    assert state.threshold_inputs_pending()
    assert state.low_signal_inputs_pending()
    assert state.topk_inputs_pending()
    assert (
        state.metric_family_state(MetricFamily.SATURATION)
        == MetricFamilyState.PENDING_INPUTS
    )
    assert (
        state.metric_family_state(MetricFamily.LOW_SIGNAL)
        == MetricFamilyState.PENDING_INPUTS
    )
    assert (
        state.metric_family_state(MetricFamily.TOPK)
        == MetricFamilyState.PENDING_INPUTS
    )

    assert state.apply_pending_threshold_value()
    assert state.apply_pending_low_signal_threshold_value()
    assert state.apply_pending_avg_count_value()

    assert state.threshold_value == pytest.approx(42.0)
    assert state.low_signal_threshold_value == pytest.approx(7.0)
    assert state.avg_count_value == 5
    assert not state.threshold_inputs_pending()
    assert not state.low_signal_inputs_pending()
    assert not state.topk_inputs_pending()


def test_scan_metric_setup_defaults_and_presets(
    state: MetricsPipelineController,
) -> None:
    assert state.scan_metric_preset == ScanMetricPreset.MINIMAL
    assert state.scan_metric_families() == (MetricFamily.STATIC_SCAN,)
    assert state.scan_metric_family_values() == ["static_scan"]

    state.set_scan_metric_preset(ScanMetricPreset.THRESHOLD_REVIEW)

    assert state.scan_metric_families() == (
        MetricFamily.STATIC_SCAN,
        MetricFamily.SATURATION,
        MetricFamily.LOW_SIGNAL,
    )


def test_custom_scan_metric_setup_forces_static_and_filters_unknowns(
    state: MetricsPipelineController,
) -> None:
    state.set_custom_scan_metric_families(
        [
            MetricFamily.TOPK,
            "roi",
            "background_applied",
            "missing",
            MetricFamily.TOPK,
        ],
    )

    assert state.scan_metric_preset == ScanMetricPreset.CUSTOM
    assert state.scan_metric_families() == (
        MetricFamily.STATIC_SCAN,
        MetricFamily.TOPK,
        MetricFamily.ROI,
    )

    state.restore_scan_metric_setup(
        preset="not-a-preset",
        families=["roi_topk"],
    )

    assert state.scan_metric_preset == ScanMetricPreset.MINIMAL
    assert state.scan_metric_families() == (MetricFamily.STATIC_SCAN,)
    assert state.custom_scan_metric_families == (
        MetricFamily.STATIC_SCAN,
        MetricFamily.ROI_TOPK,
    )


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
    assert state.roi_maxs.shape == (2,)
    assert state.roi_sums.shape == (2,)
    assert state.roi_means.shape == (2,)
    assert state.roi_topk_means.shape == (2,)

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
        maxs=np.array([4.0, np.nan]),
        sums=np.array([8.0, np.nan]),
        means=np.array([2.0, np.nan]),
        stds=np.array([1.0, np.nan]),
        sems=np.array([0.5, np.nan]),
        valid_count=1,
        topk_means=np.array([3.5, np.nan]),
        topk_stds=np.array([0.5, np.nan]),
        topk_sems=np.array([0.25, np.nan]),
    )

    state.apply_roi_result(result)

    np.testing.assert_allclose(state.roi_maxs[:1], np.array([4.0]))
    assert np.isnan(state.roi_maxs[1])
    np.testing.assert_allclose(state.roi_sums[:1], np.array([8.0]))
    assert np.isnan(state.roi_sums[1])
    np.testing.assert_allclose(state.roi_means[:1], np.array([2.0]))
    assert np.isnan(state.roi_means[1])
    np.testing.assert_allclose(state.roi_stds[:1], np.array([1.0]))
    np.testing.assert_allclose(state.roi_sems[:1], np.array([0.5]))
    np.testing.assert_allclose(state.roi_topk_means[:1], np.array([3.5]))
    np.testing.assert_allclose(state.roi_topk_stds[:1], np.array([0.5]))
    np.testing.assert_allclose(state.roi_topk_sems[:1], np.array([0.25]))


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

    cancelled_stats_job_id = state.cancel_stats_job()
    assert cancelled_stats_job_id == 2
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


def test_low_signal_mask_and_count_follow_applied_threshold(
    state: MetricsPipelineController,
) -> None:
    state.maxs = np.array([3, 8, 11], dtype=np.int64)
    state.low_signal_threshold_value = 8

    mask = state.low_signal_mask(path_count=3)

    assert mask is not None
    np.testing.assert_array_equal(mask, np.array([True, True, False], dtype=bool))
    assert state.low_signal_image_count(path_count=3) == 2

    state.low_signal_threshold_value = 0
    assert state.low_signal_mask(path_count=3) is None
    assert state.low_signal_image_count(path_count=3) == 0
