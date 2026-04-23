"""Dataset discovery, caching, and background-aware image loading."""

from __future__ import annotations

from collections import Counter
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
import warnings

import numpy as np
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import QSignalBlocker, QThread, Qt

from ..background import (
    BackgroundLibrary,
    canonical_exposure_key,
    select_reference,
    validate_reference_shape,
)
from ..file_dialogs import choose_existing_directory
from ..image_io import (
    is_supported_image,
    read_2d_image,
    source_kind_for_path,
    supported_suffixes,
)
from ..metadata import clear_metadata_cache
from ..metrics_cache import (
    FileMetricIdentity,
    MetricCacheWrite,
    STATIC_METRIC_KIND,
    static_metric_signature_hash,
)
from ..processing_failures import (
    ProcessingFailure,
    failure_reason_from_exception,
    make_processing_failure,
)
from ..native import backend as native_backend
from ..raw_decode import (
    RawDecodeResolverContext,
    build_image_metric_identity,
    raw_decode_spec_fingerprint,
    resolve_raw_decode_spec,
)
from ..workers import (
    DatasetLoadBatch,
    DatasetLoadProgress,
    DatasetLoadSummary,
    DatasetLoadWorker,
    dataset_scan_chunk_size,
    dataset_scan_worker_count,
    scan_single_static_image,
)


