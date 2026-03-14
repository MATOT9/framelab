"""Density tokens and adaptive visibility policy for FrameLab UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ui_settings import DensityMode, UiPreferences


class DensityTier(StrEnum):
    """Resolved density tier used by the active UI chrome."""

    COMFORTABLE = "comfortable"
    COMPACT = "compact"


@dataclass(frozen=True, slots=True)
class DensityTokens:
    """Spacing and typography tokens for one density tier."""

    root_margin: int
    page_spacing: int
    panel_margin_h: int
    panel_margin_v: int
    panel_spacing: int
    command_bar_margin_h: int
    command_bar_margin_v: int
    command_bar_spacing: int
    header_margin_h: int
    header_margin_v: int
    header_spacing: int
    summary_card_margin_h: int
    summary_card_margin_v: int
    summary_card_spacing: int
    chip_spacing: int
    chip_padding_h: int
    chip_padding_v: int
    button_padding_h: int
    button_padding_v: int
    input_padding_h: int
    input_padding_v: int
    menu_item_padding_h: int
    menu_item_padding_v: int
    toolbar_padding_h: int
    toolbar_padding_v: int
    tab_padding_h: int
    tab_padding_v: int
    title_pt: int
    subtitle_pt: int
    summary_value_pt: int
    summary_label_pt: int
    chip_pt: int


@dataclass(frozen=True, slots=True)
class AdaptiveUiContext:
    """Current runtime context used to resolve density and visibility."""

    usable_height: int
    active_page: str
    has_processing_banner: bool
    has_loaded_data: bool


@dataclass(frozen=True, slots=True)
class VisibilityPolicy:
    """Resolved visibility defaults for secondary UI chrome."""

    show_subtitles: bool
    show_summary_strip: bool
    collapse_data_advanced_row: bool
    collapse_analysis_plugin_controls: bool
    show_measure_help_labels: bool
    show_plot_help_labels: bool


_COMFORTABLE_TOKENS = DensityTokens(
    root_margin=12,
    page_spacing=10,
    panel_margin_h=12,
    panel_margin_v=10,
    panel_spacing=8,
    command_bar_margin_h=14,
    command_bar_margin_v=12,
    command_bar_spacing=8,
    header_margin_h=16,
    header_margin_v=14,
    header_spacing=8,
    summary_card_margin_h=12,
    summary_card_margin_v=10,
    summary_card_spacing=4,
    chip_spacing=8,
    chip_padding_h=10,
    chip_padding_v=4,
    button_padding_h=12,
    button_padding_v=6,
    input_padding_h=7,
    input_padding_v=5,
    menu_item_padding_h=18,
    menu_item_padding_v=6,
    toolbar_padding_h=8,
    toolbar_padding_v=7,
    tab_padding_h=12,
    tab_padding_v=6,
    title_pt=20,
    subtitle_pt=12,
    summary_value_pt=16,
    summary_label_pt=11,
    chip_pt=11,
)

_COMPACT_TOKENS = DensityTokens(
    root_margin=8,
    page_spacing=6,
    panel_margin_h=10,
    panel_margin_v=8,
    panel_spacing=6,
    command_bar_margin_h=10,
    command_bar_margin_v=8,
    command_bar_spacing=6,
    header_margin_h=12,
    header_margin_v=10,
    header_spacing=6,
    summary_card_margin_h=8,
    summary_card_margin_v=6,
    summary_card_spacing=3,
    chip_spacing=6,
    chip_padding_h=8,
    chip_padding_v=3,
    button_padding_h=10,
    button_padding_v=5,
    input_padding_h=6,
    input_padding_v=4,
    menu_item_padding_h=14,
    menu_item_padding_v=5,
    toolbar_padding_h=6,
    toolbar_padding_v=5,
    tab_padding_h=10,
    tab_padding_v=5,
    title_pt=18,
    subtitle_pt=11,
    summary_value_pt=15,
    summary_label_pt=10,
    chip_pt=10,
)

_AUTO_COMFORTABLE_MIN_HEIGHT = 900
_AUTO_SUBTITLE_MIN_HEIGHT = 820
_AUTO_MEASURE_SUMMARY_MIN_HEIGHT = 700
_AUTO_ANALYSIS_SUMMARY_MIN_HEIGHT = 840
_AUTO_DATA_SUMMARY_MIN_HEIGHT = 820
_AUTO_MEASURE_HELP_MIN_HEIGHT = 860
_AUTO_PLOT_HELP_MIN_HEIGHT = 920
_AUTO_DATA_ADVANCED_COLLAPSE_HEIGHT = 860
_AUTO_ANALYSIS_CONTROLS_COLLAPSE_HEIGHT = 900


def comfortable_density_tokens() -> DensityTokens:
    """Return the baseline comfortable density tokens."""

    return _COMFORTABLE_TOKENS


def compact_density_tokens() -> DensityTokens:
    """Return the compact density tokens."""

    return _COMPACT_TOKENS


class UiDensityResolver:
    """Resolve active density tokens and adaptive visibility defaults."""

    def resolve_tier(
        self,
        mode: DensityMode,
        context: AdaptiveUiContext,
    ) -> DensityTier:
        """Resolve the active density tier for one mode and context."""

        if mode == DensityMode.COMFORTABLE:
            return DensityTier.COMFORTABLE
        if mode == DensityMode.COMPACT:
            return DensityTier.COMPACT
        if context.usable_height >= _AUTO_COMFORTABLE_MIN_HEIGHT:
            return DensityTier.COMFORTABLE
        return DensityTier.COMPACT

    def tokens_for_mode(
        self,
        mode: DensityMode,
        context: AdaptiveUiContext,
    ) -> DensityTokens:
        """Return active tokens for the requested density mode."""

        tier = self.resolve_tier(mode, context)
        if tier == DensityTier.COMFORTABLE:
            return _COMFORTABLE_TOKENS
        return _COMPACT_TOKENS

    def visibility_policy(
        self,
        mode: DensityMode,
        context: AdaptiveUiContext,
        *,
        preferences: UiPreferences | None = None,
        user_overrides: dict[str, bool | None] | None = None,
    ) -> VisibilityPolicy:
        """Return resolved secondary-chrome visibility defaults."""

        prefs = preferences or UiPreferences()
        overrides = user_overrides or {}
        tier = self.resolve_tier(mode, context)
        show_subtitles = prefs.show_page_subtitles
        show_summary_strip = not prefs.collapse_summary_strips_by_default
        show_measure_help_labels = tier == DensityTier.COMFORTABLE
        show_plot_help_labels = tier == DensityTier.COMFORTABLE
        collapse_data_advanced_row = prefs.collapse_data_advanced_row_by_default
        collapse_analysis_plugin_controls = (
            prefs.collapse_analysis_plugin_controls_by_default
        )

        if mode == DensityMode.AUTO:
            show_subtitles = (
                prefs.show_page_subtitles
                and context.usable_height >= _AUTO_SUBTITLE_MIN_HEIGHT
            )
            if context.active_page == "measure":
                show_summary_strip = (
                    not prefs.collapse_summary_strips_by_default
                    and context.usable_height >= _AUTO_MEASURE_SUMMARY_MIN_HEIGHT
                )
            elif context.active_page == "analysis":
                show_summary_strip = (
                    not prefs.collapse_summary_strips_by_default
                    and context.usable_height >= _AUTO_ANALYSIS_SUMMARY_MIN_HEIGHT
                )
            else:
                show_summary_strip = (
                    not prefs.collapse_summary_strips_by_default
                    and context.usable_height >= _AUTO_DATA_SUMMARY_MIN_HEIGHT
                )
            show_measure_help_labels = (
                context.active_page == "measure"
                and context.usable_height >= _AUTO_MEASURE_HELP_MIN_HEIGHT
            )
            show_plot_help_labels = (
                context.active_page == "analysis"
                and context.usable_height >= _AUTO_PLOT_HELP_MIN_HEIGHT
            )
            collapse_data_advanced_row = (
                prefs.collapse_data_advanced_row_by_default
                or context.usable_height < _AUTO_DATA_ADVANCED_COLLAPSE_HEIGHT
            )
            collapse_analysis_plugin_controls = (
                prefs.collapse_analysis_plugin_controls_by_default
                or context.usable_height < _AUTO_ANALYSIS_CONTROLS_COLLAPSE_HEIGHT
            )

        data_override = overrides.get("data.advanced_row")
        if data_override is not None:
            collapse_data_advanced_row = not bool(data_override)

        analysis_override = overrides.get("analysis.plugin_controls")
        if analysis_override is not None:
            collapse_analysis_plugin_controls = not bool(analysis_override)

        summary_override = overrides.get(f"{context.active_page}.summary_strip")
        if summary_override is not None:
            show_summary_strip = bool(summary_override)

        return VisibilityPolicy(
            show_subtitles=show_subtitles,
            show_summary_strip=show_summary_strip,
            collapse_data_advanced_row=collapse_data_advanced_row,
            collapse_analysis_plugin_controls=collapse_analysis_plugin_controls,
            show_measure_help_labels=show_measure_help_labels,
            show_plot_help_labels=show_plot_help_labels,
        )


__all__ = [
    "AdaptiveUiContext",
    "comfortable_density_tokens",
    "compact_density_tokens",
    "DensityTier",
    "DensityTokens",
    "UiDensityResolver",
    "VisibilityPolicy",
]
