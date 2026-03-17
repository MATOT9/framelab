"""Explicit dataset/session state ownership for the main window."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def _is_same_or_child_path(path: Path, root: Path) -> bool:
    """Return whether ``path`` is the same as or below ``root``."""

    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _normalize_subtree_root(root: str | Path) -> Path:
    """Normalize a subtree root, accepting either folder or file paths."""

    candidate = Path(root).expanduser()
    if candidate.exists():
        return (candidate if candidate.is_dir() else candidate.parent).resolve()
    return (candidate.parent if candidate.suffix else candidate).resolve()


@dataclass(frozen=True, slots=True)
class DatasetScopeNode:
    """One node in the active workflow ancestry chain."""

    node_id: str
    type_id: str
    display_name: str
    folder_path: Path


@dataclass(frozen=True, slots=True)
class DatasetScopeSnapshot:
    """Current dataset scope, whether workflow-driven or manual."""

    source: str = "manual"
    root: Path | None = None
    kind: str | None = None
    label: str | None = None
    workflow_profile_id: str | None = None
    workflow_anchor_type_id: str | None = None
    workflow_anchor_label: str | None = None
    workflow_anchor_path: Path | None = None
    workflow_is_partial: bool = False
    active_node_id: str | None = None
    active_node_type: str | None = None
    active_node_path: Path | None = None
    ancestor_chain: tuple[DatasetScopeNode, ...] = ()


class DatasetStateController:
    """Own loaded-dataset state outside the main window UI object."""

    def __init__(self) -> None:
        self.dataset_root: Path | None = None
        self.paths: list[str] = []
        self.path_metadata: dict[str, dict[str, object]] = {}
        self.metadata_source_mode = "json"
        self.preferred_metadata_source_mode = "json"
        self.has_json_metadata_source = False
        self.metadata_visible_paths: list[str] = []
        self.selected_index: int | None = None
        self.scope_snapshot = DatasetScopeSnapshot()
        self.scope_effective_metadata: dict[str, object] = {}
        self.scope_metadata_sources: dict[str, str] = {}

    def clear_loaded_dataset(self) -> None:
        """Clear loaded-dataset content while preserving source preferences."""
        self.dataset_root = None
        self.paths = []
        self.path_metadata = {}
        self.metadata_visible_paths = []
        self.selected_index = None

    def clear_scope(self) -> None:
        """Clear workflow/manual scope context without touching loaded data."""

        self.scope_snapshot = DatasetScopeSnapshot()
        self.scope_effective_metadata = {}
        self.scope_metadata_sources = {}

    def set_loaded_dataset(
        self,
        dataset_root: Path | str | None,
        paths: Iterable[str],
    ) -> None:
        """Replace the current loaded dataset root and path list."""
        self.dataset_root = (
            Path(dataset_root).expanduser()
            if dataset_root is not None
            else None
        )
        self.paths = [str(path) for path in paths]
        self.path_metadata = {}
        self.metadata_visible_paths = []
        self.selected_index = None

    def set_manual_scope(
        self,
        root: Path | str | None,
        *,
        kind: str = "folder",
        label: str | None = None,
    ) -> DatasetScopeSnapshot:
        """Store one manual folder-driven dataset scope."""

        resolved_root = (
            Path(root).expanduser().resolve()
            if root is not None
            else None
        )
        if resolved_root is None:
            self.clear_scope()
            return self.scope_snapshot
        scope_label = str(label).strip() if label else resolved_root.name or str(resolved_root)
        self.scope_snapshot = DatasetScopeSnapshot(
            source="manual",
            root=resolved_root,
            kind=str(kind).strip() or "folder",
            label=scope_label,
        )
        self.scope_effective_metadata = {}
        self.scope_metadata_sources = {}
        return self.scope_snapshot

    def set_workflow_scope(
        self,
        *,
        root: Path | str,
        kind: str,
        label: str | None,
        workflow_profile_id: str | None,
        workflow_anchor_type_id: str | None = None,
        workflow_anchor_label: str | None = None,
        workflow_anchor_path: Path | str | None = None,
        workflow_is_partial: bool = False,
        active_node_id: str | None = None,
        active_node_type: str | None = None,
        active_node_path: Path | str | None = None,
        ancestor_chain: Iterable[DatasetScopeNode] = (),
        effective_metadata: dict[str, object] | None = None,
        metadata_sources: dict[str, str] | None = None,
    ) -> DatasetScopeSnapshot:
        """Store one workflow-derived dataset scope and metadata context."""

        resolved_root = Path(root).expanduser().resolve()
        resolved_node_path = (
            Path(active_node_path).expanduser().resolve()
            if active_node_path is not None
            else resolved_root
        )
        resolved_anchor_path = (
            Path(workflow_anchor_path).expanduser().resolve()
            if workflow_anchor_path is not None
            else resolved_root
        )
        normalized_chain = tuple(
            DatasetScopeNode(
                node_id=str(node.node_id),
                type_id=str(node.type_id),
                display_name=str(node.display_name),
                folder_path=Path(node.folder_path).expanduser().resolve(),
            )
            for node in ancestor_chain
        )
        clean_kind = str(kind).strip() or None
        clean_label = str(label).strip() if label else None
        self.scope_snapshot = DatasetScopeSnapshot(
            source="workflow",
            root=resolved_root,
            kind=clean_kind,
            label=clean_label or resolved_root.name or str(resolved_root),
            workflow_profile_id=(
                str(workflow_profile_id).strip() if workflow_profile_id else None
            ),
            workflow_anchor_type_id=(
                str(workflow_anchor_type_id).strip()
                if workflow_anchor_type_id
                else None
            ),
            workflow_anchor_label=(
                str(workflow_anchor_label).strip()
                if workflow_anchor_label
                else None
            ),
            workflow_anchor_path=resolved_anchor_path,
            workflow_is_partial=bool(workflow_is_partial),
            active_node_id=str(active_node_id).strip() if active_node_id else None,
            active_node_type=str(active_node_type).strip() if active_node_type else None,
            active_node_path=resolved_node_path,
            ancestor_chain=normalized_chain,
        )
        self.scope_effective_metadata = dict(effective_metadata or {})
        self.scope_metadata_sources = {
            str(key): str(value)
            for key, value in (metadata_sources or {}).items()
            if str(key).strip()
        }
        return self.scope_snapshot

    def has_loaded_data(self) -> bool:
        """Return whether a dataset is currently loaded."""
        return bool(self.paths)

    def path_count(self) -> int:
        """Return number of currently loaded dataset paths."""
        return len(self.paths)

    def set_path_metadata(
        self,
        mapping: dict[str, dict[str, object]],
    ) -> None:
        """Replace cached metadata for the currently loaded paths."""
        self.path_metadata = {
            str(path): dict(payload)
            for path, payload in mapping.items()
        }

    def update_path_metadata(
        self,
        mapping: dict[str, dict[str, object]],
    ) -> None:
        """Merge refreshed metadata for a subset of already loaded paths."""

        if not mapping:
            return
        merged = dict(self.path_metadata)
        for path, payload in mapping.items():
            merged[str(path)] = dict(payload)
        self.path_metadata = merged

    def set_metadata_visible_paths(self, paths: Iterable[str]) -> None:
        """Store current metadata-table visible row ordering."""
        self.metadata_visible_paths = [str(path) for path in paths]

    def visible_metadata_path(self, row: int) -> str | None:
        """Return visible metadata-table path for one row, if present."""
        if 0 <= int(row) < len(self.metadata_visible_paths):
            return self.metadata_visible_paths[int(row)]
        return None

    def source_index_for_path(self, path: str) -> int | None:
        """Return loaded-path index for a path, if the path is present."""
        try:
            return self.paths.index(str(path))
        except ValueError:
            return None

    def metadata_for_path(self, path: str) -> dict[str, object]:
        """Return cached metadata for one loaded path."""
        return self.path_metadata.get(str(path), {})

    def paths_within_root(self, root: str | Path | None) -> list[str]:
        """Return loaded paths that sit within one filesystem subtree."""

        if root is None:
            return list(self.paths)
        resolved_root = _normalize_subtree_root(root)
        matched: list[str] = []
        for path in self.paths:
            candidate = Path(path).expanduser()
            if _is_same_or_child_path(candidate, resolved_root):
                matched.append(str(path))
        return matched

    def set_selected_index(
        self,
        index: int | None,
        *,
        path_count: int | None = None,
    ) -> int | None:
        """Store current selected dataset row, clamped when path count is known."""
        if index is None:
            self.selected_index = None
            return None
        try:
            value = int(index)
        except Exception:
            self.selected_index = None
            return None
        if path_count is not None:
            if path_count <= 0:
                self.selected_index = None
                return None
            value = min(max(value, 0), int(path_count) - 1)
        self.selected_index = value
        return value

    def update_metadata_source_availability(self, has_json: bool) -> str:
        """Update JSON availability and return the active source mode."""
        self.has_json_metadata_source = bool(has_json)
        if not self.has_json_metadata_source and self.metadata_source_mode == "json":
            self.metadata_source_mode = "path"
        elif self.has_json_metadata_source:
            preferred = self.preferred_metadata_source_mode
            if preferred not in {"path", "json"}:
                preferred = "json"
            self.metadata_source_mode = preferred
        return self.metadata_source_mode

    def request_metadata_source_mode(self, mode: str | None) -> bool:
        """Set requested metadata source mode and return whether it changed."""
        selected = str(mode or "path")
        if selected not in {"path", "json"}:
            selected = "path"
        if selected == "json" and not self.has_json_metadata_source:
            selected = "path"
        changed = selected != self.metadata_source_mode
        self.preferred_metadata_source_mode = selected
        self.metadata_source_mode = selected
        return changed

    def scope_summary_value(self) -> str:
        """Return a compact human-readable summary of the active scope."""

        scope = self.scope_snapshot
        if scope.root is None:
            return "None"
        prefix = (
            str(scope.kind).replace("_", " ").title()
            if scope.kind
            else "Scope"
        )
        label = scope.label or scope.root.name or str(scope.root)
        if scope.source == "workflow" and scope.workflow_is_partial:
            anchor_label = scope.workflow_anchor_label or "Partial subtree"
            if (
                scope.active_node_path is not None
                and scope.workflow_anchor_path is not None
                and scope.workflow_anchor_path == scope.active_node_path
            ):
                return f"{anchor_label}: {label}"
            return f"{prefix}: {label} ({anchor_label})"
        return f"{prefix}: {label}"

    def as_debug_dict(self) -> dict[str, Any]:
        """Return a compact debug snapshot of controller-owned dataset state."""
        return {
            "dataset_root": (
                str(self.dataset_root) if self.dataset_root is not None else None
            ),
            "scope_root": (
                str(self.scope_snapshot.root)
                if self.scope_snapshot.root is not None
                else None
            ),
            "scope_source": self.scope_snapshot.source,
            "scope_kind": self.scope_snapshot.kind,
            "workflow_profile_id": self.scope_snapshot.workflow_profile_id,
            "workflow_anchor_type_id": self.scope_snapshot.workflow_anchor_type_id,
            "workflow_anchor_path": (
                str(self.scope_snapshot.workflow_anchor_path)
                if self.scope_snapshot.workflow_anchor_path is not None
                else None
            ),
            "workflow_is_partial": self.scope_snapshot.workflow_is_partial,
            "active_node_id": self.scope_snapshot.active_node_id,
            "path_count": len(self.paths),
            "metadata_source_mode": self.metadata_source_mode,
            "preferred_metadata_source_mode": self.preferred_metadata_source_mode,
            "has_json_metadata_source": self.has_json_metadata_source,
            "visible_metadata_rows": len(self.metadata_visible_paths),
        }
