# Quick Start

Use this page when you want the shortest reliable path from launch to interpretable results.

This workflow assumes you already know which dataset you want to inspect and which acquisition variable you intend to compare.

## Recommended session flow

1. Launch the app and enable only the plugins required for the session.
2. If you are preparing or selecting acquisitions inside a session rather than going straight to one dataset folder, open **Session Manager** first and load the intended acquisition into the main window.
3. On **Data**, select the dataset folder and click **Scan Folder**.
4. If unwanted files were included, open **Edit Skip Rules...**, update the patterns, and rescan.
5. Review the metadata table and choose the correct metadata source.
6. If the dataset carries hierarchical JSON metadata or an eBUS snapshot, decide whether you need the **Session Manager**, **Acquisition Datacard Wizard**, or **eBUS Config Tools** before continuing.
7. On **Measure**, choose the measurement mode that matches the comparison you want to make.
8. Verify the preview, histogram, and measurement table before moving on.
9. On **Analyze**, select the analysis plugin and configure the plot for the intended sweep or comparison.

## Minimal decision path

When time is limited, make these decisions in order:

### 1. Confirm the metadata source

Choose the source that most faithfully represents the acquisition:

- **Path** when file names and folders already encode the experiment correctly
- **Acquisition JSON** when the acquisition-root JSON path defines the authoritative metadata, including any inherited session or campaign defaults

Do not continue to measurement until exposure, iris position, and grouping fields are correct in the Data table.

### 2. Decide whether session-level preparation is needed

Use **Session Manager** when you need to:

- create or delete acquisition folders inside one session
- normalize or reindex acquisition numbering
- rename acquisition labels
- copy one acquisition datacard to another acquisition
- toggle acquisition-local eBUS enable state before loading the dataset

If the acquisition already exists and only its canonical metadata needs authoring, you can skip straight to the wizard.

### 3. Decide whether acquisition-side metadata editing is needed

Use:

- **Acquisition Datacard Wizard** when defaults, frame-targeted overrides, or canonical acquisition metadata must be authored or corrected
- **eBUS Config Tools** when you need to inspect or compare `.pvcfg` snapshots before deciding whether a canonical app-side override is justified

Do not open the wizard simply because an eBUS snapshot exists. Use it when a canonical acquisition record or approved app-side override is actually required.

### 4. Choose the measurement mode

Use:

- **Top-K Mean** for bright-feature tracking when the brightest region may move slightly
- **ROI Mean** when the same spatial region must be compared across images
- **Disabled** when you only need threshold-based metrics such as saturation inspection

### 5. Verify exposure-dependent metrics

If later interpretation depends on `DN/ms`, verify that exposure metadata is present and numerically valid before leaving **Data**.

### 6. Choose the analysis plugin

On **Analyze**, use the plugin that matches the question being asked. In the current app, the primary built-in analysis plugin is **Intensity Trend Explorer**.

## Fast sanity checklist

Before trusting a result, confirm:

- the intended dataset root was scanned
- the correct metadata source is selected
- exposure and iris values are populated where required
- the chosen measurement mode matches the physical comparison
- any session-manager, datacard, or eBUS intervention was intentional rather than incidental

## Related pages

- [Data Workflow](data-workflow.md)
- [Session Manager](data/session-manager.md)
- [Datacard Wizard](data/datacard-wizard.md)
- [eBUS Config Tools](data/ebus-config-tools.md)
- [Measure Workflow](measure-workflow.md)
- [Analysis Workflow](analysis-workflow.md)
