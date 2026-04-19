"""Dynamic metric jobs, table refresh, preview, and ROI runtime helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread

from ..metrics_cache import (
    DYNAMIC_METRIC_KIND,
    ROI_METRIC_KIND,
    MetricCacheWrite,
    background_signature_payload,
    dynamic_metric_signature_hash,
    roi_metric_signature_hash,
)
from ..metrics_state import DynamicStatsResult, RoiApplyResult
from ..native import backend as native_backend
from ..processing_failures import make_processing_failure
from ..workers import DynamicStatsWorker, RoiApplyWorker


class MetricsRuntimeMixin:
    """Live metric computation and preview refresh helpers."""

    PREVIEW_FAST_MAX_DIM = 768

    @staticmethod
    def _dynamic_stats_mode_for_average_mode(mode: str) -> str:
        """Map UI average mode onto the dynamic metrics worker mode."""

        return "topk" if mode == "topk" else "none"

    @staticmethod
    def _build_preview_rgb(
        image: np.ndarray,
        *,
        threshold_value: float,
        max_dim: int | None = None,
    ) -> np.ndarray:
        """Build one RGB preview buffer with thresholded pixels highlighted."""
        metric_arr = np.asarray(image)
        if (
            max_dim is not None
            and max_dim > 0
            and metric_arr.ndim == 2
            and max(metric_arr.shape) > int(max_dim)
        ):
            step = max(1, int(np.ceil(max(metric_arr.shape) / float(max_dim))))
            metric_arr = metric_arr[::step, ::step]
        imgf = np.array(metric_arr, dtype=np.float32, copy=True, order="C")
        mn = float(imgf.min()) if imgf.size > 0 else 0.0
        mx = float(imgf.max()) if imgf.size > 0 else 0.0
        if mx > mn:
            imgf -= mn
            imgf *= 255.0 / (mx - mn)
            np.clip(imgf, 0.0, 255.0, out=imgf)
            gray = imgf.astype(np.uint8)
        else:
            gray = np.zeros(metric_arr.shape, dtype=np.uint8)

        rgb = np.empty((*gray.shape, 3), dtype=np.uint8)
        rgb[..., 0] = gray
        rgb[..., 1] = gray
        rgb[..., 2] = gray

        hot_mask = metric_arr >= threshold_value
        rgb[..., 0][hot_mask] = 255
        rgb[..., 1][hot_mask] = 0
        rgb[..., 2][hot_mask] = 0
        return rgb

    @staticmethod
    def _preview_downsample_step(
        shape: tuple[int, ...],
        *,
        max_dim: int,
    ) -> int:
        if max_dim <= 0 or len(shape) < 2:
            return 1
        longest_edge = max(int(shape[0]), int(shape[1]))
        if longest_edge <= max_dim:
            return 1
        return max(1, int(np.ceil(longest_edge / float(max_dim))))

    def _build_fast_preview_metric_image(
        self,
        image: np.ndarray,
        *,
        reference: np.ndarray,
    ) -> np.ndarray:
        """Return a reduced corrected image for immediate preview refreshes."""

        step = self._preview_downsample_step(
            np.asarray(image).shape,
            max_dim=self.PREVIEW_FAST_MAX_DIM,
        )
        sampled_image = (
            image
            if step <= 1
            else np.asarray(image)[::step, ::step]
        )
        sampled_reference = (
            reference
            if step <= 1
            else np.asarray(reference)[::step, ::step]
        )
        return native_backend.apply_background_f32(
            np.ascontiguousarray(sampled_image),
            background=np.ascontiguousarray(sampled_reference),
            clip_negative=self.metrics_state.background_config.clip_negative,
        )

    def _background_signature_payload(self) -> dict[str, object]:
        """Return the stable background-input payload used for cache keys."""

        dataset = self.dataset_state
        workflow = getattr(self, "workflow_state_controller", None)
        return background_signature_payload(
            self.metrics_state.background_library,
            self._background_config_snapshot(),
            dataset_root=dataset.dataset_root,
            workspace_root=getattr(workflow, "workspace_root", None),
        )

    def _dynamic_metric_signature_hash(self, mode: str) -> str:
        """Return cache signature for the current dynamic row-metric settings."""

        metrics = self.metrics_state
        normalized_mode = self._dynamic_stats_mode_for_average_mode(mode)
        return dynamic_metric_signature_hash(
            mode=normalized_mode,
            threshold_value=metrics.threshold_value,
            avg_count_value=metrics.avg_count_value,
            background_payload=self._background_signature_payload(),
        )

    def _roi_metric_signature_hash(self) -> str | None:
        """Return cache signature for the current ROI settings."""

        roi_rect = self.metrics_state.roi_rect
        if roi_rect is None:
            return None
        return roi_metric_signature_hash(
            roi_rect=roi_rect,
            background_payload=self._background_signature_payload(),
        )

    def _cached_dynamic_payloads(
        self,
        signature_hash: str,
    ) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
        """Load cached dynamic metric payloads for the current dataset."""

        cache = getattr(self, "metrics_cache", None)
        dataset = self.dataset_state
        identities = self._metric_cache_identities(
            [Path(path) for path in dataset.paths],
            dataset_root=dataset.dataset_root,
        )
        if cache is None or not identities:
            return (identities, {})
        cached = cache.fetch_entries(
            identities.values(),
            metric_kind=DYNAMIC_METRIC_KIND,
            signature_hash=signature_hash,
        )
        return (identities, cached)

    def _cached_roi_payloads(
        self,
        signature_hash: str,
    ) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
        """Load cached ROI payloads for the current dataset."""

        cache = getattr(self, "metrics_cache", None)
        dataset = self.dataset_state
        identities = self._metric_cache_identities(
            [Path(path) for path in dataset.paths],
            dataset_root=dataset.dataset_root,
        )
        if cache is None or not identities:
            return (identities, {})
        cached = cache.fetch_entries(
            identities.values(),
            metric_kind=ROI_METRIC_KIND,
            signature_hash=signature_hash,
        )
        return (identities, cached)

    def _prefill_dynamic_metric_arrays(
        self,
        *,
        mode: str,
        update_kind: str,
        cached_payloads: dict[str, dict[str, object]],
    ) -> tuple[
        np.ndarray,
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        list[int],
    ]:
        """Build partially cached dynamic metric arrays and return miss indices."""

        dataset = self.dataset_state
        metrics = self.metrics_state
        n = dataset.path_count()
        cached_sat_counts = np.zeros(n, dtype=np.int64)
        cached_max_pixels = np.zeros(n, dtype=np.int64)
        cached_min_non_zero = np.zeros(n, dtype=np.int64)
        cached_bg_applied = np.zeros(n, dtype=bool)
        cached_avg_topk = (
            np.full(n, np.nan, dtype=np.float64)
            if mode == "topk"
            else None
        )
        cached_avg_topk_std = (
            np.full(n, np.nan, dtype=np.float64)
            if mode == "topk"
            else None
        )
        cached_avg_topk_sem = (
            np.full(n, np.nan, dtype=np.float64)
            if mode == "topk"
            else None
        )
        hit_indices: set[int] = set()
        for index, path in enumerate(dataset.paths):
            payload = cached_payloads.get(path)
            if payload is None:
                continue
            hit_indices.add(index)
            cached_sat_counts[index] = int(payload.get("sat_count", 0))
            cached_max_pixels[index] = int(payload.get("max_pixel", 0))
            cached_min_non_zero[index] = int(payload.get("min_non_zero", 0))
            cached_bg_applied[index] = bool(payload.get("bg_applied", False))
            if mode == "topk" and cached_avg_topk is not None:
                cached_avg_topk[index] = float(payload.get("avg_topk", np.nan))
                if cached_avg_topk_std is not None:
                    cached_avg_topk_std[index] = float(
                        payload.get("avg_topk_std", np.nan),
                    )
                if cached_avg_topk_sem is not None:
                    cached_avg_topk_sem[index] = float(
                        payload.get("avg_topk_sem", np.nan),
                    )

        if update_kind == "threshold_only":
            existing_max_pixels = (
                np.asarray(metrics.maxs, dtype=np.int64)
                if metrics.maxs is not None and len(metrics.maxs) == n
                else cached_max_pixels
            )
            existing_min_non_zero = (
                np.asarray(metrics.min_non_zero, dtype=np.int64)
                if metrics.min_non_zero is not None and len(metrics.min_non_zero) == n
                else cached_min_non_zero
            )
            existing_bg_applied = (
                np.asarray(metrics.bg_applied_mask, dtype=bool)
                if metrics.bg_applied_mask is not None and len(metrics.bg_applied_mask) == n
                else cached_bg_applied
            )
            existing_avg_topk = (
                np.asarray(metrics.avg_maxs, dtype=np.float64)
                if mode == "topk"
                and metrics.avg_maxs is not None
                and len(metrics.avg_maxs) == n
                else cached_avg_topk
            )
            existing_avg_topk_std = (
                np.asarray(metrics.avg_maxs_std, dtype=np.float64)
                if mode == "topk"
                and metrics.avg_maxs_std is not None
                and len(metrics.avg_maxs_std) == n
                else cached_avg_topk_std
            )
            existing_avg_topk_sem = (
                np.asarray(metrics.avg_maxs_sem, dtype=np.float64)
                if mode == "topk"
                and metrics.avg_maxs_sem is not None
                and len(metrics.avg_maxs_sem) == n
                else cached_avg_topk_sem
            )
        else:
            existing_max_pixels = cached_max_pixels
            existing_min_non_zero = cached_min_non_zero
            existing_bg_applied = cached_bg_applied
            existing_avg_topk = cached_avg_topk
            existing_avg_topk_std = cached_avg_topk_std
            existing_avg_topk_sem = cached_avg_topk_sem

        missing_indices = [
            index
            for index in range(n)
            if index not in hit_indices
        ]
        return (
            cached_sat_counts,
            existing_avg_topk,
            existing_avg_topk_std,
            existing_avg_topk_sem,
            existing_max_pixels,
            existing_min_non_zero,
            existing_bg_applied,
            missing_indices,
        )

    def _store_cached_dynamic_metrics(
        self,
        result: DynamicStatsResult,
    ) -> None:
        """Persist newly computed dynamic metric rows into the SQLite cache."""

        pending = getattr(self, "_dynamic_cache_pending", None)
        self._dynamic_cache_pending = None
        if not pending:
            return
        cache = getattr(self, "metrics_cache", None)
        if cache is None:
            return
        identities = pending["identities"]
        source_indices = pending["source_indices"]
        mode = pending["mode"]
        writes: list[MetricCacheWrite] = []
        for index in source_indices:
            path = self.dataset_state.paths[index]
            identity = identities.get(path)
            if identity is None:
                continue
            payload = {
                "sat_count": int(result.sat_counts[index]),
                "max_pixel": int(result.max_pixels[index]),
                "min_non_zero": int(result.min_non_zero[index]),
                "bg_applied": bool(result.bg_applied_mask[index]),
            }
            if mode == "topk" and result.avg_topk is not None:
                payload["avg_topk"] = float(result.avg_topk[index])
                if result.avg_topk_std is not None:
                    payload["avg_topk_std"] = float(result.avg_topk_std[index])
                if result.avg_topk_sem is not None:
                    payload["avg_topk_sem"] = float(result.avg_topk_sem[index])
            writes.append(MetricCacheWrite(identity=identity, payload=payload))
        cache.store_entries(
            writes,
            metric_kind=DYNAMIC_METRIC_KIND,
            signature_hash=str(pending["signature_hash"]),
        )

    def _prefill_roi_metric_arrays(
        self,
        cached_payloads: dict[str, dict[str, object]],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[int]]:
        """Build partially cached ROI arrays and return miss indices."""

        dataset = self.dataset_state
        n = dataset.path_count()
        maxs = np.full(n, np.nan, dtype=np.float64)
        means = np.full(n, np.nan, dtype=np.float64)
        stds = np.full(n, np.nan, dtype=np.float64)
        sems = np.full(n, np.nan, dtype=np.float64)
        hit_indices: set[int] = set()
        for index, path in enumerate(dataset.paths):
            payload = cached_payloads.get(path)
            if payload is None:
                continue
            hit_indices.add(index)
            maxs[index] = float(payload.get("max", np.nan))
            means[index] = float(payload.get("mean", np.nan))
            stds[index] = float(payload.get("std", np.nan))
            sems[index] = float(payload.get("sem", np.nan))
        missing_indices = [
            index
            for index in range(n)
            if index not in hit_indices
        ]
        return (maxs, means, stds, sems, missing_indices)

    def _store_cached_roi_metrics(
        self,
        result: RoiApplyResult,
    ) -> None:
        """Persist newly computed ROI rows into the SQLite cache."""

        pending = getattr(self, "_roi_cache_pending", None)
        self._roi_cache_pending = None
        if not pending:
            return
        cache = getattr(self, "metrics_cache", None)
        if cache is None:
            return
        identities = pending["identities"]
        source_indices = pending["source_indices"]
        writes: list[MetricCacheWrite] = []
        for index in source_indices:
            path = self.dataset_state.paths[index]
            identity = identities.get(path)
            if identity is None:
                continue
            writes.append(
                MetricCacheWrite(
                    identity=identity,
                    payload={
                        "max": float(result.maxs[index]),
                        "mean": float(result.means[index]),
                        "std": float(result.stds[index]),
                        "sem": float(result.sems[index]),
                    },
                ),
            )
        cache.store_entries(
            writes,
            metric_kind=ROI_METRIC_KIND,
            signature_hash=str(pending["signature_hash"]),
        )

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
        self._dynamic_cache_pending = None
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
        mode = self._dynamic_stats_mode_for_average_mode(
            self._current_average_mode(),
        )
        dataset = self.dataset_state
        signature_hash = self._dynamic_metric_signature_hash(mode)
        identities, cached_payloads = self._cached_dynamic_payloads(signature_hash)
        (
            existing_sat_counts,
            existing_avg_topk,
            existing_avg_topk_std,
            existing_avg_topk_sem,
            existing_max_pixels,
            existing_min_non_zero,
            existing_bg_applied,
            missing_indices,
        ) = self._prefill_dynamic_metric_arrays(
            mode=mode,
            update_kind=update_kind,
            cached_payloads=cached_payloads,
        )

        if not missing_indices:
            self._dynamic_cache_pending = None
            self._on_dynamic_stats_finished(
                DynamicStatsResult(
                    job_id=job_id,
                    sat_counts=existing_sat_counts,
                    avg_topk=existing_avg_topk,
                    avg_topk_std=existing_avg_topk_std,
                    avg_topk_sem=existing_avg_topk_sem,
                    max_pixels=existing_max_pixels,
                    min_non_zero=existing_min_non_zero,
                    bg_applied_mask=existing_bg_applied,
                ),
            )
            return

        thread = QThread(self)
        worker = DynamicStatsWorker(
            job_id=job_id,
            paths=[dataset.paths[index] for index in missing_indices],
            source_indices=missing_indices,
            result_length=dataset.path_count(),
            threshold_value=metrics.threshold_value,
            mode=mode,
            avg_count_value=metrics.avg_count_value,
            update_kind=update_kind,
            background_config=self._background_config_snapshot(),
            background_library=self._background_library_snapshot(),
            path_metadata=dict(dataset.path_metadata),
            raw_resolver_context=self._raw_decode_resolver_context(
                path_metadata_by_path=dict(dataset.path_metadata),
            ),
            existing_sat_counts=existing_sat_counts,
            existing_avg_topk=existing_avg_topk,
            existing_avg_topk_std=existing_avg_topk_std,
            existing_avg_topk_sem=existing_avg_topk_sem,
            existing_max_pixels=existing_max_pixels,
            existing_min_non_zero=existing_min_non_zero,
            existing_bg_applied_mask=existing_bg_applied,
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
        self._dynamic_cache_pending = {
            "signature_hash": signature_hash,
            "identities": identities,
            "source_indices": missing_indices,
            "mode": mode,
        }
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
        self._store_cached_dynamic_metrics(result)
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
        self._dynamic_cache_pending = None
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
        signature_hash = self._roi_metric_signature_hash()
        if signature_hash is None:
            return
        identities, cached_payloads = self._cached_roi_payloads(signature_hash)
        existing_maxs, existing_means, existing_stds, existing_sems, missing_indices = (
            self._prefill_roi_metric_arrays(cached_payloads)
        )
        if not missing_indices:
            self._roi_cache_pending = None
            self._on_roi_apply_finished(
                RoiApplyResult(
                    job_id=job_id,
                    maxs=existing_maxs,
                    means=existing_means,
                    stds=existing_stds,
                    sems=existing_sems,
                    valid_count=int(np.count_nonzero(np.isfinite(existing_means))),
                ),
            )
            return

        thread = QThread(self)
        worker = RoiApplyWorker(
            job_id=job_id,
            paths=[dataset.paths[index] for index in missing_indices],
            source_indices=missing_indices,
            result_length=dataset.path_count(),
            roi_rect=self.metrics_state.roi_rect,
            background_config=self._background_config_snapshot(),
            background_library=self._background_library_snapshot(),
            path_metadata=dict(dataset.path_metadata),
            raw_resolver_context=self._raw_decode_resolver_context(
                path_metadata_by_path=dict(dataset.path_metadata),
            ),
            existing_maxs=existing_maxs,
            existing_means=existing_means,
            existing_stds=existing_stds,
            existing_sems=existing_sems,
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
        self._roi_cache_pending = {
            "signature_hash": signature_hash,
            "identities": identities,
            "source_indices": missing_indices,
        }
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
        self._store_cached_roi_metrics(result)

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
        self._refresh_workspace_document_dirty_state()
        self._set_status("ROI applied to all images")

    def _on_roi_apply_cancelled(self, job_id: int) -> None:
        """Handle ROI apply cancellation."""
        if job_id != self.metrics_state.roi_apply_job_id:
            return
        self._roi_cache_pending = None
        self._finish_roi_apply_ui()
        self._set_status("ROI apply cancelled")

    def _on_roi_apply_failed(self, job_id: int, message: str) -> None:
        """Handle ROI apply worker failure."""
        if job_id != self.metrics_state.roi_apply_job_id:
            return
        self._roi_cache_pending = None
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
        if self._is_dataset_load_running():
            self._update_average_controls()
            self._set_status("Dataset load in progress")
            return
        if not self._has_loaded_data():
            self._update_average_controls()
            self._refresh_workspace_document_dirty_state()
            self._set_status()
            return

        metrics = self.metrics_state
        metrics.threshold_value = self.threshold_spin.value()
        metrics.low_signal_threshold_value = self.low_signal_spin.value()
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
        self._refresh_workspace_document_dirty_state()
        self._set_status()

    def _apply_threshold_update(self) -> None:
        """Refresh saturation display without rebuilding unrelated metrics."""
        if self._is_dataset_load_running():
            self._set_status("Wait for dataset loading to finish")
            return
        metrics = self.metrics_state
        threshold_value = self.threshold_spin.value()
        threshold_changed = float(threshold_value) != float(metrics.threshold_value)
        metrics.threshold_value = threshold_value

        if not self._has_loaded_data():
            self._update_average_controls()
            self._refresh_workspace_document_dirty_state()
            self._set_status()
            return

        if not threshold_changed:
            if (
                self.dataset_state.selected_index is not None
                and 0 <= self.dataset_state.selected_index < self.dataset_state.path_count()
            ):
                self._display_image(self.dataset_state.selected_index)
            self._refresh_workspace_document_dirty_state()
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
        self._refresh_workspace_document_dirty_state()
        self._set_status("Updating saturation counts")

    def _apply_low_signal_threshold_update(self) -> None:
        """Refresh low-signal row highlighting using the cached max-pixel values."""
        if self._is_dataset_load_running():
            self._set_status("Wait for dataset loading to finish")
            return

        metrics = self.metrics_state
        metrics.low_signal_threshold_value = self.low_signal_spin.value()

        if self._has_loaded_data():
            self._refresh_table(update_analysis=False)
        else:
            self._update_average_controls()
            if hasattr(self, "_refresh_measure_header_state"):
                self._refresh_measure_header_state()
        self._refresh_workspace_document_dirty_state()
        if float(metrics.low_signal_threshold_value) <= 0.0:
            self._set_status("Low-signal detection disabled")
        else:
            self._set_status("Updated low-signal image highlighting")

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
            self._clear_pending_preview_requests()
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
                self._invalidate_analysis_context(refresh_visible_plugin=True)
            self._update_background_status_label()
            self._apply_dynamic_visibility_policy()
            if hasattr(self, "_refresh_measure_header_state"):
                self._refresh_measure_header_state()
            return

        mode = self._current_average_mode()
        streaming_update = bool(
            getattr(self, "_dataset_load_batch_applying", False),
        )
        iris_positions, exposure_ms = self._metadata_numeric_arrays()
        if streaming_update and mode == "roi" and not self.metrics_state.roi_applied_to_all:
            self.metrics_state.dn_per_ms_values = None
            self.metrics_state.dn_per_ms_stds = None
            self.metrics_state.dn_per_ms_sems = None
        else:
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
        previous_selected_index = dataset.selected_index
        update_kind = self.table_model.update_metrics(
            paths=dataset.paths,
            iris_positions=iris_positions,
            exposure_ms=exposure_ms,
            maxs=metrics.maxs,
            roi_maxs=metrics.roi_maxs,
            min_non_zero=metrics.min_non_zero,
            sat_counts=metrics.sat_counts,
            low_signal_flags=metrics.low_signal_mask(path_count=dataset.path_count()),
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
        n_rows = dataset.path_count()
        self._ensure_measure_table_row_visibility(n_rows)
        self._update_table_columns()
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

        if update_kind == "reset" or not current_index.isValid():
            self._set_table_current_source_row(target_index)

        if self._is_multi_cell_selection():
            self._pause_preview_updates = True
            self._clear_pending_preview_requests()
            if update_analysis:
                self._invalidate_analysis_context(refresh_visible_plugin=True)
            self._update_background_status_label()
            return
        self._pause_preview_updates = False
        should_refresh_preview = not (
            update_kind == "append"
            and previous_selected_index == target_index
            and current_index.isValid()
        )
        if should_refresh_preview:
            self._schedule_row_preview_refresh(target_index, debounce=True)
        if update_analysis:
            self._invalidate_analysis_context(refresh_visible_plugin=True)
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
        """Update the selected row index and queue one settled preview refresh."""
        dataset = self.dataset_state
        if not dataset.paths:
            return
        if self._is_multi_cell_selection():
            self._pause_preview_updates = True
            self._clear_pending_preview_requests()
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
        self._pause_preview_updates = False
        if dataset.selected_index == row:
            if was_paused:
                self._schedule_row_preview_refresh(row, debounce=True)
            return
        dataset.set_selected_index(row, path_count=dataset.path_count())
        self._schedule_row_preview_refresh(row, debounce=True)
        if hasattr(self, "_schedule_workspace_document_dirty_state_refresh"):
            self._schedule_workspace_document_dirty_state_refresh()
        else:
            self._refresh_workspace_document_dirty_state()

    def _clear_pending_preview_requests(self) -> None:
        """Cancel any queued selection-driven preview refreshes."""

        self._preview_selection_timer.stop()
        self._pending_selection_preview_index = None
        self._pending_selection_preview_generation = 0

    def _histogram_preview_is_active(self) -> bool:
        """Return whether histogram rendering is currently user-visible."""

        if not self.show_histogram_preview:
            return False
        preview_pages = getattr(self, "preview_pages", None)
        if preview_pages is None:
            return bool(self.show_histogram_preview)
        if hasattr(preview_pages, "isTabVisible") and not preview_pages.isTabVisible(1):
            return False
        return preview_pages.currentIndex() == 1

    def _schedule_row_preview_refresh(
        self,
        idx: int,
        *,
        debounce: bool,
    ) -> None:
        """Queue one selection-driven preview refresh for the latest stable row."""

        if not (0 <= idx < self.dataset_state.path_count()):
            return
        self._preview_generation += 1
        generation = int(self._preview_generation)
        self._pending_selection_preview_index = idx
        self._pending_selection_preview_generation = generation
        self._preview_selection_timer.stop()
        if not (self.show_image_preview or self.show_histogram_preview):
            return
        if debounce:
            self._preview_selection_timer.start()
            return
        self._flush_pending_selection_preview()

    def _flush_pending_selection_preview(self) -> None:
        """Render one settled preview for the latest selected row."""

        idx = self._pending_selection_preview_index
        generation = int(self._pending_selection_preview_generation)
        if idx is None or self._pause_preview_updates:
            return
        if self._is_dataset_load_running() or getattr(
            self,
            "_dataset_load_batch_applying",
            False,
        ):
            self._preview_selection_timer.start()
            return
        if self.dataset_state.selected_index != idx:
            return
        if generation != int(self._preview_generation):
            return
        self._pending_selection_preview_index = None
        self._pending_selection_preview_generation = 0
        self._render_display_image(
            idx,
            exact_preview=True,
            preview_generation=generation,
        )

    def _display_image(self, idx: int) -> None:
        """Refresh one row preview immediately for explicit non-browsing updates."""

        if not (0 <= idx < self.dataset_state.path_count()):
            return
        self._preview_generation += 1
        generation = int(self._preview_generation)
        self._clear_pending_preview_requests()
        self._render_display_image(
            idx,
            exact_preview=True,
            preview_generation=generation,
        )

    def _render_display_image(
        self,
        idx: int,
        *,
        exact_preview: bool,
        preview_generation: int | None = None,
    ) -> None:
        """Render image preview, histogram, and info text for a row."""
        dataset = self.dataset_state
        metrics = self.metrics_state
        if self._pause_preview_updates:
            return
        if (
            preview_generation is not None
            and int(preview_generation) != int(self._preview_generation)
        ):
            return
        if (
            not self._has_loaded_data()
            or metrics.min_non_zero is None
            or metrics.maxs is None
            or metrics.sat_counts is None
            or not (0 <= idx < dataset.path_count())
        ):
            return

        image_path = dataset.paths[idx]
        raw_image = self._get_image_by_index(idx)
        if raw_image is None:
            self.image_preview.clear_image()
            self.image_preview.set_intensity_image(None)
            self.histogram_widget.clear_histogram()
            self.info_label.setText("Could not read image.")
            if hasattr(self, "_refresh_measure_header_state"):
                self._refresh_measure_header_state()
            return

        reference = None
        if hasattr(self, "_validated_reference_for_image"):
            reference = self._validated_reference_for_image(raw_image, image_path)
        bg_applied = reference is not None

        if self.show_image_preview:
            if exact_preview and bg_applied:
                metric_img, _cached_bg_applied = self._get_metric_image_by_index(idx)
                if metric_img is None:
                    self.image_preview.clear_image()
                    self.image_preview.set_intensity_image(None)
                    self.info_label.setText("Could not build corrected preview.")
                    return
                preview_arr = np.asarray(metric_img)
                preview_rgb = self._build_preview_rgb(
                    preview_arr,
                    threshold_value=metrics.threshold_value,
                    max_dim=None,
                )
                intensity_image = preview_arr
            else:
                preview_arr = (
                    self._build_fast_preview_metric_image(raw_image, reference=reference)
                    if bg_applied
                    else np.asarray(raw_image)
                )
                preview_rgb = self._build_preview_rgb(
                    preview_arr,
                    threshold_value=metrics.threshold_value,
                    max_dim=None if bg_applied else self.PREVIEW_FAST_MAX_DIM,
                )
                intensity_image = (
                    preview_arr
                    if np.asarray(preview_arr).shape == np.asarray(raw_image).shape
                    else None
                )
            self.image_preview.set_rgb_image(
                preview_rgb,
                image_size=(int(raw_image.shape[1]), int(raw_image.shape[0])),
            )
            self.image_preview.set_intensity_image(intensity_image)
            self.image_preview.set_roi_rect(metrics.roi_rect)
        else:
            self.image_preview.clear_image()
            self.image_preview.set_intensity_image(None)

        if (
            preview_generation is not None
            and int(preview_generation) != int(self._preview_generation)
        ):
            return

        if self._histogram_preview_is_active():
            self.histogram_widget.set_image(
                raw_image,
                exact=(
                    exact_preview
                    and not self._is_dataset_load_running()
                    and not getattr(self, "_dataset_load_batch_applying", False)
                ),
                background=reference,
                clip_negative=metrics.background_config.clip_negative,
            )
        else:
            if not self.show_histogram_preview:
                self.histogram_widget.clear_histogram()
        self._update_average_controls()

        image_name = Path(image_path).name
        info = (
            f"{image_name} | min_non_zero={int(metrics.min_non_zero[idx])} "
            f"max={int(metrics.maxs[idx])} "
            f"| saturated={int(metrics.sat_counts[idx])}"
        )
        if (
            float(metrics.low_signal_threshold_value) > 0.0
            and int(metrics.maxs[idx]) <= int(metrics.low_signal_threshold_value)
        ):
            info += " | low-signal"
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
    ) -> tuple[float, float, float, float]:
        """Compute ROI max, mean, std, and sem for one image index."""
        dataset = self.dataset_state
        roi_rect = self.metrics_state.roi_rect
        if not self._has_loaded_data() or roi_rect is None:
            return (np.nan, np.nan, np.nan, np.nan)
        if not (0 <= index < dataset.path_count()):
            return (np.nan, np.nan, np.nan, np.nan)

        signature_hash = self._roi_metric_signature_hash()
        path = dataset.paths[index]
        cache = getattr(self, "metrics_cache", None)
        identity = None
        if signature_hash is not None:
            identities = self._metric_cache_identities(
                [Path(path)],
                dataset_root=dataset.dataset_root,
            )
            identity = identities.get(str(Path(path).resolve()))
            if cache is not None and identity is not None:
                cached = cache.fetch_entries(
                    [identity],
                    metric_kind=ROI_METRIC_KIND,
                    signature_hash=signature_hash,
                )
                cached_payload = cached.get(str(Path(path).resolve()))
                if cached_payload is not None:
                    return (
                        float(cached_payload.get("max", np.nan)),
                        float(cached_payload.get("mean", np.nan)),
                        float(cached_payload.get("std", np.nan)),
                        float(cached_payload.get("sem", np.nan)),
                    )

        image = self._get_image_by_index(index)
        if image is None:
            return (np.nan, np.nan, np.nan, np.nan)

        roi_max, roi_mean, roi_std, roi_sem = native_backend.compute_roi_metrics(
            image,
            roi_rect=roi_rect,
            background=self._get_reference_for_path(path),
            clip_negative=self.metrics_state.background_config.clip_negative,
        )
        if (
            cache is not None
            and identity is not None
            and signature_hash is not None
        ):
            cache.store_entries(
                [
                    MetricCacheWrite(
                        identity=identity,
                        payload={
                            "max": roi_max,
                            "mean": roi_mean,
                            "std": roi_std,
                            "sem": roi_sem,
                        },
                    ),
                ],
                metric_kind=ROI_METRIC_KIND,
                signature_hash=signature_hash,
            )
        return (roi_max, roi_mean, roi_std, roi_sem)

    def _on_average_mode_changed(self) -> None:
        """Respond to average-mode UI changes."""
        self._update_average_controls()
        self._update_table_columns()
        self._apply_live_update()

    def _on_roi_selected(self, rect: object) -> None:
        """Store current ROI selection and refresh ROI metrics."""
        if not self._has_loaded_data() or self.dataset_state.selected_index is None:
            return
        if self._current_average_mode() != "roi":
            return
        self._apply_roi_rect_to_current_dataset(rect, status_message=None)

    def _apply_roi_to_all_images(self) -> None:
        """Start ROI propagation across all loaded images."""
        if not self._has_loaded_data() or self.metrics_state.roi_rect is None:
            return
        if self._current_average_mode() != "roi":
            return
        self._start_roi_apply_job()
