# Analysis Workflow

The **Analyze** tab is the final interpretation stage of the app. It uses the dataset and measurement results prepared upstream to build plots, derived tables, and comparison views through enabled analysis plugins.

This page assumes the following are already correct:

- the intended dataset has been scanned in **Data**
- the metadata source and grouping are correct
- the measurement mode and related options were configured in **Measure**

The Analyze tab is not the place to repair missing metadata or ambiguous measurement choices. A well-formed plot can still be physically misleading if the upstream dataset or measurement state was wrong.

## Purpose of the Analyze tab

Use the Analyze tab to convert per-image measurement results into higher-level comparisons such as:

- signal versus exposure
- signal versus iris position
- gain relative to a reference condition
- aggregated trends with uncertainty bars

Analysis plugins do not create new raw measurements. They reorganize, aggregate, and visualize quantities that already exist in the measurement stage.

## Normal workflow

1. Enable at least one analysis plugin in the startup selector.
2. Scan the dataset in **Data**.
3. Verify metadata source, metadata values, and grouping.
4. Configure the required measurement mode in **Measure**.
5. Open **Analyze**.
6. Select the desired **analysis plugin** from the page-level plugin selector.
7. Configure the plugin-specific controls.
8. Interpret the result table and plot together.

If no analysis plugin was enabled at startup, the **Analyze** tab is hidden.

## Page structure

The exact controls depend on the active analysis plugin, but the Analyze tab generally contains:

- an **Analysis Plugin** selector at the top of the page
- a plugin-specific control panel
- a result table
- a plot area
- plugin-specific runtime actions in the **Plugins** menu

The selector at the top of the page switches between analysis plugins that were already loaded for the current session. It is not a preset manager and it does not load disabled plugins after launch.

## Startup selector versus plugin selector

Two selectors are involved in analysis, and they serve different roles.

### Startup selector

The **startup selector** appears before the main window opens. Its job is to determine which plugins exist in the session at all.

If an analysis plugin is disabled here:

- its code is not loaded for the session
- its widget is not created
- its runtime menu actions do not appear
- it cannot be selected later from the Analyze tab

### Analyze-page plugin selector

The **Analysis Plugin** selector inside the Analyze tab switches between analysis plugins that were already enabled at startup.

Use it when you want to change the active analysis view without restarting the app.

## What analysis plugins receive

Analysis plugins consume a prepared `AnalysisContext`, not raw TIFF files.

That context already contains:

- the active measurement mode
- per-row metadata resolved from the selected metadata source
- mean/std/SEM values for the active average mode
- peak, min non-zero, and saturation count metadata where available
- `DN/ms`, `DN/ms` std, and `DN/ms` SEM where available
- background-state labels
- the active raw versus normalized intensity context

Because of that, analysis results are downstream of the Data and Measure choices. Changing metadata source, normalization, or background handling changes what the plugin receives.

## Working with analysis plugins

A good operating sequence is:

1. confirm that the plugin was enabled before launch
2. confirm that the required measurement quantities exist
3. select the plugin in the Analyze-page selector
4. configure plugin-specific controls
5. compare the plot against the result table
6. use plugin runtime actions when needed

In practice, the table and the plot should be read together:

- use the **plot** for trend shape, monotonicity, spread, and reference comparison
- use the **table** for exact point values, sample counts, and uncertainty values

A plot alone is usually insufficient when you need to verify aggregation behavior or judge whether a trend is supported by enough samples.

## Current built-in analysis plugin

The current built-in analysis plugin is **Intensity Trend Explorer**.

Use its dedicated page for plugin-specific details such as:

- axis options
- gain semantics
- curve construction
- error-bar meaning
- overlay behavior
- plugin-specific runtime actions

See: [Intensity Trend Explorer](analysis/intensity-trend-explorer.md)

## Common failure patterns

### Analyze tab missing

Cause:

- no analysis plugin was enabled at startup

### Selector present, but expected plugin missing

Cause:

- the plugin was disabled at startup
- or a different plugin set was loaded than the one you intended

### Plot looks valid but interpretation is wrong

Cause:

- the plot is downstream of wrong upstream state, such as metadata source, normalization, background handling, or measurement mode

Action:

- return to **Data** and **Measure** first
- verify the upstream state before trusting the analysis result

## What to verify before trusting an analysis result

- the plugin was enabled intentionally
- the selected dataset is correct
- the metadata source is correct
- the active measurement mode produced the metric the plugin needs
- normalization and background state are the intended ones
- the plotted result is consistent with the plugin's result table

## Related pages

- [Concepts and Limits](concepts-and-limits.md)
- [Measure Workflow](measure-workflow.md)
- [Intensity Trend Explorer](analysis/intensity-trend-explorer.md)