class DatasetLoadingMixin:
    """Dataset lifecycle helpers for dataset discovery and image access."""

    @staticmethod
    def _qthread_is_running(thread: QThread | None) -> bool:
        """Return whether one Qt thread object still exists and is running."""

        if thread is None:
            return False
        try:
            return bool(thread.isRunning())
        except RuntimeError:
            return False

    def _manual_raw_decode_overrides(self) -> dict[str, object]:
        """Return session-local fallback RAW decode inputs from the Data page."""

        getter = getattr(self, "_raw_decode_manual_overrides", None)
        if callable(getter):
            return dict(getter())
        return {}

    def _raw_decode_resolver_context(
        self,
        *,
        path_metadata_by_path: dict[str, dict[str, object]] | None = None,
    ) -> RawDecodeResolverContext:
        """Build one shared RAW resolver context for image-loading call sites."""

        boundary_root = (
            self.dataset_state.scope_snapshot.root
            if self.dataset_state.scope_snapshot.source == "workflow"
            else None
        )
        return RawDecodeResolverContext(
            path_metadata_by_path=(
                path_metadata_by_path
                if path_metadata_by_path is not None
                else dict(self.dataset_state.path_metadata)
            ),
            scope_metadata=dict(self.dataset_state.scope_effective_metadata),
            manual_overrides=self._manual_raw_decode_overrides(),
            metadata_boundary_root=boundary_root,
        )

    def _image_cache_key_for_path(self, path: str | Path) -> object:
        """Return the cache key for one image path, including RAW spec when needed."""

        resolved = str(Path(path).expanduser().resolve())
        if source_kind_for_path(resolved) != "raw":
            return resolved
        spec = resolve_raw_decode_spec(
            resolved,
            context=self._raw_decode_resolver_context(),
        )
        return (resolved, raw_decode_spec_fingerprint(spec))

    def _corrected_image_cache_key_for_path(self, path: str | Path) -> tuple[object, int]:
        """Return the corrected-image cache key for one path and background state."""

        return (
            self._image_cache_key_for_path(path),
            self.metrics_state.background_signature,
        )

    def _apply_dataset_load_summary_payload(
        self,
        folder: Path,
        summary: DatasetLoadSummary,
    ) -> None:
        """Canonicalize loaded dataset state from the worker's final summary."""

        paths = list(getattr(summary, "loaded_paths", ()) or ())
        if not paths:
            return

        min_non_zero = getattr(summary, "min_non_zero", None)
        max_pixels = getattr(summary, "max_pixels", None)
        metadata_by_path = dict(getattr(summary, "metadata_by_path", {}) or {})
        count = len(paths)
        mins = (
            np.asarray(min_non_zero, dtype=np.int64).copy()
            if min_non_zero is not None and len(min_non_zero) == count
            else np.zeros(count, dtype=np.int64)
        )
        maxs = (
            np.asarray(max_pixels, dtype=np.int64).copy()
            if max_pixels is not None and len(max_pixels) == count
            else np.zeros(count, dtype=np.int64)
        )

        self.dataset_state.set_loaded_dataset(folder, paths)
        self.dataset_state.update_path_metadata(metadata_by_path)
        self.metrics_state.initialize_loaded_dataset(count)
        self.metrics_state.min_non_zero = mins
        self.metrics_state.maxs = maxs

    def unload_folder(self, *, clear_folder_edit: bool = False) -> None:
        """Clear the currently loaded dataset and reset dependent UI state."""
        dataset = self.dataset_state
        metrics = self.metrics_state
        self._cancel_pending_dataset_load_refresh()
        self._cancel_dataset_load_job()
        self._cancel_stats_job()
        self._cancel_roi_apply_job()
        self._clear_image_cache()
        clear_metadata_cache()
        if hasattr(self, "_clear_processing_failures"):
            self._clear_processing_failures()
        dataset.clear_loaded_dataset()
        metrics.clear_dataset_state()
        dataset.set_selected_index(None)
        self.base_status = "Select a folder."
        if clear_folder_edit and hasattr(self, "folder_edit"):
            self.folder_edit.clear()
        self._update_metadata_source_options(False)
        if hasattr(self, "_refresh_ebus_config_status"):
            self._refresh_ebus_config_status()
        if hasattr(self, "_refresh_metadata_table"):
            self._refresh_metadata_table()
        if hasattr(self, "image_preview"):
            self.image_preview.set_roi_rect(None)
            self.image_preview.reset_view()
        self._refresh_table()
        self._refresh_workspace_document_dirty_state()
        self._set_status()

    def browse_folder(self) -> None:
        """Open a directory picker and trigger dataset loading."""
        initial_dir = self.folder_edit.text().strip() or str(Path.home())
        selected = choose_existing_directory(self, "Select image folder", initial_dir)
        if not selected:
            return
        self.folder_edit.setText(selected)
        self.load_folder()

    def _find_tiffs(
        self,
        folder: Path,
        *,
        apply_skip_patterns: bool = True,
    ) -> list[Path]:
        """Recursively find supported image files while pruning skipped paths."""
        found: list[Path] = []
        root = folder.resolve()
        pruned_dirs = 0
        skipped_files = 0

        for current_root, dir_names, file_names in os.walk(root, topdown=True):
            root_path = Path(current_root)
            relative_root = root_path.relative_to(root)

            kept_dirs: list[str] = []
            for dirname in dir_names:
                candidate_path = root_path / dirname
                rel_path = (relative_root / dirname).as_posix()
                should_skip = apply_skip_patterns and self._is_path_skipped(
                    name=dirname,
                    rel_path=rel_path,
                    abs_path=str(candidate_path),
                )
                if should_skip:
                    pruned_dirs += 1
                    continue
                kept_dirs.append(dirname)
            dir_names[:] = kept_dirs

            for filename in file_names:
                candidate = root_path / filename
                if not is_supported_image(candidate):
                    continue
                rel_file_path = (relative_root / filename).as_posix()
                if apply_skip_patterns and self._is_path_skipped(
                    name=filename,
                    rel_path=rel_file_path,
                    abs_path=str(candidate),
                ):
                    skipped_files += 1
                    continue
                found.append(candidate)

        self._last_scan_pruned_dirs = pruned_dirs
        self._last_scan_skipped_files = skipped_files
        return sorted(found)

    def _read_2d_image(self, path: Path) -> np.ndarray:
        """Read one supported image file and coerce it to a single 2D frame."""
        return read_2d_image(
            path,
            raw_spec_resolver=resolve_raw_decode_spec,
            raw_resolver_context=self._raw_decode_resolver_context(),
        )

    def _scan_worker_count(self) -> int:
        """Return worker count used for image scanning."""
        prefs = getattr(self, "ui_preferences", None)
        worker_override = (
            getattr(prefs, "scan_worker_count_override", None)
            if prefs is not None
            else None
        )
        return dataset_scan_worker_count(worker_override)

    @staticmethod
    def _chunk_size_for_scan(total_files: int) -> int:
        """Return scan chunk size based on dataset size."""
        return dataset_scan_chunk_size(total_files)

    def _scan_single_tiff(
        self,
        path: Path,
    ) -> tuple[Optional[tuple[str, int, int]], tuple[object, ...]]:
        """Read a single image and derive quick static metrics."""
        return scan_single_static_image(
            path,
            raw_resolver_context=self._raw_decode_resolver_context(),
        )

    def _scan_tiffs_chunked_parallel(
        self,
        files: list[Path],
        *,
        update_status: bool = False,
        dataset_root: Path | None = None,
    ) -> tuple[list[str], list[int], list[int], int, list[object]]:
        """Scan image files in chunks and preserve source order."""
        if not files:
            return ([], [], [], 0, [])

        chunk_size = self._chunk_size_for_scan(len(files))
        max_workers = self._scan_worker_count()
        skipped = 0
        processed = 0
        failures: list[object] = []
        cache = getattr(self, "metrics_cache", None)
        static_signature = static_metric_signature_hash()
        identities_by_path = self._metric_cache_identities(
            files,
            dataset_root=dataset_root,
        )
        cached_metrics: dict[str, tuple[int, int]] = {}
        if cache is not None and identities_by_path:
            cached_payloads = cache.fetch_entries(
                identities_by_path.values(),
                metric_kind=STATIC_METRIC_KIND,
                signature_hash=static_signature,
            )
            cached_metrics = {
                path: (
                    int(payload.get("min_non_zero", 0)),
                    int(payload.get("max_pixel", 0)),
                )
                for path, payload in cached_payloads.items()
            }
        processed = len(cached_metrics)

        uncached_files = [
            path
            for path in files
            if str(path.resolve()) not in cached_metrics
        ]
        computed_metrics: dict[str, tuple[int, int]] = {}
        cache_writes: list[MetricCacheWrite] = []

        if uncached_files:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for start in range(0, len(uncached_files), chunk_size):
                    chunk = uncached_files[start:start + chunk_size]
                    future_to_index = {
                        executor.submit(self._scan_single_tiff, path): i
                        for i, path in enumerate(chunk)
                    }
                    chunk_results: list[
                        tuple[Optional[tuple[str, int, int]], tuple[object, ...]]
                    ] = [(None, ()) for _ in chunk]

                    for future in as_completed(future_to_index):
                        idx = future_to_index[future]
                        try:
                            chunk_results[idx] = future.result()
                        except Exception as exc:
                            chunk_results[idx] = (
                                None,
                                (
                                    make_processing_failure(
                                        stage="scan",
                                        path=chunk[idx],
                                        reason=failure_reason_from_exception(exc),
                                    ),
                                ),
                            )

                    for result, chunk_failures in chunk_results:
                        processed += 1
                        failures.extend(chunk_failures)
                        if result is None:
                            skipped += 1
                            continue
                        path_str, min_non_zero, max_pixel = result
                        resolved_path = str(Path(path_str).resolve())
                        computed_metrics[resolved_path] = (
                            min_non_zero,
                            max_pixel,
                        )
                        identity = identities_by_path.get(resolved_path)
                        if identity is not None:
                            cache_writes.append(
                                MetricCacheWrite(
                                    identity=identity,
                                    payload={
                                        "min_non_zero": int(min_non_zero),
                                        "max_pixel": int(max_pixel),
                                    },
                                ),
                            )

                    if update_status:
                        self.statusBar().showMessage(
                            f"Scanning images... {processed}/{len(files)}"
                        )

        if cache is not None and cache_writes:
            cache.store_entries(
                cache_writes,
                metric_kind=STATIC_METRIC_KIND,
                signature_hash=static_signature,
            )

        paths: list[str] = []
        mins: list[int] = []
        maxs: list[int] = []
        for path in files:
            resolved_path = str(path.resolve())
            metrics = cached_metrics.get(resolved_path)
            if metrics is None:
                metrics = computed_metrics.get(resolved_path)
            if metrics is None:
                continue
            paths.append(resolved_path)
            mins.append(int(metrics[0]))
            maxs.append(int(metrics[1]))

        return (paths, mins, maxs, skipped, failures)

    def _has_loaded_data(self) -> bool:
        """Return whether a dataset is currently loaded."""
        return self.dataset_state.has_loaded_data()

    def _metrics_cache_context(
        self,
        *,
        dataset_root: Path | None = None,
    ) -> dict[str, Path | None]:
        """Return cache-key roots used to build portable file identities."""

        active_dataset_root = dataset_root
        if active_dataset_root is None:
            controller = getattr(self, "dataset_state", None)
            active_dataset_root = getattr(controller, "dataset_root", None)
        workflow_controller = getattr(self, "workflow_state_controller", None)
        workflow_root = getattr(workflow_controller, "workspace_root", None)
        return {
            "dataset_root": active_dataset_root,
            "workspace_root": workflow_root,
        }

    def _metric_cache_identities(
        self,
        paths: list[Path | str],
        *,
        dataset_root: Path | None = None,
    ) -> dict[str, FileMetricIdentity]:
        """Build file identities for cache lookup/store where files still exist."""

        context = self._metrics_cache_context(dataset_root=dataset_root)
        identities: dict[str, FileMetricIdentity] = {}
        for item in paths:
            candidate = Path(item).expanduser()
            if not candidate.exists():
                continue
            try:
                identity = build_image_metric_identity(
                    candidate,
                    dataset_root=context["dataset_root"],
                    workspace_root=context["workspace_root"],
                    raw_resolver_context=self._raw_decode_resolver_context(),
                )
            except Exception:
                continue
            identities[str(candidate.resolve())] = identity
        return identities

    def _invalidate_background_cache(self) -> None:
        """Invalidate corrected-image cache after background changes."""
        self.metrics_state.background_signature += 1
        self._corrected_cache.clear()

    def _background_library_snapshot(self) -> BackgroundLibrary:
        """Return a shared read-only view used by worker threads."""
        return self.metrics_state.background_library.shared_snapshot()

    def _clear_image_cache(self) -> None:
        """Clear cached raw and corrected images."""
        self._image_cache.clear()
        self._corrected_cache.clear()

    def _cache_image(self, path: str, image: np.ndarray) -> None:
        """Store one raw image under the configured byte budget."""
        self._image_cache.put(self._image_cache_key_for_path(path), image)

    def _cache_corrected_image(
        self,
        path: str,
        image: np.ndarray,
    ) -> None:
        """Cache a background-corrected image for the active signature."""
        key = self._corrected_image_cache_key_for_path(path)
        self._corrected_cache.put(key, image)

    def _get_image_by_index(self, index: int) -> Optional[np.ndarray]:
        """Return raw image data for a table row, using cache when possible."""
        dataset = self.dataset_state
        if not (0 <= index < dataset.path_count()):
            return None
        path = dataset.paths[index]
        try:
            cache_key = self._image_cache_key_for_path(path)
        except Exception as exc:
            if hasattr(self, "_record_processing_failures"):
                self._record_processing_failures(
                    [
                        make_processing_failure(
                            stage="preview",
                            path=path,
                            reason=failure_reason_from_exception(exc),
                        ),
                    ],
                    replace_stage="preview",
                )
            return None
        cached = self._image_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            img = self._read_2d_image(Path(path))
        except Exception as exc:
            if hasattr(self, "_record_processing_failures"):
                self._record_processing_failures(
                    [
                        make_processing_failure(
                            stage="preview",
                            path=path,
                            reason=failure_reason_from_exception(exc),
                        ),
                    ],
                    replace_stage="preview",
                )
            return None

        self._image_cache.put(cache_key, img)
        return img

    def _get_reference_for_path(self, path: str) -> Optional[np.ndarray]:
        """Return the background reference selected for a given image path."""
        metrics = self.metrics_state
        if not metrics.background_config.enabled:
            return None
        if not metrics.background_library.has_any_reference():
            return None
        metadata = self.dataset_state.metadata_for_path(path)
        exposure_ms = metadata.get("exposure_ms")
        return select_reference(
            exposure_ms,
            metrics.background_library,
            metrics.background_config.exposure_policy,
        )

    def _background_reference_label_for_path(self, path: str) -> str:
        """Return a human-readable background reference label."""
        metrics = self.metrics_state
        if metrics.background_library.global_ref is not None:
            return "global"
        metadata = self.dataset_state.metadata_for_path(path)
        key = canonical_exposure_key(metadata.get("exposure_ms"))
        if key is None:
            return "missing exposure"
        return metrics.background_library.label_by_exposure_ms.get(
            key,
            f"{key:g} ms",
        )

    def _validated_reference_for_image(
        self,
        image: np.ndarray,
        path: str,
    ) -> Optional[np.ndarray]:
        """Return a shape-compatible background reference for one image."""

        reference = self._get_reference_for_path(path)
        if reference is None:
            return None
        if not validate_reference_shape(image.shape, reference.shape):
            return None
        return reference

    def _get_metric_image_by_index(
        self,
        index: int,
    ) -> tuple[Optional[np.ndarray], bool]:
        """Return image used for metrics/preview and BG-applied state."""
        image = self._get_image_by_index(index)
        if image is None:
            return (None, False)
        metrics = self.metrics_state
        if not metrics.background_config.enabled:
            return (image, False)
        if not metrics.background_library.has_any_reference():
            return (image, False)

        path = self.dataset_state.paths[index]
        cache_key = self._corrected_image_cache_key_for_path(path)
        cached = self._corrected_cache.get(cache_key)
        if cached is not None:
            return (cached, True)

        reference = self._validated_reference_for_image(image, path)
        if reference is None:
            return (image, False)

        corrected = native_backend.apply_background_f32(
            image,
            background=reference,
            clip_negative=metrics.background_config.clip_negative,
        )
        corrected = np.asarray(corrected, dtype=np.float32, order="C")
        self._corrected_cache.put(cache_key, corrected)
        return (corrected, True)

    def _reset_roi_metrics(self) -> None:
        """Reset ROI-derived metric arrays to empty NaN-filled buffers."""
        self.metrics_state.reset_roi_metrics(self.dataset_state.path_count())

    def _is_dataset_load_running(self) -> bool:
        """Return whether one dataset load worker is currently active."""

        thread = getattr(self, "_dataset_load_thread", None)
        return bool(
            thread is not None
            and (
                self._qthread_is_running(thread)
                or bool(getattr(self, "_dataset_load_start_pending", False))
            )
        )

    def _dispose_dataset_load_thread_objects(
        self,
        thread: QThread,
        worker: DatasetLoadWorker | None,
    ) -> None:
        """Dispose one dataset-load thread/worker pair without blocking."""

        if getattr(self, "_dataset_load_worker", None) is worker:
            self._dataset_load_worker = None
        if getattr(self, "_dataset_load_thread", None) is thread:
            self._dataset_load_thread = None
            self._dataset_load_start_pending = False
        if worker is not None:
            try:
                thread.started.disconnect(worker.run)
            except Exception:
                pass
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    worker.batch_ready.disconnect(self._on_dataset_load_batch)
            except Exception:
                pass
            try:
                worker.deleteLater()
            except RuntimeError:
                pass
        try:
            thread.deleteLater()
        except RuntimeError:
            pass

    def _cancel_dataset_load_job(self) -> None:
        """Cancel any in-flight dataset load worker and drop queued callbacks."""

        thread = getattr(self, "_dataset_load_thread", None)
        if thread is None:
            return
        worker = getattr(self, "_dataset_load_worker", None)
        job_id = getattr(self, "_dataset_load_job_id", 0)
        callbacks = getattr(self, "_dataset_load_callbacks", None)
        if isinstance(callbacks, dict):
            callbacks.pop(job_id, None)
        auto_metrics = getattr(self, "_dataset_load_auto_metrics", None)
        if isinstance(auto_metrics, dict):
            auto_metrics.pop(job_id, None)
        notices = getattr(self, "_dataset_load_workflow_notices", None)
        if isinstance(notices, dict):
            notices.pop(job_id, None)
        thread_running = self._qthread_is_running(thread)
        if worker is not None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    worker.batch_ready.disconnect(self._on_dataset_load_batch)
            except Exception:
                pass
            try:
                thread.requestInterruption()
            except Exception:
                pass
        if not thread_running:
            self._dispose_dataset_load_thread_objects(thread, worker)
        self._update_dataset_load_ui(
            active=False,
            processed=0,
            total=0,
            message="",
        )

    def _on_dataset_load_thread_finished(
        self,
        thread: QThread,
        worker: DatasetLoadWorker,
    ) -> None:
        """Clean up dataset loader worker objects after thread shutdown."""

        if getattr(self, "_dataset_load_worker", None) is worker:
            self._dataset_load_worker = None
        if getattr(self, "_dataset_load_thread", None) is thread:
            self._dataset_load_thread = None
            self._dataset_load_start_pending = False
        try:
            thread.deleteLater()
        except RuntimeError:
            pass

    def _start_dataset_load_thread_if_current(
        self,
        *,
        thread: QThread,
        worker: DatasetLoadWorker,
        job_id: int,
    ) -> None:
        """Start one prepared dataset-load thread when it is still current."""

        if (
            int(job_id) != int(getattr(self, "_dataset_load_job_id", -1))
            or getattr(self, "_dataset_load_thread", None) is not thread
        ):
            return
        self._dataset_load_start_pending = False
        try:
            thread.start()
        except RuntimeError:
            self._dispose_dataset_load_thread_objects(thread, worker)

    def _register_dataset_load_callback(
        self,
        job_id: int,
        callback,
    ) -> None:
        """Register one callback to run when a specific load job completes."""

        callbacks = getattr(self, "_dataset_load_callbacks", None)
        if not isinstance(callbacks, dict):
            return
        callbacks.setdefault(int(job_id), []).append(callback)

    def _run_dataset_load_callbacks(
        self,
        summary: DatasetLoadSummary,
    ) -> None:
        """Run and clear callbacks queued for one completed load job."""

        callbacks = getattr(self, "_dataset_load_callbacks", None)
        if not isinstance(callbacks, dict):
            return
        for callback in callbacks.pop(int(summary.job_id), []):
            try:
                callback(summary)
            except Exception:
                continue

    def _cancel_pending_dataset_load_refresh(self) -> None:
        """Stop any coalesced table refresh queued for streamed load batches."""

        timer = getattr(self, "_dataset_load_refresh_timer", None)
        if timer is not None:
            timer.stop()

    def _schedule_dataset_load_table_refresh(self) -> None:
        """Coalesce streamed dataset rows into bounded-rate table refreshes."""

        timer = getattr(self, "_dataset_load_refresh_timer", None)
        if timer is None:
            self._flush_dataset_load_table_refresh()
            return
        if not timer.isActive():
            timer.start()

    def _flush_dataset_load_table_refresh(self) -> None:
        """Apply one coalesced table refresh for streamed dataset batches."""

        self._cancel_pending_dataset_load_refresh()
        if not self._has_loaded_data():
            return
        self._dataset_load_batch_applying = True
        try:
            self._refresh_table(update_analysis=False)
        finally:
            self._dataset_load_batch_applying = False

    def _update_dataset_load_ui(
        self,
        *,
        active: bool,
        processed: int,
        total: int,
        message: str,
    ) -> None:
        """Refresh dataset-load progress widgets shared across Data and Measure."""

        progress_value = min(max(int(processed), 0), max(int(total), 0))
        progress_total = max(int(total), 0)
        status_text = str(message or "")
        if hasattr(self, "data_load_progress"):
            if progress_total > 0:
                self.data_load_progress.setRange(0, progress_total)
                self.data_load_progress.setValue(progress_value)
                self.data_load_progress.setFormat(f"Load %v/{progress_total}")
            else:
                self.data_load_progress.setRange(0, 0)
                self.data_load_progress.setFormat("Loading...")
            self.data_load_progress.setVisible(bool(active))
        if hasattr(self, "measure_load_progress"):
            if progress_total > 0:
                self.measure_load_progress.setRange(0, progress_total)
                self.measure_load_progress.setValue(progress_value)
                self.measure_load_progress.setFormat(f"Load %v/{progress_total}")
            else:
                self.measure_load_progress.setRange(0, 0)
                self.measure_load_progress.setFormat("Loading...")
            self.measure_load_progress.setVisible(bool(active))
        if hasattr(self, "cancel_dataset_load_button"):
            self.cancel_dataset_load_button.setVisible(bool(active))
            self.cancel_dataset_load_button.setEnabled(bool(active))
        if hasattr(self, "cancel_dataset_load_button_measure"):
            self.cancel_dataset_load_button_measure.setVisible(bool(active))
            self.cancel_dataset_load_button_measure.setEnabled(bool(active))
        if hasattr(self, "histogram_widget"):
            self.histogram_widget.set_exact_refresh_suppressed(bool(active))
        if hasattr(self, "_refresh_data_header_state"):
            self._refresh_data_header_state()
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()
        if hasattr(self, "_update_average_controls"):
            self._update_average_controls()
        if status_text:
            self._set_status(status_text)
        elif hasattr(self, "_set_status"):
            self._set_status()

    def _start_dataset_load_job(
        self,
        folder: Path,
        *,
        workflow_notice: str | None = None,
        after_load=None,
        suppress_auto_metrics: bool = True,
    ) -> int:
        """Start one asynchronous dataset load job and return its job id."""

        previous_thread = getattr(self, "_dataset_load_thread", None)
        self.unload_folder(clear_folder_edit=False)
        self.dataset_state.begin_loaded_dataset(folder)
        self.metrics_state.initialize_loaded_dataset(0)
        self._clear_image_cache()
        if hasattr(self, "image_preview"):
            self.image_preview.set_roi_rect(None)
            self.image_preview.reset_view()
        if hasattr(self, "_clear_processing_failures"):
            self._clear_processing_failures()
        if hasattr(self, "_refresh_metadata_table"):
            self._refresh_metadata_table()
        self._last_scan_pruned_dirs = 0
        self._last_scan_skipped_files = 0
        self.base_status = f"Loading {folder.name or str(folder)}"
        self._update_metadata_source_options(False)

        self._dataset_load_job_id = int(getattr(self, "_dataset_load_job_id", 0)) + 1
        job_id = self._dataset_load_job_id
        self._dataset_load_auto_metrics[job_id] = not bool(suppress_auto_metrics)
        self._dataset_load_workflow_notices[job_id] = (
            str(workflow_notice) if workflow_notice else ""
        )
        if after_load is not None:
            self._register_dataset_load_callback(job_id, after_load)

        metadata_boundary_root = (
            self.dataset_state.scope_snapshot.root
            if self.dataset_state.scope_snapshot.source == "workflow"
            else None
        )
        worker = DatasetLoadWorker(
            job_id=job_id,
            folder=str(folder),
            skip_patterns=tuple(self.skip_patterns),
            scan_worker_count_override=(
                getattr(self.ui_preferences, "scan_worker_count_override", None)
                if hasattr(self, "ui_preferences")
                else None
            ),
            metadata_source=self.dataset_state.metadata_source_mode,
            metadata_boundary_root=(
                str(metadata_boundary_root)
                if metadata_boundary_root is not None
                else None
            ),
            scope_effective_metadata=dict(self.dataset_state.scope_effective_metadata),
            raw_manual_overrides=self._manual_raw_decode_overrides(),
            cache_path=str(self.metrics_cache.path),
            workspace_root=(
                str(self.workflow_state_controller.workspace_root)
                if getattr(self.workflow_state_controller, "workspace_root", None)
                is not None
                else None
            ),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # Consume streamed batches synchronously on the GUI thread so the
        # worker cannot reach `finished` and tear down before later batches
        # have been appended into the live dataset/table state.
        worker.batch_ready.connect(
            self._on_dataset_load_batch,
            Qt.BlockingQueuedConnection,
        )
        worker.progress.connect(self._on_dataset_load_progress)
        worker.finished.connect(self._on_dataset_load_finished)
        worker.failed.connect(self._on_dataset_load_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda t=thread, w=worker: self._on_dataset_load_thread_finished(t, w),
        )

        self._dataset_load_thread = thread
        self._dataset_load_worker = worker
        self._dataset_load_start_pending = False
        start_message = "Discovering image files..."
        if self._qthread_is_running(previous_thread):
            self._dataset_load_start_pending = True
            start_message = "Waiting for previous load to stop..."

            def _start_when_previous_finishes(
                target_thread: QThread = thread,
                target_worker: DatasetLoadWorker = worker,
                target_job_id: int = job_id,
            ) -> None:
                self._start_dataset_load_thread_if_current(
                    thread=target_thread,
                    worker=target_worker,
                    job_id=target_job_id,
                )

            previous_thread.finished.connect(_start_when_previous_finishes)
        else:
            self._start_dataset_load_thread_if_current(
                thread=thread,
                worker=worker,
                job_id=job_id,
            )
        self._update_dataset_load_ui(
            active=True,
            processed=0,
            total=0,
            message=start_message,
        )
        return job_id

    def _on_dataset_load_batch(self, batch: object) -> None:
        """Append one ordered dataset-load batch into live controllers and table."""

        if not isinstance(batch, DatasetLoadBatch):
            return
        if int(batch.job_id) != int(getattr(self, "_dataset_load_job_id", -1)):
            return

        self.dataset_state.append_loaded_paths(batch.paths)
        self.dataset_state.update_path_metadata(batch.metadata_by_path)
        self.metrics_state.reserve_loaded_dataset(max(0, int(batch.total)))
        self.metrics_state.append_loaded_batch(
            batch.min_non_zero,
            batch.max_pixels,
        )
        if hasattr(self, "_record_processing_failures") and batch.failures:
            self._record_processing_failures(
                list(batch.failures),
                replace_stage=None,
            )
        self._schedule_dataset_load_table_refresh()
        self._update_dataset_load_ui(
            active=True,
            processed=batch.processed,
            total=batch.total,
            message=f"Loading images... {batch.processed}/{batch.total}",
        )

    def _on_dataset_load_progress(self, progress: object) -> None:
        """Update progress UI for one active dataset load job."""

        if not isinstance(progress, DatasetLoadProgress):
            return
        if int(progress.job_id) != int(getattr(self, "_dataset_load_job_id", -1)):
            return
        self._update_dataset_load_ui(
            active=True,
            processed=progress.processed,
            total=progress.total,
            message=progress.message,
        )

    @staticmethod
    def _dataset_load_failure_hint(reason: str) -> str | None:
        """Return a next-step hint for one common dataset load failure reason."""

        normalized = " ".join(str(reason or "").split()).lower()
        if "missing raw decode spec fields" in normalized:
            return (
                "Add acquisition/session/campaign metadata, attach an eBUS "
                "config in the acquisition, or provide session-local RAW "
                "fallback values, then re-scan."
            )
        if "unsupported raw pixel format" in normalized:
            return (
                "Use a supported RAW pixel format in metadata, an eBUS "
                "config, the filename token, or session-local RAW fallback "
                "values, then re-scan."
            )
        if "width must be greater than 0" in normalized or "height must be greater than 0" in normalized:
            return (
                "Add acquisition/session/campaign metadata, an eBUS config, "
                "a filename token like w2848_h2848_pMono12Packed, or "
                "session-local RAW fallback values, then re-scan."
            )
        if "expected 2d image" in normalized:
            return (
                "Verify the selected files contain single-frame 2D image data, "
                "then re-scan."
            )
        return None

    def _dataset_load_failure_message(
        self,
        *,
        total_candidates: int,
        failures: tuple[ProcessingFailure, ...],
    ) -> str:
        """Build a troubleshooting-focused dataset load error message."""

        total = max(int(total_candidates), len(failures))
        noun = "file" if total == 1 else "files"
        lines = [f"All {total} supported image {noun} failed to load."]
        if not failures:
            lines.append("Open Processing Issues for per-file details.")
            return "\n".join(lines)

        reason_counts = Counter(
            failure.reason
            for failure in failures
            if str(failure.reason).strip()
        )
        if not reason_counts:
            lines.append("Open Processing Issues for per-file details.")
            return "\n".join(lines)

        ordered = sorted(
            reason_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
        if len(ordered) == 1:
            reason, _count = ordered[0]
            lines.append(f"Most likely cause: {reason}")
            hint = self._dataset_load_failure_hint(reason)
            if hint:
                lines.append(hint)
        else:
            summary_parts: list[str] = []
            for reason, count in ordered[:2]:
                label = f"{reason} ({count})" if count > 1 else reason
                summary_parts.append(label)
            if len(ordered) > 2:
                summary_parts.append(f"+{len(ordered) - 2} more")
            lines.append("Observed failure types: " + "; ".join(summary_parts))

        lines.append("Open Processing Issues for per-file details.")
        return "\n".join(lines)

    def _on_dataset_load_finished(self, summary: object) -> None:
        """Finalize dataset state after the async loader completes or cancels."""

        if not isinstance(summary, DatasetLoadSummary):
            return
        if int(summary.job_id) != int(getattr(self, "_dataset_load_job_id", -1)):
            return

        self._cancel_pending_dataset_load_refresh()
        folder = Path(summary.dataset_root).expanduser()
        self._last_scan_pruned_dirs = int(summary.pruned_dirs)
        self._last_scan_skipped_files = int(summary.skipped_files)
        self._update_dataset_load_ui(
            active=False,
            processed=summary.loaded_count,
            total=summary.total_candidates,
            message="",
        )
        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures(
                list(getattr(summary, "failures", ()) or ()),
                replace_stage="scan",
            )

        if summary.no_files:
            self.dataset_state.clear_loaded_dataset()
            self.metrics_state.clear_dataset_state()
            self._refresh_table(update_analysis=False)
            self._update_metadata_source_options(False)
            suffix_text = "/".join(supported_suffixes())
            msg = f"No supported image files ({suffix_text}) found."
            if self.skip_patterns:
                msg = (
                    f"No supported image files ({suffix_text}) found after applying "
                    "skip patterns."
                )
                details: list[str] = []
                if self._last_scan_pruned_dirs > 0:
                    details.append(f"{self._last_scan_pruned_dirs} folders pruned")
                if self._last_scan_skipped_files > 0:
                    details.append(f"{self._last_scan_skipped_files} files skipped")
                if details:
                    msg += f"\n({', '.join(details)})"
            self.base_status = "Select a folder."
            self._show_info("No image files", msg)
            self._run_dataset_load_callbacks(summary)
            self.datasetLoadCompleted.emit(summary)
            return

        self._apply_dataset_load_summary_payload(folder, summary)

        if summary.loaded_count <= 0 or not self.dataset_state.has_loaded_data():
            self.dataset_state.clear_loaded_dataset()
            self.metrics_state.clear_dataset_state()
            self._refresh_table(update_analysis=False)
            self._update_metadata_source_options(False)
            self.base_status = "Load failed"
            self._clear_image_cache()
            self._show_error(
                "Load failed",
                self._dataset_load_failure_message(
                    total_candidates=int(summary.total_candidates),
                    failures=tuple(getattr(summary, "failures", ()) or ()),
                ),
            )
            self._run_dataset_load_callbacks(summary)
            self.datasetLoadCompleted.emit(summary)
            return

        if getattr(self.dataset_state.scope_snapshot, "source", "manual") == "workflow":
            if hasattr(self, "_sync_dataset_scope_to_workflow"):
                self._sync_dataset_scope_to_workflow(
                    update_folder_edit=False,
                    unload_mismatched_dataset=False,
                )
        elif hasattr(self, "_set_manual_dataset_scope"):
            self._set_manual_dataset_scope(folder)

        if hasattr(self, "_refresh_ebus_config_status"):
            self._refresh_ebus_config_status(folder)
        has_json_metadata = (
            self._dataset_has_json_metadata(self.dataset_state.paths)
            or self._folder_has_json_metadata(folder)
        )
        self._update_metadata_source_options(has_json_metadata)
        self._refresh_metadata_table()

        skipped_parts: list[str] = []
        if summary.pruned_dirs > 0:
            skipped_parts.append(f"{summary.pruned_dirs} folders pruned")
        if summary.skipped_files > 0:
            skipped_parts.append(f"{summary.skipped_files} files pattern-skipped")
        if summary.skipped_unreadable > 0:
            skipped_parts.append(f"{summary.skipped_unreadable} unreadable skipped")
        if summary.was_cancelled:
            skipped_parts.append("load cancelled")
        self.base_status = f"Loaded {self.dataset_state.path_count()} images"
        if skipped_parts:
            self.base_status += f" ({', '.join(skipped_parts)})"

        auto_metrics = bool(
            self._dataset_load_auto_metrics.pop(int(summary.job_id), False),
        )
        workflow_notice = self._dataset_load_workflow_notices.pop(
            int(summary.job_id),
            "",
        )
        if auto_metrics:
            self._refresh_table(update_analysis=False)
            self._apply_live_update()
        else:
            self._refresh_table(update_analysis=False)
            if hasattr(self, "_invalidate_analysis_context"):
                self._invalidate_analysis_context(refresh_visible_plugin=True)
            self._update_background_status_label()
            self._apply_dynamic_visibility_policy()
            self._update_average_controls()
            self._refresh_workspace_document_dirty_state()
            self._set_status()

        self._run_dataset_load_callbacks(summary)
        if workflow_notice:
            self.statusBar().showMessage(str(workflow_notice), 5000)
        self.datasetLoadCompleted.emit(summary)

    def _on_dataset_load_failed(self, job_id: int, message: str) -> None:
        """Handle fatal loader failures from the dataset worker."""

        if int(job_id) != int(getattr(self, "_dataset_load_job_id", -1)):
            return
        self._cancel_pending_dataset_load_refresh()
        summary = DatasetLoadSummary(
            job_id=int(job_id),
            dataset_root=str(
                getattr(self.dataset_state, "dataset_root", None) or ""
            ),
            loaded_count=self.dataset_state.path_count(),
            total_candidates=self.dataset_state.path_count(),
            failed=True,
            failure_message=str(message or "Unknown error"),
        )
        self._dataset_load_auto_metrics.pop(int(job_id), None)
        self._dataset_load_workflow_notices.pop(int(job_id), None)
        self._update_dataset_load_ui(
            active=False,
            processed=0,
            total=0,
            message="",
        )
        self.base_status = "Load failed"
        self._run_dataset_load_callbacks(summary)
        self.datasetLoadCompleted.emit(summary)
        self._show_error("Dataset load failed", message or "Unknown error")

    def load_folder(
        self,
        *,
        after_load=None,
        suppress_auto_metrics: bool = True,
    ) -> None:
        """Start asynchronous dataset loading for the selected folder."""
        folder = Path(self.folder_edit.text().strip()).expanduser()
        workflow_notice = None
        if hasattr(self, "_resolve_requested_dataset_scope_folder"):
            folder = self._resolve_requested_dataset_scope_folder(folder)
            workflow_notice = getattr(
                self,
                "_workflow_scope_transition_message",
                None,
            )
            self._workflow_scope_transition_message = None
        if not folder.is_dir():
            self._show_error("Invalid folder", "Choose a valid directory.")
            return
        if hasattr(self, "_set_folder_edit_text"):
            self._set_folder_edit_text(str(folder))
        elif hasattr(self, "folder_edit"):
            self.folder_edit.setText(str(folder))

        if hasattr(self, "metadata_filter_edit"):
            filter_text = self.metadata_filter_edit.text().strip()
            if filter_text:
                blocker = QSignalBlocker(self.metadata_filter_edit)
                self.metadata_filter_edit.clear()
                del blocker
        self._start_dataset_load_job(
            folder,
            workflow_notice=workflow_notice,
            after_load=after_load,
            suppress_auto_metrics=suppress_auto_metrics,
        )

    def _compute_static_stats(
        self,
        precomputed: Optional[tuple[np.ndarray, np.ndarray]] = None,
    ) -> None:
        """Populate static image metrics, optionally from precomputed arrays."""
        if precomputed is not None:
            self.metrics_state.min_non_zero, self.metrics_state.maxs = precomputed
            return

        if not self._has_loaded_data():
            self.metrics_state.min_non_zero = None
            self.metrics_state.maxs = None
            return

        dataset = self.dataset_state
        file_paths = [Path(path) for path in dataset.paths]
        path_list, mins, maxs, _skipped, _failures = self._scan_tiffs_chunked_parallel(
            file_paths,
            update_status=False,
            dataset_root=dataset.dataset_root,
        )
        if not path_list:
            self.metrics_state.min_non_zero = np.zeros(
                dataset.path_count(),
                dtype=np.int64,
            )
            self.metrics_state.maxs = np.zeros(dataset.path_count(), dtype=np.int64)
            return

        metric_by_path = {
            path: (mn, mx)
            for path, mn, mx in zip(path_list, mins, maxs)
        }
        ordered_mins: list[int] = []
        ordered_maxs: list[int] = []
        for path in dataset.paths:
            mn_mx = metric_by_path.get(path)
            if mn_mx is None:
                ordered_mins.append(0)
                ordered_maxs.append(0)
                continue
            ordered_mins.append(mn_mx[0])
            ordered_maxs.append(mn_mx[1])

        self.metrics_state.min_non_zero = np.asarray(ordered_mins, dtype=np.int64)
        self.metrics_state.maxs = np.asarray(ordered_maxs, dtype=np.int64)
