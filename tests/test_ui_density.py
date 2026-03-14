"""Tests for density token resolution and adaptive visibility policy."""

from __future__ import annotations

import unittest

from framelab.ui_density import AdaptiveUiContext, DensityTier, UiDensityResolver
from framelab.ui_settings import DensityMode, UiPreferences


class UiDensityResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = UiDensityResolver()

    @staticmethod
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

    def test_auto_resolves_comfortable_tier_at_tall_heights(self) -> None:
        tier = self.resolver.resolve_tier(
            DensityMode.AUTO,
            self._context(usable_height=940),
        )
        tokens = self.resolver.tokens_for_mode(
            DensityMode.AUTO,
            self._context(usable_height=940),
        )

        self.assertEqual(tier, DensityTier.COMFORTABLE)
        self.assertEqual(tokens.root_margin, 12)
        self.assertEqual(tokens.title_pt, 20)

    def test_auto_resolves_compact_tier_at_short_heights(self) -> None:
        tier = self.resolver.resolve_tier(
            DensityMode.AUTO,
            self._context(usable_height=740),
        )
        tokens = self.resolver.tokens_for_mode(
            DensityMode.AUTO,
            self._context(usable_height=740),
        )

        self.assertEqual(tier, DensityTier.COMPACT)
        self.assertEqual(tokens.root_margin, 8)
        self.assertEqual(tokens.title_pt, 18)

    def test_auto_visibility_collapses_analysis_controls_before_measure_summary(self) -> None:
        prefs = UiPreferences()
        analysis_policy = self.resolver.visibility_policy(
            DensityMode.AUTO,
            self._context(usable_height=880, active_page="analysis"),
            preferences=prefs,
        )
        measure_policy = self.resolver.visibility_policy(
            DensityMode.AUTO,
            self._context(usable_height=880, active_page="measure"),
            preferences=prefs,
        )

        self.assertTrue(analysis_policy.collapse_analysis_plugin_controls)
        self.assertTrue(measure_policy.show_summary_strip)

    def test_user_override_prevents_auto_collapse(self) -> None:
        prefs = UiPreferences()
        policy = self.resolver.visibility_policy(
            DensityMode.AUTO,
            self._context(usable_height=720, active_page="analysis"),
            preferences=prefs,
            user_overrides={"analysis.plugin_controls": True},
        )

        self.assertFalse(policy.collapse_analysis_plugin_controls)

    def test_subtitle_preference_still_caps_auto_visibility(self) -> None:
        policy = self.resolver.visibility_policy(
            DensityMode.AUTO,
            self._context(usable_height=950, active_page="data"),
            preferences=UiPreferences(show_page_subtitles=False),
        )

        self.assertFalse(policy.show_subtitles)


if __name__ == "__main__":
    unittest.main()
