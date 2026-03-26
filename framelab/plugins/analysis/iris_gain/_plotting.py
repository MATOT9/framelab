"""Plot rendering and matplotlib interaction helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6 import QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt

from ._shared import _CurveSeries, _FitHoverItem, _FitSeries


class IrisGainPlotMixin:
    """Plot state, rendering, and interactive gesture helpers."""

    def _apply_plot_layout(self) -> None:
        """Keep plot margins stable across empty and populated states."""
        if self._figure is None or self._axes is None or self._canvas is None:
            return
        base_left = 0.115
        right = 0.985
        bottom = 0.16
        top = 0.965
        self._figure.subplots_adjust(
            left=base_left,
            right=right,
            bottom=bottom,
            top=top,
        )
        for _ in range(5):
            try:
                self._canvas.draw()
                renderer = self._canvas.get_renderer()
            except Exception:
                return
            if renderer is None:
                return
            try:
                figure_bbox = self._figure.get_window_extent(renderer)
                axes_bbox = self._axes.get_window_extent(renderer)
                tight_bbox = self._axes.get_tightbbox(renderer)
            except Exception:
                return
            if (
                figure_bbox.width <= 0.0
                or axes_bbox.width <= 0.0
                or tight_bbox.width <= 0.0
            ):
                return

            figure_width = float(figure_bbox.width)
            current_left = float(self._figure.subplotpars.left)
            desired_left = current_left

            desired_left = max(
                desired_left,
                max(0.0, float(axes_bbox.x0) - float(tight_bbox.x0) + 8.0)
                / figure_width,
            )

            # If labels still spill beyond the rendered figure edge, grow the
            # left inset by the measured overflow plus a small safety margin.
            overflow_px = 1.0 - float(tight_bbox.x0)
            if overflow_px > 0.0:
                desired_left = max(
                    desired_left,
                    current_left + (overflow_px + 4.0) / figure_width,
                )

            # Split-pane layouts can leave the plot canvas much narrower than
            # the main window. Allow a substantially larger left inset so the
            # y-axis label and wide tick labels stay inside the rendered figure.
            bounded_left = min(max(base_left, desired_left), 0.92)
            if abs(bounded_left - current_left) < 0.002:
                break
            self._figure.subplots_adjust(
                left=bounded_left,
                right=right,
                bottom=bottom,
                top=top,
            )

    @staticmethod
    def _finite_range(values: np.ndarray) -> Optional[tuple[float, float]]:
        """Return finite min/max range for a vector."""
        arr = np.asarray(values, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return None
        return (float(np.min(arr)), float(np.max(arr)))

    @staticmethod
    def _set_artist_visible(artist: object, visible: bool) -> None:
        """Set visibility for line or errorbar-like artist containers."""
        if isinstance(artist, (list, tuple)):
            for part in artist:
                IrisGainPlotMixin._set_artist_visible(part, visible)
            return

        if hasattr(artist, "set_visible"):
            try:
                artist.set_visible(visible)
            except Exception:
                pass

        lines = getattr(artist, "lines", None)
        if lines is None:
            return
        for item in lines:
            if isinstance(item, (list, tuple)):
                for part in item:
                    if hasattr(part, "set_visible"):
                        try:
                            part.set_visible(visible)
                        except Exception:
                            continue
            elif hasattr(item, "set_visible"):
                try:
                    item.set_visible(visible)
                except Exception:
                    continue

    def _sync_legend_alpha(self, label: str) -> None:
        """Fade legend entries for hidden curves."""
        visible = self._curve_visibility.get(label, True)
        alpha = 1.0 if visible else 0.3
        handle = self._legend_handle_by_label.get(label)
        text = self._legend_text_by_label.get(label)
        if handle is not None and hasattr(handle, "set_alpha"):
            try:
                handle.set_alpha(alpha)
            except Exception:
                pass
        if text is not None and hasattr(text, "set_alpha"):
            try:
                text.set_alpha(alpha)
            except Exception:
                pass

    def _configure_legend_pick(self, legend: object, labels: list[str]) -> None:
        """Configure clickable legend entries to toggle curve visibility."""
        self._legend_pick_map.clear()
        self._legend_handle_by_label.clear()
        self._legend_text_by_label.clear()

        handles = list(
            getattr(legend, "legend_handles", [])
            or getattr(legend, "legendHandles", [])
        )
        if not handles and hasattr(legend, "get_lines"):
            handles = list(legend.get_lines())
        texts = list(legend.get_texts()) if hasattr(legend, "get_texts") else []

        for idx, label in enumerate(labels):
            handle = handles[idx] if idx < len(handles) else None
            text = texts[idx] if idx < len(texts) else None

            if handle is not None:
                if hasattr(handle, "set_picker"):
                    handle.set_picker(True)
                if hasattr(handle, "set_pickradius"):
                    handle.set_pickradius(8)
                self._legend_pick_map[id(handle)] = label
                self._legend_handle_by_label[label] = handle

            if text is not None:
                if hasattr(text, "set_picker"):
                    text.set_picker(True)
                self._legend_pick_map[id(text)] = label
                self._legend_text_by_label[label] = text

            self._sync_legend_alpha(label)

    def _autoscale_visible_series(self) -> None:
        """Autoscale axes to currently visible curves only."""
        if self._axes is None:
            return

        x_ranges: list[tuple[float, float]] = []
        y_ranges: list[tuple[float, float]] = []
        for label, x_arr, y_arr, _std_arr, _sem_arr in self._plot_points:
            if not self._curve_visibility.get(label, True):
                continue
            x_range = self._finite_range(x_arr)
            y_range = self._finite_range(y_arr)
            if x_range is not None:
                x_ranges.append(x_range)
            if y_range is not None:
                y_ranges.append(y_range)
        for label, x_arr, y_arr in self._fit_plot_points:
            if not self._curve_visibility.get(label, True):
                continue
            x_range = self._finite_range(x_arr)
            y_range = self._finite_range(y_arr)
            if x_range is not None:
                x_ranges.append(x_range)
            if y_range is not None:
                y_ranges.append(y_range)

        if not x_ranges or not y_ranges:
            self._axes.set_xlim(0.0, 1.0)
            self._axes.set_ylim(0.0, 1.0)
            return

        x_min = min(item[0] for item in x_ranges)
        x_max = max(item[1] for item in x_ranges)
        y_min = min(item[0] for item in y_ranges)
        y_max = max(item[1] for item in y_ranges)

        x_span = max(1e-12, x_max - x_min)
        y_span = max(1e-12, y_max - y_min)
        self._axes.set_xlim(x_min - 0.08 * x_span, x_max + 0.08 * x_span)
        self._axes.set_ylim(y_min - 0.12 * y_span, y_max + 0.12 * y_span)

    def _reset_plot_view(self) -> None:
        """Reset plot view to all currently visible data."""
        if self._axes is None or self._canvas is None:
            return
        self._autoscale_visible_series()
        self._apply_plot_layout()
        self._canvas.draw_idle()

    def _show_all_curves(self) -> None:
        """Set every curve visible and refresh plot."""
        if not self._plot_series:
            return
        for curve in self._plot_series:
            self._curve_visibility[curve.label] = True
        fit_series = self._build_overlay_series(
            self._plot_series,
            self._plot_overlay_mode,
            self._plot_x_mode,
            self._plot_y_mode,
            self._plot_err_mode,
        )
        self._update_plot(
            self._plot_series,
            self._plot_x_label,
            self._plot_y_label,
            self._plot_err_mode,
            fit_series,
            self._plot_overlay_mode != "off",
            self._plot_overlay_mode,
        )

    def _copy_plot_to_clipboard(self) -> None:
        """Copy rendered plot canvas image to clipboard."""
        if self._canvas is None:
            return
        pixmap = self._canvas.grab()
        if pixmap.isNull():
            return
        qtw.QApplication.clipboard().setPixmap(pixmap)

    @staticmethod
    def _plot_export_suffix_for_filter(selected_filter: str) -> str:
        """Return the preferred suffix for one save-dialog filter."""

        lowered = str(selected_filter).strip().lower()
        if "pdf" in lowered:
            return ".pdf"
        if "jpeg" in lowered or "jpg" in lowered:
            return ".jpg"
        return ".png"

    @staticmethod
    def _plot_export_format_for_path(path: Path) -> str:
        """Return the matplotlib format key for one export path."""

        suffix = path.suffix.lower()
        if suffix == ".png":
            return "png"
        if suffix in {".jpg", ".jpeg"}:
            return "jpeg"
        if suffix == ".pdf":
            return "pdf"
        raise ValueError("Plot export format must be .png, .jpg, .jpeg, or .pdf.")

    def _suggest_plot_export_path(self) -> Path:
        """Return the default save path used by plot export."""

        last_path = str(getattr(self, "_plot_export_last_path", "") or "").strip()
        if last_path:
            return Path(last_path).expanduser()

        base_dir = Path.home()
        context = getattr(self, "_context", None)
        for raw_path in (
            getattr(context, "active_node_path", None),
            getattr(context, "dataset_scope_root", None),
            getattr(context, "workflow_anchor_path", None),
        ):
            if not raw_path:
                continue
            candidate = Path(str(raw_path)).expanduser()
            if candidate.exists():
                base_dir = candidate if candidate.is_dir() else candidate.parent
                break
        return base_dir / "intensity-trend.png"

    def _export_plot_to_file(
        self,
        export_path: str | Path,
        *,
        dpi: int,
    ) -> Path:
        """Export the current plot to one supported file path."""

        if self._figure is None:
            raise RuntimeError("Plot export is unavailable because matplotlib is not installed.")

        path = Path(export_path).expanduser()
        export_format = self._plot_export_format_for_path(path)
        clean_dpi = max(36, int(dpi))
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._canvas is not None:
            self._canvas.draw()
        self._figure.savefig(
            path,
            format=export_format,
            dpi=clean_dpi,
            bbox_inches="tight",
            facecolor=self._figure.get_facecolor(),
            edgecolor=self._figure.get_edgecolor(),
        )
        self._plot_export_dpi = clean_dpi
        self._plot_export_last_path = str(path)
        return path

    def _export_plot_dialog(self) -> None:
        """Prompt for a plot-export path and dpi, then save the figure."""

        if self._figure is None:
            return
        parent = self._root if self._root is not None else None
        file_path, selected_filter = qtw.QFileDialog.getSaveFileName(
            parent,
            "Export Plot",
            str(self._suggest_plot_export_path()),
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;PDF Document (*.pdf)",
        )
        if not file_path:
            return

        export_path = Path(file_path).expanduser()
        if export_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf"}:
            export_path = export_path.with_suffix(
                self._plot_export_suffix_for_filter(selected_filter),
            )

        dpi, accepted = qtw.QInputDialog.getInt(
            parent,
            "Export Plot",
            "DPI:",
            value=int(getattr(self, "_plot_export_dpi", 200)),
            minValue=36,
            maxValue=1200,
            step=12,
        )
        if not accepted:
            return
        try:
            self._export_plot_to_file(export_path, dpi=dpi)
        except Exception as exc:
            qtw.QMessageBox.warning(parent, "Export Plot", str(exc))

    def _show_plot_context_menu(self) -> None:
        """Open right-click context menu for plot actions."""
        parent = self._root if self._root is not None else None
        menu = qtw.QMenu(parent)
        reset_action = menu.addAction("Reset View")
        show_all_action = menu.addAction("Show All Curves")
        menu.addSeparator()
        copy_plot_action = menu.addAction("Copy Plot Image")
        export_plot_action = menu.addAction("Export Plot...")
        export_plot_action.setEnabled(self._figure is not None)
        chosen = menu.exec(QtGui.QCursor.pos())
        if chosen == reset_action:
            self._reset_plot_view()
            return
        if chosen == show_all_action:
            self._show_all_curves()
            return
        if chosen == copy_plot_action:
            self._copy_plot_to_clipboard()
            return
        if chosen == export_plot_action:
            self._export_plot_dialog()

    def _set_hover_annotation_style(
        self,
        text_color: str,
        box_color: str,
        edge_color: str,
    ) -> None:
        """Initialize reusable hover annotation for point readout."""
        if self._axes is None:
            return
        self._hover_annotation = self._axes.annotate(
            "",
            xy=(0.0, 0.0),
            xytext=(12, 12),
            textcoords="offset points",
            ha="left",
            va="bottom",
            fontsize=8,
            color=text_color,
            bbox={
                "boxstyle": "round,pad=0.35",
                "fc": box_color,
                "ec": edge_color,
                "alpha": 0.95,
            },
        )
        self._hover_annotation.set_visible(False)
        self._fit_stats_annotation = self._axes.annotate(
            "",
            xy=(0.015, 0.985),
            xycoords="axes fraction",
            ha="left",
            va="top",
            fontsize=8,
            color=text_color,
            bbox={
                "boxstyle": "round,pad=0.35",
                "fc": box_color,
                "ec": edge_color,
                "alpha": 0.95,
            },
        )
        self._fit_stats_annotation.set_visible(False)

    def _hide_hover_annotation(self) -> None:
        """Hide point hover annotation when no valid point is hovered."""
        if self._hover_annotation is None:
            return
        self._hover_annotation.set_visible(False)

    def _set_fit_stats_text(self, fit: Optional[_FitSeries]) -> None:
        """Display global fit parameters in-plot, or hide when unavailable."""
        if self._fit_stats_annotation is None:
            return
        if fit is None or fit.kind != "linear_fit":
            self._fit_stats_annotation.set_visible(False)
            return
        r2_text = "-" if not np.isfinite(fit.r2) else f"{fit.r2:.4f}"
        self._fit_stats_annotation.set_text(
            (
                f"Linear fit\n"
                f"y = {fit.slope:.4g}x + {fit.intercept:.4g}\n"
                f"$R^2$ = {r2_text}"
            ),
        )
        self._fit_stats_annotation.set_visible(True)

    def _update_hover_annotation(self, event: object) -> None:
        """Update nearest tooltip for points and fitted lines."""
        if (
            self._axes is None
            or self._canvas is None
            or self._hover_annotation is None
        ):
            return
        if (
            getattr(event, "inaxes", None) is not self._axes
            or getattr(event, "x", None) is None
            or getattr(event, "y", None) is None
        ):
            if self._hover_annotation.get_visible():
                self._hide_hover_annotation()
                self._canvas.draw_idle()
            return

        event_x = float(event.x)
        event_y = float(event.y)
        best_label: Optional[str] = None
        best_x = 0.0
        best_y = 0.0
        best_dist2 = float("inf")
        best_text = ""
        overlay_mode = self._plot_overlay_mode

        if overlay_mode == "off":
            for label, x_arr, y_arr, _std_arr, _sem_arr in self._plot_points:
                if not self._curve_visibility.get(label, True):
                    continue
                if x_arr.size == 0 or y_arr.size == 0:
                    continue
                points = np.column_stack((x_arr, y_arr))
                display = self._axes.transData.transform(points)
                dx = display[:, 0] - event_x
                dy = display[:, 1] - event_y
                dist2 = dx * dx + dy * dy
                idx = int(np.argmin(dist2))
                value = float(dist2[idx])
                if value < best_dist2:
                    best_dist2 = value
                    best_label = label
                    best_x = float(x_arr[idx])
                    best_y = float(y_arr[idx])
                    best_text = (
                        f"{label}\nx={self._format_float(best_x)}\n"
                        f"y={self._format_float(best_y)}"
                    )
        else:
            for item in self._fit_hover_items:
                x_arr = item.x_values
                y_arr = item.y_values
                if x_arr.size == 0 or y_arr.size == 0:
                    continue
                points = np.column_stack((x_arr, y_arr))
                display = self._axes.transData.transform(points)
                dx = display[:, 0] - event_x
                dy = display[:, 1] - event_y
                dist2 = dx * dx + dy * dy
                idx = int(np.argmin(dist2))
                value = float(dist2[idx])
                if value >= best_dist2:
                    continue

                best_dist2 = value
                best_label = item.label
                best_x = float(x_arr[idx])
                best_y = float(y_arr[idx])
                if item.kind == "mean_x":
                    std_arr = (
                        item.std_values
                        if item.std_values is not None
                        else np.asarray([], dtype=np.float64)
                    )
                    sem_arr = (
                        item.sem_values
                        if item.sem_values is not None
                        else np.asarray([], dtype=np.float64)
                    )
                    point_std = (
                        float(std_arr[idx])
                        if idx < std_arr.size
                        else float(np.nan)
                    )
                    point_sem = (
                        float(sem_arr[idx])
                        if idx < sem_arr.size
                        else float(np.nan)
                    )
                    if self._plot_y_mode in {"gain", "gain_last"}:
                        point_abs_unc = (
                            point_std
                            if self._plot_err_mode == "std"
                            else point_sem
                            if self._plot_err_mode == "stderr"
                            else float(np.nan)
                        )
                        best_text = (
                            f"{item.label}\nx={self._format_float(best_x)}\n"
                            f"gain={self._format_float(best_y)}\n"
                            f"abs unc={self._format_float(point_abs_unc)}"
                        )
                    else:
                        best_text = (
                            f"{item.label}\nx={self._format_float(best_x)}\n"
                            f"mean={self._format_float(best_y)}\n"
                            f"std={self._format_float(point_std)}\n"
                            f"std err={self._format_float(point_sem)}"
                        )
                else:
                    best_text = (
                        f"{item.label}\nx={self._format_float(best_x)}\n"
                        f"y_fit={self._format_float(best_y)}"
                    )

        hover_radius_px = 11.0
        if best_label is None or best_dist2 > hover_radius_px * hover_radius_px:
            if self._hover_annotation.get_visible():
                self._hide_hover_annotation()
                self._canvas.draw_idle()
            return

        x_offset = 12
        y_offset = 12
        h_align = "left"
        v_align = "bottom"
        bbox = self._axes.bbox
        if event_x > float(bbox.x0 + bbox.width * 0.72):
            x_offset = -12
            h_align = "right"
        elif event_x < float(bbox.x0 + bbox.width * 0.12):
            x_offset = 12
            h_align = "left"
        if event_y > float(bbox.y0 + bbox.height * 0.76):
            y_offset = -12
            v_align = "top"
        elif event_y < float(bbox.y0 + bbox.height * 0.20):
            y_offset = 12
            v_align = "bottom"

        self._hover_annotation.xy = (best_x, best_y)
        self._hover_annotation.set_text(best_text)
        self._hover_annotation.set_ha(h_align)
        self._hover_annotation.set_va(v_align)
        self._hover_annotation.set_position((x_offset, y_offset))
        self._hover_annotation.set_visible(True)
        self._canvas.draw_idle()

    def _on_plot_leave_axes(self, _event: object) -> None:
        """Hide hover label when pointer leaves the axes area."""
        if self._canvas is None or self._hover_annotation is None:
            return
        if self._hover_annotation.get_visible():
            self._hide_hover_annotation()
            self._canvas.draw_idle()

    def _on_plot_pick(self, event: object) -> None:
        """Toggle plotted curve visibility when clicking legend entries."""
        if self._canvas is None:
            return
        artist = getattr(event, "artist", None)
        if artist is None:
            return
        label = self._legend_pick_map.get(id(artist))
        if label is None:
            return

        visible = not self._curve_visibility.get(label, True)
        self._curve_visibility[label] = visible
        fit_series = self._build_overlay_series(
            self._plot_series,
            self._plot_overlay_mode,
            self._plot_x_mode,
            self._plot_y_mode,
            self._plot_err_mode,
        )
        self._update_plot(
            self._plot_series,
            self._plot_x_label,
            self._plot_y_label,
            self._plot_err_mode,
            fit_series,
            self._plot_overlay_mode != "off",
            self._plot_overlay_mode,
        )
        self._hide_hover_annotation()
        self._canvas.draw_idle()

    def _on_plot_press(self, event: object) -> None:
        """Handle context menu, reset, and drag-pan start for plot axes."""
        if self._axes is None or self._canvas is None:
            return
        if getattr(event, "inaxes", None) is not self._axes:
            return
        if bool(getattr(event, "dblclick", False)):
            self._reset_plot_view()
            return
        if getattr(event, "button", None) == 3:
            self._show_plot_context_menu()
            return

        if getattr(event, "button", None) not in (1, 2):
            return
        x_data = getattr(event, "xdata", None)
        y_data = getattr(event, "ydata", None)
        if x_data is None or y_data is None:
            return

        self._is_plot_panning = True
        self._plot_pan_state = (
            float(x_data),
            float(y_data),
            tuple(self._axes.get_xlim()),
            tuple(self._axes.get_ylim()),
        )
        self._canvas.setCursor(Qt.ClosedHandCursor)

    def _on_plot_release(self, _event: object) -> None:
        """Finish drag-pan mode."""
        if self._canvas is None:
            return
        self._is_plot_panning = False
        self._plot_pan_state = None
        self._canvas.setCursor(Qt.ArrowCursor)

    def _on_plot_scroll(self, event: object) -> None:
        """Zoom plot around cursor position using mouse wheel."""
        if self._axes is None or self._canvas is None:
            return
        if getattr(event, "inaxes", None) is not self._axes:
            return
        x_data = getattr(event, "xdata", None)
        y_data = getattr(event, "ydata", None)
        if x_data is None or y_data is None:
            return

        xlim = tuple(self._axes.get_xlim())
        ylim = tuple(self._axes.get_ylim())
        if xlim[0] == xlim[1] or ylim[0] == ylim[1]:
            return

        button = str(getattr(event, "button", "up"))
        zoom_scale = 0.92 if button == "up" else 1.08

        x_span = float(xlim[1] - xlim[0])
        y_span = float(ylim[1] - ylim[0])
        x_ratio = (float(x_data) - float(xlim[0])) / x_span
        y_ratio = (float(y_data) - float(ylim[0])) / y_span

        base_x_ranges: list[tuple[float, float]] = []
        base_y_ranges: list[tuple[float, float]] = []
        for label, x_arr, y_arr, _std_arr, _sem_arr in self._plot_points:
            if not self._curve_visibility.get(label, True):
                continue
            x_range = self._finite_range(x_arr)
            y_range = self._finite_range(y_arr)
            if x_range is not None:
                base_x_ranges.append(x_range)
            if y_range is not None:
                base_y_ranges.append(y_range)
        for label, x_arr, y_arr in self._fit_plot_points:
            if not self._curve_visibility.get(label, True):
                continue
            x_range = self._finite_range(x_arr)
            y_range = self._finite_range(y_arr)
            if x_range is not None:
                base_x_ranges.append(x_range)
            if y_range is not None:
                base_y_ranges.append(y_range)

        if base_x_ranges:
            data_x_span = max(item[1] for item in base_x_ranges) - min(
                item[0] for item in base_x_ranges
            )
        else:
            data_x_span = x_span
        if base_y_ranges:
            data_y_span = max(item[1] for item in base_y_ranges) - min(
                item[0] for item in base_y_ranges
            )
        else:
            data_y_span = y_span

        min_x_span = max(1e-9, data_x_span * 1e-6)
        min_y_span = max(1e-9, data_y_span * 1e-6)
        max_x_span = max(min_x_span * 10.0, data_x_span * 20.0)
        max_y_span = max(min_y_span * 10.0, data_y_span * 20.0)

        new_x_span = min(max(x_span * zoom_scale, min_x_span), max_x_span)
        new_y_span = min(max(y_span * zoom_scale, min_y_span), max_y_span)
        if (
            np.isclose(new_x_span, 0.0, atol=1e-18)
            or np.isclose(new_y_span, 0.0, atol=1e-18)
        ):
            return

        x0 = float(x_data) - x_ratio * new_x_span
        x1 = x0 + new_x_span
        y0 = float(y_data) - y_ratio * new_y_span
        y1 = y0 + new_y_span
        self._axes.set_xlim(x0, x1)
        self._axes.set_ylim(y0, y1)
        self._hide_hover_annotation()
        self._apply_plot_layout()
        self._canvas.draw_idle()

    def _on_plot_motion(self, event: object) -> None:
        """Handle drag-pan and hover point info updates."""
        if self._axes is None or self._canvas is None:
            return
        if (
            self._is_plot_panning
            and self._plot_pan_state is not None
            and getattr(event, "inaxes", None) is self._axes
            and getattr(event, "xdata", None) is not None
            and getattr(event, "ydata", None) is not None
        ):
            start_x, start_y, start_xlim, start_ylim = self._plot_pan_state
            delta_x = float(getattr(event, "xdata")) - start_x
            delta_y = float(getattr(event, "ydata")) - start_y
            self._axes.set_xlim(start_xlim[0] - delta_x, start_xlim[1] - delta_x)
            self._axes.set_ylim(start_ylim[0] - delta_y, start_ylim[1] - delta_y)
            self._hide_hover_annotation()
            self._apply_plot_layout()
            self._canvas.draw_idle()
            return

        self._update_hover_annotation(event)

    def _set_empty(self, _message: str) -> None:
        """Clear plugin outputs and show an empty-state message."""
        if self._table is not None:
            self._table.setRowCount(0)
        self._update_plot([], "X", "Y", "off", [], False, "off")

    def _update_plot(
        self,
        curves: list[_CurveSeries],
        x_label: str,
        y_label: str,
        err_mode: str,
        fit_series: list[_FitSeries],
        fit_enabled: bool,
        overlay_mode: str,
    ) -> None:
        """Render plot contents for the current analysis result."""
        self._plot_series = list(curves)
        self._plot_x_label = x_label
        self._plot_y_label = y_label
        self._plot_err_mode = err_mode
        self._plot_fit_series = list(fit_series)
        self._plot_fit_enabled = bool(fit_enabled)
        self._plot_overlay_mode = (
            overlay_mode
            if overlay_mode in {"off", "linear_fit", "mean_x"}
            else "off"
        )

        if self._axes is None or self._canvas is None or self._figure is None:
            return

        self._curve_artists.clear()
        self._plot_points = []
        self._fit_plot_points = []
        self._fit_hover_items = []
        self._legend_pick_map.clear()
        self._legend_handle_by_label.clear()
        self._legend_text_by_label.clear()
        self._is_plot_panning = False
        self._plot_pan_state = None

        if self._theme_mode == "dark":
            fig_bg = "#1f2937"
            axes_bg = "#111827"
            text = "#e5e7eb"
            major_grid = "#64748b"
            minor_grid = "#94a3b8"
            major_grid_alpha = 0.42
            minor_grid_alpha = 0.24
            edge = "#dbeafe"
        else:
            fig_bg = "#ffffff"
            axes_bg = "#f8fbff"
            text = "#1f2937"
            major_grid = "#c7d6ea"
            minor_grid = "#dbe5f3"
            major_grid_alpha = 0.62
            minor_grid_alpha = 0.4
            edge = "#1e3a8a"

        palette = (
            "#60a5fa",
            "#f59e0b",
            "#22c55e",
            "#ef4444",
            "#a855f7",
            "#06b6d4",
            "#f97316",
            "#84cc16",
        )

        ax = self._axes
        ax.clear()
        self._figure.patch.set_facecolor(fig_bg)
        self._figure.patch.set_edgecolor(fig_bg)
        self._canvas.setStyleSheet(
            f"background-color: {fig_bg}; border: none;",
        )
        ax.set_facecolor(axes_bg)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(major_grid)
        ax.spines["bottom"].set_color(major_grid)
        ax.tick_params(which="both", colors=text)
        ax.xaxis.label.set_color(text)
        ax.yaxis.label.set_color(text)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.minorticks_on()
        ax.grid(
            True,
            which="major",
            color=major_grid,
            alpha=major_grid_alpha,
            linewidth=0.85,
        )
        ax.grid(
            True,
            which="minor",
            color=minor_grid,
            alpha=minor_grid_alpha,
            linewidth=0.65,
            linestyle=":",
        )
        self._set_hover_annotation_style(text, axes_bg, major_grid)
        self._set_fit_stats_text(None)

        if not curves:
            ax.text(
                0.5,
                0.5,
                "No plot data",
                color=text,
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_xlim(0.0, 1.0)
            ax.set_ylim(0.0, 1.0)
            self._apply_plot_layout()
            self._canvas.draw_idle()
            return

        fit_value = fit_series[0] if fit_series else None
        show_mean_x_overlay = (
            fit_enabled and fit_value is not None and fit_value.kind == "mean_x"
        )
        show_lines = (
            self._show_lines_checkbox.isChecked()
            if self._show_lines_checkbox is not None
            else True
        )
        align_gain_last = self._is_gain_last_alignment_enabled(
            self._plot_y_mode,
        )
        hide_raw_series = self._plot_hide_raw_series or (
            fit_enabled and err_mode != "off"
        )

        for idx, curve in enumerate(curves):
            color = palette[idx % len(palette)]
            x_arr = np.asarray(curve.x_values, dtype=np.float64)
            y_arr = np.asarray(curve.y_values, dtype=np.float64)
            curve_uncertainty_scale = 1.0
            if align_gain_last:
                y_plot_arr, curve_uncertainty_scale, _ = (
                    self._apply_gain_last_alignment(y_arr)
                )
            else:
                y_plot_arr = y_arr
            visible = self._curve_visibility.get(curve.label, True)
            if hide_raw_series:
                artist = ax.plot(
                    [],
                    [],
                    marker="o",
                    linestyle="-",
                    markersize=5,
                    linewidth=1.4,
                    color=color,
                    markeredgecolor=edge,
                    label=curve.label,
                )[0]
                self._set_artist_visible(artist, visible)
                self._curve_artists[curve.label] = artist
                if not self._plot_hide_raw_series:
                    std_arr = np.asarray(
                        curve.std_values,
                        dtype=np.float64,
                    ) * curve_uncertainty_scale
                    sem_arr = np.asarray(
                        curve.sem_values,
                        dtype=np.float64,
                    ) * curve_uncertainty_scale
                    self._plot_points.append(
                        (curve.label, x_arr, y_plot_arr, std_arr, sem_arr),
                    )
                self._curve_visibility.setdefault(curve.label, True)
                continue

            draw_raw_error_bars = err_mode != "off" and not show_mean_x_overlay
            if draw_raw_error_bars:
                err_arr = (
                    np.asarray(curve.error_values, dtype=np.float64)
                    * curve_uncertainty_scale
                )
                err_arr = np.where(
                    np.isfinite(err_arr) & (err_arr >= 0.0),
                    err_arr,
                    np.nan,
                )
                fmt = "o"
                line_style = "None" if fit_enabled or not show_lines else "-"
                artist = ax.errorbar(
                    x_arr,
                    y_plot_arr,
                    yerr=err_arr,
                    fmt=fmt,
                    linestyle=line_style,
                    markersize=5,
                    color=color,
                    markerfacecolor=color,
                    markeredgecolor=edge,
                    ecolor=edge,
                    elinewidth=1.0,
                    capsize=3,
                    linewidth=1.4,
                    label=curve.label,
                )
            else:
                line_style = "None" if fit_enabled or not show_lines else "-"
                artist = ax.plot(
                    x_arr,
                    y_plot_arr,
                    marker="o",
                    linestyle=line_style,
                    markersize=5,
                    linewidth=1.4,
                    color=color,
                    markerfacecolor=color,
                    markeredgecolor=edge,
                    label=curve.label,
                )[0]

            self._set_artist_visible(artist, visible)
            self._curve_artists[curve.label] = artist
            std_arr = (
                np.asarray(curve.std_values, dtype=np.float64)
                * curve_uncertainty_scale
            )
            sem_arr = (
                np.asarray(curve.sem_values, dtype=np.float64)
                * curve_uncertainty_scale
            )
            self._plot_points.append(
                (curve.label, x_arr, y_plot_arr, std_arr, sem_arr),
            )
            self._curve_visibility.setdefault(curve.label, True)

        if fit_enabled and fit_value is not None:
            fit_x_values = np.asarray(fit_value.x_values, dtype=np.float64)
            fit_y_values = np.asarray(fit_value.y_values, dtype=np.float64)
            fit_uncertainty_scale = 1.0
            if align_gain_last:
                fit_y_plot_values, fit_uncertainty_scale, _ = (
                    self._apply_gain_last_alignment(fit_y_values)
                )
            else:
                fit_y_plot_values = fit_y_values
            ax.plot(
                fit_x_values,
                fit_y_plot_values,
                "-",
                linewidth=1.9,
                color=edge,
                alpha=0.95,
                label="_nolegend_",
            )[0]
            data_x = np.asarray([], dtype=np.float64)
            hover_x_chunks: list[np.ndarray] = []
            for curve in curves:
                if not self._curve_visibility.get(curve.label, True):
                    continue
                x_arr = np.asarray(curve.x_values, dtype=np.float64)
                if x_arr.size:
                    hover_x_chunks.append(x_arr)
            if hover_x_chunks:
                data_x = np.unique(np.concatenate(hover_x_chunks))
                data_x = data_x[np.isfinite(data_x)]
            if fit_value.kind == "mean_x" and err_mode != "off":
                fit_err_source = (
                    fit_value.std_values
                    if err_mode == "std"
                    else fit_value.sem_values
                )
                fit_err_arr = (
                    np.asarray(fit_err_source, dtype=np.float64)
                    if fit_err_source is not None
                    else np.asarray([], dtype=np.float64)
                )
                fit_err_arr *= fit_uncertainty_scale
                fit_err_arr = np.where(
                    np.isfinite(fit_err_arr) & (fit_err_arr >= 0.0),
                    fit_err_arr,
                    np.nan,
                )
                if fit_err_arr.size == np.asarray(fit_value.y_values).size:
                    ax.errorbar(
                        fit_x_values,
                        fit_y_plot_values,
                        yerr=fit_err_arr,
                        fmt="o",
                        linestyle="None",
                        markersize=5.5,
                        color=edge,
                        markerfacecolor=edge,
                        markeredgecolor=edge,
                        ecolor=edge,
                        elinewidth=1.15,
                        capsize=3.0,
                        linewidth=0.0,
                        label="_nolegend_",
                    )
            elif fit_value.kind == "mean_x":
                ax.plot(
                    fit_x_values,
                    fit_y_plot_values,
                    marker="o",
                    linestyle="None",
                    markersize=5.5,
                    color=edge,
                    markerfacecolor=edge,
                    markeredgecolor=edge,
                    label="_nolegend_",
                )
            elif (
                fit_value.kind == "linear_fit"
                and err_mode != "off"
                and data_x.size > 0
            ):
                mean_overlay = self._build_mean_x_overlay(curves)
                mean_fit = mean_overlay[0] if mean_overlay else None
                err_by_x: dict[float, float] = {}
                if mean_fit is not None:
                    err_source = (
                        mean_fit.std_values
                        if err_mode == "std"
                        else mean_fit.sem_values
                    )
                    err_arr = (
                        np.asarray(err_source, dtype=np.float64)
                        if err_source is not None
                        else np.asarray([], dtype=np.float64)
                    )
                    for idx, x_value in enumerate(
                        np.asarray(mean_fit.x_values, dtype=np.float64)
                    ):
                        if idx < err_arr.size:
                            err_by_x[self._x_key(float(x_value))] = float(
                                err_arr[idx]
                            )
                trend_err = np.asarray(
                    [
                        err_by_x.get(self._x_key(float(x_value)), float(np.nan))
                        for x_value in data_x
                    ],
                    dtype=np.float64,
                )
                trend_err = np.where(
                    np.isfinite(trend_err) & (trend_err >= 0.0),
                    trend_err,
                    np.nan,
                )
                trend_err *= fit_uncertainty_scale
                if align_gain_last:
                    trend_y = np.interp(
                        data_x,
                        fit_x_values,
                        fit_y_plot_values,
                    )
                else:
                    trend_y = fit_value.slope * data_x + fit_value.intercept
                ax.errorbar(
                    data_x,
                    trend_y,
                    yerr=trend_err,
                    fmt="o",
                    linestyle="None",
                    markersize=5.5,
                    color=edge,
                    markerfacecolor=edge,
                    markeredgecolor=edge,
                    ecolor=edge,
                    elinewidth=1.15,
                    capsize=3.0,
                    linewidth=0.0,
                    label="_nolegend_",
                )
            elif fit_value.kind == "linear_fit" and data_x.size > 0:
                trend_y = (
                    np.interp(
                        data_x,
                        fit_x_values,
                        fit_y_plot_values,
                    )
                    if align_gain_last
                    else fit_value.slope * data_x + fit_value.intercept
                )
                ax.plot(
                    data_x,
                    trend_y,
                    marker="o",
                    linestyle="None",
                    markersize=5.5,
                    color=edge,
                    markerfacecolor=edge,
                    markeredgecolor=edge,
                    label="_nolegend_",
                )
            self._fit_plot_points.append(
                (fit_value.label, fit_x_values, fit_y_plot_values),
            )

            if fit_value.kind == "linear_fit" and data_x.size >= 2:
                dense_count = int(min(256, max(96, data_x.size * 4)))
                dense_x = np.linspace(
                    float(data_x[0]),
                    float(data_x[-1]),
                    dense_count,
                )
                hover_x = np.unique(np.concatenate((data_x, dense_x)))
            elif data_x.size > 0:
                hover_x = data_x
            else:
                hover_x = np.asarray(fit_value.x_values, dtype=np.float64)
            hover_y = (
                (
                    np.interp(hover_x, fit_x_values, fit_y_plot_values)
                    if align_gain_last
                    else fit_value.slope * hover_x + fit_value.intercept
                )
                if hover_x.size and fit_value.kind == "linear_fit"
                else np.asarray(fit_y_plot_values, dtype=np.float64)
                if fit_value.kind == "mean_x"
                else np.asarray([], dtype=np.float64)
            )
            if fit_value.kind == "mean_x":
                mean_x = fit_x_values
                mean_y = fit_y_plot_values
                if mean_x.size and mean_y.size:
                    common_x, _, idx_mean = np.intersect1d(
                        hover_x,
                        mean_x,
                        return_indices=True,
                    )
                    if common_x.size:
                        hover_x = common_x
                        hover_y = mean_y[idx_mean]
            hover_std: Optional[np.ndarray] = None
            hover_sem: Optional[np.ndarray] = None
            if fit_value.kind == "mean_x":
                mean_x = np.asarray(fit_value.x_values, dtype=np.float64)
                mean_std = (
                    np.asarray(fit_value.std_values, dtype=np.float64)
                    if fit_value.std_values is not None
                    else np.asarray([], dtype=np.float64)
                )
                mean_sem = (
                    np.asarray(fit_value.sem_values, dtype=np.float64)
                    if fit_value.sem_values is not None
                    else np.asarray([], dtype=np.float64)
                )
                mean_std *= fit_uncertainty_scale
                mean_sem *= fit_uncertainty_scale
                if (
                    mean_x.size
                    and hover_x.size
                    and mean_std.size == mean_x.size
                    and mean_sem.size == mean_x.size
                ):
                    _, _, idx_mean = np.intersect1d(
                        hover_x,
                        mean_x,
                        return_indices=True,
                    )
                    if idx_mean.size:
                        hover_std = mean_std[idx_mean]
                        hover_sem = mean_sem[idx_mean]

            self._fit_hover_items.append(
                _FitHoverItem(
                    label=fit_value.label,
                    kind=fit_value.kind,
                    x_values=hover_x,
                    y_values=hover_y,
                    std_values=hover_std,
                    sem_values=hover_sem,
                ),
            )
            self._set_fit_stats_text(fit_value)
        else:
            self._set_fit_stats_text(None)

        if curves:
            legend = ax.legend(loc="best", fontsize=8, frameon=True)
            legend_frame = legend.get_frame()
            legend_frame.set_facecolor(axes_bg)
            legend_frame.set_edgecolor(major_grid)
            for text_item in legend.get_texts():
                text_item.set_color(text)
            self._configure_legend_pick(
                legend,
                [curve.label for curve in curves],
            )

        self._autoscale_visible_series()
        self._apply_plot_layout()
        self._canvas.draw_idle()
