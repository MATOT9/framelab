"""Generic node-metadata schema and ancestry-based resolution helpers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .datacard_authoring.mapping import load_field_mapping
from .datacard_labels import label_for_metadata_field
from .node_metadata import (
    NodeMetadataCard,
    discover_nodecard_roots,
    load_nodecard,
    save_nodecard,
)
from .payload_utils import flatten_payload_dict, unflatten_payload_dict
from .workflow import workflow_profile_by_id
from .workflow.governance_config import promote_field_rule


def _is_same_or_child_path(path: Path, boundary: Path) -> bool:
    """Return whether ``path`` is the same as or below ``boundary``."""

    try:
        path.resolve().relative_to(boundary.resolve())
    except ValueError:
        return False
    return True


def _merge_inherit(base: Any, override: Any) -> Any:
    """Merge nested dictionaries using metadata inheritance semantics."""

    if override is None:
        return deepcopy(base)
    if isinstance(override, dict):
        merged = deepcopy(base) if isinstance(base, dict) else {}
        for key, value in override.items():
            if value is None:
                if key not in merged:
                    merged[key] = None
                continue
            base_value = merged.get(key)
            if isinstance(value, dict):
                merged[key] = _merge_inherit(base_value, value)
            elif isinstance(value, list):
                merged[key] = deepcopy(value)
            else:
                merged[key] = deepcopy(value)
        return merged
    if isinstance(override, list):
        return deepcopy(override)
    return deepcopy(override)


@dataclass(frozen=True, slots=True)
class MetadataFieldDefinition:
    """Lightweight field definition used by the metadata controller."""

    key: str
    label: str
    group: str = "General"
    value_type: str = "any"
    source_kind: str = "core"
    required: bool = False
    inheritable: bool = True
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetadataSchemaSnapshot:
    """Resolved schema view for one profile plus discovered ad-hoc fields."""

    profile_id: str | None
    fields: tuple[MetadataFieldDefinition, ...]

    def by_key(self) -> dict[str, MetadataFieldDefinition]:
        """Return schema fields indexed by key."""

        return {field.key: field for field in self.fields}


@dataclass(frozen=True, slots=True)
class MetadataFieldSource:
    """Provenance details for one effective metadata key."""

    key: str
    value: Any
    provenance: str
    schema_source_kind: str
    source_path: Path
    profile_id: str | None = None
    node_type_id: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataLayerSnapshot:
    """One local metadata layer that participated in effective resolution."""

    source_path: Path
    provenance: str
    profile_id: str | None
    node_type_id: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MetadataValidationIssue:
    """One metadata validation or governance issue."""

    severity: str
    key: str | None
    group: str | None
    message: str


@dataclass(frozen=True, slots=True)
class MetadataGroupStatus:
    """Compact completeness summary for one metadata group."""

    group: str
    status: str
    total_fields: int
    present_fields: int
    missing_required: int
    ad_hoc_fields: int


@dataclass(frozen=True, slots=True)
class MetadataValidationSnapshot:
    """Validation and governance summary for one effective metadata view."""

    issues: tuple[MetadataValidationIssue, ...]
    missing_required_keys: tuple[str, ...]
    ad_hoc_keys: tuple[str, ...]
    group_statuses: tuple[MetadataGroupStatus, ...]
    template_keys: tuple[str, ...]

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")


@dataclass(frozen=True, slots=True)
class EffectiveMetadataSnapshot:
    """Effective resolved metadata and provenance from node ancestry."""

    effective_metadata: dict[str, Any]
    flat_metadata: dict[str, Any]
    field_sources: dict[str, MetadataFieldSource]
    layers: tuple[MetadataLayerSnapshot, ...]
    schema: MetadataSchemaSnapshot
    validation: MetadataValidationSnapshot

    @property
    def has_metadata(self) -> bool:
        """Return whether any node-local metadata was discovered."""

        return bool(self.layers)


class MetadataStateController:
    """Own generic node-metadata loading, schema, and ancestry resolution."""

    def __init__(self, workflow_state_controller: object | None = None) -> None:
        self._workflow_state_controller = workflow_state_controller
        self._nodecard_cache: dict[Path, NodeMetadataCard] = {}

    def clear_cache(self) -> None:
        """Clear cached nodecard payloads."""

        self._nodecard_cache.clear()

    def schema_for_profile(
        self,
        profile_id: str | None = None,
        *,
        node_type_id: str | None = None,
        additional_keys: tuple[str, ...] = (),
    ) -> MetadataSchemaSnapshot:
        """Return one lightweight schema snapshot for the requested profile."""

        definitions: dict[str, MetadataFieldDefinition] = {}
        profile = workflow_profile_by_id(profile_id) if profile_id else None
        # LEGACY_COMPAT[acquisition_mapping_schema_bridge]: Reuse acquisition field-mapping labels and type hints while workflow node metadata still overlaps with the older datacard vocabulary. Remove after: workflow metadata owns a dedicated schema source instead of borrowing acquisition mapping defaults.
        try:
            mapping = load_field_mapping()
        except Exception:
            mapping = None
        if mapping is not None:
            for field in mapping.fields:
                definitions[field.key] = MetadataFieldDefinition(
                    key=field.key,
                    label=field.label.strip() or label_for_metadata_field(field.key),
                    group=field.group.strip() or "General",
                    value_type=field.value_type,
                    source_kind="core",
                    options=tuple(field.options),
                )
        governance = profile.metadata_governance if profile is not None else None
        if governance is not None:
            for rule in governance.field_rules:
                existing = definitions.get(rule.key)
                merged_source_kind = (
                    existing.source_kind
                    if existing is not None and existing.source_kind == "core"
                    else "profile"
                )
                definitions[rule.key] = MetadataFieldDefinition(
                    key=rule.key,
                    label=rule.label or (
                        existing.label if existing is not None else label_for_metadata_field(rule.key)
                    ),
                    group=rule.group or (existing.group if existing is not None else "Workflow"),
                    value_type=rule.value_type or (
                        existing.value_type if existing is not None else "any"
                    ),
                    source_kind=merged_source_kind,
                    required=rule.applies_as_required(node_type_id),
                    inheritable=rule.inheritable if existing is None else existing.inheritable,
                    options=rule.options or (existing.options if existing is not None else ()),
                )
        for key in sorted({str(item).strip() for item in additional_keys if str(item).strip()}):
            if key in definitions:
                continue
            definitions[key] = MetadataFieldDefinition(
                key=key,
                label=label_for_metadata_field(key),
                group=self._group_name_for_key(key, source_kind="ad_hoc"),
                value_type="any",
                source_kind="ad_hoc",
            )
        return MetadataSchemaSnapshot(
            profile_id=(str(profile_id).strip() or None) if profile_id else None,
            fields=tuple(sorted(definitions.values(), key=lambda item: item.key)),
        )

    def load_node_metadata(
        self,
        path: str | Path,
    ) -> NodeMetadataCard:
        """Load one nodecard payload with a small in-controller cache."""

        resolved_path = Path(path).expanduser().resolve()
        cached = self._nodecard_cache.get(resolved_path)
        if cached is not None:
            return cached
        card = load_nodecard(resolved_path)
        self._nodecard_cache[resolved_path] = card
        return card

    def save_node_metadata(
        self,
        path: str | Path,
        metadata: dict[str, Any],
        *,
        profile_id: str | None = None,
        node_type_id: str | None = None,
        extra_top_level: dict[str, Any] | None = None,
    ) -> Path:
        """Write one nodecard payload and refresh the cached copy."""

        saved_path = save_nodecard(
            path,
            metadata,
            profile_id=profile_id,
            node_type_id=node_type_id,
            extra_top_level=extra_top_level,
        )
        node_root = saved_path.parent.parent.resolve()
        self._nodecard_cache[node_root] = load_nodecard(node_root)
        return saved_path

    def resolve_path_metadata(
        self,
        path: str | Path,
        *,
        node_type_id: str | None = None,
        exclude_paths: tuple[str | Path, ...] = (),
        boundary_root: str | Path | None = None,
    ) -> EffectiveMetadataSnapshot:
        """Resolve effective node metadata from ancestor nodecards."""

        target = Path(path).expanduser()
        target_dir = target if target.is_dir() else target.parent
        normalized_boundary_root: Path | None = None
        if boundary_root is not None:
            candidate_boundary = Path(boundary_root).expanduser().resolve()
            if _is_same_or_child_path(target_dir.resolve(), candidate_boundary):
                normalized_boundary_root = candidate_boundary
        effective_excludes = list(exclude_paths)
        if normalized_boundary_root is not None:
            effective_excludes.extend(normalized_boundary_root.parents)
        roots = discover_nodecard_roots(
            target_dir,
            exclude_paths=tuple(effective_excludes),
        )
        merged: dict[str, Any] = {}
        field_sources: dict[str, MetadataFieldSource] = {}
        layers: list[MetadataLayerSnapshot] = []
        additional_keys: set[str] = set()

        profile_id = self._profile_id_for_resolution(roots)
        schema = self.schema_for_profile(profile_id, node_type_id=node_type_id)
        schema_index = schema.by_key()
        known_keys = set(schema_index)

        for root in roots:
            card = self.load_node_metadata(root)
            if not card.metadata:
                continue
            provenance = (
                "node_local"
                if root.resolve() == target_dir.resolve()
                else "node_inherited"
            )
            merged = _merge_inherit(merged, card.metadata)
            layers.append(
                MetadataLayerSnapshot(
                    source_path=root.resolve(),
                    provenance=provenance,
                    profile_id=card.profile_id,
                    node_type_id=card.node_type_id,
                    metadata=deepcopy(card.metadata),
                ),
            )
            for key, value in flatten_payload_dict(card.metadata).items():
                if key not in known_keys:
                    additional_keys.add(key)
                if value is not None:
                    field_def = schema_index.get(key)
                    field_sources[key] = MetadataFieldSource(
                        key=key,
                        value=deepcopy(value),
                        provenance=provenance,
                        schema_source_kind=(
                            field_def.source_kind if field_def is not None else "ad_hoc"
                        ),
                        source_path=root.resolve(),
                        profile_id=card.profile_id,
                        node_type_id=card.node_type_id,
                    )

        if additional_keys:
            schema = self.schema_for_profile(
                profile_id,
                node_type_id=node_type_id,
                additional_keys=tuple(sorted(additional_keys)),
            )
            schema_index = schema.by_key()
            for key, source in list(field_sources.items()):
                field_def = schema_index.get(key)
                if field_def is None:
                    continue
                field_sources[key] = MetadataFieldSource(
                    key=source.key,
                    value=deepcopy(source.value),
                    provenance=source.provenance,
                    schema_source_kind=field_def.source_kind,
                    source_path=source.source_path,
                    profile_id=source.profile_id,
                    node_type_id=source.node_type_id,
                )
        flat_metadata = flatten_payload_dict(merged)
        validation = self._validate_effective_metadata(
            profile_id=profile_id,
            node_type_id=node_type_id,
            schema=schema,
            flat_metadata=flat_metadata,
            field_sources=field_sources,
        )
        return EffectiveMetadataSnapshot(
            effective_metadata=merged,
            flat_metadata=flat_metadata,
            field_sources=field_sources,
            layers=tuple(layers),
            schema=schema,
            validation=validation,
        )

    def resolve_active_node_metadata(self) -> EffectiveMetadataSnapshot | None:
        """Resolve node-local metadata for the active workflow node when present."""

        controller = self._workflow_state_controller
        if controller is None or not hasattr(controller, "active_node"):
            return None
        active_node = controller.active_node()
        if active_node is None:
            return None
        return self.resolve_path_metadata(
            active_node.folder_path,
            node_type_id=active_node.type_id,
            boundary_root=getattr(controller, "workspace_root", None),
        )

    def governance_for_profile(self, profile_id: str | None):
        """Return metadata governance configuration for one profile."""

        profile = workflow_profile_by_id(profile_id) if profile_id else None
        return profile.metadata_governance if profile is not None else None

    def template_for_node(
        self,
        profile_id: str | None,
        node_type_id: str | None,
    ) -> dict[str, Any]:
        """Return template metadata payload for one profile/node type."""

        governance = self.governance_for_profile(profile_id)
        if governance is None:
            return {}
        flat_template = governance.template_metadata_for_node_type(node_type_id)
        if not flat_template:
            return {}
        return unflatten_payload_dict(flat_template)

    def apply_template(
        self,
        path: str | Path,
        *,
        profile_id: str | None,
        node_type_id: str | None,
        preserve_existing: bool = True,
    ) -> Path | None:
        """Apply the node-type template to local metadata for one node."""

        template = self.template_for_node(profile_id, node_type_id)
        if not template:
            return None
        existing_card = self.load_node_metadata(path)
        metadata = deepcopy(existing_card.metadata)
        if preserve_existing:
            metadata = _merge_inherit(template, metadata)
        else:
            metadata = _merge_inherit(metadata, template)
        return self.save_node_metadata(
            path,
            metadata,
            profile_id=profile_id,
            node_type_id=node_type_id,
            extra_top_level=dict(existing_card.extra_top_level),
        )

    def promote_field_to_profile(
        self,
        profile_id: str | None,
        *,
        key: str,
        label: str,
        group: str,
        value_type: str = "string",
        options: tuple[str, ...] = (),
    ) -> Path:
        """Promote one ad-hoc field into the profile-governance overlay."""

        if not profile_id:
            raise ValueError("profile_id is required to promote a field")
        saved_path = promote_field_rule(
            profile_id,
            key=key,
            label=label,
            group=group,
            value_type=value_type,
            options=options,
        )
        self.clear_cache()
        return saved_path

    def _profile_id_for_resolution(
        self,
        roots: tuple[Path, ...],
    ) -> str | None:
        for root in reversed(roots):
            card = self.load_node_metadata(root)
            if card.profile_id:
                return card.profile_id
        controller = self._workflow_state_controller
        if controller is None:
            return None
        return getattr(controller, "profile_id", None)

    @staticmethod
    def _group_name_for_key(key: str, *, source_kind: str) -> str:
        if source_kind == "ad_hoc":
            prefix = key.split(".", 1)[0].strip()
            return prefix.replace("_", " ").title() if prefix else "Ad Hoc"
        return "General"

    @staticmethod
    def _has_meaningful_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, dict, tuple, set)):
            return bool(value)
        return True

    def _validate_effective_metadata(
        self,
        *,
        profile_id: str | None,
        node_type_id: str | None,
        schema: MetadataSchemaSnapshot,
        flat_metadata: dict[str, Any],
        field_sources: dict[str, MetadataFieldSource],
    ) -> MetadataValidationSnapshot:
        schema_index = schema.by_key()
        governance = self.governance_for_profile(profile_id)
        issues: list[MetadataValidationIssue] = []
        missing_required_keys: list[str] = []
        template_key_set: set[str] = set()
        if governance is not None and node_type_id is not None:
            template_key_set = set(
                governance.template_metadata_for_node_type(node_type_id).keys(),
            )
        ad_hoc_keys = sorted(
            key
            for key, field in schema_index.items()
            if field.source_kind == "ad_hoc"
        )
        for key, field in schema_index.items():
            if not field.required:
                continue
            value = flat_metadata.get(key)
            if self._has_meaningful_value(value):
                continue
            missing_required_keys.append(key)
            issues.append(
                MetadataValidationIssue(
                    severity="warning",
                    key=key,
                    group=field.group,
                    message=f"Required field '{field.label}' is missing for {node_type_id or 'this node'}.",
                ),
            )

        if governance is not None and not governance.allow_ad_hoc_fields:
            for key in ad_hoc_keys:
                group = schema_index[key].group if key in schema_index else None
                issues.append(
                    MetadataValidationIssue(
                        severity="warning",
                        key=key,
                        group=group,
                        message=(
                            f"Ad-hoc field '{key}' is outside the governed "
                            f"{profile_id or 'current'} profile schema."
                        ),
                    ),
                )

        grouped: dict[str, list[MetadataFieldDefinition]] = {}
        for field in schema.fields:
            if (
                field.key not in flat_metadata
                and not field.required
                and field.key not in template_key_set
            ):
                continue
            grouped.setdefault(field.group or "General", []).append(field)

        group_statuses: list[MetadataGroupStatus] = []
        for group_name, fields in sorted(grouped.items(), key=lambda item: item[0].lower()):
            total_fields = len(fields)
            present_fields = sum(
                1
                for field in fields
                if self._has_meaningful_value(flat_metadata.get(field.key))
            )
            missing_required = sum(1 for field in fields if field.required and not self._has_meaningful_value(flat_metadata.get(field.key)))
            ad_hoc_fields = sum(1 for field in fields if field.source_kind == "ad_hoc")
            if missing_required > 0:
                status = "warning"
            elif ad_hoc_fields > 0:
                status = "info"
            elif present_fields > 0:
                status = "success"
            else:
                status = "neutral"
            group_statuses.append(
                MetadataGroupStatus(
                    group=group_name,
                    status=status,
                    total_fields=total_fields,
                    present_fields=present_fields,
                    missing_required=missing_required,
                    ad_hoc_fields=ad_hoc_fields,
                ),
            )
        template_keys = tuple(sorted(template_key_set))
        return MetadataValidationSnapshot(
            issues=tuple(issues),
            missing_required_keys=tuple(sorted(missing_required_keys)),
            ad_hoc_keys=tuple(ad_hoc_keys),
            group_statuses=tuple(group_statuses),
            template_keys=template_keys,
        )


_DEFAULT_METADATA_STATE = MetadataStateController()


def clear_metadata_state_cache() -> None:
    """Clear module-level cached nodecard payloads."""

    _DEFAULT_METADATA_STATE.clear_cache()


def resolve_path_node_metadata(
    path: str | Path,
    *,
    exclude_paths: tuple[str | Path, ...] = (),
    boundary_root: str | Path | None = None,
) -> EffectiveMetadataSnapshot:
    """Resolve effective node metadata using the module-level controller."""

    return _DEFAULT_METADATA_STATE.resolve_path_metadata(
        path,
        exclude_paths=exclude_paths,
        boundary_root=boundary_root,
    )
