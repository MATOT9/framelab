from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
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


pytestmark = [pytest.mark.data, pytest.mark.core]


class _DatasetScanHarness(DatasetLoadingMixin):
    def __init__(self) -> None:
        self.cached: dict[str, np.ndarray] = {}

    def _read_2d_image(self, path: Path) -> np.ndarray:
        return read_2d_image(path)

    def _cache_image(self, path: str, image: np.ndarray) -> None:
        self.cached[path] = image


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
    assert str(valid_path) in harness.cached
    assert len(failures) == 1
    assert failures[0].stage == "scan"
    assert failures[0].path == str(invalid_path)
    assert "InvalidImageError" in failures[0].reason
