# Plugin Selector

The startup plugin selector defines which plugins are loaded for the current session. This step is operationally important. It affects which menus, pages, and analysis tools exist after launch.

## Purpose

Use the selector to build a session that contains exactly the workflows you need. A smaller plugin set usually means:

- lower startup overhead
- fewer runtime actions in the **Plugins** menu
- fewer analysis choices to manage
- less visual clutter in the main window

A larger plugin set is appropriate when you are actively using those workflows or testing their interaction.

## What the selector changes

When a plugin is disabled at startup:

- its entrypoint is not imported
- its widgets are not created
- its runtime actions are not registered
- any plugin-owned analysis view is absent from the session

The selector therefore changes runtime behavior. It does not merely hide checkboxes.

## Window layout

Plugins are grouped by workflow category:

- **Data**
- **Measure**
- **Analysis**

Each row shows:

- a checkbox
- the plugin display name
- a short description of its role

## Dependency behavior

### Enabling a plugin

When you enable a plugin, the selector checks whether other plugins are required for that plugin to work. If dependencies are missing, they are enabled automatically so the final selection remains valid.

### Disabling a plugin

When you disable a plugin, the selector checks whether any enabled plugin depends on it. If so, dependent plugins are also disabled. This prevents invalid plugin combinations from reaching the main window.

## Launch behavior

When you click **Launch**:

1. the selected plugin IDs are stored for the session
2. the main app window opens
3. only the enabled plugin entrypoints are imported
4. plugin-owned workflow areas become available in the UI

If you click **Cancel**, the app exits without opening the main window.

## Practical selection strategy

A few common plugin sets are:

### Single-acquisition measurement session

Enable:

- **Acquisition Datacard Wizard** when metadata editing may be needed
- **Background Correction** when you use background-reference workflows
- **Intensity Trend Explorer** when you intend to analyze the results immediately
- **Event Signature** when you need per-frame event traces

### Structure and session-preparation session

Enable:

- **Acquisition Datacard Wizard**
- **Session Manager (Legacy)** only if you still need datacard copy/paste or acquisition-local eBUS toggles

Use the built-in **Edit -> Advanced -> eBUS Config Tools** menu when snapshot interpretation must be reviewed.

## Common misunderstanding

The startup selector and the **Plugins** menu do different jobs.

- The **startup selector** decides which plugins exist in the session.
- The **Plugins** menu exposes runtime actions for the plugins already loaded.

Opening the **Plugins** menu later does not load a plugin that was disabled before launch.

## Related pages

- [Workflow Structure and Required Folder Layout](workflow-structure.md)
- [Plugin Guide](plugins.md)
- [Session Manager](data/session-manager.md)
- [Datacard Wizard](data/datacard-wizard.md)
- [Measure Workflow](measure-workflow.md)
- [Intensity Trend Explorer](analysis/intensity-trend-explorer.md)
- [Event Signature](analysis/event-signature.md)
