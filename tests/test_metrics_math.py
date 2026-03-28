from __future__ import annotations

import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets as qtw

from framelab.dataset_state import DatasetStateController
from framelab.background import BackgroundConfig
from framelab.main_window.analysis import AnalysisPageMixin
from framelab.main_window.inspect_page import InspectPageMixin
from framelab.main_window.window_actions import WindowActionsMixin
from framelab.metric_reducers import compute_roi_stats
from framelab.metrics_state import MetricsPipelineController
from framelab.models import MetricsTableModel


class _InspectMathHarness:
    _compute_dn_per_ms_metrics = InspectPageMixin._compute_dn_per_ms_metrics
    _normalization_scale = InspectPageMixin._normalization_scale
    _format_mean_std_sem = InspectPageMixin._format_mean_std_sem

    def __init__(self) -> None:
        self.avg_maxs = None
        self.avg_maxs_std = None
        self.avg_maxs_sem = None
        self.roi_means = None
        self.roi_stds = None
        self.roi_sems = None
        self.maxs = None
        self.normalize_intensity_values = False
        self.rounding_mode = "off"


class _AnalysisHarness(AnalysisPageMixin):
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.path_metadata: dict[str, dict[str, object]] = {}
        self.maxs = None
        self.min_non_zero = None
        self.sat_counts = None
        self.dn_per_ms_values = None
        self.dn_per_ms_stds = None
        self.dn_per_ms_sems = None
        self.avg_maxs = None
        self.avg_maxs_std = None
        self.avg_maxs_sem = None
        self.roi_means = None
        self.roi_stds = None
        self.roi_sems = None
        self.normalize_intensity_values = False
        self.background_config = BackgroundConfig()
        self._bg_applied_mask = None
        self._mode = "none"
        self._scale = 1.0

    def _current_average_mode(self) -> str:
        return self._mode

    def _normalization_scale(self) -> float:
        return self._scale

    def _background_reference_label_for_path(self, path: str) -> str:
        return f"ref:{path}"


class _PreviewStub:
    def __init__(self) -> None:
        self.roi_rect = None

    def set_roi_rect(self, rect) -> None:
        self.roi_rect = rect


class _RoiSelectionHarness(WindowActionsMixin, InspectPageMixin):
    _compute_dn_per_ms_metrics = InspectPageMixin._compute_dn_per_ms_metrics
    _metadata_numeric_arrays = InspectPageMixin._metadata_numeric_arrays

    def __init__(self) -> None:
        self.dataset_state = DatasetStateController()
        self.metrics_state = MetricsPipelineController()
        self.image_preview = _PreviewStub()
        self._images: list[np.ndarray] = []
        self.last_status = None

    def load_images(
        self,
        images: list[np.ndarray],
        path_metadata: dict[str, dict[str, object]],
    ) -> None:
        paths = [f"/tmp/image-{index}.tiff" for index in range(len(images))]
        self._images = [np.asarray(image, dtype=np.float64) for image in images]
        self.dataset_state.set_loaded_dataset(None, paths)
        self.dataset_state.set_path_metadata(
            {
                path: dict(path_metadata.get(path, {}))
                for path in paths
            },
        )
        count = len(paths)
        self.metrics_state.maxs = np.asarray(
            [int(np.max(image)) for image in self._images],
            dtype=np.int64,
        )
        self.metrics_state.min_non_zero = np.asarray(
            [
                int(np.min(image[np.nonzero(image)]))
                if np.any(image)
                else 0
                for image in self._images
            ],
            dtype=np.int64,
        )
        self.metrics_state.sat_counts = np.zeros(count, dtype=np.int64)
        self.metrics_state.reset_roi_metrics(count)

    def _has_loaded_data(self) -> bool:
        return self.dataset_state.has_loaded_data()

    def _get_metric_image_by_index(self, index: int):
        if not (0 <= index < len(self._images)):
            return (None, False)
        return (self._images[index], False)

    def _reset_roi_metrics(self) -> None:
        self.metrics_state.reset_roi_metrics(self.dataset_state.path_count())

    def _compute_roi_stats_for_index(
        self,
        index: int,
    ) -> tuple[float, float, float, float]:
        roi_rect = self.metrics_state.roi_rect
        if roi_rect is None:
            return (np.nan, np.nan, np.nan, np.nan)
        image = self._images[index]
        x0, y0, x1, y1 = roi_rect
        return compute_roi_stats(image[y0:y1, x0:x1])

    def _update_average_controls(self) -> None:
        return

    def _refresh_table(self, *, update_analysis: bool = True) -> None:
        _iris_positions, exposure_ms = self._metadata_numeric_arrays()
        (
            self.metrics_state.dn_per_ms_values,
            self.metrics_state.dn_per_ms_stds,
            self.metrics_state.dn_per_ms_sems,
        ) = self._compute_dn_per_ms_metrics("roi", exposure_ms)

    def _refresh_workspace_document_dirty_state(self) -> None:
        return

    def _set_status(self, warning: str | None = None) -> None:
        self.last_status = warning


