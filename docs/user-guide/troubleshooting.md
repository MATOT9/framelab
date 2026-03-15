# Troubleshooting

Use this page for operational issues encountered during normal use of the app.

This page is organized by workflow stage so you can isolate whether the problem is in startup, workflow scope, dataset intake, session tools, eBUS inspection, measurement, or analysis.

## 1. App and startup issues

### The Analyze tab is missing

Cause:

- no analysis plugin was enabled at startup

Action:

- close the app
- relaunch it
- enable at least one analysis plugin in the startup selector

### A plugin action is missing from the Plugins menu

Cause:

- the plugin was not enabled before launch
- or the current plugin does not expose a runtime action for the task you expected
- or a plugin such as Session Manager, Background Correction, or eBUS Config Tools was not enabled at startup

Action:

- verify the plugin was enabled in the startup selector
- relaunch with the required plugin enabled

### Help opens the wrong page or a directory listing

Cause:

- the bundled offline help content is stale or was not rebuilt correctly

Action:

- rebuild the bundled documentation
- verify the packaged help files were refreshed after the latest documentation edits

## 2. Workflow profile and scope issues

### The workflow tree looks wrong immediately after loading a folder

Possible causes:

- the selected folder is above or below the intended logical root
- the wrong workflow profile was chosen
- the filesystem layout does not match the profile you chose

Action:

- verify whether you chose **Calibration** or **Trials**
- verify whether the selected path represents a workspace, camera, campaign, session, or acquisition subtree
- compare the actual folder tree against [Workflow Structure and Required Folder Layout](workflow-structure.md)

### A campaign folder was opened, but sessions are missing

Possible causes:

- sessions are not stored directly under the campaign or under `01_sessions` / `sessions`
- the session folders do not contain `session_datacard.json`
- the session folders do not contain discoverable acquisitions

Action:

- verify the campaign layout
- verify the session folder contents
- add `session_datacard.json` where appropriate

### The session loads, but acquisitions are missing from the tree

Possible causes:

- `session_datacard.json.paths.acquisitions_root_rel` points to the wrong place
- acquisitions are stored outside the resolved acquisitions root
- acquisition folders do not match the managed naming contract and do not carry acquisition datacards

Action:

- inspect `session_datacard.json`
- verify the actual acquisitions root on disk
- verify acquisition folder naming and datacard presence

## 3. Data and metadata issues

### No TIFF files were found

Possible causes:

- the selected folder does not contain supported `.tif` or `.tiff` files
- skip rules are excluding the intended files
- the wrong dataset root was selected

Action:

- verify the selected folder
- review skip rules
- rescan after correcting the rule set or folder choice

### The table contains unexpected extra files

Cause:

- the dataset root includes exports, cache folders, previews, or other unrelated TIFFs

Action:

- add or refine skip rules
- rescan the dataset

### Exposure or iris values are missing

Possible causes:

- the wrong metadata source is selected
- the file naming pattern does not encode the expected values
- the acquisition datacard is missing, incomplete, or inconsistent
- the field you expected is eBUS-managed but not actually mapped or discoverable for this acquisition
- the Data table is showing `path_fallback` where you expected authored JSON values

Action:

- switch metadata source and compare the table
- inspect the acquisition datacard if JSON metadata is expected
- inspect the eBUS status line and mapping-backed field behavior if the acquisition relies on an eBUS snapshot
- inspect source fields, not just the numeric value columns
- correct the acquisition metadata before trusting later results

### Grouping looks wrong

Cause:

- the grouping field does not match the intended experiment structure
- the required metadata field is missing or inconsistent across rows
- some rows are empty for the chosen grouping key and therefore fall into group `0`

Action:

- choose the grouping field that corresponds to the sweep variable or folder structure
- inspect the raw grouping values in the Data table
- correct metadata inconsistencies before moving on

### The eBUS status line is missing

Possible causes:

- the selected dataset folder is not the actual acquisition root
- there is no readable root-level `.pvcfg` file
- more than one root-level `.pvcfg` file exists, so the app refuses to guess

Action:

- verify the acquisition root
- verify that exactly one root-level `.pvcfg` file exists
- remove ambiguity before expecting automatic discovery

