"""Workflow tree loading and active-node controller state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..acquisition_datacard import (
    parse_acquisition_folder_name,
    resolve_acquisition_datacard_path,
    resolve_session_datacard_path,
)
from ..node_metadata import load_nodecard
from ..session_manager import resolve_acquisitions_root
from .models import WorkflowNode, WorkflowProfile
from .profiles import built_in_workflow_profiles, workflow_profile_by_id

_SKIPPED_DIR_NAMES = {"__pycache__", ".framelab"}
_SESSION_CONTAINER_NAMES = {"01_sessions", "sessions"}


@dataclass(frozen=True, slots=True)
class WorkflowLoadResult:
    """Summary of one workflow load into controller state."""

    workspace_root: Path
    profile_id: str
    anchor_type_id: str
    root_node_id: str
    active_node_id: str
    node_count: int
    warnings: tuple[str, ...] = ()


class WorkflowStateController:
    """Load and own one profile-driven workflow tree."""

    def __init__(self, profiles: tuple[WorkflowProfile, ...] | None = None) -> None:
        profile_list = tuple(profiles or built_in_workflow_profiles())
        self._profiles = {profile.profile_id: profile for profile in profile_list}
        self.clear()

    def clear(self) -> None:
        """Reset loaded workflow state."""

        self.workspace_root: Path | None = None
        self.profile: WorkflowProfile | None = None
        self.anchor_type_id: str | None = None
        self.root_node_id: str | None = None
        self.active_node_id: str | None = None
        self._nodes_by_id: dict[str, WorkflowNode] = {}
        self._node_ids_in_order: list[str] = []
        self._node_id_by_path: dict[Path, str] = {}
        self._warnings: tuple[str, ...] = ()

    def available_profiles(self) -> tuple[WorkflowProfile, ...]:
        """Return known workflow profiles in stable order."""

        return tuple(self._profiles.values())

    @property
    def profile_id(self) -> str | None:
        """Return active workflow profile id when loaded."""

        if self.profile is None:
            return None
        return self.profile.profile_id

    def node(self, node_id: str | None) -> WorkflowNode | None:
        """Return one loaded node by identifier."""

        if not node_id:
            return None
        return self._nodes_by_id.get(str(node_id))

    def nodes(self) -> tuple[WorkflowNode, ...]:
        """Return all loaded nodes in deterministic order."""

        return tuple(self._nodes_by_id[node_id] for node_id in self._node_ids_in_order)

    def active_node(self) -> WorkflowNode | None:
        """Return currently selected workflow node."""

        return self.node(self.active_node_id)

    def warnings(self) -> tuple[str, ...]:
        """Return load-time warnings for the current workflow."""

        return self._warnings

    def is_partial_workspace(self) -> bool:
        """Return whether the current load is anchored below logical root."""

        return bool(self.anchor_type_id and self.anchor_type_id != "root")

    def anchor_summary_label(self) -> str:
        """Return a compact label describing the loaded anchor scope."""

        if self.profile is None or self.anchor_type_id is None:
            return "Folder mode"
        if self.anchor_type_id == "root":
            return "Full workspace"
        try:
            display = self.profile.node_type(self.anchor_type_id).display_name
        except KeyError:
            display = self.anchor_type_id.replace("_", " ").title()
        return f"{display} subtree"

    def children_of(self, node_id: str | None) -> tuple[WorkflowNode, ...]:
        """Return direct children of one node."""

        node = self.node(node_id)
        if node is None:
            return ()
        return tuple(
            self._nodes_by_id[child_id]
            for child_id in node.child_ids
            if child_id in self._nodes_by_id
        )

    def ancestry_for(self, node_id: str | None) -> tuple[WorkflowNode, ...]:
        """Return root-to-node ancestry for one loaded node."""

        node = self.node(node_id)
        if node is None:
            return ()
        lineage: list[WorkflowNode] = []
        current = node
        while True:
            lineage.append(current)
            if current.parent_id is None:
                break
            parent = self.node(current.parent_id)
            if parent is None:
                break
            current = parent
        return tuple(reversed(lineage))

    def resolve_node_id_for_path(self, path: str | Path) -> str | None:
        """Return exact or nearest ancestor node id for one filesystem path."""

        candidate = Path(path).expanduser()
        if self.workspace_root is None:
            return None
        search_root = candidate if candidate.is_dir() else candidate.parent
        for current in (search_root, *search_root.parents):
            resolved = current.resolve()
            node_id = self._node_id_by_path.get(resolved)
            if node_id is not None:
                return node_id
            if resolved == self.workspace_root:
                break
        return None

    def set_active_node(self, node_id: str | None) -> WorkflowNode | None:
        """Set the active node, falling back to root when needed."""

        if not self._nodes_by_id:
            self.active_node_id = None
            return None
        selected_id = str(node_id).strip() if node_id is not None else ""
        if selected_id not in self._nodes_by_id:
            selected_id = self.root_node_id or ""
        self.active_node_id = selected_id or None
        return self.active_node()

    def load_workspace(
        self,
        workspace_root: str | Path,
        profile_id: str,
        *,
        anchor_type_id: str | None = None,
        active_node_id: str | None = None,
    ) -> WorkflowLoadResult:
        """Load one workflow tree from disk using the requested profile."""

        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"workflow workspace root does not exist: {root}")

        profile = self._resolve_profile(profile_id)

        nodes_in_order: list[WorkflowNode] = []
        warnings: list[str] = []
        resolved_anchor_type = self._normalize_anchor_type_id(profile, anchor_type_id)
        if resolved_anchor_type is None:
            resolved_anchor_type = self._infer_anchor_type_for_path(profile, root)
            if resolved_anchor_type is None:
                resolved_anchor_type = "root"
                warnings.append(
                    f"Could not confidently detect node type for '{root.name}'. "
                    "Opened as full workspace; choose an explicit anchor type if needed.",
                )
        root_node = self._build_tree(
            profile=profile,
            workspace_root=root,
            node_type_id=resolved_anchor_type,
            folder_path=root,
            parent_id=None,
            depth=0,
            relative_path="",
            nodes_in_order=nodes_in_order,
            warnings=warnings,
        )
        nodes_by_id = {node.node_id: node for node in nodes_in_order}
        self.workspace_root = root
        self.profile = profile
        self.anchor_type_id = resolved_anchor_type
        self.root_node_id = root_node.node_id
        self._nodes_by_id = nodes_by_id
        self._node_ids_in_order = [node.node_id for node in nodes_in_order]
        self._node_id_by_path = {
            node.folder_path.resolve(): node.node_id for node in nodes_in_order
        }
        self._warnings = tuple(dict.fromkeys(warnings))
        self.set_active_node(active_node_id)
        assert self.active_node_id is not None
        return WorkflowLoadResult(
            workspace_root=root,
            profile_id=profile.profile_id,
            anchor_type_id=resolved_anchor_type,
            root_node_id=root_node.node_id,
            active_node_id=self.active_node_id,
            node_count=len(nodes_in_order),
            warnings=self._warnings,
        )

    def refresh(self) -> WorkflowLoadResult | None:
        """Reload the current workspace and preserve selection when possible."""

        if self.workspace_root is None or self.profile is None:
            return None
        return self.load_workspace(
            self.workspace_root,
            self.profile.profile_id,
            anchor_type_id=self.anchor_type_id,
            active_node_id=self.active_node_id,
        )

    def infer_anchor_type(
        self,
        workspace_root: str | Path,
        profile_id: str,
    ) -> str | None:
        """Infer the likely workflow node type represented by the selected path."""

        root = Path(workspace_root).expanduser().resolve()
        if not root.exists():
            return None
        profile = self._resolve_profile(profile_id)
        return self._infer_anchor_type_for_path(profile, root)

    def supports_load_path(
        self,
        workspace_root: str | Path,
        profile_id: str,
        *,
        anchor_type_id: str | None = None,
    ) -> bool:
        """Return whether a path matches the supported workflow layout."""

        root = Path(workspace_root).expanduser().resolve()
        if not root.exists():
            return False
        profile = self._resolve_profile(profile_id)
        normalized_anchor = self._normalize_anchor_type_id(profile, anchor_type_id)
        if normalized_anchor is None:
            return self._infer_anchor_type_for_path(profile, root) is not None
        return self._path_matches_anchor_type(profile, root, normalized_anchor)

    def unsupported_load_message(
        self,
        workspace_root: str | Path,
        profile_id: str,
        *,
        anchor_type_id: str | None = None,
    ) -> str | None:
        """Return a user-facing warning when a folder is above the supported root."""

        if self.supports_load_path(
            workspace_root,
            profile_id,
            anchor_type_id=anchor_type_id,
        ):
            return None
        profile = self._resolve_profile(profile_id)
        subtree_labels = ", ".join(
            node_type.display_name for node_type in profile.node_types[1:]
        )
        return (
            f"FrameLab currently supports opening {profile.display_name} workflows "
            "only from the full workspace root or one of its recognized subtree "
            f"folders ({subtree_labels}). The selected folder appears to be above "
            "that supported level or does not match the expected workflow layout yet."
        )

    def as_debug_dict(self) -> dict[str, object]:
        """Return a compact workflow-state snapshot for debugging."""

        active = self.active_node()
        return {
            "workspace_root": (
                str(self.workspace_root) if self.workspace_root is not None else None
            ),
            "profile_id": self.profile_id,
            "anchor_type_id": self.anchor_type_id,
            "node_count": len(self._nodes_by_id),
            "root_node_id": self.root_node_id,
            "active_node_id": self.active_node_id,
            "active_node_path": (
                str(active.folder_path) if active is not None else None
            ),
            "warnings": list(self._warnings),
        }

    def _build_tree(
        self,
        *,
        profile: WorkflowProfile,
        workspace_root: Path,
        node_type_id: str,
        folder_path: Path,
        parent_id: str | None,
        depth: int,
        relative_path: str,
        nodes_in_order: list[WorkflowNode],
        warnings: list[str],
    ) -> WorkflowNode:
        node_id = self._node_id_for(
            profile.profile_id,
            node_type_id,
            relative_path,
        )
        insert_index = len(nodes_in_order)
        child_nodes: list[WorkflowNode] = []
        child_type_ids = profile.node_type(node_type_id).child_type_ids
        if len(child_type_ids) > 1:
            warnings.append(
                f"profile '{profile.profile_id}' node type '{node_type_id}' "
                "declares more than one child type; only the first is used",
            )
        if child_type_ids:
            child_type_id = child_type_ids[0]
            for child_folder in self._discover_child_dirs(
                profile=profile,
                parent_type_id=node_type_id,
                folder_path=folder_path,
            ):
                child_relative = child_folder.relative_to(workspace_root).as_posix()
                child_node = self._build_tree(
                    profile=profile,
                    workspace_root=workspace_root,
                    node_type_id=child_type_id,
                    folder_path=child_folder,
                    parent_id=node_id,
                    depth=depth + 1,
                    relative_path=child_relative,
                    nodes_in_order=nodes_in_order,
                    warnings=warnings,
                )
                child_nodes.append(child_node)

        display_name = folder_path.name
        if parent_id is None:
            display_name = folder_path.name or profile.root_display_name
        node = WorkflowNode(
            node_id=node_id,
            type_id=node_type_id,
            name=folder_path.name or profile.root_display_name,
            display_name=display_name,
            parent_id=parent_id,
            profile_id=profile.profile_id,
            folder_path=folder_path.resolve(),
            relative_path=relative_path,
            depth=depth,
            child_ids=tuple(child.node_id for child in child_nodes),
        )
        nodes_in_order.insert(insert_index, node)
        return node

    def _discover_child_dirs(
        self,
        *,
        profile: WorkflowProfile,
        parent_type_id: str,
        folder_path: Path,
    ) -> tuple[Path, ...]:
        node_type = profile.node_type(parent_type_id)
        mode = node_type.discovery_mode
        if mode == "leaf":
            return ()
        if mode == "session_acquisitions":
            return self._discover_session_acquisition_dirs(folder_path)
        child_type_ids = node_type.child_type_ids
        if (
            parent_type_id == "campaign"
            and child_type_ids
            and child_type_ids[0] == "session"
        ):
            return self._discover_campaign_session_dirs(folder_path)
        return self._discover_generic_child_dirs(folder_path)

    @staticmethod
    def _discover_generic_child_dirs(folder_path: Path) -> tuple[Path, ...]:
        children: list[Path] = []
        if not folder_path.is_dir():
            return ()
        for child in sorted(folder_path.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            if child.name in _SKIPPED_DIR_NAMES or child.name.startswith("."):
                continue
            children.append(child.resolve())
        return tuple(children)

    @classmethod
    def _discover_campaign_session_dirs(cls, campaign_root: Path) -> tuple[Path, ...]:
        """Return session folders for campaigns that may use a nested sessions dir."""

        if not campaign_root.is_dir():
            return ()
        session_dirs: list[Path] = []
        seen: set[Path] = set()

        def _append_session_candidates(root: Path) -> None:
            for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                if not child.is_dir():
                    continue
                if child.name in _SKIPPED_DIR_NAMES or child.name.startswith("."):
                    continue
                resolved = child.resolve()
                if resolved in seen or not cls._looks_like_session_anchor(resolved):
                    continue
                seen.add(resolved)
                session_dirs.append(resolved)

        _append_session_candidates(campaign_root)
        for child in sorted(campaign_root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            if child.name.lower() not in _SESSION_CONTAINER_NAMES:
                continue
            _append_session_candidates(child)
        return tuple(session_dirs)

    @staticmethod
    def _discover_session_acquisition_dirs(session_root: Path) -> tuple[Path, ...]:
        candidate_roots: list[Path] = []
        try:
            # LEGACY_COMPAT[session_acquisition_layout_bridge]: Preserve session_datacard.json and nested acquisitions-folder discovery while the workflow shell is still migrating from session-manager assumptions. Remove after: workflow management and migration tools no longer depend on the legacy session/acquisitions layout.
            if (
                resolve_session_datacard_path(session_root).is_file()
                or session_root.joinpath("acquisitions").is_dir()
            ):
                candidate_roots.append(resolve_acquisitions_root(session_root))
        except Exception:
            pass
        candidate_roots.append(session_root)

        seen: set[Path] = set()
        acquisition_dirs: list[Path] = []
        for candidate_root in candidate_roots:
            resolved_root = candidate_root.resolve()
            if resolved_root in seen or not resolved_root.is_dir():
                continue
            seen.add(resolved_root)
            for child in sorted(
                resolved_root.iterdir(),
                key=lambda item: item.name.lower(),
            ):
                if not child.is_dir():
                    continue
                parsed = parse_acquisition_folder_name(child.name)
                if parsed is None and not resolve_acquisition_datacard_path(child).is_file():
                    continue
                acquisition_dirs.append(child.resolve())
            if acquisition_dirs:
                break
        return tuple(acquisition_dirs)

    @staticmethod
    def _node_id_for(profile_id: str, node_type_id: str, relative_path: str) -> str:
        clean_relative = str(relative_path).strip().strip("/")
        if not clean_relative:
            if node_type_id == "root":
                return f"{profile_id}:root"
            return f"{profile_id}:{node_type_id}"
        return f"{profile_id}:{node_type_id}:{clean_relative}"

    def _resolve_profile(self, profile_id: str) -> WorkflowProfile:
        profile = self._profiles.get(str(profile_id).strip().lower())
        if profile is None:
            fallback = workflow_profile_by_id(profile_id)
            if fallback is None:
                raise KeyError(f"unknown workflow profile '{profile_id}'")
            profile = fallback
        return profile

    @staticmethod
    def _normalize_anchor_type_id(
        profile: WorkflowProfile,
        anchor_type_id: str | None,
    ) -> str | None:
        clean = str(anchor_type_id).strip().lower() if anchor_type_id else ""
        if not clean:
            return None
        if clean not in profile.node_type_index:
            raise KeyError(
                f"unknown anchor node type '{anchor_type_id}' "
                f"for profile '{profile.profile_id}'",
            )
        return clean

    def _infer_anchor_type_for_path(
        self,
        profile: WorkflowProfile,
        path: Path,
    ) -> str | None:
        card = load_nodecard(path)
        if card.node_type_id and card.node_type_id in profile.node_type_index:
            return card.node_type_id
        if (
            path.name.lower() in _SESSION_CONTAINER_NAMES
            and "campaign" in profile.node_type_index
            and self._discover_campaign_session_dirs(path)
        ):
            return "campaign"
        if "acquisition" in profile.node_type_index and self._looks_like_acquisition_anchor(path):
            return "acquisition"
        if "session" in profile.node_type_index and self._looks_like_session_anchor(path):
            return "session"

        candidates: list[tuple[int, str]] = []
        for node_type in profile.node_types:
            score = self._anchor_type_score(
                profile,
                path,
                node_type.type_id,
                max_depth=max(len(profile.node_types) + 1, 2),
            )
            if score <= 0:
                continue
            candidates.append((score, node_type.type_id))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1] != "root", item[1]))
        return candidates[0][1]

    def _path_matches_anchor_type(
        self,
        profile: WorkflowProfile,
        path: Path,
        anchor_type_id: str,
    ) -> bool:
        card = load_nodecard(path)
        if card.node_type_id == anchor_type_id:
            return True
        max_depth = max(len(profile.node_types) + 1, 2)
        return self._anchor_type_score(
            profile,
            path,
            anchor_type_id,
            max_depth=max_depth,
        ) > 0

    def _anchor_type_score(
        self,
        profile: WorkflowProfile,
        path: Path,
        node_type_id: str,
        *,
        max_depth: int,
    ) -> int:
        if max_depth <= 0:
            return 0
        if node_type_id == "acquisition":
            return 100 if self._looks_like_acquisition_anchor(path) else 0
        if node_type_id == "session":
            return 90 if self._looks_like_session_anchor(path) else 0

        card = load_nodecard(path)
        if card.node_type_id == node_type_id:
            return 95

        child_type_ids = profile.node_type(node_type_id).child_type_ids
        if not child_type_ids:
            return 0
        child_type_id = child_type_ids[0]
        children = self._discover_child_dirs(
            profile=profile,
            parent_type_id=node_type_id,
            folder_path=path,
        )
        if not children:
            return 0

        child_scores: list[int] = []
        for child in children:
            child_score = self._anchor_type_score(
                profile,
                child,
                child_type_id,
                max_depth=max_depth - 1,
            )
            if child_score <= 0:
                return 0
            child_scores.append(child_score)
        return 10 + min(child_scores)

    @staticmethod
    def _looks_like_acquisition_anchor(path: Path) -> bool:
        if resolve_acquisition_datacard_path(path).is_file():
            return True
        if parse_acquisition_folder_name(path.name) is not None and path.joinpath("frames").is_dir():
            return True
        return False

    @classmethod
    def _looks_like_session_anchor(cls, path: Path) -> bool:
        if resolve_session_datacard_path(path).is_file():
            return True
        if not path.is_dir():
            return False
        try:
            return bool(cls._discover_session_acquisition_dirs(path))
        except Exception:
            return False
