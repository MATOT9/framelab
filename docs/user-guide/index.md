# User Guide

Use this section to operate the app efficiently while still understanding the engineering meaning of its outputs.

The pages below are organized in the same order as a normal session: startup, dataset intake, session-level acquisition preparation when needed, acquisition metadata authoring or eBUS inspection, measurement, then analysis.

## Recommended reading order

1. [Concepts and Limits](concepts-and-limits.md)
2. [Quick Start](quick-start.md)
3. [Plugin Guide](plugins.md)
4. [Plugin Selector](plugin-selector.md)
5. [Data Workflow](data-workflow.md)
6. [Session Manager](data/session-manager.md)
7. [Datacard Wizard](data/datacard-wizard.md)
8. [eBUS Config Tools](data/ebus-config-tools.md)
9. [Measure Workflow](measure-workflow.md)
10. [Analysis Workflow](analysis-workflow.md)
11. [Intensity Trend Explorer](analysis/intensity-trend-explorer.md)
12. [Troubleshooting](troubleshooting.md)

## Page summary

- [Concepts and Limits](concepts-and-limits.md): core vocabulary, metadata hierarchy, measurement concepts, and interpretation limits.
- [Quick Start](quick-start.md): shortest reliable path from launch to usable results.
- [Plugin Guide](plugins.md): what plugins are, what they can change, and where plugin-specific instructions live.
- [Plugin Selector](plugin-selector.md): how startup plugin selection changes the session.
- [Data Workflow](data-workflow.md): dataset scan, skip rules, metadata sources, grouping, and pre-flight verification.
- [Session Manager](data/session-manager.md): session-level acquisition numbering, creation, deletion, datacard copy/paste, and acquisition-local eBUS enable state.
- [Datacard Wizard](data/datacard-wizard.md): acquisition-datacard authoring, inheritance model, frame mapping, and eBUS-managed default behavior.
- [eBUS Config Tools](data/ebus-config-tools.md): inspection and comparison of raw and effective eBUS snapshots.
- [Measure Workflow](measure-workflow.md): thresholding, Top-K, ROI, normalization, background subtraction, and measurement interpretation.
- [Analysis Workflow](analysis-workflow.md): using analysis plugins after the dataset and measurements are already valid.
- [Intensity Trend Explorer](analysis/intensity-trend-explorer.md): analysis-plugin controls, trend interpretation, gain, uncertainty, and overlays.
- [Troubleshooting](troubleshooting.md): workflow-stage troubleshooting for normal app use.

## Operating principle

The app should be read from left to right in workflow terms:

1. define the session and enabled plugins
2. build a trustworthy dataset table
3. prepare the acquisition and metadata record where needed
4. compute meaningful per-image measurements
5. interpret those values in analysis