pytestmark = [pytest.mark.fast, pytest.mark.analysis]


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp) -> None:
    _ = qapp


def test_compute_dn_per_ms_metrics_handles_valid_zero_and_missing_exposure() -> None:
    host = _InspectMathHarness()
    host.avg_maxs = np.array([20.0, 30.0, 40.0])
    host.avg_maxs_std = np.array([2.0, 3.0, 4.0])
    host.avg_maxs_sem = np.array([1.0, 1.5, 2.0])
    exposure_ms = np.array([10.0, 0.0, np.nan])

    values, stds, sems = host._compute_dn_per_ms_metrics("topk", exposure_ms)

    np.testing.assert_allclose(values[:1], np.array([2.0]))
    np.testing.assert_allclose(stds[:1], np.array([0.2]))
    np.testing.assert_allclose(sems[:1], np.array([0.1]))
    assert np.isnan(values[1])
    assert np.isnan(values[2])
    assert np.isnan(stds[1])
    assert np.isnan(sems[2])


def test_compute_dn_per_ms_metrics_uses_roi_arrays_in_roi_mode() -> None:
    host = _InspectMathHarness()
    host.roi_means = np.array([12.0])
    host.roi_stds = np.array([3.0])
    host.roi_sems = np.array([1.5])

    values, stds, sems = host._compute_dn_per_ms_metrics(
        "roi",
        np.array([4.0]),
    )

    np.testing.assert_allclose(values, np.array([3.0]))
    np.testing.assert_allclose(stds, np.array([0.75]))
    np.testing.assert_allclose(sems, np.array([0.375]))


def test_apply_roi_rect_uses_fallback_selection_for_dn_per_ms() -> None:
    host = _RoiSelectionHarness()
    path_metadata = {
        "/tmp/image-0.tiff": {"exposure_ms": 10.0},
        "/tmp/image-1.tiff": {"exposure_ms": 20.0},
    }
    host.load_images(
        [
            np.full((4, 4), 4.0, dtype=np.float64),
            np.full((4, 4), 12.0, dtype=np.float64),
        ],
        path_metadata,
    )
    host.dataset_state.set_selected_index(None)

    applied = host._apply_roi_rect_to_current_dataset(
        (0, 0, 2, 2),
        status_message=None,
    )

    assert applied
    assert host.dataset_state.selected_index == 0
    assert host.image_preview.roi_rect == (0, 0, 2, 2)
    assert float(host.metrics_state.roi_means[0]) == pytest.approx(4.0)
    assert np.isnan(host.metrics_state.roi_means[1])
    assert float(host.metrics_state.dn_per_ms_values[0]) == pytest.approx(0.4)
    assert np.isnan(host.metrics_state.dn_per_ms_values[1])


def test_apply_roi_rect_derives_dn_per_ms_from_raw_exposure_metadata() -> None:
    host = _RoiSelectionHarness()
    path_metadata = {
        "/tmp/image-0.tiff": {"camera_settings.exposure_us": 12500},
    }
    host.load_images(
        [np.full((4, 4), 10.0, dtype=np.float64)],
        path_metadata,
    )
    host.dataset_state.set_selected_index(0, path_count=1)

    applied = host._apply_roi_rect_to_current_dataset(
        (0, 0, 2, 2),
        status_message=None,
    )

    assert applied
    assert float(host.metrics_state.roi_means[0]) == pytest.approx(10.0)
    assert float(host.metrics_state.dn_per_ms_values[0]) == pytest.approx(0.8)


