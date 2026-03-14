# Session Manager

Use **Session Manager** when you need to manage acquisition folders inside one session before or alongside ordinary dataset analysis.

This tool is a session-level organizer. It does not replace the **Data** tab, and it does not replace the **Acquisition Datacard Wizard**. Instead, it helps you prepare the acquisition tree that the rest of the app will later scan and interpret.

## What this tool is for

Use **Session Manager** to:

- load one session root and inspect all managed acquisitions under it
- create a new acquisition folder at the end of the numbering sequence
- rename the label suffix of an existing acquisition folder
- delete an acquisition and close the numbering gap behind it
- normalize or reindex acquisition numbering from a chosen starting number
- open the selected acquisition directly in the main window
- open the datacard wizard for the selected acquisition
- copy one acquisition datacard and paste a normalized copy onto another acquisition
- toggle the acquisition-local eBUS enabled state when the eBUS tools plugin is also enabled

## Session structure expected by the tool

The Session Manager looks for a **session root** and then resolves the **acquisitions root** from `session_datacard.json`.

Current behavior:

- if `session_datacard.json.paths.acquisitions_root_rel` is present and non-empty, that relative path is used
- otherwise the default acquisitions root is `session_root/acquisitions`

Only folders whose names match the acquisition naming contract are managed:

```text
acq-#### 
acq-####__label
```

Folders that do not match that pattern are ignored by the acquisition list.

## Main workflow

A reliable operating sequence is:

1. Open **Plugins -> Open Session Manager...**
2. Choose the session folder and click **Load Session**
3. Inspect numbering state, clipboard state, and acquisition list
4. Perform any structural edits needed for the session
5. Use **Load Selected** to push the chosen acquisition into the main window
6. Continue in **Data**, **Measure**, and **Analyze** as usual

## Understanding the acquisition table

The table summarizes one row per managed acquisition.

Current columns are:

- **Number** — parsed acquisition number from the folder name
- **Name** — label suffix, if present
- **Folder** — acquisition folder name
- **Datacard** — whether `acquisition_datacard.json` exists
- **eBUS Snapshot** — whether one readable root-level `.pvcfg` snapshot is discoverable
- **eBUS** — whether acquisition-local eBUS usage is enabled in the datacard
- **Frames** — discovered frame count when the configured frames directory can be indexed

Use the table as a session-preparation surface, not as a substitute for the main dataset table.

## Numbering rules

The Session Manager is intentionally conservative about structural edits.

### Valid numbering

A session is considered numbering-valid when the managed acquisitions are contiguous from the detected starting number.

Example of valid numbering:

```text
acq-0011__one
acq-0012__two
acq-0013__three
```

### Invalid numbering

A session becomes numbering-invalid when there is a gap or other non-contiguous sequence.

Example:

```text
acq-0011__one
acq-0013__three
```

When numbering is invalid:

- the dialog warns that reindexing is needed
- **Add Acquisition** is blocked
- **Delete Acquisition** is blocked
- **Normalize/Reindex** remains available so the sequence can be repaired

This is intentional. The tool does not silently guess how structural edits should behave when the sequence is already inconsistent.

## Actions and what they actually do

### Load Selected

Loads the selected acquisition into the main window by writing its path into the host dataset field and triggering a full dataset load.

Use this when you want Session Manager to act as the acquisition chooser for the rest of the app.

### Add Acquisition

Creates a new acquisition folder at the end of the current contiguous sequence.

Current behavior:

- the new folder is named from the detected or requested starting number and label
- standard child folders `frames`, `notes`, and `thumbs` are created
- no acquisition datacard is forced immediately

### Rename

Changes only the label suffix of the selected acquisition folder while preserving its acquisition number.

If the acquisition already has a datacard, the datacard is normalized so that identity and path fields remain consistent with the new folder name.

### Delete Acquisition

Deletes the selected acquisition folder and then renumbers later acquisitions contiguously to close the gap.

Use this cautiously. It is a structural edit, not only a metadata edit.

