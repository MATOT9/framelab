# Keyboard Shortcuts

This page documents the current shortcut and pointer interaction contract.

Shortcut usefulness depends on context. Some actions are app-wide menu commands, while others operate only on the currently focused table or plot.

## App-wide menu shortcuts

| Shortcut | Scope | Action |
| --- | --- | --- |
| `Ctrl+O` | app-wide | Open a dataset folder |
| `Ctrl+R` | app-wide | Scan or rescan the current dataset folder |
| `Ctrl+Shift+E` | app-wide | Export the current image-metrics table |
| `Ctrl+C` | focused table context | Copy selected cells from the active metrics/result table |
| `Ctrl+A` | focused metrics table context | Select all cells in the active metrics table |

## Scope notes

### `Ctrl+C`

`Ctrl+C` is meaningful only when a copy-capable table has focus or an active selection.

Current supported contexts include:

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
| Right-click | analysis plot | Open the plot context menu |
| Legend click | analysis plot | Toggle series visibility |

## Platform note

On macOS, standard Qt shortcuts may appear with `Cmd` instead of `Ctrl` depending on platform conventions.

## Usage guidance

Shortcuts are most useful after a dataset is already loaded and the intended table or plot has focus.

If a shortcut appears inactive, first confirm:

- the relevant workflow page is open
- the relevant widget has focus
- the current dataset state makes the action meaningful
