# Quick Start

Use this page when you want the shortest reliable path from launch to interpretable results. This workflow assumes you already know which dataset you want to inspect and which acquisition variable you intend to compare.

## Recommended session flow

1. Launch the app and enable only the plugins required for the session.
2. Choose the workflow profile and workspace root.
3. Confirm the active node, breadcrumb, and scope chips in **Workflow Explorer**.
4. If the filesystem layout is still being designed or repaired, stop and read [Workflow Structure and Required Folder Layout](workflow-structure.md) before scanning.
5. Use **Metadata Inspector** to confirm inherited and local metadata for the active node.
6. On **Data**, confirm the dataset folder implied by the active node scope and click **Scan Selected Scope** if needed.
7. If unwanted files were included, open **Edit Skip Rules...**, update the patterns, and rescan.
8. Review the metadata table and choose the correct metadata source.
9. If the dataset carries hierarchical JSON metadata or an eBUS snapshot, decide whether you need **Workflow Explorer -> Structure**, the **Acquisition Datacard Wizard**, **eBUS Config Tools**, or the **Session Manager (Legacy)** fallback before continuing.
10. On **Measure**, choose the measurement mode that matches the comparison you want to make.
11. Verify the preview, histogram, and measurement table before moving on.
12. On **Analyze**, select the analysis plugin and configure the plot for the intended sweep or comparison.

## Minimal decision path

When time is limited, make these decisions in order.

### 1. Confirm the workflow profile and scope

For most work, use the **Calibration** profile. Its intended logical hierarchy is:

```text
workspace -> camera -> campaign -> session -> acquisition
```

Use the **Trials** profile only when a trial-first layout is truly required. It is still experimental. Do not continue until you know whether you opened the full workspace or only a subtree such as one camera, campaign, session, or acquisition.

### 2. Confirm the metadata source

Choose the source that most faithfully represents the acquisition:

- **Path** when file names and folders already encode the experiment correctly
- **Acquisition JSON** when the acquisition-root JSON path defines the authoritative metadata, including any inherited session, campaign, or node-level values

Do not continue to measurement until exposure, iris position, and grouping fields are correct in the Data table.

### 3. Decide whether structure work is still needed

Use **Workflow Explorer** first when you need to:

- change the active workspace scope
- move between workflow nodes
- inspect which node is currently driving Data, Measure, and Analyze

Use **Workflow Explorer -> Structure** when you need to:

- create or delete sessions
- create or delete acquisition folders inside one session
- normalize or reindex acquisition numbering
- rename acquisition labels

Use **Session Manager (Legacy)** only when you specifically need to:

- copy one acquisition datacard to another acquisition
- toggle acquisition-local eBUS enable state before loading the dataset

If the acquisition already exists and only its canonical metadata needs authoring, you can skip straight to the wizard.

### 4. Decide whether metadata editing is needed

Use:

- **Metadata Inspector** when you need to edit generic workflow-node metadata or understand inherited values
- **Acquisition Datacard Wizard** when defaults, frame-targeted overrides, or canonical acquisition metadata must be authored or corrected
- **eBUS Config Tools** when you need to inspect or compare `.pvcfg` snapshots before deciding whether a canonical app-side override is justified

Do not open the wizard simply because an eBUS snapshot exists. Use it when a canonical acquisition record or approved app-side override is actually required.

### 5. Choose the measurement mode

Use:

- **Top-K Mean** for bright-feature tracking when the brightest region may move slightly
- **ROI Mean** when the same spatial region must be compared across images
- **Disabled** when you only need threshold-based metrics such as saturation inspection

### 6. Verify exposure-dependent metrics

If later interpretation depends on `DN/ms`, verify that exposure metadata is present and numerically valid before leaving **Data**.

### 7. Choose the analysis plugin

On **Analyze**, use the plugin that matches the question being asked. In the current app, the primary built-in analysis plugin is **Intensity Trend Explorer**.

## Fast sanity checklist

Before trusting a result, confirm:

- the intended workflow profile is loaded
- the intended dataset scope was scanned
- the folder structure matches the workflow you think you are using
- the correct metadata source is selected
- exposure and iris values are populated where required
- the chosen measurement mode matches the physical comparison
- any workflow-structure, legacy session-manager, datacard, or eBUS intervention was intentional rather than incidental

## Related pages

- [Workflow Structure and Required Folder Layout](workflow-structure.md)
- [Data Workflow](data-workflow.md)
- [Session Manager (Legacy)](data/session-manager.md)
- [Datacard Wizard](data/datacard-wizard.md)
- [eBUS Config Tools](data/ebus-config-tools.md)
- [Measure Workflow](measure-workflow.md)
- [Analysis Workflow](analysis-workflow.md)
