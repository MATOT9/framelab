"""Tests for density-aware theme stylesheet rendering."""

from __future__ import annotations

import pytest

from framelab.ui_density import compact_density_tokens, comfortable_density_tokens
from stylesheets import build_dark_theme, build_light_theme


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_light_and_dark_builders_include_density_values() -> None:
    compact = compact_density_tokens()
    dark_sheet = build_dark_theme(compact)
    light_sheet = build_light_theme(compact)

    assert "font-size: 18px;" in dark_sheet
    assert "padding: 5px 10px;" in dark_sheet
    assert "padding: 5px 10px;" in light_sheet


def test_compact_stylesheet_is_tighter_than_comfortable() -> None:
    comfortable_sheet = build_dark_theme(comfortable_density_tokens())
    compact_sheet = build_dark_theme(compact_density_tokens())

    assert "padding: 6px 12px;" in comfortable_sheet
    assert "padding: 5px 10px;" in compact_sheet
    assert "font-size: 20px;" in comfortable_sheet
    assert "font-size: 18px;" in compact_sheet
