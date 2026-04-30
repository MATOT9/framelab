"""Dynamic metric jobs, table refresh, preview, and ROI runtime helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread

from ..metrics_cache import (
    BACKGROUND_METRIC_KIND,
    ROI_METRIC_KIND,
    SATURATION_METRIC_KIND,
    TOPK_METRIC_KIND,
    MetricCacheWrite,
    background_metric_signature_hash,
    background_signature_payload,
    roi_metric_signature_hash,
    saturation_metric_signature_hash,
    topk_metric_signature_hash,
)
from ..metrics_state import (
    DynamicStatsResult,
    MetricFamily,
    MetricFamilyState,
    RoiApplyResult,
)
from ..native import backend as native_backend
from ..processing_failures import make_processing_failure
from ..refresh_policy import (
    RefreshReason,
    ensure_compute_reason,
    log_refresh_event,
)
from ..runtime_tasks import RuntimeTaskState
from ..workers import DynamicStatsWorker, MetricComputeRequest, RoiApplyWorker


class MetricsRuntimeMixin:
    """Live metric computation and preview refresh helpers."""

    PREVIEW_FAST_MAX_DIM = 768

    @staticmethod
    def _dynamic_stats_mode_for_average_mode(mode: str) -> str:
        """Map UI average mode onto the dynamic metrics worker mode."""

        return "topk" if mode == "topk" else "none"

    @staticmethod
    def _average_mode_uses_roi(mode: str) -> bool:
        """Return whether one average mode depends on the selected ROI."""

        return mode in {"roi", "roi_topk"}

    @staticmethod
    def _dynamic_stats_task_id(job_id: int) -> str:
        """Return the runtime-task id for one dynamic metric job."""

        return f"dynamic_stats:{int(job_id)}"

    @staticmethod
    def _roi_apply_task_id(job_id: int) -> str:
        """Return the runtime-task id for one ROI apply job."""

        return f"roi_apply:{int(job_id)}"

    @staticmethod
    def _dynamic_task_label(requested: tuple[MetricFamily, ...]) -> str:
        """Return a compact label for requested dynamic metric families."""

        if requested == (MetricFamily.SATURATION,):
            return "Threshold update"
        if requested == (MetricFamily.TOPK,):
            return "Top-K compute"
        if MetricFamily.TOPK in requested:
            return "Top-K compute"
        if MetricFamily.BACKGROUND_APPLIED in requested:
            return "Metric compute"
        return "Metric compute"

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

    def _dynamic_metric_family_signature_hash(self, family: MetricFamily) -> str:
        """Return cache signature for one targeted dynamic metric family."""

        metrics = self.metrics_state
        background_payload = self._background_signature_payload()
        if family == MetricFamily.SATURATION:
            return saturation_metric_signature_hash(
                threshold_value=metrics.threshold_value,
                background_payload=background_payload,
            )
        if family == MetricFamily.TOPK:
            return topk_metric_signature_hash(
                avg_count_value=metrics.avg_count_value,
                background_payload=background_payload,
            )
        if family == MetricFamily.BACKGROUND_APPLIED:
            return background_metric_signature_hash(
                background_payload=background_payload,
            )
        raise ValueError(f"Unsupported dynamic metric family: {family!r}")

    def _dynamic_metric_family_kind(self, family: MetricFamily) -> str:
        """Return cache metric kind for one targeted dynamic metric family."""

        if family == MetricFamily.SATURATION:
            return SATURATION_METRIC_KIND
        if family == MetricFamily.TOPK:
            return TOPK_METRIC_KIND
        if family == MetricFamily.BACKGROUND_APPLIED:
            return BACKGROUND_METRIC_KIND
        raise ValueError(f"Unsupported dynamic metric family: {family!r}")

    def _roi_metric_signature_hash(
        self,
        mode_override: str | None = None,
    ) -> str | None:
        """Return cache signature for the current ROI settings."""

        roi_rect = self.metrics_state.roi_rect
        if roi_rect is None:
            return None
        mode = mode_override or self._current_average_mode()
        return roi_metric_signature_hash(
            roi_rect=roi_rect,
            topk_count=(
                self.metrics_state.avg_count_value
                if mode == "roi_topk"
                else None
            ),
            background_payload=self._background_signature_payload(),
        )

    def _cached_dynamic_payloads(
        self,
        requested_families: tuple[MetricFamily, ...],
    ) -> tuple[
        dict[str, object],
        dict[MetricFamily, dict[str, dict[str, object]]],
        dict[MetricFamily, str],
    ]:
        """Load cached payloads for targeted dynamic metric families."""

        cache = getattr(self, "metrics_cache", None)
        dataset = self.dataset_state
        identities = self._metric_cache_identities(
            [Path(path) for path in dataset.paths],
            dataset_root=dataset.dataset_root,
        )
        signatures = {
            family: self._dynamic_metric_family_signature_hash(family)
            for family in requested_families
        }
        if cache is None or not identities:
            return (identities, {}, signatures)
        cached_by_family: dict[MetricFamily, dict[str, dict[str, object]]] = {}
        for family, signature_hash in signatures.items():
            cached_by_family[family] = cache.fetch_entries(
                identities.values(),
                metric_kind=self._dynamic_metric_family_kind(family),
                signature_hash=signature_hash,
            )
        return (identities, cached_by_family, signatures)

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
        requested_families: tuple[MetricFamily, ...],
        cached_payloads: dict[MetricFamily, dict[str, dict[str, object]]],
    ) -> tuple[
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
        list[int],
    ]:
        """Build partially cached targeted metric arrays and return miss indices."""

        dataset = self.dataset_state
        metrics = self.metrics_state
        n = dataset.path_count()
        requested = set(requested_families)
        missing_indices: set[int] = set()

        sat_counts = (
            np.asarray(metrics.sat_counts, dtype=np.int64).copy()
            if metrics.sat_counts is not None and len(metrics.sat_counts) == n
            else np.zeros(n, dtype=np.int64)
        ) if MetricFamily.SATURATION in requested else None
        avg_topk = (
            np.asarray(metrics.avg_maxs, dtype=np.float64).copy()
            if metrics.avg_maxs is not None and len(metrics.avg_maxs) == n
            else np.full(n, np.nan, dtype=np.float64)
        ) if MetricFamily.TOPK in requested else None
        avg_topk_std = (
            np.asarray(metrics.avg_maxs_std, dtype=np.float64).copy()
            if metrics.avg_maxs_std is not None and len(metrics.avg_maxs_std) == n
            else np.full(n, np.nan, dtype=np.float64)
        ) if MetricFamily.TOPK in requested else None
        avg_topk_sem = (
            np.asarray(metrics.avg_maxs_sem, dtype=np.float64).copy()
            if metrics.avg_maxs_sem is not None and len(metrics.avg_maxs_sem) == n
            else np.full(n, np.nan, dtype=np.float64)
        ) if MetricFamily.TOPK in requested else None
        max_pixels = (
            np.asarray(metrics.maxs, dtype=np.int64).copy()
            if metrics.maxs is not None and len(metrics.maxs) == n
            else np.zeros(n, dtype=np.int64)
        ) if MetricFamily.BACKGROUND_APPLIED in requested else None
        min_non_zero = (
            np.asarray(metrics.min_non_zero, dtype=np.int64).copy()
            if metrics.min_non_zero is not None and len(metrics.min_non_zero) == n
            else np.zeros(n, dtype=np.int64)
        ) if MetricFamily.BACKGROUND_APPLIED in requested else None
        bg_applied = (
            np.asarray(metrics.bg_applied_mask, dtype=bool).copy()
            if metrics.bg_applied_mask is not None and len(metrics.bg_applied_mask) == n
            else np.zeros(n, dtype=bool)
        ) if MetricFamily.BACKGROUND_APPLIED in requested else None

        for index, path in enumerate(dataset.paths):
            for family in requested_families:
                payload = cached_payloads.get(family, {}).get(path)
                if payload is None:
                    missing_indices.add(index)
                    continue
                if family == MetricFamily.SATURATION and sat_counts is not None:
                    sat_counts[index] = int(payload.get("sat_count", 0))
                elif family == MetricFamily.TOPK and avg_topk is not None:
                    avg_topk[index] = float(payload.get("avg_topk", np.nan))
                    if avg_topk_std is not None:
                        avg_topk_std[index] = float(
                            payload.get("avg_topk_std", np.nan),
                        )
                    if avg_topk_sem is not None:
                        avg_topk_sem[index] = float(
                            payload.get("avg_topk_sem", np.nan),
                        )
                elif (
                    family == MetricFamily.BACKGROUND_APPLIED
                    and max_pixels is not None
                    and min_non_zero is not None
                    and bg_applied is not None
                ):
                    max_pixels[index] = int(payload.get("max_pixel", 0))
                    min_non_zero[index] = int(payload.get("min_non_zero", 0))
                    bg_applied[index] = bool(payload.get("bg_applied", False))

        return (
            sat_counts,
            avg_topk,
            avg_topk_std,
            avg_topk_sem,
            max_pixels,
            min_non_zero,
            bg_applied,
            sorted(missing_indices),
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
        signatures = pending["signatures"]
        requested_families = tuple(pending["requested_families"])
        for family in requested_families:
            writes: list[MetricCacheWrite] = []
            for index in source_indices:
                path = self.dataset_state.paths[index]
                identity = identities.get(path)
                if identity is None:
                    continue
                if family == MetricFamily.SATURATION and result.sat_counts is not None:
                    payload = {"sat_count": int(result.sat_counts[index])}
                elif family == MetricFamily.TOPK and result.avg_topk is not None:
                    payload = {"avg_topk": float(result.avg_topk[index])}
                    if result.avg_topk_std is not None:
                        payload["avg_topk_std"] = float(result.avg_topk_std[index])
                    if result.avg_topk_sem is not None:
                        payload["avg_topk_sem"] = float(result.avg_topk_sem[index])
                elif (
                    family == MetricFamily.BACKGROUND_APPLIED
                    and result.max_pixels is not None
                    and result.min_non_zero is not None
                    and result.bg_applied_mask is not None
                ):
                    payload = {
                        "max_pixel": int(result.max_pixels[index]),
                        "min_non_zero": int(result.min_non_zero[index]),
                        "bg_applied": bool(result.bg_applied_mask[index]),
                    }
                else:
                    continue
                writes.append(MetricCacheWrite(identity=identity, payload=payload))
            cache.store_entries(
                writes,
                metric_kind=self._dynamic_metric_family_kind(family),
                signature_hash=str(signatures[family]),
            )

    def _prefill_roi_metric_arrays(
        self,
        cached_payloads: dict[str, dict[str, object]],
        *,
        include_topk: bool,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
        list[int],
    ]:
        """Build partially cached ROI arrays and return miss indices."""

        dataset = self.dataset_state
        n = dataset.path_count()
        maxs = np.full(n, np.nan, dtype=np.float64)
        sums = np.full(n, np.nan, dtype=np.float64)
        means = np.full(n, np.nan, dtype=np.float64)
        stds = np.full(n, np.nan, dtype=np.float64)
        sems = np.full(n, np.nan, dtype=np.float64)
        topk_means = np.full(n, np.nan, dtype=np.float64) if include_topk else None
        topk_stds = np.full(n, np.nan, dtype=np.float64) if include_topk else None
        topk_sems = np.full(n, np.nan, dtype=np.float64) if include_topk else None
        hit_indices: set[int] = set()
        for index, path in enumerate(dataset.paths):
            payload = cached_payloads.get(path)
            if payload is None:
                continue
            hit_indices.add(index)
            maxs[index] = float(payload.get("max", np.nan))
            sums[index] = float(payload.get("sum", np.nan))
            means[index] = float(payload.get("mean", np.nan))
            stds[index] = float(payload.get("std", np.nan))
            sems[index] = float(payload.get("sem", np.nan))
            if topk_means is not None:
                topk_means[index] = float(payload.get("topk_mean", np.nan))
            if topk_stds is not None:
                topk_stds[index] = float(payload.get("topk_std", np.nan))
            if topk_sems is not None:
                topk_sems[index] = float(payload.get("topk_sem", np.nan))
        missing_indices = [
            index
            for index in range(n)
            if index not in hit_indices
        ]
        return (
            maxs,
            sums,
            means,
            stds,
            sems,
            topk_means,
            topk_stds,
            topk_sems,
            missing_indices,
        )

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
                        "sum": float(result.sums[index]),
                        "mean": float(result.means[index]),
                        "std": float(result.stds[index]),
                        "sem": float(result.sems[index]),
                        **(
                            {
                                "topk_mean": float(result.topk_means[index]),
                                "topk_std": float(result.topk_stds[index]),
                                "topk_sem": float(result.topk_sems[index]),
                            }
                            if (
                                result.topk_means is not None
                                and result.topk_stds is not None
                                and result.topk_sems is not None
                            )
                            else {}
                        ),
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
        worker = self._stats_worker
        job_id = metrics.stats_job_id
        self._dynamic_cache_pending = None
        metrics.cancel_stats_job()
        self._stop_threshold_summary_animation()
        if hasattr(self, "_finish_runtime_task"):
            self._finish_runtime_task(
                self._dynamic_stats_task_id(job_id),
                state=RuntimeTaskState.CANCELLED,
                status="Cancelled",
            )
        if thread is None:
            return
        if worker is not None:
            try:
                worker.finished.disconnect(self._on_dynamic_stats_finished)
            except Exception:
                pass
            try:
                worker.failed.disconnect(self._on_dynamic_stats_failed)
            except Exception:
                pass
        if not thread.isRunning():
            if worker is not None:
                self._on_stats_thread_finished(thread, worker)
            return
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
        mode_override: str | None = None,
        requested_families: tuple[MetricFamily | str, ...] | None = None,
        reason: RefreshReason | str | None = None,
    ) -> None:
        """Start asynchronous dynamic metric computation for the dataset."""
        normalized_reason = ensure_compute_reason(
            reason,
            operation="dynamic metric computation",
        )
        if not self._has_loaded_data():
            return

        metrics = self.metrics_state
        self._cancel_stats_job()
        mode = self._dynamic_stats_mode_for_average_mode(
            mode_override or self._current_average_mode(),
        )
        if requested_families is None:
            if update_kind == "threshold_only":
                requested = (MetricFamily.SATURATION,)
            elif mode == "topk":
                requested = (
                    MetricFamily.SATURATION,
                    MetricFamily.TOPK,
                    MetricFamily.BACKGROUND_APPLIED,
                )
            else:
                requested = (MetricFamily.SATURATION, MetricFamily.BACKGROUND_APPLIED)
        else:
            requested = metrics.normalize_metric_families(requested_families)
        requested = tuple(
            family
            for family in requested
            if family in {
                MetricFamily.SATURATION,
                MetricFamily.TOPK,
                MetricFamily.BACKGROUND_APPLIED,
            }
        )
        if not requested:
            return
        job_id = metrics.begin_stats_job(
            update_kind=update_kind,
            refresh_analysis=refresh_analysis,
            requested_families=requested,
            reason=normalized_reason,
        )
        log_refresh_event(
            "dynamic_stats.start",
            reason=normalized_reason,
            host=self,
            family=",".join(family.value for family in requested),
            update_kind=update_kind,
        )
        if hasattr(self, "_begin_runtime_task"):
            self._begin_runtime_task(
                self._dynamic_stats_task_id(job_id),
                self._dynamic_task_label(requested),
                target=f"{self.dataset_state.path_count()} images",
                status="Checking cache",
                progress_done=None,
                progress_total=None,
            )
        dataset = self.dataset_state
        identities, cached_payloads, signatures = self._cached_dynamic_payloads(
            requested,
        )
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
            requested_families=requested,
            cached_payloads=cached_payloads,
        )

        if not missing_indices:
            self._dynamic_cache_pending = None
            if hasattr(self, "_update_runtime_task"):
                self._update_runtime_task(
                    self._dynamic_stats_task_id(job_id),
                    status="Loaded from cache",
                )
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
                    requested_families=requested,
                ),
            )
            return

        thread = QThread(self)
        request = MetricComputeRequest(
            job_id=job_id,
            paths=tuple(dataset.paths[index] for index in missing_indices),
            source_indices=tuple(missing_indices),
            result_length=dataset.path_count(),
            requested_families=requested,
            threshold_value=metrics.threshold_value,
            avg_count_value=metrics.avg_count_value,
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
            family_signatures={family.value: signatures[family] for family in requested},
        )
        worker = DynamicStatsWorker.from_request(request)
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
            "identities": identities,
            "source_indices": missing_indices,
            "requested_families": requested,
            "signatures": signatures,
        }
        if requested == (MetricFamily.SATURATION,):
            self._start_threshold_summary_animation()
        else:
            self._stop_threshold_summary_animation()
        if hasattr(self, "_update_runtime_task"):
            self._update_runtime_task(
                self._dynamic_stats_task_id(job_id),
                status=f"Computing {len(missing_indices)} missing",
            )
        thread.start()

    def _on_dynamic_stats_finished(self, result: object) -> None:
        """Apply completed dynamic stats results to the active dataset."""
        if not isinstance(result, DynamicStatsResult):
            return
        metrics = self.metrics_state
        if result.job_id != metrics.stats_job_id:
            return

        refresh_reason = metrics.stats_refresh_reason
        refresh_analysis = metrics.stats_refresh_analysis
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
        if hasattr(self, "_finish_runtime_task"):
            self._finish_runtime_task(
                self._dynamic_stats_task_id(result.job_id),
                state=RuntimeTaskState.SUCCEEDED,
                status="Complete",
            )
        self._stop_threshold_summary_animation()
        self._refresh_table(update_analysis=refresh_analysis, reason=refresh_reason)
        self._update_background_status_label()
        self._update_average_controls()
        self._set_status()

    def _on_dynamic_stats_failed(self, job_id: int, message: str) -> None:
        """Handle dynamic stats worker failure."""
        metrics = self.metrics_state
        if job_id != metrics.stats_job_id:
            return
        requested = tuple(
            (self._dynamic_cache_pending or {}).get("requested_families", ()),
        )
        self._dynamic_cache_pending = None
        metrics.finish_stats_job()
        if hasattr(self, "_finish_runtime_task"):
            self._finish_runtime_task(
                self._dynamic_stats_task_id(job_id),
                state=RuntimeTaskState.FAILED,
                status=message or "Metric computation failed",
            )
        if not requested:
            requested = (MetricFamily.SATURATION,)
        for family in requested:
            metrics.set_metric_family_state(
                family,
                MetricFamilyState.FAILED,
                message or "Unknown error",
            )
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
        job_id = metrics.roi_apply_job_id
        metrics.cancel_roi_apply()
        if hasattr(self, "_finish_runtime_task"):
            self._finish_runtime_task(
                self._roi_apply_task_id(job_id),
                state=RuntimeTaskState.CANCELLED,
                status="Cancelled",
            )
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

    def _start_roi_apply_job(self, mode_override: str | None = None) -> None:
        """Start asynchronous ROI application across the full dataset."""
        return self._start_roi_apply_job_for_reason(
            mode_override=mode_override,
            reason=RefreshReason.APPLY_ROI,
        )

    def _start_roi_apply_job_for_reason(
        self,
        mode_override: str | None = None,
        *,
        reason: RefreshReason | str | None,
    ) -> None:
        """Start asynchronous ROI application with an explicit compute reason."""
        normalized_reason = ensure_compute_reason(
            reason,
            operation="ROI metric computation",
        )
        metrics = self.metrics_state
        mode = mode_override or self._current_average_mode()
        if (
            not self._has_loaded_data()
            or metrics.roi_rect is None
            or not self._average_mode_uses_roi(mode)
        ):
            return
        if (
            self._roi_apply_thread is not None
            and self._roi_apply_thread.isRunning()
        ):
            self._set_status("ROI apply already running")
            return

        dataset = self.dataset_state
        include_topk = mode == "roi_topk"
        requested_roi_families = (
            (MetricFamily.ROI, MetricFamily.ROI_TOPK)
            if include_topk
            else (MetricFamily.ROI,)
        )
        job_id = metrics.begin_roi_apply(
            dataset.path_count(),
            requested_families=requested_roi_families,
            reason=normalized_reason,
        )
        log_refresh_event(
            "roi_apply.start",
            reason=normalized_reason,
            host=self,
            family=",".join(family.value for family in requested_roi_families),
            mode=mode,
        )
        if hasattr(self, "_begin_runtime_task"):
            self._begin_runtime_task(
                self._roi_apply_task_id(job_id),
                "ROI apply",
                target=f"{dataset.path_count()} images",
                status="Checking cache",
                progress_done=0,
                progress_total=dataset.path_count(),
            )
        metrics.set_metric_family_state(
            MetricFamily.ROI,
            MetricFamilyState.COMPUTING,
            reason=normalized_reason,
        )
        if include_topk:
            metrics.set_metric_family_state(
                MetricFamily.ROI_TOPK,
                MetricFamilyState.COMPUTING,
                reason=normalized_reason,
            )
        else:
            metrics.set_metric_family_state(
                MetricFamily.ROI_TOPK,
                (
                    MetricFamilyState.PENDING_INPUTS
                    if metrics.topk_inputs_pending()
                    else MetricFamilyState.NOT_REQUESTED
                ),
            )
        signature_hash = self._roi_metric_signature_hash(mode_override=mode)
        if signature_hash is None:
            if hasattr(self, "_finish_runtime_task"):
                self._finish_runtime_task(
                    self._roi_apply_task_id(job_id),
                    state=RuntimeTaskState.FAILED,
                    status="Missing ROI",
                )
            self._finish_roi_apply_ui()
            return
        identities, cached_payloads = self._cached_roi_payloads(signature_hash)
        (
            existing_maxs,
            existing_sums,
            existing_means,
            existing_stds,
            existing_sems,
            existing_topk_means,
            existing_topk_stds,
            existing_topk_sems,
            missing_indices,
        ) = (
            self._prefill_roi_metric_arrays(
                cached_payloads,
                include_topk=include_topk,
            )
        )
        if not missing_indices:
            self._roi_cache_pending = None
            if hasattr(self, "_update_runtime_task"):
                self._update_runtime_task(
                    self._roi_apply_task_id(job_id),
                    status="Loaded from cache",
                    progress_done=dataset.path_count(),
                    progress_total=dataset.path_count(),
                )
            self._on_roi_apply_finished(
                RoiApplyResult(
                    job_id=job_id,
                    maxs=existing_maxs,
                    sums=existing_sums,
                    means=existing_means,
                    stds=existing_stds,
                    sems=existing_sems,
                    valid_count=int(np.count_nonzero(np.isfinite(existing_means))),
                    topk_means=existing_topk_means,
                    topk_stds=existing_topk_stds,
                    topk_sems=existing_topk_sems,
                    requested_families=requested_roi_families,
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
            topk_count=metrics.avg_count_value if include_topk else None,
            requested_families=requested_roi_families,
            existing_maxs=existing_maxs,
            existing_sums=existing_sums,
            existing_means=existing_means,
            existing_stds=existing_stds,
            existing_sems=existing_sems,
            existing_topk_means=existing_topk_means,
            existing_topk_stds=existing_topk_stds,
            existing_topk_sems=existing_topk_sems,
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
            "mode": mode,
            "requested_families": requested_roi_families,
        }
        self.roi_apply_progress.setRange(0, max(1, metrics.roi_apply_total))
        self.roi_apply_progress.setValue(0)
        self.roi_apply_progress.setFormat("ROI apply %v/%m")
        self.roi_apply_progress.setVisible(True)
        self._update_average_controls()
        self._set_status("Applying ROI to all images...")
        if hasattr(self, "_update_runtime_task"):
            self._update_runtime_task(
                self._roi_apply_task_id(job_id),
                status=f"Computing {len(missing_indices)} missing",
                progress_done=0,
                progress_total=dataset.path_count(),
            )
        thread.start()

    def _on_roi_apply_progress(self, done: int, total: int) -> None:
        """Update ROI apply progress indicator."""
        metrics = self.metrics_state
        if not metrics.is_roi_applying:
            return
        metrics.update_roi_apply_progress(done, total)
        if hasattr(self, "_update_runtime_task"):
            self._update_runtime_task(
                self._roi_apply_task_id(metrics.roi_apply_job_id),
                status="Applying ROI",
                progress_done=metrics.roi_apply_done,
                progress_total=metrics.roi_apply_total,
            )
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
        refresh_reason = self.metrics_state.roi_apply_reason
        self._finish_roi_apply_ui()
        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures(
                list(result.failures),
                replace_stage="roi",
            )
        self._store_cached_roi_metrics(result)

        means = np.asarray(result.means, dtype=np.float64)
        if result.valid_count <= 0 or not np.any(np.isfinite(means)):
            if hasattr(self, "_finish_runtime_task"):
                self._finish_runtime_task(
                    self._roi_apply_task_id(result.job_id),
                    state=RuntimeTaskState.FAILED,
                    status="Invalid ROI",
                )
            self._show_error(
                "Invalid ROI",
                "Draw a valid ROI before applying.",
            )
            self._set_status("ROI apply failed")
            return

        self.metrics_state.apply_roi_result(result)
        if hasattr(self, "_finish_runtime_task"):
            self._finish_runtime_task(
                self._roi_apply_task_id(result.job_id),
                state=RuntimeTaskState.SUCCEEDED,
                status="Complete",
            )
        self._refresh_table(reason=refresh_reason)
        self._refresh_workspace_document_dirty_state()
        self._set_status("ROI applied to all images")

    def _on_roi_apply_cancelled(self, job_id: int) -> None:
        """Handle ROI apply cancellation."""
        if job_id != self.metrics_state.roi_apply_job_id:
            return
        self._roi_cache_pending = None
        self._finish_roi_apply_ui()
        if hasattr(self, "_finish_runtime_task"):
            self._finish_runtime_task(
                self._roi_apply_task_id(job_id),
                state=RuntimeTaskState.CANCELLED,
                status="Cancelled",
            )
        self._set_status("ROI apply cancelled")

    def _on_roi_apply_failed(self, job_id: int, message: str) -> None:
        """Handle ROI apply worker failure."""
        if job_id != self.metrics_state.roi_apply_job_id:
            return
        mode = str((self._roi_cache_pending or {}).get("mode", "none"))
        self._roi_cache_pending = None
        self._finish_roi_apply_ui()
        if hasattr(self, "_finish_runtime_task"):
            self._finish_runtime_task(
                self._roi_apply_task_id(job_id),
                state=RuntimeTaskState.FAILED,
                status=message or "ROI apply failed",
            )
        self.metrics_state.set_metric_family_state(
            MetricFamily.ROI,
            MetricFamilyState.FAILED,
            message or "Unknown error",
        )
        if mode == "roi_topk":
            self.metrics_state.set_metric_family_state(
                MetricFamily.ROI_TOPK,
                MetricFamilyState.FAILED,
                message or "Unknown error",
            )
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
        elif mode == "roi_topk":
            mean_header = "ROI Top-K"
            std_header = "ROI Top-K Std"
            sem_header = "ROI Top-K Std Err"
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

    def _apply_live_update(
        self,
        *,
        reason: RefreshReason | str | None,
    ) -> None:
        """Refresh only background-sensitive metric families already in use."""
        normalized_reason = ensure_compute_reason(
            reason,
            operation="live metric update",
        )
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
        count = self.dataset_state.path_count()
        mode = self._current_average_mode()
        metrics.prepare_for_live_update(path_count=count, mode=mode)

        self._refresh_table(update_analysis=False)
        requested = [MetricFamily.BACKGROUND_APPLIED]
        if (
            metrics.sat_counts is not None
            or metrics.metric_family_state(MetricFamily.SATURATION)
            in {MetricFamilyState.READY, MetricFamilyState.STALE}
        ):
            requested.append(MetricFamily.SATURATION)
        if (
            metrics.avg_maxs is not None
            or metrics.metric_family_state(MetricFamily.TOPK)
            in {MetricFamilyState.READY, MetricFamilyState.STALE}
        ):
            requested.append(MetricFamily.TOPK)
        self._start_dynamic_stats_job(
            update_kind="full",
            refresh_analysis=True,
            requested_families=tuple(requested),
            reason=normalized_reason,
        )
        if metrics.roi_applied_to_all and metrics.roi_rect is not None:
            roi_mode = "roi_topk" if metrics.roi_topk_means is not None else "roi"
            self._start_roi_apply_job_for_reason(
                mode_override=roi_mode,
                reason=normalized_reason,
            )
        self._update_average_controls()
        self._refresh_workspace_document_dirty_state()
        self._set_status()

    def _apply_scan_metric_setup_after_scan(
        self,
        *,
        reason: RefreshReason | str = RefreshReason.SCAN_LOAD,
    ) -> None:
        """Run metric jobs requested by the Data-page scan setup."""
        normalized_reason = ensure_compute_reason(
            reason,
            operation="scan metric setup",
        )

        if not self._has_loaded_data():
            return

        metrics = self.metrics_state
        families = set(metrics.scan_metric_families())
        path_count = self.dataset_state.path_count()
        started_job = False

        if MetricFamily.TOPK in families:
            metrics.prepare_for_live_update(path_count=path_count, mode="topk")
            self._refresh_table(update_analysis=False)
            self._start_dynamic_stats_job(
                update_kind="full",
                refresh_analysis=True,
                mode_override="topk",
                requested_families=(
                    MetricFamily.SATURATION,
                    MetricFamily.TOPK,
                ),
                reason=normalized_reason,
            )
            started_job = True
        elif MetricFamily.SATURATION in families:
            self._start_dynamic_stats_job(
                update_kind="threshold_only",
                refresh_analysis=True,
                mode_override="none",
                requested_families=(MetricFamily.SATURATION,),
                reason=normalized_reason,
            )
            started_job = True

        if MetricFamily.LOW_SIGNAL in families:
            if metrics.low_signal_inputs_pending():
                metrics.set_metric_family_state(
                    MetricFamily.LOW_SIGNAL,
                    MetricFamilyState.PENDING_INPUTS,
                )
            else:
                metrics.set_metric_family_state(
                    MetricFamily.LOW_SIGNAL,
                    (
                        MetricFamilyState.READY
                        if metrics.low_signal_threshold_value > 0.0
                        else MetricFamilyState.NOT_REQUESTED
                    ),
                )
            self._refresh_table(update_analysis=False)

        roi_requested = (
            MetricFamily.ROI in families or MetricFamily.ROI_TOPK in families
        )
        if roi_requested:
            if metrics.roi_rect is None:
                metrics.set_metric_family_state(
                    MetricFamily.ROI,
                    MetricFamilyState.PENDING_INPUTS,
                    "Select an ROI before scan-time ROI metrics can run.",
                )
                if MetricFamily.ROI_TOPK in families:
                    metrics.set_metric_family_state(
                        MetricFamily.ROI_TOPK,
                        MetricFamilyState.PENDING_INPUTS,
                        "Select an ROI before scan-time ROI Top-K metrics can run.",
                    )
            else:
                self._start_roi_apply_job_for_reason(
                    mode_override=(
                        "roi_topk"
                        if MetricFamily.ROI_TOPK in families
                        else "roi"
                    ),
                    reason=normalized_reason,
                )
                started_job = True

        if not started_job:
            self._update_average_controls()
            self._set_status()

    def _apply_topk_update(self) -> None:
        """Apply the pending Top-K count and recompute only Top-K dependents."""
        if self._is_dataset_load_running():
            self._set_status("Wait for dataset loading to finish")
            return
        metrics = self.metrics_state
        if hasattr(self, "avg_spin"):
            metrics.set_pending_avg_count_value(self.avg_spin.value())
        changed = metrics.apply_pending_avg_count_value()
        mode = self._current_average_mode()

        if not self._has_loaded_data():
            self._update_average_controls()
            self._refresh_workspace_document_dirty_state()
            self._set_status()
            return

        if mode == "topk":
            metrics.prepare_for_live_update(
                path_count=self.dataset_state.path_count(),
                mode=mode,
            )
            self._refresh_table(update_analysis=False)
            self._start_dynamic_stats_job(
                update_kind="full",
                refresh_analysis=True,
                requested_families=(MetricFamily.TOPK,),
                reason=RefreshReason.APPLY_TOPK,
            )
            self._set_status("Updating Top-K metrics")
        elif mode == "roi_topk" and metrics.roi_rect is not None:
            if metrics.roi_applied_to_all:
                self._start_roi_apply_job_for_reason(
                    reason=RefreshReason.APPLY_TOPK,
                )
            else:
                self._apply_roi_rect_to_current_dataset(
                    metrics.roi_rect,
                    status_message=(
                        "Updated ROI Top-K metrics"
                        if changed
                        else None
                    ),
                )
        else:
            self._refresh_table(update_analysis=False)
            self._set_status()
        self._update_average_controls()
        self._refresh_workspace_document_dirty_state()

    def _apply_threshold_update(self) -> None:
        """Refresh saturation display without rebuilding unrelated metrics."""
        if self._is_dataset_load_running():
            self._set_status("Wait for dataset loading to finish")
            return
        metrics = self.metrics_state
        if hasattr(self, "threshold_spin"):
            metrics.set_pending_threshold_value(self.threshold_spin.value())
        threshold_changed = metrics.apply_pending_threshold_value()

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
            requested_families=(MetricFamily.SATURATION,),
            reason=RefreshReason.APPLY_THRESHOLD,
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
        if hasattr(self, "low_signal_spin"):
            metrics.set_pending_low_signal_threshold_value(
                self.low_signal_spin.value(),
            )
        metrics.apply_pending_low_signal_threshold_value()

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

    def _on_threshold_control_value_changed(self, value: float) -> None:
        """Record a pending saturation threshold edit without computing."""

        self.metrics_state.set_pending_threshold_value(value)
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()
        if hasattr(self, "_schedule_workspace_document_dirty_state_refresh"):
            self._schedule_workspace_document_dirty_state_refresh()
        else:
            self._refresh_workspace_document_dirty_state()

    def _on_low_signal_control_value_changed(self, value: float) -> None:
        """Record a pending low-signal threshold edit without computing."""

        self.metrics_state.set_pending_low_signal_threshold_value(value)
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()
        if hasattr(self, "_schedule_workspace_document_dirty_state_refresh"):
            self._schedule_workspace_document_dirty_state_refresh()
        else:
            self._refresh_workspace_document_dirty_state()

    def _on_topk_control_value_changed(self, value: int) -> None:
        """Record a pending Top-K edit without computing."""

        self.metrics_state.set_pending_avg_count_value(value)
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()
        if hasattr(self, "_schedule_workspace_document_dirty_state_refresh"):
            self._schedule_workspace_document_dirty_state_refresh()
        else:
            self._refresh_workspace_document_dirty_state()

    def _refresh_table(
        self,
        *,
        update_analysis: bool = True,
        reason: RefreshReason | str = RefreshReason.VIEW_REBIND,
    ) -> None:
        """Refresh the measure table and linked preview state."""
        if (
            not self._has_loaded_data()
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
                self._invalidate_analysis_context(
                    refresh_visible_plugin=True,
                    reason=reason,
                )
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
        elapsed_time_s = self._metadata_elapsed_time_s_array()
        if (
            streaming_update
            and self._average_mode_uses_roi(mode)
            and not self.metrics_state.roi_applied_to_all
        ):
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
            roi_sums=metrics.roi_sums,
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
            avg_roi_topk=metrics.roi_topk_means if mode == "roi_topk" else None,
            avg_roi_topk_std=metrics.roi_topk_stds if mode == "roi_topk" else None,
            avg_roi_topk_sem=metrics.roi_topk_sems if mode == "roi_topk" else None,
            dn_per_ms=metrics.dn_per_ms_values,
            elapsed_time_s=elapsed_time_s,
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
                self._invalidate_analysis_context(
                    refresh_visible_plugin=True,
                    reason=reason,
                )
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
            self._invalidate_analysis_context(
                refresh_visible_plugin=True,
                reason=reason,
            )
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
            f"max={int(metrics.maxs[idx])}"
        )
        if metrics.sat_counts is not None and idx < len(metrics.sat_counts):
            info += f" | saturated={int(metrics.sat_counts[idx])}"
        else:
            info += " | saturated=not computed"
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
        elif self._average_mode_uses_roi(mode):
            if metrics.roi_rect is not None:
                x0, y0, x1, y1 = metrics.roi_rect
                info += f" | roi=({x0},{y0})-({x1},{y1})"
            if mode == "roi_topk":
                roi_value = (
                    metrics.roi_topk_means[idx]
                    if metrics.roi_topk_means is not None
                    and idx < len(metrics.roi_topk_means)
                    else np.nan
                )
                roi_std = (
                    metrics.roi_topk_stds[idx]
                    if metrics.roi_topk_stds is not None
                    and idx < len(metrics.roi_topk_stds)
                    else np.nan
                )
                roi_sem = (
                    metrics.roi_topk_sems[idx]
                    if metrics.roi_topk_sems is not None
                    and idx < len(metrics.roi_topk_sems)
                    else np.nan
                )
            else:
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
    ) -> dict[str, object]:
        """Compute ROI stats for one image index."""
        dataset = self.dataset_state
        roi_rect = self.metrics_state.roi_rect
        if not self._has_loaded_data() or roi_rect is None:
            return {}
        if not (0 <= index < dataset.path_count()):
            return {}

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
                    return {
                        "roi_max": float(cached_payload.get("max", np.nan)),
                        "roi_sum": float(cached_payload.get("sum", np.nan)),
                        "roi_mean": float(cached_payload.get("mean", np.nan)),
                        "roi_std": float(cached_payload.get("std", np.nan)),
                        "roi_sem": float(cached_payload.get("sem", np.nan)),
                        "roi_topk_mean": float(
                            cached_payload.get("topk_mean", np.nan),
                        ),
                        "roi_topk_std": float(
                            cached_payload.get("topk_std", np.nan),
                        ),
                        "roi_topk_sem": float(
                            cached_payload.get("topk_sem", np.nan),
                        ),
                    }

        image = self._get_image_by_index(index)
        if image is None:
            return {}

        include_topk = self._current_average_mode() == "roi_topk"
        roi_result = native_backend.compute_roi_metrics_full(
            image,
            roi_rect=roi_rect,
            topk_count=self.metrics_state.avg_count_value if include_topk else None,
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
                            "max": float(roi_result["roi_max"]),
                            "sum": float(roi_result["roi_sum"]),
                            "mean": float(roi_result["roi_mean"]),
                            "std": float(roi_result["roi_std"]),
                            "sem": float(roi_result["roi_sem"]),
                            **(
                                {
                                    "topk_mean": float(roi_result["roi_topk_mean"]),
                                    "topk_std": float(roi_result["roi_topk_std"]),
                                    "topk_sem": float(roi_result["roi_topk_sem"]),
                                }
                                if include_topk
                                else {}
                            ),
                        },
                    ),
                ],
                metric_kind=ROI_METRIC_KIND,
                signature_hash=signature_hash,
            )
        return roi_result

    def _on_average_mode_changed(self) -> None:
        """Respond to average-mode UI changes."""
        self._update_average_controls()
        self._update_table_columns()
        self._refresh_table(update_analysis=False)
        self._refresh_workspace_document_dirty_state()
        self._set_status()

    def _on_roi_selected(self, rect: object) -> None:
        """Store current ROI selection and refresh ROI metrics."""
        if not self._has_loaded_data() or self.dataset_state.selected_index is None:
            return
        if not self._average_mode_uses_roi(self._current_average_mode()):
            return
        self._apply_roi_rect_to_current_dataset(rect, status_message=None)

    def _apply_roi_to_all_images(self) -> None:
        """Start ROI propagation across all loaded images."""
        if not self._has_loaded_data() or self.metrics_state.roi_rect is None:
            return
        if not self._average_mode_uses_roi(self._current_average_mode()):
            return
        self._start_roi_apply_job_for_reason(reason=RefreshReason.APPLY_ROI)
