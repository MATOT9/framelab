from __future__ import annotations

import unittest

import numpy as np

from framelab.analysis_context import AnalysisContextController
from framelab.dataset_state import DatasetStateController
from framelab.metrics_state import MetricsPipelineController


class AnalysisContextControllerTests(unittest.TestCase):
    def test_build_context_normalizes_metric_fields_but_keeps_raw_metadata(self) -> None:
        dataset = DatasetStateController()
        dataset.set_loaded_dataset(None, ["/tmp/a.tif"])
        dataset.set_path_metadata(
            {
                "/tmp/a.tif": {
                    "iris_position": 3,
                    "exposure_ms": 25.0,
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

        self.assertTrue(context.normalization_enabled)
        self.assertEqual(context.normalization_scale, 100.0)
        self.assertEqual(len(context.records), 1)
        record = context.records[0]
        self.assertAlmostEqual(record.mean, 0.5)
        self.assertAlmostEqual(record.std, 0.1)
        self.assertAlmostEqual(record.sem, 0.05)
        self.assertAlmostEqual(float(record.metadata["dn_per_ms"]), 0.02)
        self.assertAlmostEqual(float(record.metadata["dn_per_ms_std"]), 0.004)
        self.assertAlmostEqual(float(record.metadata["dn_per_ms_sem"]), 0.002)
        self.assertEqual(float(record.metadata["max_pixel"]), 100.0)
        self.assertEqual(float(record.metadata["min_non_zero"]), 4.0)
        self.assertEqual(float(record.metadata["sat_count"]), 3.0)
        self.assertEqual(float(record.metadata["exposure_ms"]), 25.0)

    def test_build_context_sets_background_flags_and_reference_labels(self) -> None:
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
        self.assertTrue(record_a.metadata["background_enabled"])
        self.assertTrue(record_a.metadata["background_applied"])
        self.assertEqual(record_a.metadata["background_reference"], "ref:/tmp/a.tif")
        self.assertTrue(record_b.metadata["background_enabled"])
        self.assertFalse(record_b.metadata["background_applied"])
        self.assertEqual(record_b.metadata["background_reference"], "raw_fallback")


if __name__ == "__main__":
    unittest.main()
