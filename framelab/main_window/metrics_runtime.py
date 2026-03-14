"""Dynamic metric jobs, table refresh, preview, and ROI runtime helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread

from ..metrics_state import DynamicStatsResult, RoiApplyResult
from ..processing_failures import make_processing_failure
from ..workers import DynamicStatsWorker, RoiApplyWorker


class MetricsRuntimeMixin:
    """Live metric computation and preview refresh helpers."""

    def _start_threshold_summary_animation(self) -> None:
        """Start the light pulse used while threshold counts are recomputing."""
        self._threshold_summary_anim_phase = 0
        timer = getattr(self, "_threshold_summary_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()

    def _stop_threshold_summary_animation(self) -> None:
        """Stop threshold-summary animation and reset its phase."""
        timer = getattr(self, "_threshold_summary_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._threshold_summary_anim_phase = 0

    def _advance_threshold_summary_animation(self) -> None:
        """Advance the threshold-summary pulse while a threshold job is active."""
        metrics = self.metrics_state
        if (
            not metrics.is_stats_running
            or metrics.stats_update_kind != "threshold_only"
        ):
            self._stop_threshold_summary_animation()
            return
        self._threshold_summary_anim_phase = (
            self._threshold_summary_anim_phase + 1
        ) % 4
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()

    def _cancel_stats_job(self) -> None:
        """Stop any in-flight dynamic metrics worker."""
        metrics = self.metrics_state
        thread = self._stats_thread
        metrics.finish_stats_job()
        self._stop_threshold_summary_animation()
        if thread is None:
            return
        if thread.isRunning():
            thread.requestInterruption()
            thread.quit()

    def _on_stats_thread_finished(
        self,
        thread: QThread,
        worker: DynamicStatsWorker,
    ) -> None:
        """Clean up stats worker objects after thread shutdown."""
        if self._stats_worker is worker:
            self._stats_worker = None
        if self._stats_thread is thread:
            self._stats_thread = None
        worker.deleteLater()
        thread.deleteLater()

    def _start_dynamic_stats_job(
        self,
        *,
        update_kind: str = "full",
        refresh_analysis: bool = True,
    ) -> None:
        """Start asynchronous dynamic metric computation for the dataset."""
        if not self._has_loaded_data():
            return

        metrics = self.metrics_state
        self._cancel_stats_job()
        job_id = metrics.begin_stats_job(
            update_kind=update_kind,
            refresh_analysis=refresh_analysis,
        )
        mode = self._current_average_mode()
        dataset = self.dataset_state

        thread = QThread(self)
        worker = DynamicStatsWorker(
            job_id=job_id,
            paths=list(dataset.paths),
            threshold_value=metrics.threshold_value,
            mode=mode,
            avg_count_value=metrics.avg_count_value,
            update_kind=update_kind,
            background_config=self._background_config_snapshot(),
            background_library=self._background_library_snapshot(),
            path_metadata=dict(dataset.path_metadata),
            existing_avg_topk=metrics.avg_maxs,
            existing_avg_topk_std=metrics.avg_maxs_std,
            existing_avg_topk_sem=metrics.avg_maxs_sem,
            existing_max_pixels=metrics.maxs,
            existing_min_non_zero=metrics.min_non_zero,
            existing_bg_applied_mask=metrics.bg_applied_mask,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_dynamic_stats_finished)
        worker.failed.connect(self._on_dynamic_stats_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(
            lambda t=thread, w=worker: self._on_stats_thread_finished(t, w)
        )

        self._stats_thread = thread
        self._stats_worker = worker
        if metrics.stats_update_kind == "threshold_only":
            self._start_threshold_summary_animation()
        else:
            self._stop_threshold_summary_animation()
        thread.start()

    def _on_dynamic_stats_finished(self, result: object) -> None:
        """Apply completed dynamic stats results to the active dataset."""
        if not isinstance(result, DynamicStatsResult):
            return
        metrics = self.metrics_state
        if result.job_id != metrics.stats_job_id:
            return

        metrics.apply_dynamic_stats_result(
            result,
            path_count=self.dataset_state.path_count(),
        )
        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures(
                list(result.failures),
                replace_stage="metrics",
            )
        metrics.finish_stats_job()
        self._stop_threshold_summary_animation()
        self._refresh_table(
            update_analysis=metrics.stats_refresh_analysis,
        )
        self._update_background_status_label()
        self._update_average_controls()
        self._set_status()

    def _on_dynamic_stats_failed(self, job_id: int, message: str) -> None:
        """Handle dynamic stats worker failure."""
        metrics = self.metrics_state
        if job_id != metrics.stats_job_id:
            return
        metrics.finish_stats_job()
        self._stop_threshold_summary_animation()
        self._update_background_status_label()
        self._set_status("Metric computation failed")
        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures(
                [
                    make_processing_failure(
                        stage="metrics",
                        path="",
                        reason=message or "Unknown error",
                    ),
                ],
                replace_stage="metrics",
            )
        self._show_error(
            "Metric computation failed",
            message or "Unknown error",
        )

    def _cancel_roi_apply_job(self) -> None:
        """Cancel any in-flight ROI apply worker."""
        metrics = self.metrics_state
        thread = self._roi_apply_thread
        if thread is None:
            return
        metrics.cancel_roi_apply()
        self._finish_roi_apply_ui()
        if thread.isRunning():
            thread.requestInterruption()
            thread.quit()
            self._set_status("Cancelling ROI apply...")

    def _on_roi_apply_thread_finished(
        self,
        thread: QThread,
        worker: RoiApplyWorker,
    ) -> None:
        """Clean up ROI apply worker objects after thread shutdown."""
        if self._roi_apply_worker is worker:
            self._roi_apply_worker = None
        if self._roi_apply_thread is thread:
            self._roi_apply_thread = None
        self._update_average_controls()
        worker.deleteLater()
        thread.deleteLater()

    def _finish_roi_apply_ui(self) -> None:
        """Reset ROI apply progress UI state."""
        self.metrics_state.finish_roi_apply()
        self.roi_apply_progress.setValue(0)
        self.roi_apply_progress.setVisible(False)
        self._update_average_controls()

    def _start_roi_apply_job(self) -> None:
        """Start asynchronous ROI application across the full dataset."""
        metrics = self.metrics_state
        if (
            not self._has_loaded_data()
            or metrics.roi_rect is None
            or self._current_average_mode() != "roi"
        ):
            return
        if (
            self._roi_apply_thread is not None
            and self._roi_apply_thread.isRunning()
        ):
            self._set_status("ROI apply already running")
            return

        dataset = self.dataset_state
        job_id = metrics.begin_roi_apply(dataset.path_count())
        thread = QThread(self)
        worker = RoiApplyWorker(
            job_id=job_id,
            paths=list(dataset.paths),
            roi_rect=self.metrics_state.roi_rect,
            background_config=self._background_config_snapshot(),
            background_library=self._background_library_snapshot(),
            path_metadata=dict(dataset.path_metadata),
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_roi_apply_progress)
        worker.finished.connect(self._on_roi_apply_finished)
        worker.cancelled.connect(self._on_roi_apply_cancelled)
        worker.failed.connect(self._on_roi_apply_failed)
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(
            lambda t=thread, w=worker: self._on_roi_apply_thread_finished(t, w)
        )

        self._roi_apply_thread = thread
        self._roi_apply_worker = worker
        self.roi_apply_progress.setRange(0, max(1, metrics.roi_apply_total))
        self.roi_apply_progress.setValue(0)
        self.roi_apply_progress.setFormat("ROI apply %v/%m")
        self.roi_apply_progress.setVisible(True)
        self._update_average_controls()
        self._set_status("Applying ROI to all images...")
        thread.start()

    def _on_roi_apply_progress(self, done: int, total: int) -> None:
        """Update ROI apply progress indicator."""
        metrics = self.metrics_state
        if not metrics.is_roi_applying:
            return
        metrics.update_roi_apply_progress(done, total)
        self.roi_apply_progress.setRange(0, max(1, metrics.roi_apply_total))
        self.roi_apply_progress.setValue(
            min(metrics.roi_apply_done, metrics.roi_apply_total),
        )
        if (
            metrics.roi_apply_total > 0
            and metrics.roi_apply_done >= metrics.roi_apply_total
        ):
            self._set_status("Finalizing ROI apply...")

    def _on_roi_apply_finished(self, result: object) -> None:
        """Apply completed ROI metrics to the active dataset."""
        if not isinstance(result, RoiApplyResult):
            return
        if result.job_id != self.metrics_state.roi_apply_job_id:
            return
        self._finish_roi_apply_ui()
        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures(
                list(result.failures),
                replace_stage="roi",
            )

        means = np.asarray(result.means, dtype=np.float64)
        if result.valid_count <= 0 or not np.any(np.isfinite(means)):
            self._show_error(
                "Invalid ROI",
                "Draw a valid ROI before applying.",
            )
            self._set_status("ROI apply failed")
            return

        self.metrics_state.apply_roi_result(result)
        self._refresh_table()
        self._set_status("ROI applied to all images")

    def _on_roi_apply_cancelled(self, job_id: int) -> None:
        """Handle ROI apply cancellation."""
        if job_id != self.metrics_state.roi_apply_job_id:
            return
        self._finish_roi_apply_ui()
        self._set_status("ROI apply cancelled")

    def _on_roi_apply_failed(self, job_id: int, message: str) -> None:
        """Handle ROI apply worker failure."""
        if job_id != self.metrics_state.roi_apply_job_id:
            return
        self._finish_roi_apply_ui()
        self._set_status("ROI apply failed")
        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures(
                [
                    make_processing_failure(
                        stage="roi",
                        path="",
                        reason=message or "Unknown error",
                    ),
                ],
                replace_stage="roi",
            )
        self._show_error("ROI apply failed", message or "Unknown error")

    def _update_table_columns(self) -> None:
        """Refresh measure-table headers for the active metric mode."""
        mode = self._current_average_mode()
        if mode == "topk":
            mean_header = "Top-K"
            std_header = "Top-K Std"
            sem_header = "Top-K Std Err"
        elif mode == "roi":
            mean_header = "ROI"
            std_header = "ROI Std"
            sem_header = "ROI Std Err"
        else:
            mean_header = "Average Metric"
            std_header = "Std"
            sem_header = "Std Err"

        self.table_model.set_average_header(mean_header)
        self.table_model.set_std_header(std_header)
        self.table_model.set_sem_header(sem_header)
        self.table_model.set_dn_per_ms_header("DN/ms")
        self._apply_measure_table_visibility()
        self._sync_column_menu_actions()

    def _apply_live_update(self) -> None:
        """Apply UI-driven metric settings to the loaded dataset."""
        if not self._has_loaded_data():
            self._update_average_controls()
            self._set_status()
            return

        metrics = self.metrics_state
        metrics.threshold_value = self.threshold_spin.value()
        metrics.avg_count_value = self.avg_spin.value()
        count = self.dataset_state.path_count()
        mode = self._current_average_mode()
        metrics.prepare_for_live_update(path_count=count, mode=mode)

        self._refresh_table(update_analysis=False)
        self._start_dynamic_stats_job(
            update_kind="full",
            refresh_analysis=True,
        )
        self._update_average_controls()
        self._set_status()

    def _apply_threshold_update(self) -> None:
        """Refresh saturation display without rebuilding unrelated metrics."""
        metrics = self.metrics_state
        threshold_value = self.threshold_spin.value()
        threshold_changed = float(threshold_value) != float(metrics.threshold_value)
        metrics.threshold_value = threshold_value

        if not self._has_loaded_data():
            self._update_average_controls()
            self._set_status()
            return

        if not threshold_changed:
            if (
                self.dataset_state.selected_index is not None
                and 0 <= self.dataset_state.selected_index < self.dataset_state.path_count()
            ):
                self._display_image(self.dataset_state.selected_index)
            self._set_status()
            return

        self._start_dynamic_stats_job(
            update_kind="threshold_only",
            refresh_analysis=False,
        )
        self._update_average_controls()
        if (
            self.dataset_state.selected_index is not None
            and 0 <= self.dataset_state.selected_index < self.dataset_state.path_count()
        ):
            self._display_image(self.dataset_state.selected_index)
        self._set_status("Updating saturation counts")

    def _refresh_table(self, *, update_analysis: bool = True) -> None:
        """Refresh the measure table and linked preview state."""
        if (
            not self._has_loaded_data()
            or self.metrics_state.sat_counts is None
            or self.metrics_state.min_non_zero is None
            or self.metrics_state.maxs is None
        ):
            dataset = self.dataset_state
            metrics = self.metrics_state
            self.table_model.clear()
            dataset.set_selected_index(None)
            self.image_preview.clear_image()
            self.image_preview.set_intensity_image(None)
            self.histogram_widget.clear_histogram()
            self.info_label.setText("No image selected.")
            metrics.dn_per_ms_values = None
            metrics.dn_per_ms_stds = None
            metrics.dn_per_ms_sems = None
            metrics.bg_applied_mask = None
            metrics.bg_total_count = 0
            metrics.bg_unmatched_count = 0
            if update_analysis:
                self._update_analysis_context()
            self._update_background_status_label()
            self._apply_dynamic_visibility_policy()
            if hasattr(self, "_refresh_measure_header_state"):
                self._refresh_measure_header_state()
            return

        mode = self._current_average_mode()
        iris_positions, exposure_ms = self._metadata_numeric_arrays()
        (
            self.metrics_state.dn_per_ms_values,
            self.metrics_state.dn_per_ms_stds,
            self.metrics_state.dn_per_ms_sems,
        ) = self._compute_dn_per_ms_metrics(mode, exposure_ms)
        self.table_model.set_intensity_normalization(
            self.metrics_state.normalize_intensity_values,
            self._normalization_scale(),
        )
        dataset = self.dataset_state
        metrics = self.metrics_state
        model_reset = self.table_model.update_metrics(
            paths=dataset.paths,
            iris_positions=iris_positions,
            exposure_ms=exposure_ms,
            maxs=metrics.maxs,
            min_non_zero=metrics.min_non_zero,
            sat_counts=metrics.sat_counts,
            avg_mode=mode,
            avg_topk=metrics.avg_maxs if mode == "topk" else None,
            avg_topk_std=metrics.avg_maxs_std if mode == "topk" else None,
            avg_topk_sem=metrics.avg_maxs_sem if mode == "topk" else None,
            avg_roi=metrics.roi_means if mode == "roi" else None,
            avg_roi_std=metrics.roi_stds if mode == "roi" else None,
            avg_roi_sem=metrics.roi_sems if mode == "roi" else None,
            dn_per_ms=metrics.dn_per_ms_values,
        )
        self._apply_table_sort()
        self._update_table_columns()

        n_rows = dataset.path_count()
        if n_rows == 0:
            dataset.set_selected_index(None)
            return

        target_index = dataset.selected_index
        current_index = self.table.currentIndex()
        if target_index is None or not (0 <= target_index < n_rows):
            if current_index.isValid():
                mapped_row = self._source_row_from_proxy_index(current_index)
                target_index = mapped_row if mapped_row is not None else 0
            else:
                target_index = 0
        target_index = dataset.set_selected_index(
            target_index,
            path_count=n_rows,
        )
        assert target_index is not None

        if model_reset or not current_index.isValid():
            self._set_table_current_source_row(target_index)

        if self._is_multi_cell_selection():
            self._pause_preview_updates = True
            if update_analysis:
                self._update_analysis_context()
            self._update_background_status_label()
            return
        self._pause_preview_updates = False
        self._display_image(target_index)
        if update_analysis:
            self._update_analysis_context()
        self._update_background_status_label()
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()

    def _is_multi_cell_selection(self) -> bool:
        """Return whether the table currently has a multi-cell selection."""
        selection = self.table.selectionModel()
        if selection is None:
            return False
        return len(selection.selectedIndexes()) > 1

    def on_row_selected(self) -> None:
        """Update the selected row index and refresh preview if needed."""
        dataset = self.dataset_state
        if not dataset.paths:
            return
        if self._is_multi_cell_selection():
            self._pause_preview_updates = True
            return

        current = self.table.currentIndex()
        row = self._source_row_from_proxy_index(current)
        if row is None:
            selection = self.table.selectionModel()
            if selection is None:
                return
            indexes = selection.selectedIndexes()
            if not indexes:
                return
            row = self._source_row_from_proxy_index(indexes[0])
            if row is None:
                return

        if not (0 <= row < dataset.path_count()):
            return
        was_paused = self._pause_preview_updates
        if dataset.selected_index == row:
            self._pause_preview_updates = False
            if was_paused:
                self._display_image(row)
            return
        self._pause_preview_updates = False
        dataset.set_selected_index(row, path_count=dataset.path_count())
        self._display_image(row)

    def _display_image(self, idx: int) -> None:
        """Refresh image preview, histogram, and info text for a row."""
        dataset = self.dataset_state
        metrics = self.metrics_state
        if self._pause_preview_updates:
            return
        if (
            not self._has_loaded_data()
            or metrics.min_non_zero is None
            or metrics.maxs is None
            or metrics.sat_counts is None
            or not (0 <= idx < dataset.path_count())
        ):
            return

        metric_img, bg_applied = self._get_metric_image_by_index(idx)
        if metric_img is None:
            self.image_preview.clear_image()
            self.image_preview.set_intensity_image(None)
            self.histogram_widget.clear_histogram()
            self.info_label.setText("Could not read image.")
            if hasattr(self, "_refresh_measure_header_state"):
                self._refresh_measure_header_state()
            return

        if self.show_image_preview:
            imgf = np.asarray(metric_img, dtype=np.float32)
            mn, mx = float(imgf.min()), float(imgf.max())
            if mx > mn:
                gray = ((imgf - mn) / (mx - mn) * 255.0).astype(np.uint8)
            else:
                gray = np.zeros_like(imgf, dtype=np.uint8)

            rgb = np.repeat(gray[..., None], 3, axis=2)
            rgb[metric_img >= metrics.threshold_value] = [255, 0, 0]
            self.image_preview.set_rgb_image(rgb)
            self.image_preview.set_intensity_image(np.asarray(metric_img))
            self.image_preview.set_roi_rect(metrics.roi_rect)
        else:
            self.image_preview.clear_image()
            self.image_preview.set_intensity_image(None)

        if self.show_histogram_preview:
            self.histogram_widget.set_image(np.asarray(metric_img))
        else:
            self.histogram_widget.clear_histogram()
        self._update_average_controls()

        image_path = dataset.paths[idx]
        image_name = Path(image_path).name
        info = (
            f"{image_name} | min_non_zero={int(metrics.min_non_zero[idx])} "
            f"max={int(metrics.maxs[idx])} "
            f"| saturated={int(metrics.sat_counts[idx])}"
        )
        if metrics.background_config.enabled:
            if bg_applied:
                ref_label = self._background_reference_label_for_path(
                    image_path,
                )
                info += f" | bg=applied ({ref_label})"
            else:
                info += " | bg=raw fallback"
        mode = self._current_average_mode()
        if mode == "topk":
            mean_value = (
                metrics.avg_maxs[idx]
                if metrics.avg_maxs is not None and idx < len(metrics.avg_maxs)
                else np.nan
            )
            std_value = (
                metrics.avg_maxs_std[idx]
                if metrics.avg_maxs_std is not None and idx < len(metrics.avg_maxs_std)
                else np.nan
            )
            sem_value = (
                metrics.avg_maxs_sem[idx]
                if metrics.avg_maxs_sem is not None and idx < len(metrics.avg_maxs_sem)
                else np.nan
            )
            mean_text, std_text, sem_text = self._format_mean_std_sem(
                float(mean_value),
                float(std_value),
                float(sem_value),
            )
            info += (
                f" | mean={mean_text} | std={std_text}"
                f" | stderr={sem_text}"
            )
        elif mode == "roi":
            if metrics.roi_rect is not None:
                x0, y0, x1, y1 = metrics.roi_rect
                info += f" | roi=({x0},{y0})-({x1},{y1})"
            roi_value = (
                metrics.roi_means[idx]
                if metrics.roi_means is not None
                else np.nan
            )
            roi_std = (
                metrics.roi_stds[idx]
                if metrics.roi_stds is not None
                else np.nan
            )
            roi_sem = (
                metrics.roi_sems[idx]
                if metrics.roi_sems is not None
                else np.nan
            )
            mean_text, std_text, sem_text = self._format_mean_std_sem(
                float(roi_value),
                float(roi_std),
                float(roi_sem),
            )
            info += (
                f" | mean={mean_text} | std={std_text}"
                f" | stderr={sem_text}"
            )
        if metrics.is_stats_running:
            info += " | updating metrics..."
        self.info_label.setText(info)
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()

    def _compute_roi_stats_for_index(
        self,
        index: int,
    ) -> tuple[float, float, float]:
        """Compute ROI mean, std, and sem for one image index."""
        dataset = self.dataset_state
        roi_rect = self.metrics_state.roi_rect
        if not self._has_loaded_data() or roi_rect is None:
            return (np.nan, np.nan, np.nan)
        if not (0 <= index < dataset.path_count()):
            return (np.nan, np.nan, np.nan)

        metric_img, _bg_applied = self._get_metric_image_by_index(index)
        if metric_img is None:
            return (np.nan, np.nan, np.nan)

        x0, y0, x1, y1 = roi_rect
        roi = metric_img[y0:y1, x0:x1]
        if roi.size == 0:
            return (np.nan, np.nan, np.nan)
        roi_std = float(roi.std())
        roi_sem = float(roi_std / np.sqrt(roi.size))
        return (float(roi.mean()), roi_std, roi_sem)

    def _on_average_mode_changed(self) -> None:
        """Respond to average-mode UI changes."""
        self._update_average_controls()
        self._update_table_columns()
        self._apply_live_update()

    def _on_roi_selected(self, rect: object) -> None:
        """Store current ROI selection and refresh ROI metrics."""
        selected_index = self.dataset_state.selected_index
        if not self._has_loaded_data() or selected_index is None:
            return
        if self._current_average_mode() != "roi":
            return
        if not isinstance(rect, tuple) or len(rect) != 4:
            return

        metrics = self.metrics_state
        metrics.roi_rect = (
            int(rect[0]),
            int(rect[1]),
            int(rect[2]),
            int(rect[3]),
        )
        self._reset_roi_metrics()
        roi_mean, roi_std, roi_sem = self._compute_roi_stats_for_index(
            selected_index,
        )
        metrics.roi_means[selected_index] = roi_mean
        metrics.roi_stds[selected_index] = roi_std
        metrics.roi_sems[selected_index] = roi_sem
        self._update_average_controls()
        self._refresh_table()
        self._set_status()

    def _apply_roi_to_all_images(self) -> None:
        """Start ROI propagation across all loaded images."""
        if not self._has_loaded_data() or self.metrics_state.roi_rect is None:
            return
        if self._current_average_mode() != "roi":
            return
        self._start_roi_apply_job()
