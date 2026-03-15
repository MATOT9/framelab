"""Dataset discovery, caching, and background-aware image loading."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import QSignalBlocker

from ..background import (
    BackgroundLibrary,
    apply_background,
    canonical_exposure_key,
    select_reference,
    validate_reference_shape,
)
from ..image_io import is_supported_image, read_2d_image, supported_suffixes
from ..metadata import clear_metadata_cache
from ..processing_failures import (
    failure_reason_from_exception,
    make_processing_failure,
)


class DatasetLoadingMixin:
    """Dataset lifecycle helpers for TIFF discovery and image access."""

    def unload_folder(self, *, clear_folder_edit: bool = False) -> None:
        """Clear the currently loaded dataset and reset dependent UI state."""
        dataset = self.dataset_state
        metrics = self.metrics_state
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
        self._set_status()

    def browse_folder(self) -> None:
        """Open a directory picker and trigger dataset loading."""
        initial_dir = self.folder_edit.text().strip() or str(Path.home())
        dialog = qtw.QFileDialog(self, "Select TIFF folder", initial_dir)
        dialog.setFileMode(qtw.QFileDialog.Directory)
        dialog.setOption(qtw.QFileDialog.ShowDirsOnly, True)
        dialog.setOption(qtw.QFileDialog.DontUseNativeDialog, True)
        if dialog.exec():
            selected_files = dialog.selectedFiles()
            if not selected_files:
                return
            self.folder_edit.setText(selected_files[0])
            self.load_folder()

    def _find_tiffs(
        self,
        folder: Path,
        *,
        apply_skip_patterns: bool = True,
    ) -> list[Path]:
        """Recursively find TIFF files while pruning skipped paths."""
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
        return read_2d_image(path)

    def _scan_worker_count(self) -> int:
        """Return worker count used for TIFF scanning."""
        cpu = os.cpu_count() or 4
        return max(2, min(12, cpu * 2))

    @staticmethod
    def _chunk_size_for_scan(total_files: int) -> int:
        """Return scan chunk size based on dataset size."""
        if total_files <= 64:
            return 16
        if total_files <= 256:
            return 32
        return 64

    def _scan_single_tiff(
        self,
        path: Path,
    ) -> tuple[Optional[tuple[str, np.ndarray, int, int]], tuple[object, ...]]:
        """Read a single TIFF and derive quick static metrics."""
        try:
            img = self._read_2d_image(path)
        except Exception as exc:
            return (
                None,
                (
                    make_processing_failure(
                        stage="scan",
                        path=path,
                        reason=failure_reason_from_exception(exc),
                    ),
                ),
            )

        non_zero = img[img != 0]
        min_non_zero = int(non_zero.min()) if non_zero.size > 0 else 0
        max_pixel = int(img.max())
        return ((str(path), img, min_non_zero, max_pixel), ())

    def _scan_tiffs_chunked_parallel(
        self,
        files: list[Path],
        *,
        update_status: bool = False,
    ) -> tuple[list[str], list[int], list[int], int, list[object]]:
        """Scan TIFF files in chunks and preserve source order."""
        if not files:
            return ([], [], [], 0, [])

        chunk_size = self._chunk_size_for_scan(len(files))
        max_workers = self._scan_worker_count()
        paths: list[str] = []
        mins: list[int] = []
        maxs: list[int] = []
        skipped = 0
        processed = 0
        failures: list[object] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for start in range(0, len(files), chunk_size):
                chunk = files[start:start + chunk_size]
                future_to_index = {
                    executor.submit(self._scan_single_tiff, path): i
                    for i, path in enumerate(chunk)
                }
                chunk_results: list[
                    tuple[Optional[tuple[str, np.ndarray, int, int]], tuple[object, ...]]
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
                    path_str, img, min_non_zero, max_pixel = result
                    paths.append(path_str)
                    mins.append(min_non_zero)
                    maxs.append(max_pixel)
                    self._cache_image(path_str, img)

                if update_status:
                    self.statusBar().showMessage(
                        f"Scanning TIFFs... {processed}/{len(files)}"
                    )

        return (paths, mins, maxs, skipped, failures)

    def _has_loaded_data(self) -> bool:
        """Return whether a dataset is currently loaded."""
        return self.dataset_state.has_loaded_data()

    def _invalidate_background_cache(self) -> None:
        """Invalidate corrected-image cache after background changes."""
        self.metrics_state.background_signature += 1
        self._corrected_cache.clear()

    def _background_library_snapshot(self) -> BackgroundLibrary:
        """Return a copy used by worker threads for stable reads."""
        return self.metrics_state.background_library.copy()

    def _clear_image_cache(self) -> None:
        """Clear cached raw and corrected images."""
        self._image_cache.clear()
        self._corrected_cache.clear()

    def _cache_image(self, path: str, image: np.ndarray) -> None:
        """Store a raw image in the LRU cache."""
        self._image_cache[path] = image
        self._image_cache.move_to_end(path)
        while len(self._image_cache) > self._image_cache_capacity:
            self._image_cache.popitem(last=False)

    def _cache_corrected_image(
        self,
        path: str,
        image: np.ndarray,
    ) -> None:
        """Cache a background-corrected image for the active signature."""
        key = (path, self.metrics_state.background_signature)
        self._corrected_cache[key] = image
        self._corrected_cache.move_to_end(key)
        while len(self._corrected_cache) > self._corrected_cache_capacity:
            self._corrected_cache.popitem(last=False)

    def _get_image_by_index(self, index: int) -> Optional[np.ndarray]:
        """Return raw image data for a table row, using cache when possible."""
        dataset = self.dataset_state
        if not (0 <= index < dataset.path_count()):
            return None
        path = dataset.paths[index]
        cached = self._image_cache.get(path)
        if cached is not None:
            self._image_cache.move_to_end(path)
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

        self._cache_image(path, img)
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
        cache_key = (path, metrics.background_signature)
        cached = self._corrected_cache.get(cache_key)
        if cached is not None:
            self._corrected_cache.move_to_end(cache_key)
            return (cached, True)

        reference = self._get_reference_for_path(path)
        if reference is None:
            return (image, False)
        if not validate_reference_shape(image.shape, reference.shape):
            return (image, False)

        corrected = apply_background(
            image,
            reference,
            clip_negative=metrics.background_config.clip_negative,
        )
        self._cache_corrected_image(path, corrected)
        return (corrected, True)

    def _reset_roi_metrics(self) -> None:
        """Reset ROI-derived metric arrays to empty NaN-filled buffers."""
        self.metrics_state.reset_roi_metrics(self.dataset_state.path_count())

    def load_folder(self) -> None:
        """Load the dataset, compute static metrics, and refresh UI state."""
        metrics = self.metrics_state
        folder = Path(self.folder_edit.text().strip()).expanduser()
        if hasattr(self, "_resolve_requested_dataset_scope_folder"):
            folder = self._resolve_requested_dataset_scope_folder(folder)
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

        files = self._find_tiffs(folder)
        if not files:
            suffix_text = "/".join(supported_suffixes())
            msg = f"No {suffix_text} files found."
            if self.skip_patterns:
                msg = f"No {suffix_text} files found after applying skip patterns."
                details: list[str] = []
                if self._last_scan_pruned_dirs > 0:
                    details.append(
                        f"{self._last_scan_pruned_dirs} folders pruned",
                    )
                if self._last_scan_skipped_files > 0:
                    details.append(
                        f"{self._last_scan_skipped_files} files skipped",
                    )
                if details:
                    msg += f"\n({', '.join(details)})"
            self._show_info("No TIFF files", msg)
            return

        self._cancel_stats_job()
        self._cancel_roi_apply_job()
        self._clear_image_cache()
        if hasattr(self, "_clear_processing_failures"):
            self._clear_processing_failures()
        paths, mins, maxs, skipped, failures = self._scan_tiffs_chunked_parallel(
            files,
            update_status=True,
        )
        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures(failures, replace_stage="scan")

        if not paths:
            self._show_error("Load failed", "No readable 2D TIFF images.")
            self._clear_image_cache()
            return

        self.dataset_state.set_loaded_dataset(folder, paths)
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
            self._dataset_has_json_metadata(paths)
            or self._folder_has_json_metadata(folder)
        )
        self._update_metadata_source_options(has_json_metadata)
        self._refresh_metadata_cache()
        self._refresh_metadata_table()
        metrics.initialize_loaded_dataset(len(paths))
        self.image_preview.set_roi_rect(None)
        self.image_preview.reset_view()
        self._compute_static_stats(
            precomputed=(
                np.asarray(mins, dtype=np.int64),
                np.asarray(maxs, dtype=np.int64),
            )
        )
        self.base_status = f"Loaded {len(paths)} images"
        skipped_parts: list[str] = []
        if self._last_scan_pruned_dirs > 0:
            skipped_parts.append(
                f"{self._last_scan_pruned_dirs} folders pruned",
            )
        if self._last_scan_skipped_files > 0:
            skipped_parts.append(
                f"{self._last_scan_skipped_files} files pattern-skipped",
            )
        if skipped > 0:
            skipped_parts.append(f"{skipped} unreadable skipped")
        if skipped_parts:
            self.base_status += f" ({', '.join(skipped_parts)})"
        self.dataset_state.set_selected_index(0, path_count=self.dataset_state.path_count())
        self._apply_live_update()
        self._update_background_status_label()
        self._apply_dynamic_visibility_policy()

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