def test_normalization_scale_falls_back_to_one_for_empty_or_zero_max() -> None:
    host = _InspectMathHarness()
    assert host._normalization_scale() == 1.0
    host.maxs = np.array([0, 0], dtype=np.int64)
    assert host._normalization_scale() == 1.0
    host.maxs = np.array([0, 12], dtype=np.int64)
    assert host._normalization_scale() == 12.0


def test_metrics_table_normalization_changes_intensity_fields_but_not_sat_count() -> None:
    model = MetricsTableModel()
    model.update_metrics(
        paths=["/tmp/a.tif"],
        iris_positions=np.array([5.0]),
        exposure_ms=np.array([10.0]),
        maxs=np.array([100], dtype=np.int64),
        roi_maxs=np.array([80.0]),
        min_non_zero=np.array([4], dtype=np.int64),
        sat_counts=np.array([3], dtype=np.int64),
        low_signal_flags=np.array([False], dtype=bool),
        avg_mode="topk",
        avg_topk=np.array([50.0]),
        avg_topk_std=np.array([10.0]),
        avg_topk_sem=np.array([5.0]),
        avg_roi=None,
        avg_roi_std=None,
        avg_roi_sem=None,
        dn_per_ms=np.array([2.0]),
    )

    assert model.data(model.index(0, 4)) == "100"
    assert model.data(model.index(0, 5)) == "80"
    assert model.data(model.index(0, 7)) == "3"
    assert model.data(model.index(0, 8)) == "50.00"
    assert model.data(model.index(0, 11)) == "2"

    model.set_intensity_normalization(True, 100.0)

    assert model.data(model.index(0, 4)) == "1"
    assert model.data(model.index(0, 5)) == "0.8"
    assert model.data(model.index(0, 7)) == "3"
    assert model.data(model.index(0, 8)) == "0.50"
    assert model.data(model.index(0, 11)) == "0.02"


def test_metrics_table_uses_distinct_low_signal_row_highlight_with_saturation_precedence() -> None:
    model = MetricsTableModel()
    model.update_metrics(
        paths=["/tmp/a.tif", "/tmp/b.tif"],
        iris_positions=np.array([5.0, 5.0]),
        exposure_ms=np.array([10.0, 10.0]),
        maxs=np.array([4, 6], dtype=np.int64),
        roi_maxs=np.array([4.0, 6.0]),
        min_non_zero=np.array([1, 1], dtype=np.int64),
        sat_counts=np.array([0, 2], dtype=np.int64),
        low_signal_flags=np.array([True, True], dtype=bool),
        avg_mode="none",
        avg_topk=None,
        avg_topk_std=None,
        avg_topk_sem=None,
        avg_roi=None,
        avg_roi_std=None,
        avg_roi_sem=None,
        dn_per_ms=None,
    )

    assert model.data(model.index(0, 0), QtCore.Qt.BackgroundRole) == model.LOW_SIGNAL_ROW_BRUSH
    assert model.data(model.index(1, 0), QtCore.Qt.BackgroundRole) == model.SATURATED_ROW_BRUSH


def test_analysis_context_normalizes_active_metric_and_dn_per_ms_but_keeps_raw_metadata() -> None:
    host = _AnalysisHarness()
    host.paths = ["/tmp/a.tif"]
    host.path_metadata = {
        "/tmp/a.tif": {
            "iris_position": 3,
            "exposure_ms": 25.0,
        },
    }
    host.maxs = np.array([100], dtype=np.int64)
    host.min_non_zero = np.array([4], dtype=np.int64)
    host.sat_counts = np.array([3], dtype=np.int64)
    host.avg_maxs = np.array([50.0])
    host.avg_maxs_std = np.array([10.0])
    host.avg_maxs_sem = np.array([5.0])
    host.dn_per_ms_values = np.array([2.0])
    host.dn_per_ms_stds = np.array([0.4])
    host.dn_per_ms_sems = np.array([0.2])
    host.normalize_intensity_values = True
    host._mode = "topk"
    host._scale = 100.0

    context = host._build_analysis_context()

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
