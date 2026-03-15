<div class="tv-hero">
  <h1>FrameLab Documentation</h1>
  <p>Technical documentation for the FrameLab application, including workflow-scoped TIFF intake, hierarchical metadata, calibration-oriented folder structure, session and acquisition tooling, eBUS snapshot workflows, measurement pipelines, analysis plugins, and the bundled offline Help site.</p>
  <p>Use this site by intent: operator workflow, exact reference contract, developer maintenance, or cross-cutting troubleshooting.</p>
</div>

<div class="tv-link-grid">
  <a class="tv-link-card" href="user-guide/">
    <strong>User Guide</strong>
    Operator workflows for workflow selection, required folder layout, dataset scan, metadata verification, structure tools, background correction, ROI work, and analysis-plugin interpretation.
  </a>
  <a class="tv-link-card" href="reference/">
    <strong>Reference</strong>
    Canonical file locations, manifest fields, acquisition-mapping keys, eBUS catalog entries, and shortcut contracts.
  </a>
  <a class="tv-link-card" href="developer-guide/">
    <strong>Developer Guide</strong>
    Architecture, state ownership, workflow hierarchy contracts, plugin boundaries, datacard and eBUS integration, UI structure, and packaging rules.
  </a>
  <a class="tv-link-card" href="troubleshooting/">
    <strong>Troubleshooting</strong>
    Cross-cutting triage for scope mistakes, scan failures, metadata issues, eBUS anomalies, measurement problems, plugin-loading faults, and offline-help packaging issues.
  </a>
</div>

## How this documentation is organized

This site is divided by **question type** rather than by audience label alone.

### User Guide

Use the **User Guide** when the question is:

- How do I perform this workflow correctly?
- Which control should I use?
- What folder structure should I respect?
- How should I choose a setting, not just click a button?
- What does this table value, plot, or warning actually mean operationally?

Recommended entry points:

- [Concepts and Limits](user-guide/concepts-and-limits.md)
- [Quick Start](user-guide/quick-start.md)
- [Workflow Structure and Required Folder Layout](user-guide/workflow-structure.md)
- [Data Workflow](user-guide/data-workflow.md)
- [Session Manager](user-guide/data/session-manager.md)
- [Datacard Wizard](user-guide/data/datacard-wizard.md)
- [eBUS Config Tools](user-guide/data/ebus-config-tools.md)
- [Measure Workflow](user-guide/measure-workflow.md)
- [Analysis Workflow](user-guide/analysis-workflow.md)

### Reference

Use **Reference** when the question is:

- Where is this file stored?
- What keys are valid in this JSON file?
- What does one manifest or catalog field mean exactly?
- Which keyboard shortcut applies in this context?

Recommended entry points:

- [Reference Index](reference/index.md)
- [Config Files](reference/config-files.md)
- [Plugin Manifests](reference/plugin-manifests.md)
- [Acquisition Mapping](reference/acquisition-mapping.md)
- [eBUS Parameter Catalog](reference/ebus-parameter-catalog.md)

### Developer Guide

Use the **Developer Guide** when the question is:

- Which module owns this behavior?
- How does startup, workflow loading, metadata resolution, measurement, or analysis flow actually work?
- What folder-structure assumptions does the workflow shell make?
- What contract must be preserved during a refactor or extension?
- Which assets or scripts must stay synchronized for packaging?

Recommended entry points:

- [Developer Guide](developer-guide/index.md)
- [Architecture](developer-guide/architecture.md)
- [Plugin System](developer-guide/plugin-system.md)
- [Datacard System](developer-guide/datacard-system.md)
- [eBUS Config Integration](developer-guide/ebus-config-integration.md)
- [UI Structure](developer-guide/ui-structure.md)
- [Packaging](developer-guide/packaging.md)

### Troubleshooting

Use **Troubleshooting** when the question is:

- Which subsystem is most likely failing?
- Is this a workflow-scope problem, dataset problem, metadata problem, eBUS problem, measurement problem, analysis problem, or docs-bundle problem?
- What should I verify first before changing code or rewriting data?

Start here:

- [Troubleshooting](troubleshooting/index.md)
- [User Troubleshooting](user-guide/troubleshooting.md)

## Suggested starting points

- First-time operator: [Quick Start](user-guide/quick-start.md)
- Required hierarchy and naming: [Workflow Structure and Required Folder Layout](user-guide/workflow-structure.md)
- Dataset and metadata validation: [Data Workflow](user-guide/data-workflow.md)
- Structure or acquisition preparation: [Session Manager](user-guide/data/session-manager.md)
- Maintenance work: [Developer Guide](developer-guide/index.md)

## Profile maturity note

For most real work, the **Calibration** workflow profile is the primary documented path. The **Trials** profile is documented, but it should still be treated as experimental.
