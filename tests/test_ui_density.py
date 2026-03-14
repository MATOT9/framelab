"""Tests for density token resolution and adaptive visibility policy."""

from __future__ import annotations

import pytest
from framelab.ui_density import AdaptiveUiContext, DensityTier, UiDensityResolver
from framelab.ui_settings import DensityMode, UiPreferences


pytestmark = [pytest.mark.fast, pytest.mark.core]


@pytest.fixture
def resolver() -> UiDensityResolver:
    return UiDensityResolver()


def _context(
    *,
    usable_height: int,
    active_page: str = "data",
    has_processing_banner: bool = False,
    has_loaded_data: bool = False,
) -> AdaptiveUiContext:
    return AdaptiveUiContext(
        usable_height=usable_height,
        active_page=active_page,
        has_processing_banner=has_processing_banner,
        has_loaded_data=has_loaded_data,
    )


def test_auto_resolves_comfortable_tier_at_tall_heights(
    resolver: UiDensityResolver,
) -> None:
    tier = resolver.resolve_tier(
        DensityMode.AUTO,
        _context(usable_height=940),
    )
    tokens = resolver.tokens_for_mode(
        DensityMode.AUTO,
        _context(usable_height=940),
    )

    assert tier == DensityTier.COMFORTABLE
    assert tokens.root_margin == 12
    assert tokens.title_pt == 20


def test_auto_resolves_compact_tier_at_short_heights(
    resolver: UiDensityResolver,
) -> None:
    tier = resolver.resolve_tier(
        DensityMode.AUTO,
        _context(usable_height=740),
    )
    tokens = resolver.tokens_for_mode(
        DensityMode.AUTO,
        _context(usable_height=740),
    )

    assert tier == DensityTier.COMPACT
    assert tokens.root_margin == 8
    assert tokens.title_pt == 18


def test_auto_visibility_collapses_analysis_controls_before_measure_summary(
    resolver: UiDensityResolver,
) -> None:
    prefs = UiPreferences()
    analysis_policy = resolver.visibility_policy(
        DensityMode.AUTO,
        _context(usable_height=880, active_page="analysis"),
        preferences=prefs,
    )
    measure_policy = resolver.visibility_policy(
        DensityMode.AUTO,
        _context(usable_height=880, active_page="measure"),
        preferences=prefs,
    )

    assert analysis_policy.collapse_analysis_plugin_controls
    assert measure_policy.show_summary_strip


def test_user_override_prevents_auto_collapse(
    resolver: UiDensityResolver,
) -> None:
    prefs = UiPreferences()
    policy = resolver.visibility_policy(
        DensityMode.AUTO,
        _context(usable_height=720, active_page="analysis"),
        preferences=prefs,
        user_overrides={"analysis.plugin_controls": True},
    )

    assert not policy.collapse_analysis_plugin_controls


def test_subtitle_preference_still_caps_auto_visibility(
    resolver: UiDensityResolver,
) -> None:
    policy = resolver.visibility_policy(
        DensityMode.AUTO,
        _context(usable_height=950, active_page="data"),
        preferences=UiPreferences(show_page_subtitles=False),
    )

    assert not policy.show_subtitles
