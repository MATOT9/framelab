# Troubleshooting

Use this page for operational issues encountered during normal use of the app.

This page is organized by workflow stage so you can isolate whether the problem is in startup, dataset intake, session tools, eBUS inspection, measurement, or analysis.

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

## 2. Data and metadata issues

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

## 3. Session management issues

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

## 4. eBUS inspection and compare issues

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

## 5. Measurement issues

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

- compare normalized values only when the dataset context is intentionally the same
- switch back to raw values for cross-dataset engineering comparison when appropriate

### Preview and table disagree

Possible causes:

- the preview is showing a different selected row than the one you think you are reading
- the table is showing normalized values while you are visually reasoning in raw DN
- background subtraction changed the metric image even though the raw TIFF looks different

Action:

- reselect the row explicitly
- verify raw versus normalized display state
- verify whether background subtraction is active

### Exported table does not match what you expected

Possible causes:

- you exported the currently visible table, not a hypothetical full schema view
- column visibility, sorting, or active measure mode changed what was visible at export time

Action:

- verify the current visible table state before exporting again
- re-export after setting the intended columns and mode

## 6. Analysis issues

### No curves appear in the plot

Possible causes:

- the selected X or Y variable has insufficient valid data
- required metadata is missing
- the active measurement mode did not produce the quantity needed by the plugin

Action:

- verify measurement-stage values first
- check metadata completeness on **Data**
- confirm the selected Y mode is compatible with the available measurements

### The plot looks correct, but the interpretation seems wrong

Cause:

- upstream metadata source, normalization state, background handling, or measurement mode is not the intended one

Action:

- return to **Data** and **Measure**
- verify the full upstream state before drawing conclusions from the plot

### Gain jumps sharply or behaves unexpectedly

Possible causes:

- the reference point is not the one you intended
- the underlying signal is noisy or partially invalid
- exposure-dependent inputs to `DN/ms` are incorrect
- you are in the iris-position gain special case, which is built from aggregated `DN/ms`

Action:

- verify the gain reference mode
- inspect the table values behind the curve
- confirm exposure metadata and measurement stability

### The plot and result table disagree with the preview or Measure table

Possible causes:

- normalization changed the plugin input values
- background subtraction changed the metric image used upstream
- the plugin is aggregating repeated operating points, so one plotted point is not one original row

Action:

- inspect the Measure table first
- then inspect the plugin result table
- only then interpret the plot

## 7. Datacard authoring issues

### Defaults do not behave as expected

Check whether the authored value belongs in **Defaults** or **Frame Mapping**.

Use **Defaults** only for values that should apply acquisition-wide unless specifically replaced.

### An override did not clear an inherited value

Cause:

- blank override fields do not erase inherited defaults

Action:

- enter the explicit replacement value you want
- do not rely on blank fields to clear inherited metadata

### Validation fails before save

Possible causes:

- a field name is unknown
- a value type is incompatible with the mapped field definition
- frame targeting is inconsistent

Action:

- reload the field mapping if needed
- inspect the offending row and value type
- correct the structure before saving

## 8. When to escalate

Escalate beyond normal user troubleshooting when:

- repeated rescans produce inconsistent row populations without any dataset change
- correct metadata still produces obviously invalid analysis behavior
- background application appears inconsistent despite valid matching conditions
- eBUS effective compare appears inconsistent with the stored datacard override block
- the app fails during launch or scan instead of producing a recoverable workflow-state issue
