"""Mixins used to assemble the main FrameLab window."""

from .analysis import AnalysisPageMixin
from .chrome import WindowChromeMixin
from .data_page import DataPageMixin
from .dataset_loading import DatasetLoadingMixin
from .inspect_page import InspectPageMixin
from .metrics_runtime import MetricsRuntimeMixin
from .window_actions import WindowActionsMixin

__all__ = [
    "AnalysisPageMixin",
    "DataPageMixin",
    "DatasetLoadingMixin",
    "InspectPageMixin",
    "MetricsRuntimeMixin",
    "WindowChromeMixin",
    "WindowActionsMixin",
]
