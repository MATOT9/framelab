"""Shared matplotlib layout helpers for Qt-embedded plots."""

from __future__ import annotations


def adjust_single_axes_layout(
    figure,
    axes,
    canvas,
    *,
    base_left: float = 0.12,
    right: float = 0.985,
    bottom: float = 0.16,
    top: float = 0.96,
    max_left: float = 0.97,
) -> None:
    """Expand subplot margins until axis labels fit inside the rendered figure."""

    if figure is None or axes is None or canvas is None:
        return

    figure.subplots_adjust(
        left=base_left,
        right=right,
        bottom=bottom,
        top=top,
    )

    try:
        canvas.draw()
        figure.tight_layout(pad=0.6)
        resolved = figure.subplotpars
        resolved_left = min(max(base_left, float(resolved.left)), max_left)
        resolved_right = min(right, float(resolved.right))
        resolved_bottom = max(bottom, float(resolved.bottom))
        resolved_top = min(top, float(resolved.top))
        if resolved_right <= resolved_left:
            resolved_right = right
        if resolved_top <= resolved_bottom:
            resolved_top = top
        figure.subplots_adjust(
            left=resolved_left,
            right=resolved_right,
            bottom=resolved_bottom,
            top=resolved_top,
        )
    except Exception:
        pass

    for _ in range(8):
        try:
            canvas.draw()
            renderer = canvas.get_renderer()
        except Exception:
            return
        if renderer is None:
            return
        try:
            figure_bbox = figure.get_window_extent(renderer)
            axes_bbox = axes.get_window_extent(renderer)
            tight_bbox = axes.get_tightbbox(renderer)
        except Exception:
            return
        if (
            figure_bbox.width <= 0.0
            or axes_bbox.width <= 0.0
            or tight_bbox.width <= 0.0
        ):
            return

        figure_width = float(figure_bbox.width)
        current_left = float(figure.subplotpars.left)
        desired_left = current_left

        desired_left = max(
            desired_left,
            max(0.0, float(axes_bbox.x0) - float(tight_bbox.x0) + 8.0)
            / figure_width,
        )

        overflow_px = 1.0 - float(tight_bbox.x0)
        if overflow_px > 0.0:
            desired_left = max(
                desired_left,
                current_left + (overflow_px + 4.0) / figure_width,
            )

        bounded_left = min(max(base_left, desired_left), max_left)
        if abs(bounded_left - current_left) < 0.002:
            break

        figure.subplots_adjust(
            left=bounded_left,
            right=right,
            bottom=bottom,
            top=top,
        )

    try:
        canvas.draw()
        renderer = canvas.get_renderer()
        figure_bbox = figure.get_window_extent(renderer)
        tight_bbox = axes.get_tightbbox(renderer)
    except Exception:
        return
    if figure_bbox.width <= 0.0 or tight_bbox.x0 >= 1.0:
        return

    current_left = float(figure.subplotpars.left)
    desired_left = current_left + (1.0 - float(tight_bbox.x0) + 6.0) / float(
        figure_bbox.width,
    )
    bounded_left = min(max(base_left, desired_left), max_left)
    if bounded_left <= current_left + 0.001:
        return
    figure.subplots_adjust(
        left=bounded_left,
        right=right,
        bottom=bottom,
        top=top,
    )