## 4. Session management issues

### Add or delete is disabled in Session Manager

Cause:

- session numbering is not contiguous

Action:

- use **Normalize/Reindex** first
- then repeat the structural edit once numbering is valid

### Paste Datacard is disabled in Session Manager

Cause:

- the in-memory datacard clipboard is empty

Action:

- copy a source acquisition datacard first
- then return to the destination acquisition and paste the normalized payload

### Toggle eBUS is unavailable in Session Manager

Cause:

- the **eBUS Config Tools** plugin was not enabled at startup
- or no acquisition row is currently selected

Action:

- relaunch with the eBUS plugin enabled if needed
- then reopen Session Manager and select the intended acquisition

## 5. eBUS inspection and compare issues

### The compare dialog opens but does not preload the current acquisition

Cause:

- the selected dataset folder is not a readable acquisition source under the current discovery rules

Action:

- verify the selected dataset root
- verify that the folder has one readable root-level `.pvcfg`
- reopen the compare dialog after correcting the acquisition root

### Raw and effective compare show the same result

Possible causes:

- no app-side eBUS overrides exist for the loaded acquisition source
- only standalone `.pvcfg` files were added
- the changed parameters are not catalog-overridable and therefore remain raw-baseline values

Action:

- verify whether the source list contains an acquisition-root source or only standalone files
- inspect `external_sources.ebus.overrides` if you expected effective differences
- use raw mode when the goal is forensic comparison of saved snapshots only

### A field is read-only in the wizard even though it appears eBUS-related

Cause:

- the field is eBUS-managed and the catalog marks the corresponding key as non-overridable

Action:

- treat the eBUS snapshot as authoritative for that acquisition-wide field
- only use the wizard to override fields whose eBUS catalog entry explicitly allows app-side override

## 6. Measurement issues

### `DN/ms` is blank or unavailable

Cause:

- valid exposure metadata is missing, non-numeric, or zero
- or the current average mode is **Disabled**, so no mean-based quantity exists to normalize by exposure

Action:

- return to **Data**
- verify the selected metadata source
- confirm exposure values are present and valid
- confirm the active average mode is **Top-K Mean** or **ROI Mean**

### ROI metrics are blank or `NaN`

Possible causes:

- no ROI was drawn or loaded
- the ROI is empty
- the loaded ROI is incompatible with the image dimensions
- ROI batch apply was never run for the current dataset

Action:

- draw a valid ROI or load the correct saved ROI
- verify the ROI covers a real image region
- apply ROI to all images for dataset-wide ROI metrics

### Top-K results look unstable

Possible causes:

- `K` is too small for the signal morphology
- hot pixels or clipping dominate the selected brightest set
- the threshold and measurement mode are not aligned with the intended signal definition

Action:

- increase `K`
- inspect saturation count and peak behavior
- confirm that Top-K is the right metric for the study

### Background subtraction does not seem to apply consistently

Possible causes:

- no compatible reference exists for some files
- exposure-keyed matching cannot find a valid background for every image
- reference and image dimensions are incompatible
- folder-library references do not cover every exposure used by the dataset

Action:

- verify the background source and exposure coverage
- verify reference-image dimensions
- treat `raw_fallback` or partial-match status as a real measurement condition, not a cosmetic message

### Normalized values look inconsistent across different scans

Cause:

- normalization is dataset-relative and depends on the current dataset maximum pixel value under the current measurement state

Action:

- verify whether the loaded dataset population changed
- verify whether background subtraction changed the metric image
- compare raw and normalized views deliberately rather than mixing them mentally

## 7. Analysis issues

### The plot looks clean, but the result is obviously physically wrong

Possible causes:

- the wrong workflow scope was scanned
- the wrong metadata source was used
- grouping does not match the actual sweep variable
- upstream measurement settings were wrong

Action:

- return to the workflow scope, Data, and Measure stages
- verify the upstream assumptions before trusting the plot

## Related pages

- [Workflow Structure and Required Folder Layout](workflow-structure.md)
- [Data Workflow](data-workflow.md)
- [Session Manager (Legacy)](data/session-manager.md)
- [Measure Workflow](measure-workflow.md)
- [Analysis Workflow](analysis-workflow.md)
