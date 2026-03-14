from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import tifffile

from framelab.image_io import read_2d_image
from framelab.main_window.dataset_loading import DatasetLoadingMixin
from framelab.processing_failures import (
    ProcessingFailure,
    format_processing_failure_details,
    make_processing_failure,
    merge_processing_failures,
    summarize_processing_failures,
)


class _DatasetScanHarness(DatasetLoadingMixin):
    def __init__(self) -> None:
        self.cached: dict[str, np.ndarray] = {}

    def _read_2d_image(self, path: Path) -> np.ndarray:
        return read_2d_image(path)

    def _cache_image(self, path: str, image: np.ndarray) -> None:
        self.cached[path] = image


class ProcessingFailureHelpersTests(unittest.TestCase):
    def test_merge_processing_failures_dedupes_and_replaces_stage(self) -> None:
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
        self.assertEqual(merged, [scan_failure, roi_failure])

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
        self.assertEqual(len(replaced), 2)
        self.assertEqual(
            [failure.stage for failure in replaced],
            ["roi", "scan"],
        )

    def test_failure_summary_and_details_are_human_readable(self) -> None:
        failures = [
            ProcessingFailure("scan", "a.tif", "InvalidImageError: unreadable"),
            ProcessingFailure("scan", "b.tif", "InvalidImageError: missing"),
            ProcessingFailure("metrics", "", "Worker crashed"),
        ]
        summary = summarize_processing_failures(failures)
        details = format_processing_failure_details(failures)
        self.assertEqual(summary, "Scan 2, Metrics 1")
        self.assertIn("3 processing issue(s)", details)
        self.assertIn("[Scan] a.tif", details)
        self.assertIn("[Metrics] <operation>", details)


class DatasetScanFailureTests(unittest.TestCase):
    def test_scan_tiffs_chunked_parallel_returns_structured_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            valid_path = root / "valid.tif"
            invalid_path = root / "broken.tif"
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

        self.assertEqual(paths, [str(valid_path)])
        self.assertEqual(mins, [1])
        self.assertEqual(maxs, [4])
        self.assertEqual(skipped, 1)
        self.assertIn(str(valid_path), harness.cached)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].stage, "scan")
        self.assertEqual(failures[0].path, str(invalid_path))
        self.assertIn("InvalidImageError", failures[0].reason)


if __name__ == "__main__":
    unittest.main()
