# Troubleshooting

Use this section when something is wrong and you need to decide **where the fault is most likely located** before you start changing data, plugins, or code.

This section is intentionally broader than the **User Troubleshooting** page. The user-guide page handles normal operator checks during a session. This page is the cross-cutting triage page for workflow-scope mistakes, dataset issues, metadata failures, eBUS anomalies, measurement state, plugin enablement, and docs packaging.

## How to use this section

Work in the following order:

1. Confirm the problem category.
2. Perform the minimum checks for that category.
3. Decide whether the issue belongs to workflow structure, dataset content, app configuration, metadata authoring, eBUS discovery, plugin enablement, or documentation packaging.
4. Escalate to the user guide, reference, or developer guide only after the failure surface is clear.

## Problem categories

### 1. Workflow profile, hierarchy, and scope problems

Use this branch when the wrong part of the filesystem was opened or when the workflow tree itself looks wrong.

Typical symptoms:

- the loaded tree is missing sessions or acquisitions
- the selected folder opened as the wrong logical node type
- a campaign folder was opened but no sessions appear
- a session loads but acquisitions are missing
- the dataset table is internally consistent but clearly comes from the wrong scope

First checks:

- confirm whether **Calibration** or **Trials** was chosen
- confirm whether the selected folder represents a workspace, camera, campaign, session, or acquisition subtree
- compare the on-disk layout against the documented workflow structure
- inspect `session_datacard.json.paths.acquisitions_root_rel` when session contents appear incomplete

See:

- [Workflow Structure and Required Folder Layout](../user-guide/workflow-structure.md)
- [User Troubleshooting](../user-guide/troubleshooting.md)
- [Architecture](../developer-guide/architecture.md)

### 2. Dataset intake and scan failures

Use this branch when the dataset does not scan as expected or when the row count is clearly wrong.

Typical symptoms:

- no TIFF files appear after scan
- too few or too many files are loaded
- expected folders are missing from the table
- rows appear, but the dataset is obviously not the intended one

First checks:

- confirm the selected dataset folder is the intended root
- verify that the folder actually contains supported `.tif` or `.tiff` files
- inspect the active skip rules for overly broad patterns
- rescan after changing the folder or skip rules

See:

- [User Troubleshooting](../user-guide/troubleshooting.md)
- [Data Workflow](../user-guide/data-workflow.md)
- [Config Files](../reference/config-files.md)

### 3. Metadata, datacard, and eBUS resolution problems

Use this branch when images load but exposure, iris position, grouping, or frame-linked metadata are missing or suspicious.

Typical symptoms:

- exposure or iris columns are blank
- JSON-backed metadata is missing even though a datacard exists
- path-derived values disagree with authored datacard values
- frame-specific overrides do not appear where expected
- an eBUS snapshot is expected but not detected
- an eBUS-managed canonical field behaves differently than ordinary defaults

First checks:

- verify the current **Metadata Source** selection
- confirm the session root and acquisitions root are the ones you intended when using Session Manager
- confirm the acquisition root actually contains the intended datacard
- confirm the datacard defaults and overrides match the dataset layout
- confirm frame naming and indexing assumptions are correct for the acquisition
- verify whether the acquisition root contains exactly one readable root-level `.pvcfg`
- distinguish an ordinary canonical-default problem from an eBUS-managed acquisition-wide field problem

See:

- [User Troubleshooting](../user-guide/troubleshooting.md)
- [Datacard Wizard](../user-guide/data/datacard-wizard.md)
- [eBUS Config Tools](../user-guide/data/ebus-config-tools.md)
- [Acquisition Mapping](../reference/acquisition-mapping.md)
- [eBUS Parameter Catalog](../reference/ebus-parameter-catalog.md)
- [Datacard System](../developer-guide/datacard-system.md)
- [eBUS Config Integration](../developer-guide/ebus-config-integration.md)

### 4. Measurement-stage problems

Use this branch when the dataset scans correctly, but the numeric metrics look wrong, unstable, blank, or physically implausible.

