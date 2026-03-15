"""ROI persistence, export, dialog, and lifecycle helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from stylesheets import DARK_THEME, LIGHT_THEME
from ..payload_utils import read_json_dict, write_json_dict
from ..processing_failures import (
    ProcessingFailure,
    format_processing_failure_details,
    merge_processing_failures,
    summarize_processing_failures,
)
from ..window_drag import configure_secondary_window


class WindowActionsMixin:
    """Window-level actions that do not belong to a single page builder."""

    def _build_processing_failure_banner(self, page_label: str) -> qtw.QWidget:
        """Build a compact warning banner for aggregated processing issues."""
        banner = qtw.QFrame()
        banner.setObjectName("SubtlePanel")
        banner.setVisible(False)

        layout = qtw.QHBoxLayout(banner)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = qtw.QLabel("Processing Issues")
        title.setObjectName("SectionTitle")
        layout.addWidget(title, 0, Qt.AlignTop)

        label = qtw.QLabel("")
        label.setObjectName("MutedLabel")
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        details_button = qtw.QPushButton("Show Details...")
        details_button.setToolTip(
            f"Show aggregated processing failures for the {page_label} page.",
        )
        details_button.clicked.connect(self._show_processing_failures_dialog)
        layout.addWidget(details_button, 0, Qt.AlignTop)

        self._processing_failure_banners.append(banner)
        self._processing_failure_banner_labels.append(label)
        self._processing_failure_banner_layouts.append(layout)
        return banner

    def _apply_processing_banner_density(self, tokens) -> None:
        """Apply density spacing to processing-failure banners."""

        for layout in getattr(self, "_processing_failure_banner_layouts", []):
            if hasattr(self, "_set_uniform_layout_margins"):
                self._set_uniform_layout_margins(
                    layout,
                    tokens.panel_margin_h,
                    tokens.panel_margin_v,
                )
            layout.setSpacing(tokens.panel_spacing)

    def _clear_processing_failures(
        self,
        *,
        stage: str | None = None,
    ) -> None:
        """Clear all recorded processing failures or one failure stage."""
        normalized_stage = str(stage or "").strip().lower() or None
        if normalized_stage is None:
            self._processing_failures = []
        else:
            self._processing_failures = [
                failure
                for failure in self._processing_failures
                if failure.stage != normalized_stage
            ]
        self._update_processing_failure_ui()

    def _record_processing_failures(
        self,
        failures: list[ProcessingFailure] | tuple[ProcessingFailure, ...],
        *,
        replace_stage: str | None = None,
    ) -> None:
        """Merge a new batch of processing failures into the current dataset state."""
        self._processing_failures = merge_processing_failures(
            self._processing_failures,
            failures,
            replace_stage=replace_stage,
        )
        self._update_processing_failure_ui()

    def _processing_failure_count(self) -> int:
        """Return current aggregated processing-failure count."""
        return len(self._processing_failures)

    def _processing_failure_summary_text(self) -> str:
        """Return compact summary text for headers, banners, and status bar."""
        count = self._processing_failure_count()
        if count <= 0:
            return "No processing issues."
        summary = summarize_processing_failures(self._processing_failures)
        return f"{count} processing issue(s): {summary}."

    def _update_processing_failure_ui(self) -> None:
        """Refresh banner visibility and dependent header/status surfaces."""
        count = self._processing_failure_count()
        summary = self._processing_failure_summary_text()
        if count > 0:
            banner_text = (
                summary + " Valid files remain available where possible."
            )
        else:
            banner_text = ""

        for label in getattr(self, "_processing_failure_banner_labels", []):
            label.setText(banner_text)
        for banner in getattr(self, "_processing_failure_banners", []):
            banner.setVisible(count > 0)

        if hasattr(self, "_refresh_data_header_state"):
            self._refresh_data_header_state()
        if hasattr(self, "_refresh_measure_header_state"):
            self._refresh_measure_header_state()
        if hasattr(self, "_apply_dynamic_visibility_policy"):
            self._apply_dynamic_visibility_policy()
        self._set_status()

    def _show_processing_failures_dialog(self) -> None:
        """Show a read-only dialog containing aggregated processing failures."""
        if not self._processing_failures:
            self._show_info(
                "Processing Issues",
                "No processing issues are currently recorded.",
            )
            return

        dialog = qtw.QDialog(self)
        dialog.setWindowTitle("Processing Issues")
        configure_secondary_window(dialog)
        dialog.setModal(False)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.resize(860, 480)

        layout = qtw.QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        summary_label = qtw.QLabel(self._processing_failure_summary_text())
        summary_label.setObjectName("SectionTitle")
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        details = qtw.QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(
            format_processing_failure_details(self._processing_failures),
        )
        layout.addWidget(details, 1)

        button_row = qtw.QHBoxLayout()
        button_row.addStretch(1)
        close_button = qtw.QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        theme_sheet = (
            self._current_theme_stylesheet()
            if hasattr(self, "_current_theme_stylesheet")
            else DARK_THEME if self._theme_mode == "dark" else LIGHT_THEME
        )
        dialog.setStyleSheet(theme_sheet)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _save_roi_to_file(self) -> None:
        """Save current ROI rectangle to a JSON file."""
        metrics = self.metrics_state
        if (
            not self._has_loaded_data()
            or metrics.roi_rect is None
            or self._current_average_mode() != "roi"
        ):
            return

        dataset = self.dataset_state
        idx = (
            dataset.selected_index
            if dataset.selected_index is not None
            else 0
        )
        metric_img, _bg_applied = self._get_metric_image_by_index(idx)
        if metric_img is None or metric_img.ndim != 2:
            self._show_error("Save ROI failed", "No valid image available.")
            return

        default_path = Path.home() / "roi_selection.json"
        dialog = qtw.QFileDialog(
            self,
            "Save ROI",
            str(default_path),
        )
        dialog.setAcceptMode(qtw.QFileDialog.AcceptSave)
        dialog.setOption(qtw.QFileDialog.DontUseNativeDialog, True)
        dialog.setNameFilters(("JSON (*.json)", "All files (*)"))
        dialog.selectNameFilter("JSON (*.json)")
        if not dialog.exec():
            return
        selected_files = dialog.selectedFiles()
        if not selected_files:
            return

        path = Path(selected_files[0])
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        x0, y0, x1, y1 = metrics.roi_rect
        payload = {
            "x0": int(x0),
            "y0": int(y0),
            "x1": int(x1),
            "y1": int(y1),
            "image_width": int(metric_img.shape[1]),
            "image_height": int(metric_img.shape[0]),
        }
        try:
            write_json_dict(path, payload)
        except Exception as exc:
            self._show_error("Save ROI failed", str(exc))
            return
        self._set_status(f"Saved ROI to {path.name}")

    def _load_roi_from_file(self) -> None:
        """Load ROI rectangle from a JSON file and apply it to current data."""
        metrics = self.metrics_state
        if (
            not self._has_loaded_data()
            or self._current_average_mode() != "roi"
        ):
            return

        initial = str(Path.home())
        dialog = qtw.QFileDialog(self, "Load ROI", initial)
        dialog.setFileMode(qtw.QFileDialog.ExistingFile)
        dialog.setNameFilters(("JSON (*.json)", "All files (*)"))
        dialog.setOption(qtw.QFileDialog.DontUseNativeDialog, True)
        if not dialog.exec():
            return
        selected_files = dialog.selectedFiles()
        if not selected_files:
            return

        path = Path(selected_files[0])
        payload = read_json_dict(path)
        if payload is None:
            self._show_error(
                "Load ROI failed",
                "Invalid ROI file:\nCould not read a JSON object.",
            )
            return

        try:
            rect = (
                int(payload["x0"]),
                int(payload["y0"]),
                int(payload["x1"]),
                int(payload["y1"]),
            )
        except Exception as exc:
            self._show_error("Load ROI failed", f"Invalid ROI file:\n{exc}")
            return

        dataset = self.dataset_state
        idx = (
            dataset.selected_index
            if dataset.selected_index is not None
            else 0
        )
        metric_img, _bg_applied = self._get_metric_image_by_index(idx)
        if metric_img is None or metric_img.ndim != 2:
            self._show_error("Load ROI failed", "No valid image available.")
            return

        img_h, img_w = int(metric_img.shape[0]), int(metric_img.shape[1])
        x0, y0, x1, y1 = rect
        if not (0 <= x0 < x1 <= img_w and 0 <= y0 < y1 <= img_h):
            self._show_error(
                "Load ROI failed",
                (
                    "ROI coordinates are out of current image bounds:\n"
                    f"ROI=({x0},{y0})-({x1},{y1}), image={img_w}x{img_h}"
                ),
            )
            return

        metrics.roi_rect = rect
        self.image_preview.set_roi_rect(metrics.roi_rect)
        self._reset_roi_metrics()

        if dataset.selected_index is not None:
            roi_mean, roi_std, roi_sem = self._compute_roi_stats_for_index(
                dataset.selected_index,
            )
            metrics.roi_means[dataset.selected_index] = roi_mean
            metrics.roi_stds[dataset.selected_index] = roi_std
            metrics.roi_sems[dataset.selected_index] = roi_sem

        self._update_average_controls()
        self._refresh_table()
        self._set_status(f"Loaded ROI from {path.name}")

    def _clear_roi(self) -> None:
        """Clear current ROI state and ROI-derived metrics."""
        self.metrics_state.roi_rect = None
        self.image_preview.set_roi_rect(None)
        self._reset_roi_metrics()
        self._update_average_controls()
        if self._has_loaded_data():
            self._refresh_table()
        self._set_status("ROI cleared")

    def _set_status(self, warning: str | None = None) -> None:
        """Compose and display the main status-bar message."""
        metrics = self.metrics_state
        msg = self.base_status
        if self._has_loaded_data():
            msg += f" | Threshold={metrics.threshold_value:g}"
            mode = self._current_average_mode()
            if mode == "topk":
                msg += f" | Top-K mean over {metrics.avg_count_value} px"
            elif mode == "roi":
                if metrics.roi_rect is None:
                    msg += " | ROI: draw rectangle on preview"
                else:
                    x0, y0, x1, y1 = metrics.roi_rect
                    msg += f" | ROI=({x0},{y0})-({x1},{y1})"
            if metrics.background_config.enabled:
                if metrics.background_library.global_ref is not None:
                    msg += " | BG=global ref"
                elif metrics.background_library.refs_by_exposure_ms:
                    msg += (
                        " | BG refs="
                        f"{len(metrics.background_library.refs_by_exposure_ms)}"
                    )
                else:
                    msg += " | BG on (no refs)"
                if metrics.bg_total_count > 0:
                    msg += (
                        " | BG unmatched "
                        f"{metrics.bg_unmatched_count}/{metrics.bg_total_count}"
                    )
            if metrics.is_roi_applying:
                if metrics.roi_apply_total > 0:
                    msg += (
                        f" | ROI apply {metrics.roi_apply_done}"
                        f"/{metrics.roi_apply_total}"
                    )
                else:
                    msg += " | ROI apply in progress"
        if metrics.is_stats_running:
            msg += " | Updating metrics..."
        failure_count = self._processing_failure_count()
        if failure_count > 0:
            msg += f" | Issues={failure_count}"
        if self.context_hint:
            msg += f" | Hint: {self.context_hint}"
        if warning:
            msg += f" | {warning}"
        self.statusBar().showMessage(msg)

    def _collect_visible_table_values(
        self,
    ) -> tuple[list[str], list[list[str]]]:
        """Return currently visible table data in export-ready form."""
        metrics = self.metrics_state
        model = self.table.model()
        if model is None:
            return ([], [])
        visible_columns = [
            col
            for col in range(model.columnCount())
            if not self.table.isColumnHidden(col)
        ]
        headers: list[str] = []
        for col in visible_columns:
            header_value = model.headerData(col, Qt.Horizontal, Qt.UserRole)
            if header_value is None:
                header_value = model.headerData(
                    col,
                    Qt.Horizontal,
                    Qt.DisplayRole,
                )
            headers.append("" if header_value is None else str(header_value))

        rows: list[list[str]] = []
        for row in range(model.rowCount()):
            row_values: list[str] = []
            for col in visible_columns:
                value = model.data(model.index(row, col), Qt.DisplayRole)
                row_values.append("" if value is None else str(value))
            rows.append(row_values)

        if self._current_average_mode() == "roi" and metrics.roi_rect is not None:
            x0, y0, x1, y1 = metrics.roi_rect
            headers.extend(["ROI_X0", "ROI_Y0", "ROI_X1", "ROI_Y1"])
            roi_values = [str(x0), str(y0), str(x1), str(y1)]
            rows = [row + roi_values for row in rows]
        return headers, rows

    def _export_table_to_delimited(
        self,
        path: Path,
        headers: list[str],
        rows: list[list[str]],
        delimiter: str,
    ) -> None:
        """Export table rows to CSV/TSV-like delimited text."""
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=delimiter)
            writer.writerow(headers)
            writer.writerows(rows)

    def _export_table_to_json(
        self,
        path: Path,
        headers: list[str],
        rows: list[list[str]],
    ) -> None:
        """Export table rows to a JSON array of records."""
        payload = []
        for row_values in rows:
            payload.append(
                {
                    headers[i]: row_values[i] if i < len(row_values) else ""
                    for i in range(len(headers))
                }
            )
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def _export_table_to_xlsx(
        self,
        path: Path,
        headers: list[str],
        rows: list[list[str]],
    ) -> None:
        """Export table rows to an XLSX workbook."""
        try:
            from openpyxl import Workbook
        except Exception as exc:
            raise RuntimeError(
                "openpyxl is required to export .xlsx files",
            ) from exc

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Image Metrics"
        sheet.append(headers)
        for row_values in rows:
            sheet.append(row_values)
        workbook.save(str(path))

    def _export_metrics_table(self) -> None:
        """Open export dialog and write the visible metrics table."""
        headers, rows = self._collect_visible_table_values()
        if not rows:
            self._show_info(
                "Nothing to export",
                "The image metrics table is empty.",
            )
            return

        default_path = Path.home() / "image_metrics.csv"
        dialog = qtw.QFileDialog(
            self,
            "Export Image Metrics Table",
            str(default_path),
        )
        dialog.setAcceptMode(qtw.QFileDialog.AcceptSave)
        dialog.setOption(qtw.QFileDialog.DontUseNativeDialog, True)
        dialog.setNameFilters(
            (
                "CSV (*.csv)",
                "Text (*.txt)",
                "JSON (*.json)",
                "Excel Workbook (*.xlsx)",
            )
        )
        dialog.selectNameFilter("CSV (*.csv)")
        if not dialog.exec():
            return
        selected_files = dialog.selectedFiles()
        if not selected_files:
            return
        chosen_path = selected_files[0]
        selected_filter = dialog.selectedNameFilter()

        path = Path(chosen_path)
        suffix = path.suffix.lower()
        if not suffix:
            if "*.txt" in selected_filter:
                path = path.with_suffix(".txt")
            elif "*.json" in selected_filter:
                path = path.with_suffix(".json")
            elif "*.xlsx" in selected_filter:
                path = path.with_suffix(".xlsx")
            else:
                path = path.with_suffix(".csv")
            suffix = path.suffix.lower()

        try:
            if suffix == ".csv":
                self._export_table_to_delimited(path, headers, rows, ",")
            elif suffix == ".txt":
                self._export_table_to_delimited(path, headers, rows, "\t")
            elif suffix == ".json":
                self._export_table_to_json(path, headers, rows)
            elif suffix == ".xlsx":
                self._export_table_to_xlsx(path, headers, rows)
            else:
                self._show_error(
                    "Unsupported format",
                    "Choose one of: .csv, .txt, .json, .xlsx",
                )
                return
        except Exception as exc:
            self._show_error("Export failed", str(exc))
            return

        self._set_status(f"Exported metrics to {path.name}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Ensure background threads are stopped before window closes."""
        if hasattr(self, "_save_ui_state"):
            try:
                self._save_ui_state()
            except Exception:
                pass
        roi_thread = self._roi_apply_thread
        thread = self._stats_thread
        self._cancel_roi_apply_job()
        self._cancel_stats_job()
        if roi_thread is not None and roi_thread.isRunning():
            roi_thread.wait(1500)
        if thread is not None and thread.isRunning():
            thread.wait(1500)
        super().closeEvent(event)

    def _show_message(
        self,
        icon: qtw.QMessageBox.Icon,
        title: str,
        message: str,
    ) -> None:
        """Show a themed message dialog."""
        dialog = qtw.QMessageBox(self)
        dialog.setOption(qtw.QMessageBox.DontUseNativeDialog, True)
        configure_secondary_window(dialog)
        dialog.setIcon(icon)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setTextFormat(Qt.PlainText)
        dialog.setStandardButtons(qtw.QMessageBox.Ok)
        theme_sheet = (
            self._current_theme_stylesheet()
            if hasattr(self, "_current_theme_stylesheet")
            else DARK_THEME if self._theme_mode == "dark" else LIGHT_THEME
        )
        dialog.setStyleSheet(theme_sheet)
        dialog.exec()

    def _show_info(self, title: str, message: str) -> None:
        """Show an informational dialog."""
        self._show_message(qtw.QMessageBox.Information, title, message)

    def _show_error(self, title: str, message: str) -> None:
        """Show an error dialog."""
        self._show_message(qtw.QMessageBox.Critical, title, message)
