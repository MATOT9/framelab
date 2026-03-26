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