Typical symptoms:

- `DN/ms` is blank or appears only for some rows
- ROI metrics remain empty
- Top-K values behave unexpectedly after changing `K`
- saturation count does not react as expected to the threshold
- background subtraction loads but results remain inconsistent
- preview content and numeric metrics appear to disagree

First checks:

- confirm the selected **Average Mode** matches the intended measurement
- confirm exposure metadata exists when interpreting `DN/ms`
- confirm ROI mode actually has a valid ROI before batch application
- confirm the loaded background source is compatible with the dataset
- check whether missing values are caused by mixed shapes or incomplete metadata rather than a UI failure

See:

- [User Troubleshooting](../user-guide/troubleshooting.md)
- [Measure Workflow](../user-guide/measure-workflow.md)
- [Architecture](../developer-guide/architecture.md)

### 5. Analysis and plugin-loading problems

Use this branch when analysis controls, plots, or plugin-specific actions are missing or inconsistent.

Typical symptoms:

- the **Analyze** tab is absent
- an expected plugin is missing from the selector
- runtime plugin actions are missing from the **Plugins** menu
- plots load but do not reflect the intended upstream metadata or measurement state
- eBUS compare is available but the wizard hand-off action is missing

First checks:

- confirm the relevant plugin was enabled in the startup selector
- confirm required dependencies were enabled automatically or manually
- confirm the dataset and measurement stage already produced the values the plugin expects
- distinguish a missing plugin from a missing acquisition-side prerequisite such as a discoverable `.pvcfg`

See:

- [User Troubleshooting](../user-guide/troubleshooting.md)
- [Analysis Workflow](../user-guide/analysis-workflow.md)
- [Plugin Manifests](../reference/plugin-manifests.md)
- [Plugin System](../developer-guide/plugin-system.md)

### 6. Offline help and documentation packaging problems

Use this branch when the app launches, but the Help system opens stale content, directory listings, or missing-page fallbacks.

Typical symptoms:

- Help opens a directory listing instead of a page
- Help content is missing or outdated after doc edits
- packaged builds show older docs than source runs
- links resolve in the browser but not from the bundled help tree

First checks:

- rebuild the offline docs bundle
- confirm the bundled help output was copied into the expected asset location
- confirm the docs navigation and file paths match the current repository layout
- confirm you are not looking at stale packaged assets from an earlier build

See:

- [User Troubleshooting](../user-guide/troubleshooting.md)
- [Packaging](../developer-guide/packaging.md)
- [Reference Index](../reference/index.md)

## Fast triage matrix

| Symptom | Most likely layer | Go to first |
| --- | --- | --- |
| Tree missing sessions/acquisitions | workflow layout or scope | [Workflow Structure](../user-guide/workflow-structure.md) |
| No files after scan | dataset path or skip rules | [User Troubleshooting](../user-guide/troubleshooting.md) |
| Add/delete blocked in Session Manager | non-contiguous acquisition numbering | [Session Manager](../user-guide/data/session-manager.md) |
| Exposure or iris missing | metadata source or datacard | [Datacard Wizard](../user-guide/data/datacard-wizard.md) |
| eBUS snapshot not detected | acquisition-root discovery | [eBUS Config Tools](../user-guide/data/ebus-config-tools.md) |
| `DN/ms` missing | exposure metadata or measurement mode | [Measure Workflow](../user-guide/measure-workflow.md) |
| Analyze tab missing | plugin enablement | [Analysis Workflow](../user-guide/analysis-workflow.md) |
| Help opens wrong content | docs packaging | [Packaging](../developer-guide/packaging.md) |

## Escalation rule

Do not jump directly into code changes unless the failure has already been localized.

Use this rule of thumb:

- if the problem is visible during ordinary use, start in the **User Guide**
- if the problem is about file locations, schema keys, or manifests, continue to **Reference**
- if the problem is about startup flow, workflow loading, host/plugin boundaries, packaging, or internal contracts, continue to the **Developer Guide**
