"""Tests for density-aware theme stylesheet rendering."""

from __future__ import annotations

import unittest

from framelab.ui_density import compact_density_tokens, comfortable_density_tokens
from stylesheets import build_dark_theme, build_light_theme


class DensityAwareStylesheetTests(unittest.TestCase):
    def test_light_and_dark_builders_include_density_values(self) -> None:
        compact = compact_density_tokens()
        dark_sheet = build_dark_theme(compact)
        light_sheet = build_light_theme(compact)

        self.assertIn("font-size: 18px;", dark_sheet)
        self.assertIn("padding: 5px 10px;", dark_sheet)
        self.assertIn("padding: 5px 10px;", light_sheet)

    def test_compact_stylesheet_is_tighter_than_comfortable(self) -> None:
        comfortable_sheet = build_dark_theme(comfortable_density_tokens())
        compact_sheet = build_dark_theme(compact_density_tokens())

        self.assertIn("padding: 6px 12px;", comfortable_sheet)
        self.assertIn("padding: 5px 10px;", compact_sheet)
        self.assertIn("font-size: 20px;", comfortable_sheet)
        self.assertIn("font-size: 18px;", compact_sheet)


if __name__ == "__main__":
    unittest.main()
