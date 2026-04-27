from __future__ import annotations

import numpy as np
import pytest

from framelab.analysis_context import AnalysisContextController
from framelab.dataset_state import DatasetScopeNode, DatasetStateController
from framelab.metrics_state import (
    MetricFamily,
    MetricFamilyState,
    MetricsPipelineController,
)


pytestmark = [pytest.mark.analysis, pytest.mark.core]


def test_build_context_normalizes_metric_fields_but_keeps_raw_metadata() -> None:
    dataset = DatasetStateController()
    dataset.set_loaded_dataset(None, ["/tmp/a.tif"])
    dataset.set_path_metadata(
        {
            "/tmp/a.tif": {
                "iris_position": 3,
                "exposure_ms": 25.0,
                "frame_index": 7,
                "utc_timestamp_ms": 1776623606086,
            },
        },
    )
    metrics = MetricsPipelineController()
    metrics.maxs = np.array([100], dtype=np.int64)
    metrics.min_non_zero = np.array([4], dtype=np.int64)
    metrics.sat_counts = np.array([3], dtype=np.int64)
    metrics.avg_maxs = np.array([50.0])
    metrics.avg_maxs_std = np.array([10.0])
    metrics.avg_maxs_sem = np.array([5.0])
    metrics.dn_per_ms_values = np.array([2.0])
    metrics.dn_per_ms_stds = np.array([0.4])
    metrics.dn_per_ms_sems = np.array([0.2])
    metrics.normalize_intensity_values = True

    controller = AnalysisContextController(
        dataset,
        metrics,
        background_reference_label_resolver=lambda path: f"ref:{path}",
    )
    context = controller.build_context(
        mode="topk",
        normalization_scale=100.0,
    )

    assert context.normalization_enabled
    assert context.normalization_scale == 100.0
    assert len(context.records) == 1
    record = context.records[0]
    assert record.mean == pytest.approx(0.5)
    assert record.std == pytest.approx(0.1)
    assert record.sem == pytest.approx(0.05)
    assert float(record.metadata["dn_per_ms"]) == pytest.approx(0.02)
    assert float(record.metadata["dn_per_ms_std"]) == pytest.approx(0.004)
    assert float(record.metadata["dn_per_ms_sem"]) == pytest.approx(0.002)
    assert float(record.metadata["max_pixel"]) == 100.0
    assert float(record.metadata["min_non_zero"]) == 4.0
    assert float(record.metadata["sat_count"]) == 3.0
    assert float(record.metadata["exposure_ms"]) == 25.0
    assert float(record.metadata["frame_index"]) == 7.0
    assert float(record.metadata["elapsed_time_s"]) == pytest.approx(0.0)


def test_build_context_sets_background_flags_and_reference_labels() -> None:
    dataset = DatasetStateController()
    dataset.set_loaded_dataset(None, ["/tmp/a.tif", "/tmp/b.tif"])
    dataset.set_path_metadata(
        {
            "/tmp/a.tif": {},
            "/tmp/b.tif": {},
        },
    )
    metrics = MetricsPipelineController()
    metrics.background_config.enabled = True
    metrics.bg_applied_mask = np.array([True, False], dtype=bool)

    controller = AnalysisContextController(
        dataset,
        metrics,
        background_reference_label_resolver=lambda path: f"ref:{path}",
    )
    context = controller.build_context(
        mode="none",
        normalization_scale=1.0,
    )

    record_a, record_b = context.records
    assert record_a.metadata["background_enabled"]
    assert record_a.metadata["background_applied"]
    assert record_a.metadata["background_reference"] == "ref:/tmp/a.tif"
    assert record_b.metadata["background_enabled"]
    assert not record_b.metadata["background_applied"]
    assert record_b.metadata["background_reference"] == "raw_fallback"


def test_build_context_omits_uncomputed_downstream_fields() -> None:
    dataset = DatasetStateController()
    dataset.set_loaded_dataset(None, ["/tmp/a.tif"])
    metrics = MetricsPipelineController()
    metrics.maxs = np.array([100], dtype=np.int64)
    metrics.min_non_zero = np.array([4], dtype=np.int64)
    metrics.background_config.enabled = True

    controller = AnalysisContextController(
        dataset,
        metrics,
        background_reference_label_resolver=lambda path: f"ref:{path}",
    )
    context = controller.build_context(
        mode="none",
        normalization_scale=1.0,
    )

    record = context.records[0]
    assert record.metadata["max_pixel"] == 100.0
    assert record.metadata["min_non_zero"] == 4.0
    assert record.metadata["background_enabled"]
    assert "sat_count" not in record.metadata
    assert "background_applied" not in record.metadata
    assert "background_reference" not in record.metadata


def test_build_context_uses_roi_topk_metric_arrays() -> None:
    dataset = DatasetStateController()
    dataset.set_loaded_dataset(None, ["/tmp/a.tif"])
    metrics = MetricsPipelineController()
    metrics.roi_topk_means = np.array([35.0])
    metrics.roi_topk_stds = np.array([5.0])
    metrics.roi_topk_sems = np.array([2.5])

    controller = AnalysisContextController(
        dataset,
        metrics,
        background_reference_label_resolver=lambda path: f"ref:{path}",
    )
    context = controller.build_context(
        mode="roi_topk",
        normalization_scale=1.0,
    )

    record = context.records[0]
    assert record.mean == pytest.approx(35.0)
    assert record.std == pytest.approx(5.0)
    assert record.sem == pytest.approx(2.5)
    assert record.metadata["roi_topk_mean"] == pytest.approx(35.0)
    assert record.metadata["roi_topk_std"] == pytest.approx(5.0)
    assert record.metadata["roi_topk_sem"] == pytest.approx(2.5)


