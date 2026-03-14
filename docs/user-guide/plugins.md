# Plugin Guide

Plugins extend the app by adding workflow actions, embedded UI, or analysis capabilities without forcing every feature into the base window.

Use this page to understand what plugins are allowed to change, when they are loaded, and where their detailed user documentation lives.

## Plugin roles in the current app

### Data plugins

Data plugins extend dataset-side workflows. In the current app, the built-in data plugins are:

- **Acquisition Datacard Wizard** — create, edit, validate, and save acquisition datacards for the selected dataset
- **Session Manager** — manage acquisitions inside one session, including numbering, add/delete, datacard copy/paste, and acquisition-local eBUS enable state
- **eBUS Config Tools** — inspect raw `.pvcfg` snapshots, compare sources in raw or effective mode, and hand off to the datacard wizard when canonical app-side metadata changes are required

### Measure plugins

The current shipped build includes one measure-page plugin:

- **Background Correction** — opens a dedicated dialog for loading and controlling background references while still using the host-owned measurement state on the Measure page

This is an important distinction: the plugin provides a focused runtime tool, but the measurement semantics remain owned by the host workflow page.

### Analysis plugins

Analysis plugins extend the **Analyze** tab with specialized plotting or result interpretation tools. In the current app, the built-in analysis plugin is:

- **Intensity Trend Explorer** — plot measurement-stage quantities against exposure or iris position, with optional error bars and trend overlays

## What a plugin can contribute

Depending on its type, a plugin can add one or more of the following:

- a startup-selector entry
- one or more runtime actions in the **Plugins** menu
- embedded controls inside an existing workflow page
- additional fields, grouping options, or result views
- an analysis view with its own plot, table, and interpretation logic

Plugins do not all behave the same way. Some are action-oriented and only add menu entries. Others own a substantial interactive view inside the main workflow.

## Startup loading versus runtime use

These are separate concepts.

### Startup loading

The startup selector determines which plugins are part of the session at all.

If a plugin is not enabled at startup:

- its entrypoint is not imported
- its runtime actions are not registered
- its analysis view or page-local extensions do not exist in the session

### Runtime use

After startup, loaded plugins expose whatever UI they own:

- menu actions under **Plugins**
- embedded analysis views
- page-specific controls or status additions
- focused dialogs such as **Session Manager** or **Background Correction**

## Practical guidance

- Keep the enabled set lean when you want a simpler session and lower startup overhead.
- Enable additional plugins only when their workflow is part of the current task.
- Use **Session Manager** when the acquisition folders themselves still need to be prepared.
- Use the **eBUS Config Tools** plugin for snapshot inspection and cross-source compare, not as a replacement for canonical datacard authoring.
- Use the **Acquisition Datacard Wizard** when you need a stable acquisition record, frame-targeted metadata, or approved app-side overrides of eBUS-managed canonical fields.
- Use **Background Correction** when you want a focused dialog around the same host-owned background-subtraction state used by the Measure page.

## Where to find plugin-specific instructions

This page is the generic overview. Detailed usage belongs to the pages that match the plugin's workflow.

Current plugin-specific user pages:

- [Session Manager](data/session-manager.md)
- [Datacard Wizard](data/datacard-wizard.md)
- [eBUS Config Tools](data/ebus-config-tools.md)
- [Intensity Trend Explorer](analysis/intensity-trend-explorer.md)

## When to use the Plugins menu

Open the **Plugins** menu when you need:

- the **Session Manager** for one session root
- the **Acquisition Datacard Wizard** for the current dataset
- the **eBUS Config Tools** for snapshot inspect or compare work
- the **Background Correction** dialog for a focused background-reference workflow
- analysis-plugin actions such as table export or plot-copy helpers

## Related pages

- [Plugin Selector](plugin-selector.md)
- [Data Workflow](data-workflow.md)
- [Measure Workflow](measure-workflow.md)
- [Analysis Workflow](analysis-workflow.md)

<figure class="placeholder-figure">
  <img src="../assets/images/placeholders/screenshot-placeholder-16x9.svg" alt="Placeholder screenshot for the startup plugin selector">
  <figcaption>
    Placeholder — Add screenshot: Startup plugin selector with Data, Measure, and Analyze groups visible. Target:
    <code>docs/assets/images/user-guide/plugins/plugin-selector-grouped.png</code>.
    Theme: dark. Type: screenshot. State: Session Manager, Background Correction, and Intensity Trend Explorer visible in their respective groups.
  </figcaption>
</figure>