### Normalize/Reindex

Renumbers all managed acquisitions contiguously from the chosen starting number.

This is the recovery operation for sessions whose numbering is not contiguous.

### Edit Datacard

Opens the **Acquisition Datacard Wizard** directly on the selected acquisition.

This works because **Session Manager** depends on the datacard wizard plugin.

### Copy Datacard / Paste Datacard

Copies one acquisition datacard into an in-memory clipboard and pastes a normalized version onto another acquisition.

Important current behavior:

- the pasted payload is normalized for the destination acquisition folder name
- acquisition identity and path fields are rewritten for the target
- acquisition-side eBUS attachment bookkeeping is stripped during paste
- app-side eBUS override values remain part of the copied payload when present

Treat paste as a controlled reuse tool, not as a blind file copy.

### Toggle eBUS

Toggles `external_sources.ebus.enabled` for the selected acquisition.

This action is available only when the **eBUS Config Tools** plugin is also enabled.

Use it when the acquisition should explicitly opt in or out of using the discoverable root-level eBUS snapshot as part of effective metadata resolution.

## Relationship to the rest of the app

Use **Session Manager** for session structure and acquisition selection.

Use **Data** for:

- TIFF discovery
- skip rules
- metadata source choice
- row-level table verification

Use **Acquisition Datacard Wizard** for:

- editing canonical acquisition metadata
- frame-targeted overrides
- approved app-side overrides of eBUS-managed canonical fields

Use **eBUS Config Tools** for:

- raw snapshot inspection
- raw versus effective compare
- deciding whether a canonical override is justified

## Common situations

### I need a new acquisition folder before I can load data

Use **Add Acquisition**, then **Load Selected**.

### I copied the wrong acquisition metadata to the new run

Select the destination acquisition and use **Paste Datacard** with the correct clipboard payload. The tool will normalize acquisition identity and path fields for the destination.

### Session numbering is invalid and edits are blocked

Use **Normalize/Reindex** first. Structural edits are intentionally blocked until numbering becomes contiguous again.

### The selected acquisition should stop using its eBUS snapshot

Use **Toggle eBUS**. This changes the acquisition-local enabled state in the datacard rather than editing the raw `.pvcfg` file.

## Troubleshooting cues

### Add or delete is disabled

The most common reason is that session numbering is not contiguous. Reindex first.

### Copy works but paste is disabled

The datacard clipboard is empty. Copy a source acquisition datacard first.

### Toggle eBUS is disabled

The selected acquisition may be missing, or the **eBUS Config Tools** plugin was not enabled at startup.

### Load Selected did not change the dataset

Verify that the session row is selected and that the main window still exists behind the dialog.

## Related pages

- [Data Workflow](../data-workflow.md)
- [Datacard Wizard](datacard-wizard.md)
- [eBUS Config Tools](ebus-config-tools.md)
- [Reference: Config Files](../../reference/config-files.md)

<figure class="placeholder-figure">
  <img src="../../assets/images/placeholders/screenshot-placeholder-16x9.svg" alt="Placeholder screenshot for the Session Manager dialog">
  <figcaption>
    Placeholder — Add screenshot: Session Manager dialog with a loaded session and several acquisitions listed. Target:
    <code>docs/assets/images/user-guide/data/session-manager-overview.png</code>.
    Theme: dark. Type: screenshot. State: session loaded, one row selected, summary strip visible.
  </figcaption>
</figure>

<figure class="placeholder-figure">
  <img src="../../assets/images/placeholders/screenshot-placeholder-16x9.svg" alt="Placeholder screenshot for a numbering warning in Session Manager">
  <figcaption>
    Placeholder — Add screenshot: Session Manager showing non-contiguous numbering and the Normalize/Reindex workflow. Target:
    <code>docs/assets/images/user-guide/data/session-manager-reindex-warning.png</code>.
    Theme: dark. Type: screenshot. State: numbering invalid warning visible, reindex controls emphasized.
  </figcaption>
</figure>
