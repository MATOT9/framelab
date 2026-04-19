# AGENTS

These rules apply inside `framelab/workflow/`.

## Workflow Model

- Workflow loading is profile-driven, not simple folder-depth loading.
- Keep profile definitions in `profiles.py`.
- Keep typed hierarchy state and filesystem discovery in `state.py`.
- Keep reusable node/profile models in `models.py`.
- Keep profile metadata governance in `governance_config.py`.

## Behavior Rules

- Calibration is the primary documented profile.
- Trials exists but remains experimental until known structure/create-new issues are fixed.
- Session discovery should preserve documented support for direct campaign children and `01_sessions/` / `sessions/`.
- Workflow loading may tolerate datacard-backed acquisition folders that are less strict than Session Manager naming.

## Validation

- Workflow loading changes should include `tests/test_workflow_state.py`.
- UI shell selection changes should include workflow window or explorer tests.
- Update architecture and workflow-structure docs when hierarchy contracts change.
