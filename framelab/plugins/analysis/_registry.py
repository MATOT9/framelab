"""Registry and discovery helpers for analysis plugins."""

from __future__ import annotations

from typing import Iterable, Type

from ._base import AnalysisPlugin
from ..registry import (
    load_enabled_page_plugins,
    load_page_plugins,
    register_page_plugin,
)


def register_analysis_plugin(
    plugin_cls: Type[AnalysisPlugin],
) -> Type[AnalysisPlugin]:
    """Register an analysis plugin class."""
    plugin_id = getattr(plugin_cls, "plugin_id", "")
    if not plugin_id:
        raise ValueError("analysis plugin must define a non-empty plugin_id")
    register_page_plugin(plugin_cls, page="analysis")
    return plugin_cls


def _sorted_analysis_plugins(
    plugin_classes: Iterable[Type[AnalysisPlugin]],
) -> list[Type[AnalysisPlugin]]:
    """Return plugin classes sorted by display name."""
    return sorted(
        plugin_classes,
        key=lambda cls: cls.display_name.lower(),
    )


def load_enabled_analysis_plugins(
    enabled_plugin_ids: Iterable[str],
) -> list[Type[AnalysisPlugin]]:
    """Return enabled analysis plugins sorted by display name."""
    return _sorted_analysis_plugins(
        load_enabled_page_plugins("analysis", enabled_plugin_ids),
    )


def load_analysis_plugins(
    enabled_plugin_ids: Iterable[str] | None = None,
) -> list[Type[AnalysisPlugin]]:
    """Return analysis plugins sorted by display name."""
    return _sorted_analysis_plugins(
        load_page_plugins("analysis", enabled_plugin_ids),
    )
