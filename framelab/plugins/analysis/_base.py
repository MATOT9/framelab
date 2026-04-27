"""Base interfaces for analysis plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Mapping

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
class AnalysisScopeNode:
    """One workflow node in the active context ancestry chain."""

    node_id: str
    type_id: str
    display_name: str
    folder_path: str


@dataclass(frozen=True)
class AnalysisMetricFamilyStatus:
    """Read-only metric-family readiness status for analysis plugins."""

    family: str
    state: str
    message: str = ""

    @property
    def ready(self) -> bool:
        """Return whether the family is ready for plugin consumption."""

        return self.state == "ready"


@dataclass(frozen=True)
class AnalysisContext:
    """Context bundle passed to every analysis plugin."""

    mode: str
    records: tuple[AnalysisRecord, ...]
    metadata_fields: tuple[str, ...]
    normalization_enabled: bool
    normalization_scale: float
    data_signature: str = ""
    workflow_profile_id: str | None = None
    workflow_anchor_type_id: str | None = None
    workflow_anchor_label: str | None = None
    workflow_anchor_path: str | None = None
    workflow_is_partial: bool = False
    active_node_id: str | None = None
    active_node_type: str | None = None
    active_node_path: str | None = None
    active_scope_kind: str | None = None
    active_scope_label: str | None = None
    dataset_scope_root: str | None = None
    dataset_scope_source: str = "manual"
    effective_metadata: Mapping[str, object] = field(default_factory=dict)
    metadata_sources: Mapping[str, str] = field(default_factory=dict)
    ancestor_chain: tuple[AnalysisScopeNode, ...] = ()
    metric_family_statuses: Mapping[str, AnalysisMetricFamilyStatus] = field(
        default_factory=dict,
    )

    def metric_family_status(
        self,
        family: str,
    ) -> AnalysisMetricFamilyStatus:
        """Return readiness status for one metric family."""

        key = str(family)
        return self.metric_family_statuses.get(
            key,
            AnalysisMetricFamilyStatus(key, "not_requested"),
        )


@dataclass(frozen=True)
class AnalysisPreparationJob:
    """Optional background preparation requested by an analysis plugin."""

    label: str
    prepare: Callable[[], Any]


class AnalysisPlugin(ABC):
    """Interface implemented by pluggable analyses."""

    plugin_id: str = "base"
    display_name: str = "Base Analysis"
    description: str = ""
    target_page: str = "analysis"
    dependencies: tuple[str, ...] = ()
    ui_capabilities: PluginUiCapabilities = PluginUiCapabilities()
    required_metric_families: tuple[str, ...] = ()
    optional_metric_families: tuple[str, ...] = ()
    run_action_label: str = "Run Analysis"

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

    def run_analysis(self, context: AnalysisContext) -> None:
        """Run the plugin's explicit analysis action.

        The default keeps older plugins functional. New or migrated plugins should
        keep ``on_context_changed`` passive and put table/plot work behind this
        explicit hook.
        """

        self.on_context_changed(context)

    def prepare_analysis(
        self,
        context: AnalysisContext,
    ) -> AnalysisPreparationJob | None:
        """Return optional background work needed before applying analysis.

        Plugins that return a job must keep the callable independent of Qt
        widgets and mutable host state. The host runs it on a worker thread and
        passes the result to ``apply_prepared_analysis`` on the UI thread.
        """

        _ = context
        return None

    def apply_prepared_analysis(self, prepared: Any) -> None:
        """Apply one prepared background result on the UI thread."""

        _ = prepared

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
