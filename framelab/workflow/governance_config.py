"""Config-backed metadata governance overrides for workflow profiles."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..payload_utils import read_json_dict, write_json_dict
from ..scan_settings import app_config_path
from .models import MetadataFieldRule, MetadataGovernanceProfile, WorkflowProfile


_CONFIG_FILE_NAME = "workflow_metadata_governance.json"


@dataclass(frozen=True, slots=True)
class GovernanceOverride:
    """Parsed config override for one profile governance block."""

    allow_ad_hoc_fields: bool | None = None
    allow_ad_hoc_groups: bool | None = None
    field_rules: tuple[MetadataFieldRule, ...] = ()

    def field_rule_index(self) -> dict[str, MetadataFieldRule]:
        """Return override field rules indexed by metadata key."""

        return {rule.key: rule for rule in self.field_rules}


def governance_config_path() -> Path:
    """Return the runtime config path for workflow metadata governance."""

    return app_config_path(_CONFIG_FILE_NAME)


def _parse_field_rule(item: dict[str, Any]) -> MetadataFieldRule | None:
    key = str(item.get("key", "")).strip()
    label = str(item.get("label", "")).strip()
    group = str(item.get("group", "")).strip()
    if not key:
        return None
    if not label:
        label = key.replace(".", " ").replace("_", " ").title()
    if not group:
        group = key.split(".", 1)[0].replace("_", " ").title()

    def _tuple_of_strings(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(
            entry
            for entry in (
                str(item).strip() for item in value if str(item).strip()
            )
        )

    options = _tuple_of_strings(item.get("options"))
    return MetadataFieldRule(
        key=key,
        label=label,
        group=group,
        value_type=str(item.get("value_type", item.get("type", "any"))).strip() or "any",
        options=options,
        required_node_types=_tuple_of_strings(item.get("required_node_types")),
        template_node_types=_tuple_of_strings(item.get("template_node_types")),
        template_value=deepcopy(item.get("template_value")),
        inheritable=bool(item.get("inheritable", True)),
    )


def load_governance_overrides() -> dict[str, GovernanceOverride]:
    """Load user-editable governance overrides keyed by profile id."""

    payload = read_json_dict(governance_config_path())
    if not isinstance(payload, dict):
        return {}
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        return {}

    loaded: dict[str, GovernanceOverride] = {}
    for profile_id, item in profiles.items():
        if not isinstance(item, dict):
            continue
        raw_fields = item.get("fields")
        field_rules: list[MetadataFieldRule] = []
        if isinstance(raw_fields, list):
            for entry in raw_fields:
                if not isinstance(entry, dict):
                    continue
                parsed = _parse_field_rule(entry)
                if parsed is not None:
                    field_rules.append(parsed)
        loaded[str(profile_id).strip().lower()] = GovernanceOverride(
            allow_ad_hoc_fields=(
                bool(item["allow_ad_hoc_fields"])
                if "allow_ad_hoc_fields" in item
                else None
            ),
            allow_ad_hoc_groups=(
                bool(item["allow_ad_hoc_groups"])
                if "allow_ad_hoc_groups" in item
                else None
            ),
            field_rules=tuple(field_rules),
        )
    return loaded


def merge_governance(
    base_profile: WorkflowProfile,
    override: GovernanceOverride | None,
) -> WorkflowProfile:
    """Return a profile with merged governance rules and flags."""

    if override is None:
        return base_profile
    base_rules = base_profile.metadata_governance.field_rule_index()
    merged_rules = dict(base_rules)
    for key, rule in override.field_rule_index().items():
        merged_rules[key] = rule
    return WorkflowProfile(
        profile_id=base_profile.profile_id,
        display_name=base_profile.display_name,
        root_display_name=base_profile.root_display_name,
        node_types=base_profile.node_types,
        description=base_profile.description,
        metadata_governance=MetadataGovernanceProfile(
            allow_ad_hoc_fields=(
                override.allow_ad_hoc_fields
                if override.allow_ad_hoc_fields is not None
                else base_profile.metadata_governance.allow_ad_hoc_fields
            ),
            allow_ad_hoc_groups=override.allow_ad_hoc_groups
            if override.allow_ad_hoc_groups is not None
            else base_profile.metadata_governance.allow_ad_hoc_groups,
            field_rules=tuple(sorted(merged_rules.values(), key=lambda item: item.key)),
        ),
    )


def promote_field_rule(
    profile_id: str,
    *,
    key: str,
    label: str,
    group: str,
    value_type: str = "string",
    options: tuple[str, ...] = (),
) -> Path:
    """Promote one field into the user-editable profile governance overlay."""

    clean_profile_id = str(profile_id).strip().lower()
    clean_key = str(key).strip()
    if not clean_profile_id or not clean_key:
        raise ValueError("profile_id and key are required to promote a field rule")

    path = governance_config_path()
    payload = read_json_dict(path) or {"schema_version": "1.0", "profiles": {}}
    if not isinstance(payload, dict):
        payload = {"schema_version": "1.0", "profiles": {}}
    profiles = payload.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        payload["profiles"] = profiles

    profile_payload = profiles.setdefault(clean_profile_id, {})
    if not isinstance(profile_payload, dict):
        profile_payload = {}
        profiles[clean_profile_id] = profile_payload
    fields = profile_payload.setdefault("fields", [])
    if not isinstance(fields, list):
        fields = []
        profile_payload["fields"] = fields

    promoted_payload = {
        "key": clean_key,
        "label": str(label).strip() or clean_key,
        "group": str(group).strip() or clean_key.split(".", 1)[0].title(),
        "value_type": str(value_type).strip() or "string",
    }
    if options:
        promoted_payload["options"] = [str(option) for option in options]

    for index, entry in enumerate(fields):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("key", "")).strip() != clean_key:
            continue
        fields[index] = promoted_payload
        break
    else:
        fields.append(promoted_payload)

    write_json_dict(path, payload)
    return path
