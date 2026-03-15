# Workflow Structure and Required Folder Layout

Use this page to decide **how the filesystem should be organized before you start scanning TIFF data**.

This matters because the workflow shell is profile-driven. The app does not treat every directory tree as equivalent. Reliable workflow loading, session authoring, metadata inheritance, and acquisition-management tools all work best when the dataset follows the expected hierarchy.

## Recommended mental model

### Camera

A **camera** is a long-lived asset. Keep one top-level camera folder per physical system or stable camera identity.

### Campaign

A **campaign** is one coherent calibration effort.

A campaign can span multiple days. It is the right place to keep:

- final outputs for that calibration effort
- derived products that combine several sessions
- campaign-level notes or workflow metadata

### Session

A **session** is one stable block of work.

Create a new session when the setup changes meaningfully enough that you no longer want later acquisitions to inherit the same working context.

Typical reasons to split sessions:

- optics were changed
- camera configuration changed in a meaningful way
- environmental conditions changed enough to matter
- the work resumed later and should be treated as a separate capture block

Multiple sessions on the same day are supported and recommended when the setup really changed.

### Acquisition

An **acquisition** is one intent, one datacard, one block of frames.

Keep acquisitions semantically narrow. Good examples are:

- one dark sweep
- one iris sweep
- one exposure sweep
- one flat-field run
- one stability check

Do not treat an acquisition as an entire day of unrelated captures.

## Built-in workflow profiles

## Calibration

This is the primary structured workflow profile.

Its logical hierarchy is:

```text
workspace -> camera -> campaign -> session -> acquisition
```

Use this profile for lab and calibration work where cameras are long-lived assets and campaigns collect several sessions over time.

## Trials

The Trials profile is available, but it should still be treated as **experimental**.

Its logical hierarchy is:

```text
workspace -> trial -> camera -> session -> acquisition
```

Use it only when trial-first organization is genuinely the right fit and you accept that the calibration profile is the more mature path.

## Exact folder-layout expectations

## Calibration profile

The calibration profile expects a workspace whose immediate children are camera folders.

Recommended layout:

```text
<workspace_root>/
  <camera_id>/
    .framelab/nodecard.json                optional higher-level workflow metadata
    <campaign_id>/
      .framelab/nodecard.json              optional higher-level workflow metadata
      campaign_datacard.json               optional legacy compatibility layer
      01_sessions/                         optional but recommended container
        <session_id>/
          .framelab/nodecard.json          optional higher-level workflow metadata
          session_datacard.json            recommended
          acquisitions/                    default acquisitions root
            acq-0001__dark/
              acquisition_datacard.json
              frames/
              notes/
              thumbs/
            acq-0002__iris_sweep/
              acquisition_datacard.json
              frames/
              notes/
              thumbs/
```

The workflow loader also supports these variants:

- session folders directly under the campaign folder
- a session container named `sessions` instead of `01_sessions`
- a session datacard that redirects acquisitions through `paths.acquisitions_root_rel`
- an acquisition discovered from its datacard even if the folder name is not parseable, although session-management tooling is stricter than workflow discovery

### Recommended calibration layout in compact form

```text
workspace/
  camera/
    campaign/
      01_sessions/
        YYYY-MM-DD__sess01/
          session_datacard.json
          acquisitions/
            acq-0001__dark/
            acq-0002__flat/
            acq-0003__iris/
```

### What is strongly recommended versus merely supported

For the calibration profile, the safest operating choice is:

- use one camera folder per camera
- use one campaign folder per coherent calibration effort
- keep sessions inside `01_sessions/`
- keep acquisitions inside `acquisitions/`
- create `session_datacard.json` for every session
- use the `acq-####` naming contract for every managed acquisition

The loader is more tolerant than the recommended structure, but the docs intentionally describe the layout that is easiest to maintain and least surprising.

## Trials profile

Recommended layout:

```text
<workspace_root>/
  <trial_id>/
    .framelab/nodecard.json
    <camera_id>/
      .framelab/nodecard.json
      <session_id>/
        session_datacard.json
        acquisitions/
          acq-0001/
          acq-0002__run_b/
```

Again, the trials workflow should be considered experimental.

## Discovery rules that matter in practice

These rules come directly from the current workflow and session-management code.

### Session discovery under campaigns

For the calibration profile, sessions may be discovered:

- directly under the campaign folder, or
- under a child folder named `01_sessions`, or
- under a child folder named `sessions`

A folder looks like a session when either of the following is true:

- it contains `session_datacard.json`, or
- it contains discoverable acquisitions

