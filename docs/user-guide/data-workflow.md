# Data Workflow

The **Data** tab is the intake and verification stage for the entire app. Use it to:

- confirm the folder implied by the current workflow scope
- scan TIFF files recursively inside that scope
- control scan exclusions
- resolve metadata for each image
- verify that the table reflects the acquisition you actually intend to measure and analyze

If the Data tab is wrong, later measurements and plots can still look mathematically clean while being physically wrong.

## Before scanning: confirm the scope

In the workflow shell, the Data page is subordinate to the currently selected workflow node. That means the effective dataset root may come from:

- the full workspace
- a camera subtree
- a campaign subtree
- a session
- one acquisition

Before scanning, confirm:

- the active node in **Workflow Explorer**
- the breadcrumb/path row
- the folder path shown in the dataset field

If the scope itself is wrong, scanning correctly will still produce the wrong dataset. For the expected filesystem layout, see [Workflow Structure and Required Folder Layout](workflow-structure.md).

## Recommended operating sequence

1. Confirm the workflow profile and active node scope.
2. Confirm that the selected folder matches the intended scope.
3. Scan the folder.
4. Adjust skip rules if unwanted files were included.
5. Inspect the metadata table.
6. Choose the correct metadata source.
7. If structure work is still needed, use **Workflow Explorer -> Structure** before going deeper.
8. If the dataset belongs to a legacy session workflow that still needs copy/paste or acquisition-local eBUS toggles, use **Session Manager (Legacy)**.
9. If an eBUS status line appears, decide whether snapshot inspection or compare is required before continuing.
10. Confirm grouping and row content before moving to **Measure** or **Analyze**.

## Dataset input

The dataset input controls define the root path used for TIFF discovery.

| Control | Function | Typical use |
| --- | --- | --- |
| **Dataset / Scope Folder** | Holds the folder path that will be scanned recursively. | Review it to confirm the active workflow scope. |
| **Browse Scope Folder...** or **Open Folder...** | Opens the system folder picker and updates the current scope path. | Use when you intentionally want to override or choose a different folder context. |
| **Scan Selected Scope** or **Scan Folder** | Starts recursive TIFF discovery, skip-rule filtering, metadata extraction, and table refresh. | Use after changing the scope or skip rules. |

Exact button text may differ slightly depending on whether you are in workflow mode or ordinary folder mode.

## What scanning actually does

A scan is not only file listing. It is the dataset intake pass used by the rest of the app. During scan, the app:

- recursively discovers supported `.tif` and `.tiff` files
- applies the current skip rules before loading
- reads each remaining file as a 2D image and skips unreadable items
- caches loaded images for preview and later measurement use
- computes initial static quick-look values such as max pixel and minimum non-zero
- determines whether hierarchical JSON metadata is available anywhere in the selected dataset tree
- rebuilds metadata for every loaded row using the active metadata-source mode
- refreshes the Data table, Measure state, and downstream analysis context

Treat a scan as a dataset-state reset, not as a cosmetic refresh.

## Skip rules

Skip rules exclude files or folders from dataset intake. Use them to keep temporary exports, cache folders, thumbnails, or unrelated TIFFs out of the working dataset.

### Main-page behavior

- **Edit Skip Rules...** opens the dedicated editor.
- The muted status line summarizes how many patterns are active for the current session.
- Rule edits stay with the current window and are restored only when they are part of a saved `.framelab` workspace file. After changing them, rescan the dataset.

### Pattern types

Supported matching styles include common practical cases such as:

- exact names, for example `temp`
- wildcard patterns, for example `*.bak`
- relative path fragments, for example `*/cache/*`
- parent-folder matches when a directory name itself should be skipped

Skip rules are exact string/wildcard filters, not semantic dataset selectors.

## Metadata source selection

The chosen metadata source directly affects grouping, exposure-dependent metrics, and analysis-plugin inputs.

### Path metadata

Use **Path** when file names and folder structure already encode the experiment correctly. Typical examples include:

- exposure or iris embedded in the file name
- exposure or iris embedded in parent folders
- sweep grouping encoded directly in directory names

### Acquisition JSON metadata

Use **Acquisition JSON** when the acquisition-root JSON hierarchy is the authoritative source. In the current implementation, that source can combine:

- acquisition defaults and frame-targeted overrides from `acquisition_datacard.json`
- inherited session defaults from `session_datacard.json`
- inherited campaign defaults and instrument defaults from `campaign_datacard.json`
- inherited workflow-node metadata from `.framelab/nodecard.json`
- effective acquisition-wide eBUS-backed baseline values for canonical mapped fields when the acquisition carries one readable root-level `.pvcfg` snapshot and the field mapping marks the fields as eBUS-managed

