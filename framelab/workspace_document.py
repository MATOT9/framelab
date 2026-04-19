"""Versioned JSON-backed workspace document persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = 1


def _clean_text(value: object | None) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _parse_int(value: object, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_float(value: object, default: float | None = None) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    parsed: list[int] = []
    for item in value:
        number = _parse_int(item)
        if number is None:
            return []
        parsed.append(int(number))
    return parsed


def _parse_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    parsed: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        parsed.append(text)
    return parsed


def _parse_bool_map(value: object) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, bool] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip().lower()
        if not key:
            continue
        parsed[key] = _parse_bool(raw_value, False)
    return parsed


def _parse_splitter_map(value: object) -> dict[str, list[int]]:
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, list[int]] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip().lower()
        if not key:
            continue
        sizes = _parse_int_list(raw_value)
        if sizes:
            parsed[key] = sizes
    return parsed


def _parse_roi_rect(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    numbers = [_parse_int(item) for item in value]
    if any(number is None for number in numbers):
        return None
    x0, y0, x1, y1 = (int(number) for number in numbers if number is not None)
    return (x0, y0, x1, y1)


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


@dataclass(slots=True)
class WorkspaceDocumentWorkflowState:
    """Workflow context restored from one workspace document."""

    workspace_root: str | None = None
    profile_id: str | None = None
    anchor_type_id: str | None = None
    active_node_id: str | None = None


@dataclass(slots=True)
class WorkspaceDocumentDatasetState:
    """Dataset and selection state restored from one workspace document."""

    scope_source: str | None = None
    scan_root: str | None = None
    selected_image_path: str | None = None
    skip_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkspaceDocumentMeasureState:
    """Measure-page runtime state persisted in one workspace document."""

    average_mode: str = "none"
    threshold_value: float = 65520.0
    low_signal_threshold_value: float = 0.0
    avg_count_value: int = 32
    rounding_mode: str = "off"
    normalize_intensity_values: bool = False
    roi_rect: tuple[int, int, int, int] | None = None
    roi_applied_to_all: bool = False


@dataclass(slots=True)
class WorkspaceDocumentBackgroundState:
    """Background-reference settings persisted in one workspace document."""

    enabled: bool = False
    source_mode: str = "single_file"
    clip_negative: bool = True
    exposure_policy: str = "require_match"
    no_match_policy: str = "fallback_raw"
    source_path: str | None = None


@dataclass(slots=True)
class WorkspaceDocumentUiState:
    """UI state restored from one workspace document."""

    active_page: str = "data"
    analysis_plugin_id: str | None = None
    show_image_preview: bool = True
    show_histogram_preview: bool = False
    panel_states: dict[str, bool] = field(default_factory=dict)
    splitter_sizes: dict[str, list[int]] = field(default_factory=dict)


@dataclass(slots=True)
class WorkspaceDocumentSnapshot:
    """Complete structured payload for one ``.framelab`` workspace file."""

    workflow: WorkspaceDocumentWorkflowState = field(
        default_factory=WorkspaceDocumentWorkflowState,
    )
    dataset: WorkspaceDocumentDatasetState = field(
        default_factory=WorkspaceDocumentDatasetState,
    )
    measure: WorkspaceDocumentMeasureState = field(
        default_factory=WorkspaceDocumentMeasureState,
    )
    background: WorkspaceDocumentBackgroundState = field(
        default_factory=WorkspaceDocumentBackgroundState,
    )
    ui: WorkspaceDocumentUiState = field(default_factory=WorkspaceDocumentUiState)

    def to_payload(self) -> dict[str, Any]:
        """Return the normalized JSON payload for on-disk persistence."""

        return {
            "schema_version": _SCHEMA_VERSION,
            "workflow": {
                "workspace_root": self.workflow.workspace_root,
                "profile_id": self.workflow.profile_id,
                "anchor_type_id": self.workflow.anchor_type_id,
                "active_node_id": self.workflow.active_node_id,
            },
            "dataset": {
                "scope_source": self.dataset.scope_source,
                "scan_root": self.dataset.scan_root,
                "selected_image_path": self.dataset.selected_image_path,
                "skip_patterns": list(self.dataset.skip_patterns),
            },
            "measure": {
                "average_mode": self.measure.average_mode,
                "threshold_value": self.measure.threshold_value,
                "low_signal_threshold_value": self.measure.low_signal_threshold_value,
                "avg_count_value": self.measure.avg_count_value,
                "rounding_mode": self.measure.rounding_mode,
                "normalize_intensity_values": self.measure.normalize_intensity_values,
                "roi_rect": (
                    list(self.measure.roi_rect)
                    if self.measure.roi_rect is not None
                    else None
                ),
                "roi_applied_to_all": self.measure.roi_applied_to_all,
            },
            "background": {
                "enabled": self.background.enabled,
                "source_mode": self.background.source_mode,
                "clip_negative": self.background.clip_negative,
                "exposure_policy": self.background.exposure_policy,
                "no_match_policy": self.background.no_match_policy,
                "source_path": self.background.source_path,
            },
            "ui": {
                "active_page": self.ui.active_page,
                "analysis_plugin_id": self.ui.analysis_plugin_id,
                "show_image_preview": self.ui.show_image_preview,
                "show_histogram_preview": self.ui.show_histogram_preview,
                "panel_states": dict(sorted(self.ui.panel_states.items())),
                "splitter_sizes": {
                    key: [int(size) for size in value]
                    for key, value in sorted(self.ui.splitter_sizes.items())
                },
            },
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WorkspaceDocumentSnapshot:
        """Build a snapshot from one parsed JSON payload."""

        version = _parse_int(payload.get("schema_version"))
        if version != _SCHEMA_VERSION:
            raise ValueError(
                "Unsupported workspace document schema version: "
                f"{payload.get('schema_version')!r}",
            )

        workflow = _section(payload, "workflow")
        dataset = _section(payload, "dataset")
        measure = _section(payload, "measure")
        background = _section(payload, "background")
        ui = _section(payload, "ui")

        average_mode = _clean_text(measure.get("average_mode")) or "none"
        if average_mode not in {"none", "topk", "roi"}:
            average_mode = "none"
        rounding_mode = _clean_text(measure.get("rounding_mode")) or "off"
        if rounding_mode not in {"off", "std", "stderr"}:
            rounding_mode = "off"
        active_page = _clean_text(ui.get("active_page")) or "data"
        if active_page not in {"data", "measure", "analysis"}:
            active_page = "data"

        return cls(
            workflow=WorkspaceDocumentWorkflowState(
                workspace_root=_clean_text(workflow.get("workspace_root")),
                profile_id=_clean_text(workflow.get("profile_id")),
                anchor_type_id=_clean_text(workflow.get("anchor_type_id")),
                active_node_id=_clean_text(workflow.get("active_node_id")),
            ),
            dataset=WorkspaceDocumentDatasetState(
                scope_source=_clean_text(dataset.get("scope_source")),
                scan_root=_clean_text(dataset.get("scan_root")),
                selected_image_path=_clean_text(dataset.get("selected_image_path")),
                skip_patterns=_parse_string_list(dataset.get("skip_patterns")),
            ),
            measure=WorkspaceDocumentMeasureState(
                average_mode=average_mode,
                threshold_value=_parse_float(
                    measure.get("threshold_value"),
                    65520.0,
                )
                or 65520.0,
                low_signal_threshold_value=_parse_float(
                    measure.get("low_signal_threshold_value"),
                    0.0,
                )
                or 0.0,
                avg_count_value=_parse_int(measure.get("avg_count_value"), 32) or 32,
                rounding_mode=rounding_mode,
                normalize_intensity_values=_parse_bool(
                    measure.get("normalize_intensity_values"),
                    False,
                ),
                roi_rect=_parse_roi_rect(measure.get("roi_rect")),
                roi_applied_to_all=_parse_bool(
                    measure.get("roi_applied_to_all"),
                    False,
                ),
            ),
            background=WorkspaceDocumentBackgroundState(
                enabled=_parse_bool(background.get("enabled"), False),
                source_mode=_clean_text(background.get("source_mode"))
                or "single_file",
                clip_negative=_parse_bool(
                    background.get("clip_negative"),
                    True,
                ),
                exposure_policy=_clean_text(background.get("exposure_policy"))
                or "require_match",
                no_match_policy=_clean_text(background.get("no_match_policy"))
                or "fallback_raw",
                source_path=_clean_text(background.get("source_path")),
            ),
            ui=WorkspaceDocumentUiState(
                active_page=active_page,
                analysis_plugin_id=_clean_text(ui.get("analysis_plugin_id")),
                show_image_preview=_parse_bool(
                    ui.get("show_image_preview"),
                    True,
                ),
                show_histogram_preview=_parse_bool(
                    ui.get("show_histogram_preview"),
                    False,
                ),
                panel_states=_parse_bool_map(ui.get("panel_states")),
                splitter_sizes=_parse_splitter_map(ui.get("splitter_sizes")),
            ),
        )


class WorkspaceDocumentStore:
    """Read and write versioned ``.framelab`` workspace documents."""

    def load(self, path: Path | str) -> WorkspaceDocumentSnapshot:
        """Load one workspace document from disk."""

        document_path = Path(path).expanduser()
        try:
            payload = json.loads(document_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"Workspace file not found: {document_path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid workspace file JSON: {document_path}") from exc
        except OSError as exc:
            raise ValueError(f"Could not read workspace file: {document_path}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Workspace file must contain a top-level JSON object.")
        return WorkspaceDocumentSnapshot.from_payload(payload)

    def save(
        self,
        path: Path | str,
        snapshot: WorkspaceDocumentSnapshot,
    ) -> Path:
        """Write one workspace document to disk and return the final path."""

        document_path = Path(path).expanduser()
        if document_path.suffix.lower() != ".framelab":
            document_path = document_path.with_suffix(".framelab")
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            json.dumps(snapshot.to_payload(), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return document_path