def test_build_context_exposes_workflow_scope_and_effective_metadata() -> None:
    dataset = DatasetStateController()
    dataset.set_loaded_dataset("/tmp/workspace/session-01", ["/tmp/workspace/session-01/a.tif"])
    dataset.set_path_metadata(
        {
            "/tmp/workspace/session-01/a.tif": {
                "exposure_ms": 12.0,
            },
        },
    )
    dataset.set_workflow_scope(
        root="/tmp/workspace/session-01",
        kind="session",
        label="Session 01",
        workflow_profile_id="calibration",
        workflow_anchor_type_id="session",
        workflow_anchor_label="Session subtree",
        workflow_anchor_path="/tmp/workspace/session-01",
        workflow_is_partial=True,
        active_node_id="calibration:session:session-01",
        active_node_type="session",
        active_node_path="/tmp/workspace/session-01",
        ancestor_chain=(
            DatasetScopeNode(
                node_id="calibration:root",
                type_id="root",
                display_name="Calibration",
                folder_path="/tmp/workspace",
            ),
            DatasetScopeNode(
                node_id="calibration:session:session-01",
                type_id="session",
                display_name="Session 01",
                folder_path="/tmp/workspace/session-01",
            ),
        ),
        effective_metadata={"camera_settings.exposure_us": 12000},
        metadata_sources={"camera_settings.exposure_us": "node_inherited"},
    )
    metrics = MetricsPipelineController()

    controller = AnalysisContextController(
        dataset,
        metrics,
        background_reference_label_resolver=lambda path: f"ref:{path}",
    )
    context = controller.build_context(
        mode="none",
        normalization_scale=1.0,
    )

    assert context.workflow_profile_id == "calibration"
    assert context.workflow_anchor_type_id == "session"
    assert context.workflow_anchor_label == "Session subtree"
    assert context.workflow_anchor_path == "/tmp/workspace/session-01"
    assert context.workflow_is_partial
    assert context.active_node_id == "calibration:session:session-01"
    assert context.active_node_type == "session"
    assert context.active_scope_kind == "session"
    assert context.active_scope_label == "Session 01"
    assert context.dataset_scope_source == "workflow"
    assert context.dataset_scope_root == "/tmp/workspace/session-01"
    assert context.effective_metadata == {"camera_settings.exposure_us": 12000}
    assert context.metadata_sources == {
        "camera_settings.exposure_us": "node_inherited",
    }
    assert [node.type_id for node in context.ancestor_chain] == ["root", "session"]


def test_build_context_exposes_metric_family_readiness() -> None:
    dataset = DatasetStateController()
    dataset.set_loaded_dataset(None, ["/tmp/a.tif"])
    metrics = MetricsPipelineController()
    metrics.set_metric_family_state(MetricFamily.STATIC_SCAN, MetricFamilyState.READY)
    metrics.set_metric_family_state(
        MetricFamily.TOPK,
        MetricFamilyState.FAILED,
        "worker failed",
    )

    controller = AnalysisContextController(
        dataset,
        metrics,
        background_reference_label_resolver=lambda path: f"ref:{path}",
    )
    context = controller.build_context(
        mode="none",
        normalization_scale=1.0,
    )

    assert context.metric_family_status("static_scan").ready
    topk_status = context.metric_family_status("topk")
    assert topk_status.state == "failed"
    assert topk_status.message == "worker failed"
    assert context.metric_family_status("roi_topk").state == "not_requested"


def test_context_data_signature_is_stable_for_same_scientific_inputs() -> None:
    dataset = DatasetStateController()
    dataset.set_loaded_dataset(None, ["/tmp/a.tif"])
    dataset.set_path_metadata(
        {
            "/tmp/a.tif": {
                "frame_index": 1,
                "exposure_ms": 12.0,
            },
        },
    )
    metrics = MetricsPipelineController()
    metrics.maxs = np.array([100], dtype=np.int64)
    metrics.set_metric_family_state(MetricFamily.STATIC_SCAN, MetricFamilyState.READY)

    controller = AnalysisContextController(
        dataset,
        metrics,
        background_reference_label_resolver=lambda path: f"ref:{path}",
    )

    first = controller.build_context(mode="none", normalization_scale=1.0)
    second = controller.build_context(mode="none", normalization_scale=1.0)

    assert first.data_signature
    assert first.data_signature == second.data_signature


def test_context_data_signature_changes_when_exposed_data_changes() -> None:
    dataset = DatasetStateController()
    dataset.set_loaded_dataset(None, ["/tmp/a.tif"])
    dataset.set_path_metadata({"/tmp/a.tif": {"frame_index": 1}})
    metrics = MetricsPipelineController()
    metrics.maxs = np.array([100], dtype=np.int64)

    controller = AnalysisContextController(
        dataset,
        metrics,
        background_reference_label_resolver=lambda path: f"ref:{path}",
    )

    before = controller.build_context(mode="none", normalization_scale=1.0)
    metrics.maxs = np.array([101], dtype=np.int64)
    after = controller.build_context(mode="none", normalization_scale=1.0)

    assert before.data_signature != after.data_signature