### Acquisition discovery under sessions

For a session, acquisition discovery first tries the session acquisitions root:

- `session_datacard.json.paths.acquisitions_root_rel` when present and non-empty
- otherwise `session_root/acquisitions`

If that path does not yield acquisitions, the workflow loader may still fall back to direct child folders under the session when they look like acquisitions.

### Acquisition folder recognition

A folder is treated as an acquisition when either of the following is true:

- it contains `acquisition_datacard.json`, or
- its name matches `acq-####` or `acq-####__label` **and** it contains a `frames/` directory

The workflow loader is intentionally more permissive than the structural editing tools.

### Session-management naming contract

Session-management operations such as add, rename, delete, and reindex only manage acquisition folders that match this contract:

```text
acq-####
acq-####__label
```

That contract is case-insensitive for parsing, but you should not rely on mixed casing in normal usage.

## Naming guidance

The app does not strictly enforce every folder name above the acquisition level, but consistent naming reduces ambiguity.

### Camera folder

Use a stable camera identity, for example:

```text
cam_visible_main
cam_mwir_a
xenics_bobcat_640
```

### Campaign folder

Use a label that describes one coherent effort, for example:

```text
2026-03_linearity
2026-03_iris_response
uv_calibration_round2
```

### Session folder

The code accepts arbitrary non-empty folder names without path separators, but the recommended format is:

```text
YYYY-MM-DD__sessNN
```

Examples:

```text
2026-03-05__sess01
2026-03-05__sess02
2026-03-06__sess01
```

This format works well because:

- it allows multiple sessions on the same day
- it stays readable in the Workflow Explorer
- it keeps chronology obvious without forcing the app to infer meaning from folder depth

### Acquisition folder

Use the required acquisition contract:

```text
acq-0001
acq-0002__dark
acq-0003__iris_opening
```

Prefer short semantic labels after the double underscore. The label should describe the acquisition intent, not repeat the whole campaign name.

## Datacards and nodecards in the structure

Higher-level workflow metadata and acquisition-local metadata do not serve the same purpose.

### `.framelab/nodecard.json`

Use nodecards for generic workflow-node metadata on folders such as:

- camera
- campaign
- session
- trial

This is the preferred higher-level metadata mechanism for the workflow shell.

### `campaign_datacard.json`

This remains a compatibility layer for campaign-level defaults and instrument defaults.

### `session_datacard.json`

This remains operationally important because it can:

- define `session_defaults`
- redirect the acquisitions root through `paths.acquisitions_root_rel`
- support session tooling

### `acquisition_datacard.json`

This is still the authoritative acquisition-local canonical metadata record.

Use it for:

- stable acquisition defaults
- frame-targeted overrides
- acquisition-local eBUS enable state and app-side overrides

## How to decide where to split work

A practical rule is:

- new **campaign** when the work is a distinct calibration effort with its own outputs
- new **session** when the setup changed meaningfully or the work block should stand on its own
- new **acquisition** when the capture intent changed

Examples:

- change only exposure across several runs with the same setup -> usually same session, multiple acquisitions
- switch optics or move to a different physical arrangement -> new session
- begin a different calibration objective with different deliverables -> new campaign

## Common layout mistakes

### Mixing TIFF files directly under the campaign folder

This bypasses the normal camera/campaign/session/acquisition model and makes structure harder to interpret.

### Using arbitrary acquisition folder names

The workflow loader may still discover some acquisitions through datacards, but session-management tools will not treat arbitrary names as managed acquisitions.

### Treating a full day of unrelated captures as one acquisition

This usually produces a weak datacard, weak grouping, and poor analysis semantics.

### Loading a folder above the intended workspace without checking the anchor

The workflow shell can open partial subtrees, but you should confirm whether you opened:

- the full workspace
- a camera subtree
- a campaign subtree
- a session subtree
- one acquisition

Use the breadcrumb and profile chips to verify the loaded scope.

## Recommended starting point

For most work, start with the calibration profile and this layout:

```text
workspace/
  camera/
    campaign/
      01_sessions/
        YYYY-MM-DD__sess01/
          session_datacard.json
          acquisitions/
            acq-0001__dark/
            acq-0002__flat/
            acq-0003__iris/
```

That layout is the clearest match to the current code, the workflow shell, the session tools, and the metadata model.

## Related pages

- [Quick Start](quick-start.md)
- [Data Workflow](data-workflow.md)
- [Session Manager (Legacy)](data/session-manager.md)
- [Reference: Config Files](../reference/config-files.md)
- [Developer Guide: Architecture](../developer-guide/architecture.md)
