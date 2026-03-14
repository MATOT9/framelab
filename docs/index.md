<div class="tv-hero">
  <h1>FrameLab Documentation</h1>
  <p>Technical documentation for the FrameLab application, including dataset intake, hierarchical datacard metadata, session-level acquisition management, eBUS snapshot tooling, measurement workflows, analysis plugins, and the bundled offline Help site.</p>
  <p>Use this site by intent: operator workflow, exact reference contract, developer maintenance, or cross-cutting troubleshooting.</p>
</div>

<div class="tv-link-grid">
  <a class="tv-link-card" href="user-guide/">
    <strong>User Guide</strong>
    Operator workflows for dataset scan, metadata verification, session and datacard tools, background correction, ROI work, and analysis-plugin interpretation.
  </a>
  <a class="tv-link-card" href="reference/">
    <strong>Reference</strong>
    Canonical file locations, manifest fields, acquisition-mapping keys, eBUS catalog entries, and shortcut contracts.
  </a>
  <a class="tv-link-card" href="developer-guide/">
    <strong>Developer Guide</strong>
    Architecture, state ownership, plugin contracts, datacard and eBUS integration, UI boundaries, and packaging rules.
  </a>
  <a class="tv-link-card" href="troubleshooting/">
    <strong>Troubleshooting</strong>
    Cross-cutting triage for scan failures, metadata issues, eBUS anomalies, measurement problems, plugin-loading faults, and offline-help packaging issues.
  </a>
</div>

## How this documentation is organized

This site is divided by **question type** rather than by audience label alone.

### User Guide

Use the **User Guide** when the question is:

- How do I perform this workflow correctly?
- Which control should I use?
- How should I choose a setting, not just click a button?
- What does this table value, plot, or warning actually mean operationally?

Recommended entry points:

- [Concepts and Limits](user-guide/concepts-and-limits.md)
- [Quick Start](user-guide/quick-start.md)
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
- How does startup, metadata resolution, measurement, or analysis flow actually work?
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
- Is this a dataset problem, metadata problem, eBUS problem, measurement problem, analysis problem, or docs-bundle problem?
- What should I verify first before changing code or rewriting data?

Start here:

- [Troubleshooting](troubleshooting/index.md)
- [User Troubleshooting](user-guide/troubleshooting.md)

## Suggested starting points

- First-time operator: [Quick Start](user-guide/quick-start.md)
- Dataset and metadata validation: [Data Workflow](user-guide/data-workflow.md)
- Session-level acquisition preparation: [Session Manager](user-guide/data/session-manager.md)
- Datacard authoring and frame-targeted metadata: [Datacard Wizard](user-guide/data/datacard-wizard.md)
- eBUS snapshot inspection and compare workflows: [eBUS Config Tools](user-guide/data/ebus-config-tools.md)
- Measurement configuration and ROI work: [Measure Workflow](user-guide/measure-workflow.md)
- Plot interpretation and analysis plugins: [Analysis Workflow](user-guide/analysis-workflow.md)
- Schema and config lookup: [Reference](reference/index.md)
- Plugin authoring or maintenance: [Developer Guide](developer-guide/index.md)
- Problem isolation: [Troubleshooting](troubleshooting/index.md)

## Documentation conventions

- **User Guide** pages explain workflows, choice points, interpretation limits, and failure modes.
- **Reference** pages define stable file, field, and schema contracts.
- **Developer Guide** pages describe lifecycle, ownership, extension boundaries, and packaging realities.
- **Troubleshooting** pages help isolate fault location before deeper debugging begins.
- Placeholder screenshots and diagrams are intentional and include target asset paths so final figures can be dropped in without layout rework.

## Offline Help note

The same Markdown source is used to build the offline HTML help bundle opened from the application. When documentation changes are not reflected in Help, treat that as a packaging or docs-bundle issue, not as a page-authoring issue alone.

<figure class="placeholder-figure">
  <img src="assets/images/placeholders/screenshot-placeholder-16x9.svg" alt="Placeholder screenshot for the main FrameLab shell">
  <figcaption>
    Placeholder — Add screenshot: Main FrameLab shell with Data, Measure, and Analyze workflow tabs visible. Target:
    <code>docs/assets/images/user-guide/overview/app-shell-overview.png</code>.
    Theme: dark. Type: screenshot. State: app launched with a scanned dataset and all primary workflow areas visible.
  </figcaption>
</figure>
