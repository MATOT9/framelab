"""Async dataset-loading behavior tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from tifffile import imwrite

import framelab.workers as workers_module


pytestmark = [pytest.mark.ui, pytest.mark.core]


def _write_dataset(root: Path, count: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        imwrite(
            root / f"frame_{index:04d}.tiff",
            np.full((4, 4), index + 1, dtype=np.uint16),
        )
    return root


def _assert_measure_table_rows_in_sync(window, expected_rows: int) -> None:
    model = window.table.model()
    assert window.dataset_state.path_count() == expected_rows
    assert window.table_model.rowCount() == expected_rows
    assert window.table_proxy.rowCount() == expected_rows
    assert model is not None
    assert model.rowCount() == expected_rows


def test_load_folder_runs_async_and_streams_rows_progressively(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_until,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_dataset(tmp_path / "async-dataset", 8)
    original_scan = workers_module.scan_single_static_image
    monkeypatch.setattr(workers_module, "dataset_scan_chunk_size", lambda total: 1)
    release_remaining = threading.Event()
    call_count = 0

    def _slow_scan(path):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            assert release_remaining.wait(timeout=5.0)
        return original_scan(path)

    monkeypatch.setattr(workers_module, "scan_single_static_image", _slow_scan)

    window = framelab_window_factory(enabled_plugin_ids=())
    window.folder_edit.setText(str(dataset_root))

    window.load_folder()

    wait_until(window._is_dataset_load_running, timeout_ms=2000)
    wait_until(lambda: window.dataset_state.path_count() >= 1, timeout_ms=4000)

    assert 0 < window.dataset_state.path_count() < 8
    assert window._is_dataset_load_running()

    release_remaining.set()
    wait_for_dataset_load(window, timeout_ms=8000)

    assert window.dataset_state.dataset_root == dataset_root.resolve()
    assert window.dataset_state.path_count() == 8
    assert window.table_proxy.rowCount() == 8


def test_cancelling_dataset_load_keeps_loaded_subset(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_until,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_dataset(tmp_path / "cancel-dataset", 8)
    original_scan = workers_module.scan_single_static_image
    monkeypatch.setattr(workers_module, "dataset_scan_chunk_size", lambda total: 1)
    release_remaining = threading.Event()
    call_count = 0

    def _slow_scan(path):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            assert release_remaining.wait(timeout=5.0)
        return original_scan(path)

    monkeypatch.setattr(workers_module, "scan_single_static_image", _slow_scan)

    window = framelab_window_factory(enabled_plugin_ids=())
    window.folder_edit.setText(str(dataset_root))

    window.load_folder()

    wait_until(lambda: window.dataset_state.path_count() >= 1, timeout_ms=4000)
    window._cancel_dataset_load_job()
    release_remaining.set()
    wait_for_dataset_load(window, timeout_ms=8000)

    assert 1 <= window.dataset_state.path_count() < 8
    assert "load cancelled" in window.base_status.lower()


@pytest.mark.parametrize("image_count", [130, 300])
def test_large_async_dataset_load_keeps_measure_table_proxy_in_sync(
    tmp_path: Path,
    framelab_window_factory,
    wait_until,
    wait_for_dataset_load,
    image_count: int,
) -> None:
    dataset_root = _write_dataset(
        tmp_path / f"large-dataset-{image_count}",
        image_count,
    )
    window = framelab_window_factory(enabled_plugin_ids=())
    window.folder_edit.setText(str(dataset_root))

    window.load_folder()
    wait_for_dataset_load(window, timeout_ms=20000)
    wait_until(
        lambda: (
            window.dataset_state.path_count() == image_count
            and window.table_model.rowCount() == image_count
            and window.table_proxy.rowCount() == image_count
            and window.table.model() is window.table_proxy
            and window.table.model().rowCount() == image_count
        ),
        timeout_ms=20000,
    )

    _assert_measure_table_rows_in_sync(window, image_count)
    assert window.table.model() is window.table_proxy


def test_scope_switch_keeps_measure_table_proxy_sorted_and_in_sync(
    tmp_path: Path,
    framelab_window_factory,
    wait_until,
    wait_for_dataset_load,
) -> None:
    first_root = _write_dataset(tmp_path / "scope-a", 16)
    second_root = _write_dataset(tmp_path / "scope-b", 130)
    third_root = _write_dataset(tmp_path / "scope-c", 300)
    window = framelab_window_factory(enabled_plugin_ids=())

    window.folder_edit.setText(str(first_root))
    window.load_folder()
    wait_for_dataset_load(window, timeout_ms=12000)
    wait_until(lambda: window.table_proxy.rowCount() == 16, timeout_ms=12000)
    _assert_measure_table_rows_in_sync(window, 16)

    window._on_table_header_clicked(1)
    assert window.table.model() is window.table_proxy
    assert window._sort_column == 1

    window._rebind_measure_table_model(prefer_proxy=False)
    assert window.table.model() is window.table_model

    for dataset_root, expected_rows in ((second_root, 130), (third_root, 300)):
        window.folder_edit.setText(str(dataset_root))
        window.load_folder()
        wait_for_dataset_load(window, timeout_ms=20000)
        wait_until(
            lambda rows=expected_rows: (
                window.dataset_state.path_count() == rows
                and window.table_model.rowCount() == rows
                and window.table_proxy.rowCount() == rows
                and window.table.model() is window.table_proxy
                and window.table.model().rowCount() == rows
            ),
            timeout_ms=20000,
        )
        _assert_measure_table_rows_in_sync(window, expected_rows)
        assert window._sort_column == 1
