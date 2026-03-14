"""Base interfaces for analysis plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping

import numpy as np
from PySide6 import QtWidgets as qtw

from ..registry import PluginUiCapabilities


@dataclass(frozen=True)
class AnalysisRecord:
    """Single image record available to analysis plugins."""

    path: str
    metadata: Mapping[str, object]
    mean: float
    std: float
    sem: float


@dataclass(frozen=True)
class AnalysisContext:
    """Context bundle passed to every analysis plugin."""

    mode: str
    records: tuple[AnalysisRecord, ...]
    metadata_fields: tuple[str, ...]
    normalization_enabled: bool
    normalization_scale: float


class AnalysisPlugin(ABC):
    """Interface implemented by pluggable analyses."""

    plugin_id: str = "base"
    display_name: str = "Base Analysis"
    description: str = ""
    target_page: str = "analysis"
    dependencies: tuple[str, ...] = ()
    ui_capabilities: PluginUiCapabilities = PluginUiCapabilities()

    @abstractmethod
    def create_widget(self, parent: qtw.QWidget) -> qtw.QWidget:
        """Create and return plugin UI widget."""

    def create_controls_widget(
        self,
        parent: qtw.QWidget,
    ) -> qtw.QWidget | None:
        """Create and return an optional host-managed controls widget."""

        _ = parent
        return None

    def create_workspace_widget(
        self,
        parent: qtw.QWidget,
    ) -> qtw.QWidget | None:
        """Create and return an optional host-managed workspace widget."""

        _ = parent
        return None

    @abstractmethod
    def on_context_changed(self, context: AnalysisContext) -> None:
        """Handle dataset/metric updates from the host app."""

    def set_theme(self, mode: str) -> None:
        """Update theme-dependent rendering state.

        Parameters
        ----------
        mode : str
            Requested theme name.
        """
        _ = mode

    def populate_menu(self, menu: qtw.QMenu) -> None:
        """Populate plugin-specific actions under the host Plugins menu.

        Parameters
        ----------
        menu : qtw.QMenu
            Menu instance already created by the host app for this plugin.
        """
        _ = menu

    def has_collapsible_controls(self) -> bool:
        """Return whether the plugin exposes a collapsible controls surface."""

        return False

    def set_controls_collapsed(self, collapsed: bool) -> None:
        """Show or hide the plugin's secondary controls surface."""

        _ = collapsed

    def set_secondary_help_visible(self, visible: bool) -> None:
        """Show or hide secondary hint text while keeping tooltips available."""

        _ = visible

    def workspace_splitter(self) -> qtw.QSplitter | None:
        """Return an optional plugin workspace splitter for persistence."""

        return None

    @staticmethod
    def _safe_float(value: object) -> float:
        """Convert values to float with NaN fallback."""
        try:
            return float(value)
        except Exception:
            return float(np.nan)