When the hierarchical JSON stack does not provide exposure or iris values, the app can still fall back to path-derived values for those specific fields. Treat that fallback as a mixed-source convenience, not as proof that the authored metadata is complete.

### Selection rule

Choose the source that best represents the true acquisition, then keep that source fixed for one interpretation pass. Do not switch metadata source mid-analysis unless you are intentionally comparing metadata strategies.

## eBUS status line

When the selected dataset folder contains exactly one readable root-level `.pvcfg` file, the Data page shows a compact eBUS status line. Use that status line as a cue that:

- the acquisition carries an immutable raw eBUS baseline snapshot
- some canonical acquisition-wide metadata may now be driven by effective eBUS values if the datacard and field mapping declare them as eBUS-managed
- detailed inspection and compare workflows belong in the built-in **eBUS Config Tools**, not in the main Data page layout

The status line does **not** mean the app will compare or modify the snapshot automatically. It only indicates that a discoverable acquisition-local snapshot exists.

## Metadata table

The Data table is the pre-flight check for the rest of the app. Inspect it for:

- the expected number of image rows
- correct file identity and folder context
- correct exposure and iris values
- sensible exposure/iris source fields
- sensible grouping values
- obvious missing or suspicious metadata before moving on

If the table is wrong here, downstream plots inherit the error.

## Grouping

Grouping clusters rows by one selected field for table organization and operator review. Current behavior is fixed by the UI, not free-form:

- base choices are **None**, **Parent Folder**, and **Grandparent Folder**
- plugins may expose additional grouping fields such as **Iris Position** and **Exposure [ms]**
- grouping is by exact string token
- missing values become group `0`
- **None** places every row in group `1`
- non-empty values are sorted and assigned group ids starting at `1`

Grouping is useful for visually checking sweep structure before measurement or analysis. It does not change row metadata.

## Structure work versus data verification

The Data tab is where you verify what will be measured. It is not the primary place to repair hierarchy. Use **Workflow Explorer -> Structure** first when you still need to:

- create a session under a campaign
- create one or more acquisitions under a session
- rename an acquisition label
- delete or reindex acquisitions
- delete a session

Use **Session Manager (Legacy)** only when you still need the remaining legacy actions:

- acquisition-datacard copy/paste
- acquisition-local eBUS enable toggles
- direct legacy session repair outside the workflow shell

## What to verify before leaving Data

Before moving to **Measure**, confirm all of the following:

- the intended workflow scope was loaded
- the intended dataset root was scanned
- skip rules did not exclude valid images
- unreadable files, if any, were intentionally skipped or understood
- the metadata source reflects the true acquisition record
- exposure and iris values are present where required
- grouping matches the intended sweep or comparison logic
- any detected eBUS snapshot has been either accepted as baseline or explicitly reviewed through the eBUS tools when needed
- no obvious metadata inconsistency remains in the table

## Common failure modes

### Correct scan, wrong scope

Symptom:

- the table looks internally consistent, but it contains the wrong acquisition or the wrong session population

Action:

- verify the active workflow node
- verify the dataset field path
- verify whether you opened a workspace, campaign, session, or acquisition subtree

### Correct files, wrong metadata source

Symptom:

- TIFF rows look valid, but exposure or iris values are missing or wrong

Action:

- switch metadata source and re-check the table

### Valid metadata source, incomplete JSON hierarchy

Symptom:

- some rows still lack exposure or iris values even though JSON metadata is expected

Action:

- inspect the acquisition datacard
- inspect session, campaign, and node-level metadata if those layers are expected to contribute inherited defaults
- inspect source fields to see whether you are actually seeing `path_fallback`
- correct the dataset-side metadata before trusting later workflows

### eBUS status line is missing when a snapshot is expected

Symptom:

- the selected dataset should have an acquisition-local snapshot, but the status line is blank

Action:

- verify that the selected dataset folder itself is the acquisition root
- verify that exactly one root-level `.pvcfg` file exists there
- move or remove extra root-level `.pvcfg` files before expecting automatic discovery

### Unwanted files inflate the dataset

Symptom:

- unexpected extra rows appear after scan

Action:

- add skip rules and rescan

## Recommended next pages

- [Workflow Structure and Required Folder Layout](workflow-structure.md)
- [Session Manager](data/session-manager.md)
- [Datacard Wizard](data/datacard-wizard.md)
- [eBUS Config Tools](data/ebus-config-tools.md)
- [Measure Workflow](measure-workflow.md)
- [Analysis Workflow](analysis-workflow.md)
