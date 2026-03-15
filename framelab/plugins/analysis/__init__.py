"""Analysis plugin interfaces and registry."""

from ._base import AnalysisContext, AnalysisPlugin, AnalysisRecord, AnalysisScopeNode
from ._registry import (
    load_analysis_plugins,
    load_enabled_analysis_plugins,
    register_analysis_plugin,
)

__all__ = [
    "AnalysisContext",
    "AnalysisPlugin",
    "AnalysisRecord",
    "AnalysisScopeNode",
    "load_analysis_plugins",
    "load_enabled_analysis_plugins",
    "register_analysis_plugin",
]
