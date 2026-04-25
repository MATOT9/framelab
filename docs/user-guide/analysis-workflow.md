# Analysis Workflow

The **Analyze** tab is the final interpretation stage of the app. It uses the dataset and measurement results prepared upstream to build plots, derived tables, and comparison views through enabled analysis plugins. This page assumes the following are already correct:

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

Analysis plugins do not silently create new raw measurements during scan or context refresh. They reorganize, aggregate, and visualize measurement-stage quantities, and their explicit action may request missing metric families when the plugin declares them as requirements.

## Normal workflow

1. Enable at least one analysis plugin in the startup selector.
2. Scan the dataset in **Data**.
3. Verify metadata source, metadata values, and grouping.
4. Configure the required measurement mode in **Measure**.
5. Open **Analyze**.
6. Select the desired **analysis plugin** from the page-level plugin selector.
7. Review the plugin requirement message. If a required metric is missing, use the plugin action button to request it explicitly or return to **Measure** to apply the needed settings first.
8. Configure the plugin-specific controls.
9. Click the plugin action button, such as **Compute Trend** or **Build Signature**.
10. Interpret the result table and plot together.

If no analysis plugin was enabled at startup, the **Analyze** tab is hidden.

## Page structure

The exact controls depend on the active analysis plugin, but the Analyze tab generally contains:

- a top summary band with the active plugin and current dataset context
- a left rail with the **Analysis Plugin** selector, plugin requirement status, explicit plugin action, and plugin-specific controls
- a right-side workspace with the result table and plot
- plugin-specific runtime actions in the **Plugins** menu

The selector at the top of the page switches between analysis plugins that were already loaded for the current session. It is not a preset manager and it does not load disabled plugins after launch. The left rail is intentionally lightweight. If you need more horizontal room for the result table or plot, collapse the plugin controls band from the rail and keep the workspace open on the right.

## Startup selector versus plugin selector

Two selectors are involved in analysis, and they serve different roles.

### Startup selector

The **startup selector** appears before the main window opens. Its job is to determine which plugins exist in the session at all. If an analysis plugin is disabled here:

- its code is not loaded for the session
- its widget is not created
- its runtime menu actions do not appear
- it cannot be selected later from the Analyze tab

### Analyze-page plugin selector

The **Analysis Plugin** selector inside the Analyze tab switches between analysis plugins that were already enabled at startup. Use it when you want to change the active analysis view without restarting the app.

## What analysis plugins receive

Analysis plugins consume a prepared `AnalysisContext`, not raw TIFF files. That context already contains:

- the active measurement mode
- per-row metadata resolved from the selected metadata source
- mean/std/SEM values for the active average mode
- peak, min non-zero, and saturation count metadata where available
- frame index and elapsed-time metadata where available
- ROI Top-K values where available
- `DN/ms`, `DN/ms` std, and `DN/ms` SEM where available
- background-state labels
- the active raw versus normalized intensity context

Because of that, analysis results are downstream of the Data and Measure choices. Changing metadata source, normalization, or background handling changes what the plugin receives.

Context refresh is intentionally passive. Opening Analyze, switching plugins, or clicking **Refresh Context** updates the data snapshot delivered to the plugin, but it does not run the plugin's table/plot computation or add new metric work to the Data scan setup. Plugin computation starts from the plugin action button in the Analyze rail or an equivalent plugin menu action.

## Working with analysis plugins

A good operating sequence is:

1. confirm that the plugin was enabled before launch
2. confirm that the required measurement quantities exist
3. select the plugin in the Analyze-page selector
4. configure plugin-specific controls
5. click the plugin action button to compute or refresh the result
6. compare the plot against the result table
7. use plugin runtime actions when needed

In practice, the table and the plot should be read together:

- use the **plot** for trend shape, monotonicity, spread, and reference comparison
- use the **table** for exact point values, sample counts, and uncertainty values

A plot alone is usually insufficient when you need to verify aggregation behavior or judge whether a trend is supported by enough samples.

## Current built-in analysis plugins

The current built-in analysis plugins are:

- **Intensity Trend Explorer** for exposure and iris-position trend studies.
- **Event Signature** for per-frame event traces against frame index or elapsed time.

See: [Intensity Trend Explorer](analysis/intensity-trend-explorer.md) and [Event Signature](analysis/event-signature.md)

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

### Requirement message lists a missing metric

Cause:

- the dataset has not been scanned yet
- or a required metric family was not requested
- or Measure has pending inputs that need to be applied first

Action:

- scan the dataset if **Static scan** is missing
- click the plugin action button when the message says the missing metrics can be computed
- return to **Measure** and apply pending threshold, Top-K, or ROI settings when the message says inputs are pending

## What to verify before trusting an analysis result

- the plugin was enabled intentionally
- the selected dataset is correct
- the metadata source is correct
- the active measurement mode produced the metric the plugin needs
- the plugin requirement message shows required metrics are ready
- normalization and background state are the intended ones
- the plotted result is consistent with the plugin's result table

## Related pages

- [Concepts and Limits](concepts-and-limits.md)
- [Measure Workflow](measure-workflow.md)
- [Intensity Trend Explorer](analysis/intensity-trend-explorer.md)
