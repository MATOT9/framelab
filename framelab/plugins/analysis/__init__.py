"""Analysis plugin interfaces and registry."""

from ._base import (
    AnalysisContext,
    AnalysisMetricFamilyStatus,
    AnalysisPlugin,
    AnalysisRecord,
    AnalysisScopeNode,
)
from ._registry import (
    load_analysis_plugins,
    load_enabled_analysis_plugins,
    register_analysis_plugin,
)

__all__ = [
    "AnalysisContext",
    "AnalysisMetricFamilyStatus",
    "AnalysisPlugin",
    "AnalysisRecord",
    "AnalysisScopeNode",
    "load_analysis_plugins",
    "load_enabled_analysis_plugins",
    "register_analysis_plugin",
]
