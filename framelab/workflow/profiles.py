"""Built-in workflow profiles."""

from __future__ import annotations

from .governance_config import load_governance_overrides, merge_governance
from .models import (
    MetadataFieldRule,
    MetadataGovernanceProfile,
    NodeTypeDefinition,
    WorkflowProfile,
)


_CALIBRATION_GOVERNANCE = MetadataGovernanceProfile(
    allow_ad_hoc_fields=True,
    allow_ad_hoc_groups=True,
    field_rules=(
        MetadataFieldRule(
            key="workflow.operator",
            label="Operator",
            group="Workflow",
            value_type="string",
            required_node_types=("session",),
            template_node_types=("session",),
            template_value="",
        ),
        MetadataFieldRule(
            key="workflow.notes",
            label="Workflow Notes",
            group="Workflow",
            value_type="string",
            template_node_types=("session", "campaign"),
            template_value="",
        ),
        MetadataFieldRule(
            key="instrument.optics.iris.position",
            label="Iris Position",
            group="Optics",
            value_type="float",
            required_node_types=("session",),
            template_node_types=("session",),
            template_value=0,
        ),
    ),
)

_TRIALS_GOVERNANCE = MetadataGovernanceProfile(
    allow_ad_hoc_fields=True,
    allow_ad_hoc_groups=True,
    field_rules=(
        MetadataFieldRule(
            key="workflow.operator",
            label="Operator",
            group="Workflow",
            value_type="string",
            template_node_types=("session",),
            template_value="",
        ),
        MetadataFieldRule(
            key="workflow.conditions",
            label="Field Conditions",
            group="Workflow",
            value_type="string",
            template_node_types=("trial", "session"),
            template_value="",
        ),
    ),
)


CALIBRATION_WORKFLOW_PROFILE = WorkflowProfile(
    profile_id="calibration",
    display_name="Calibration",
    root_display_name="Calibration Workspace",
    description=(
        "Structured calibration hierarchy with cameras, campaigns, sessions, "
        "and acquisitions."
    ),
    metadata_governance=_CALIBRATION_GOVERNANCE,
    node_types=(
        NodeTypeDefinition(
            type_id="root",
            display_name="Workspace",
            child_type_ids=("camera",),
            discovery_mode="directories",
        ),
        NodeTypeDefinition(
            type_id="camera",
            display_name="Camera",
            child_type_ids=("campaign",),
            discovery_mode="directories",
        ),
        NodeTypeDefinition(
            type_id="campaign",
            display_name="Campaign",
            child_type_ids=("session",),
            discovery_mode="directories",
        ),
        NodeTypeDefinition(
            type_id="session",
            display_name="Session",
            child_type_ids=("acquisition",),
            discovery_mode="session_acquisitions",
        ),
        NodeTypeDefinition(
            type_id="acquisition",
            display_name="Acquisition",
            child_type_ids=(),
            discovery_mode="leaf",
        ),
    ),
)


TRIALS_WORKFLOW_PROFILE = WorkflowProfile(
    profile_id="trials",
    display_name="Trials",
    root_display_name="Trials Workspace",
    description=(
        "Field and trial hierarchy with trials, cameras, sessions, and "
        "acquisitions."
    ),
    metadata_governance=_TRIALS_GOVERNANCE,
    node_types=(
        NodeTypeDefinition(
            type_id="root",
            display_name="Workspace",
            child_type_ids=("trial",),
            discovery_mode="directories",
        ),
        NodeTypeDefinition(
            type_id="trial",
            display_name="Trial",
            child_type_ids=("camera",),
            discovery_mode="directories",
        ),
        NodeTypeDefinition(
            type_id="camera",
            display_name="Camera",
            child_type_ids=("session",),
            discovery_mode="directories",
        ),
        NodeTypeDefinition(
            type_id="session",
            display_name="Session",
            child_type_ids=("acquisition",),
            discovery_mode="session_acquisitions",
        ),
        NodeTypeDefinition(
            type_id="acquisition",
            display_name="Acquisition",
            child_type_ids=(),
            discovery_mode="leaf",
        ),
    ),
)


CUSTOM_WORKFLOW_PROFILE = WorkflowProfile(
    profile_id="custom",
    display_name="Custom",
    root_display_name="Custom Workspace",
    description=(
        "Fallback workflow for directories that do not match a structured "
        "calibration or trials hierarchy."
    ),
    node_types=(
        NodeTypeDefinition(
            type_id="root",
            display_name="Folder",
            child_type_ids=(),
            discovery_mode="leaf",
        ),
    ),
)


def built_in_workflow_profiles() -> tuple[WorkflowProfile, ...]:
    """Return the built-in workflow profiles in stable order."""

    overrides = load_governance_overrides()
    return (
        merge_governance(
            CALIBRATION_WORKFLOW_PROFILE,
            overrides.get("calibration"),
        ),
        merge_governance(
            TRIALS_WORKFLOW_PROFILE,
            overrides.get("trials"),
        ),
        merge_governance(
            CUSTOM_WORKFLOW_PROFILE,
            overrides.get("custom"),
        ),
    )


def workflow_profile_by_id(profile_id: str) -> WorkflowProfile | None:
    """Return one built-in profile by identifier."""

    target = str(profile_id).strip().lower()
    for profile in built_in_workflow_profiles():
        if profile.profile_id == target:
            return profile
    return None


def base_workflow_profile_by_id(profile_id: str) -> WorkflowProfile | None:
    """Return one built-in profile without user governance overrides."""

    target = str(profile_id).strip().lower()
    for profile in (
        CALIBRATION_WORKFLOW_PROFILE,
        TRIALS_WORKFLOW_PROFILE,
        CUSTOM_WORKFLOW_PROFILE,
    ):
        if profile.profile_id == target:
            return profile
    return None
