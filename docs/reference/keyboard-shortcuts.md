# Keyboard Shortcuts

This page documents the current shortcut and pointer interaction contract. Shortcut usefulness depends on context. Some actions are app-wide menu commands, while others operate only on the currently focused table or plot.

## App-wide menu shortcuts

| Shortcut | Scope | Action |
| --- | --- | --- |
| `Ctrl+O` | app-wide | Open a saved `.framelab` workspace file |
| `Ctrl+S` | app-wide | Save the current workspace file |
| `Ctrl+Shift+S` | app-wide | Save the current workspace to a new `.framelab` file |
| `Ctrl+R` | app-wide | Scan or rescan the current dataset folder |
| `Ctrl+Shift+W` | app-wide | Show or hide the Workflow Explorer |
| `Ctrl+Shift+E` | app-wide | Export the current image-metrics table |
| `Ctrl+C` | focused table context | Copy selected cells from the active metrics/result table |
| `Ctrl+A` | focused metrics table context | Select all cells in the active metrics table |

## Scope notes

### `Ctrl+C`

`Ctrl+C` is meaningful only when a copy-capable table has focus or an active selection. Current supported contexts include:

- the main metrics tables
- plugin result tables that implement copy behavior

### `Ctrl+A`

`Ctrl+A` is documented here for the main metrics-table workflow. Treat it as a table-selection shortcut, not as a universal “select all widgets in the app” command.

## Pointer and mouse interactions

| Interaction | Scope | Action |
| --- | --- | --- |
| Mouse wheel | image preview or analysis plot under cursor | Zoom the active view |
| Double-click | image preview or analysis plot | Reset the current view extent |
| Right-click | image preview | Open the preview context menu |
| Mouse wheel | histogram plot under cursor | Zoom the histogram around the cursor |
| Drag with left mouse button | histogram plot | Draw a zoom-selection ROI and zoom to it on release |
| Drag with middle mouse button | histogram plot | Pan the current histogram view |
| Double-click | histogram plot | Reset the histogram view extent |
| Right-click | histogram plot | Open histogram view actions such as Reset View |
| Right-click | analysis plot | Open the plot context menu |
| Legend click | analysis plot | Toggle series visibility |

## Platform note

On macOS, standard Qt shortcuts may appear with `Cmd` instead of `Ctrl` depending on platform conventions.

## Usage guidance

Shortcuts are most useful after a dataset is already loaded and the intended table or plot has focus. If a shortcut appears inactive, first confirm:

- the relevant workflow page is open
- the relevant widget has focus
- the current dataset state makes the action meaningful

The Workflow Explorer is the primary workflow surface. `Ctrl+Shift+W` is the fastest way to reveal it again if you have hidden it and need the full node tree back.

The dataset-folder chooser remains available from the File menu and toolbar, but `Ctrl+O` now belongs to the workspace-document flow rather than direct folder browsing.
