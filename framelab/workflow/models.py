"""Core workflow domain models."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DISCOVERY_MODES = {"directories", "session_acquisitions", "leaf"}


@dataclass(frozen=True, slots=True)
class NodeTypeDefinition:
    """Typed workflow node definition owned by one workflow profile."""

    type_id: str
    display_name: str
    child_type_ids: tuple[str, ...] = ()
    discovery_mode: str = "directories"

    def __post_init__(self) -> None:
        if self.discovery_mode not in _DISCOVERY_MODES:
            raise ValueError(
                f"unsupported discovery mode '{self.discovery_mode}' "
                f"for node type '{self.type_id}'",
            )


@dataclass(frozen=True, slots=True)
class MetadataFieldRule:
    """Profile-level metadata field rule used for governance and templates."""

    key: str
    label: str
    group: str
    value_type: str = "any"
    source_kind: str | None = None
    options: tuple[str, ...] = ()
    required_node_types: tuple[str, ...] = ()
    template_node_types: tuple[str, ...] = ()
    template_value: Any = None
    inheritable: bool = True

    def applies_as_required(self, node_type_id: str | None) -> bool:
        """Return whether the field is required for the requested node type."""

        if self.source_kind == "ad_hoc":
            return False
        if node_type_id is None:
            return False
        return node_type_id in self.required_node_types

    def contributes_to_template(self, node_type_id: str | None) -> bool:
        """Return whether the field contributes to the node-type template."""

        if self.source_kind == "ad_hoc":
            return False
        if node_type_id is None:
            return False
        return node_type_id in self.template_node_types


@dataclass(frozen=True, slots=True)
class MetadataGovernanceProfile:
    """Profile-specific metadata governance and authoring defaults."""

    allow_ad_hoc_fields: bool = True
    allow_ad_hoc_groups: bool = True
    field_rules: tuple[MetadataFieldRule, ...] = ()

    def field_rule_index(self) -> dict[str, MetadataFieldRule]:
        """Return field rules indexed by metadata key."""

        return {rule.key: rule for rule in self.field_rules}

    def required_keys_for_node_type(self, node_type_id: str | None) -> tuple[str, ...]:
        """Return required metadata keys for one node type."""

        if node_type_id is None:
            return ()
        return tuple(
            rule.key
            for rule in self.field_rules
            if rule.applies_as_required(node_type_id)
        )

    def template_metadata_for_node_type(
        self,
        node_type_id: str | None,
    ) -> dict[str, Any]:
        """Return template metadata payload for one node type."""

        if node_type_id is None:
            return {}
        flat: dict[str, Any] = {}
        for rule in self.field_rules:
            if not rule.contributes_to_template(node_type_id):
                continue
            flat[rule.key] = deepcopy(rule.template_value)
        return flat


@dataclass(frozen=True, slots=True)
class WorkflowProfile:
    """Profile-specific hierarchy contract used to build a workflow tree."""

    profile_id: str
    display_name: str
    root_display_name: str
    node_types: tuple[NodeTypeDefinition, ...]
    description: str = ""
    metadata_governance: MetadataGovernanceProfile = field(
        default_factory=MetadataGovernanceProfile,
    )

    def __post_init__(self) -> None:
        if not self.node_types:
            raise ValueError(f"workflow profile '{self.profile_id}' has no node types")
        type_index = {node_type.type_id: node_type for node_type in self.node_types}
        if "root" not in type_index:
            raise ValueError(
                f"workflow profile '{self.profile_id}' is missing a root node type",
            )
        for node_type in self.node_types:
            for child_type_id in node_type.child_type_ids:
                if child_type_id not in type_index:
                    raise ValueError(
                        f"workflow profile '{self.profile_id}' references "
                        f"unknown child type '{child_type_id}'",
                    )

    @property
    def node_type_index(self) -> dict[str, NodeTypeDefinition]:
        """Return node definitions indexed by type identifier."""

        return {node_type.type_id: node_type for node_type in self.node_types}

    def node_type(self, type_id: str) -> NodeTypeDefinition:
        """Return one node definition by identifier."""

        try:
            return self.node_type_index[type_id]
        except KeyError as exc:
            raise KeyError(
                f"unknown node type '{type_id}' for profile '{self.profile_id}'",
            ) from exc


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    """One concrete node inside a loaded workflow tree."""

    node_id: str
    type_id: str
    name: str
    display_name: str
    parent_id: str | None
    profile_id: str
    folder_path: Path
    relative_path: str
    depth: int
    child_ids: tuple[str, ...] = ()
    status_flags: tuple[str, ...] = ()
    warning_text: str = ""

    @property
    def is_root(self) -> bool:
        """Return whether this node is the workflow root."""

        return self.parent_id is None
