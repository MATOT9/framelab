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


def _thread_is_running(thread) -> bool:
    try:
        return bool(thread is not None and thread.isRunning())
    except RuntimeError:
        return False


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

    def _slow_scan(path, *, raw_resolver_context=None):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            assert release_remaining.wait(timeout=5.0)
        return original_scan(path, raw_resolver_context=raw_resolver_context)

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

    def _slow_scan(path, *, raw_resolver_context=None):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            assert release_remaining.wait(timeout=5.0)
        return original_scan(path, raw_resolver_context=raw_resolver_context)

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


def test_rescan_waits_for_prior_loader_to_drain_without_stale_rows(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_until,
) -> None:
    first_root = _write_dataset(tmp_path / "scope-a", 8)
    second_root = _write_dataset(tmp_path / "scope-b", 3)
    original_scan = workers_module.scan_single_static_image
    monkeypatch.setattr(
        workers_module,
        "dataset_scan_chunk_size",
        lambda total: 4 if total >= 8 else 1,
    )
    monkeypatch.setattr(
        workers_module,
        "dataset_scan_worker_count",
        lambda worker_count=None, *, cpu_count=None: 2,
    )
    release_first_tail = threading.Event()
    second_chunk_started = threading.Event()

    def _slow_scan(path, *, raw_resolver_context=None):
        resolved = Path(path).resolve()
        try:
            is_first_scope = resolved.is_relative_to(first_root.resolve())
        except AttributeError:
            is_first_scope = str(resolved).startswith(str(first_root.resolve()))
        if is_first_scope and resolved.stem.startswith("frame_"):
            index = int(resolved.stem.split("_")[1])
            if index >= 4:
                second_chunk_started.set()
                assert release_first_tail.wait(timeout=5.0)
        return original_scan(path, raw_resolver_context=raw_resolver_context)

    monkeypatch.setattr(workers_module, "scan_single_static_image", _slow_scan)

    window = framelab_window_factory(enabled_plugin_ids=())
    completed_summaries: list[object] = []
    window.datasetLoadCompleted.connect(completed_summaries.append)

    window.folder_edit.setText(str(first_root))
    window.load_folder()

    wait_until(lambda: window.dataset_state.path_count() == 4, timeout_ms=8000)
    wait_until(second_chunk_started.is_set, timeout_ms=4000)

    first_thread = window._dataset_load_thread
    assert first_thread is not None
    assert _thread_is_running(first_thread)

    window.folder_edit.setText(str(second_root))
    window.load_folder()

    wait_until(
        lambda: bool(getattr(window, "_dataset_load_start_pending", False)),
        timeout_ms=4000,
    )
    second_thread = window._dataset_load_thread
    assert second_thread is not None
    assert second_thread is not first_thread
    assert not second_thread.isRunning()
    assert window.dataset_state.path_count() == 0

    release_first_tail.set()

    wait_until(
        lambda: (
            not window._is_dataset_load_running()
            and not _thread_is_running(first_thread)
            and window.dataset_state.dataset_root == second_root.resolve()
            and window.dataset_state.path_count() == 3
            and all(
                Path(path).resolve().is_relative_to(second_root.resolve())
                for path in window.dataset_state.paths
            )
        ),
        timeout_ms=15000,
    )

    _assert_measure_table_rows_in_sync(window, 3)
    assert window.table.model() is window.table_proxy
    assert window._dataset_load_thread is None
    assert any(
        isinstance(summary, workers_module.DatasetLoadSummary)
        and Path(summary.dataset_root).resolve() == second_root.resolve()
        for summary in completed_summaries
    )


def test_closing_window_after_dataset_load_does_not_touch_deleted_worker(
    tmp_path: Path,
    framelab_window_factory,
    wait_until,
    process_events,
) -> None:
    dataset_root = _write_dataset(tmp_path / "close-after-load", 4)
    window = framelab_window_factory(enabled_plugin_ids=())
    window.folder_edit.setText(str(dataset_root))

    window.load_folder()
    wait_until(
        lambda: (
            not window._is_dataset_load_running()
            and window.dataset_state.path_count() == 4
        ),
        timeout_ms=10000,
    )

    window.close()
    process_events()


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


def test_scan_completion_does_not_start_dynamic_stats(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_for_dataset_load,
) -> None:
    dataset_root = _write_dataset(tmp_path / "scan-only-dataset", 4)
    window = framelab_window_factory(enabled_plugin_ids=())
    dynamic_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        window,
        "_start_dynamic_stats_job",
        lambda **kwargs: dynamic_calls.append(dict(kwargs)),
    )

    window.folder_edit.setText(str(dataset_root))
    window.load_folder()
    wait_for_dataset_load(window, timeout_ms=12000)

    assert dynamic_calls == []
    assert window.metrics_state.maxs is not None
    assert window.metrics_state.min_non_zero is not None
    assert window.metrics_state.sat_counts is None
    _assert_measure_table_rows_in_sync(window, 4)


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


def test_rescan_ignores_stale_dynamic_stats_from_previous_scope(
    tmp_path: Path,
    framelab_window_factory,
    monkeypatch,
    wait_until,
    wait_for_dataset_load,
) -> None:
    first_root = _write_dataset(tmp_path / "stats-scope-a", 8)
    second_root = _write_dataset(tmp_path / "stats-scope-b", 3)
    window = framelab_window_factory(enabled_plugin_ids=())

    window.folder_edit.setText(str(first_root))
    window.load_folder()
    wait_for_dataset_load(window, timeout_ms=12000)
    stale_job_id = window.metrics_state.begin_stats_job(
        update_kind="full",
        refresh_analysis=True,
    )
    assert window.metrics_state.is_stats_running
    stale_result = workers_module.DynamicStatsResult(
        job_id=stale_job_id,
        sat_counts=np.full(8, 99, dtype=np.int64),
        avg_topk=None,
        avg_topk_std=None,
        avg_topk_sem=None,
        max_pixels=np.full(8, 99, dtype=np.int64),
        min_non_zero=np.full(8, 99, dtype=np.int64),
        bg_applied_mask=np.ones(8, dtype=bool),
    )

    window.folder_edit.setText(str(second_root))
    window.load_folder(suppress_auto_metrics=True)

    wait_for_dataset_load(window, timeout_ms=12000)
    window._on_dynamic_stats_finished(stale_result)
    wait_until(
        lambda: (
            window.dataset_state.dataset_root == second_root.resolve()
            and window.dataset_state.path_count() == 3
            and not window.metrics_state.is_stats_running
            and window._stats_thread is None
            and window.metrics_state.maxs is not None
            and len(window.metrics_state.maxs) == 3
            and window.metrics_state.min_non_zero is not None
            and len(window.metrics_state.min_non_zero) == 3
            and window.metrics_state.sat_counts is None
            and all(
                Path(path).resolve().is_relative_to(second_root.resolve())
                for path in window.dataset_state.paths
            )
        ),
        timeout_ms=15000,
    )

    _assert_measure_table_rows_in_sync(window, 3)
