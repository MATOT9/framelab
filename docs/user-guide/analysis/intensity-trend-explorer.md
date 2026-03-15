# Intensity Trend Explorer

**Intensity Trend Explorer** is the built-in analysis plugin for plotting measurement-stage quantities against exposure or iris position. Use it to answer questions such as:

- how does the measured signal vary with exposure?
- how does the measured signal vary with iris position?
- how stable is the trend across repeated records at the same operating point?
- what relative gain is obtained with respect to a chosen reference condition?

The plugin does not create new raw measurements. It reorganizes and summarizes values that were already produced by the **Measure** workflow.

## Before using this plugin

Verify all of the following first:

- the correct dataset was scanned
- the correct metadata source was selected
- the measurement mode reflects the intended physical comparison
- the intended normalization and background-subtraction state were already chosen
- the required metadata fields, especially exposure and iris position, are populated

A clean plot does not compensate for incorrect upstream metadata or incorrect measurement choices.

## Control summary

### X Axis

Choose the acquisition variable placed on the horizontal axis.

| Option | Meaning |
| --- | --- |
| **Iris Position** | Plot against iris position. |
| **Exposure** | Plot against exposure time. |

Use the X axis that matches the variable intentionally changed during the experiment.

### Y Axis

Choose the measurement-stage quantity to visualize.

| Option | Meaning | Typical use |
| --- | --- | --- |
| **Intensity Gain (first ref)** | Converts the selected underlying signal to gain using the first valid point as reference. | Relative trend from the start of a sweep. |
| **Intensity Gain (last ref)** | Converts the selected underlying signal to gain using the last valid point as reference. | Relative trend from the end of a sweep. |
| **Mean Intensity** | Uses the active measurement-stage mean. | Direct comparison of Top-K or ROI mean. |
| **Intensity Rate** | Uses `DN/ms` when exposure metadata is valid. | First-order exposure-normalized comparison. |
| **Peak Intensity** | Uses the peak pixel metric. | Saturation and bright-point inspection. |

Current restriction:

- when **X Axis = Exposure**, **Intensity Rate** is intentionally unavailable

### Error Bars

Choose how uncertainty is displayed.

| Option | Meaning |
| --- | --- |
| **Off** | Do not display uncertainty bars. |
| **Std** | Display standard deviation. |
| **Std Err** | Display standard error of the mean. |

Use **Std** when you want to show spread. Use **Std Err** when you want uncertainty on the estimated mean. Practical note:

- uncertainty bars are meaningful for mean-based and `DN/ms`-based quantities
- **Peak Intensity** does not carry a dedicated uncertainty source in the current plugin, so error bars are not the main readout for that mode

### Trend

| Option | Meaning |
| --- | --- |
| **Off** | Show only the raw series. |
| **Linear fit** | Add one first-order fit across the visible raw points. |
| **Mean by X** | Collapse visible raw series into one weighted summary line at each X value. |

### Display options

| Control | Function |
| --- | --- |
| **Round Display to 1 s.d.** | Round displayed values and uncertainties to one significant digit based on the active uncertainty source. |
| **Align First Point to 1** | In last-reference gain mode, apply a constant scale factor so the first finite displayed point becomes exactly `1`. |
| **Show Series Lines** | Toggle connecting lines between visible raw points when the raw-series view is active. |

## What is actually plotted

The plugin first assigns records to series, then aggregates records that share the same X value inside each series.

### Series construction

Current series rules are:

- with **X Axis = Iris Position**, separate series are formed by exposure
- with **X Axis = Exposure**, separate series are formed by iris position
- when X is exposure and no numeric iris value is available, the plugin falls back to the iris label or parent-folder label for series naming

### Point aggregation

When several records contribute to one plotted operating point, the plugin computes a summary point from those records. For values \(y_1, \dots, y_N\):

\[y_{	ext{point}} = \frac{1}{N}\sum_{i=1}^{N} y_i\]

\[\sigma_{	ext{point}} = \mathrm{std}(y_1, \dots, y_N)\]

\[\mathrm{SEM}_{	ext{point}} = \frac{\sigma_{	ext{point}}}{\sqrt{N}}\]

Use the plotted point as a summary of the contributing records, not as the value of one individual row.

## Gain interpretation

In gain modes, the plotted value is relative to a reference point on the same series:

\[g_i = \frac{y_i}{y_{	ext{ref}}}\]

where:

- \(g_i\) is the gain at point \(i\)
- \(y_i\) is the point value before gain conversion
- \(y_{	ext{ref}}\) is the selected reference value on the same series

Gain is therefore a relative quantity. It indicates how the signal changed with respect to one operating condition; it does not report absolute radiometric magnitude.

## Special cases that matter operationally

### Iris-position gain uses `DN/ms`

When **X Axis = Iris Position** and a gain mode is selected, the plugin builds gain from mean `DN/ms` at each iris position before applying the reference conversion. That means:

- exposure metadata must be valid upstream
- the result is sensitive to correct `DN/ms` computation upstream
- the interpretation is relative optical-response change, not direct proof of constant throughput

### Exposure-axis gain uses the active mean metric

When **X Axis = Exposure** and a gain mode is selected, the plugin builds gain directly from the active mean metric rather than from `DN/ms`. That is why **Intensity Rate** is not offered as a separate Y mode when X is already exposure.

### Iris-position gain locks the overlay model

When **X Axis = Iris Position** and gain is selected, the plugin forces the trend overlay to **Mean by X** and hides the raw series view. This is intentional. In that mode the plugin is emphasizing the aggregated gain-versus-iris result rather than exposure-separated raw series.

## Mean-by-X overlay

The **Mean by X** overlay collapses visible raw series into one weighted summary line. At each X value, visible raw points are combined using sample-count weighting:

\[
\bar{y}_w = \frac{\sum_i w_i y_i}{\sum_i w_i}
\]

where \(w_i\) is the sample count associated with visible point \(i\). Use this overlay when you want one summary trend across the visible operating population instead of several separate raw series.

## Linear fit overlay

The **Linear fit** overlay applies a first-order model across all visible raw series points:

\[
y = m x + b
\]

The plugin also reports \(R^2\) as a compact goodness-of-fit descriptor. Use the fit as a descriptive trend aid, not as proof that the system is physically linear over the explored range.

## Plot and result table

The plugin page combines:

- a plot for trend inspection
- a table for exact values, uncertainty values, and contributing sample counts

Use the plot to identify structure. Use the table to verify exact numbers before drawing conclusions. Read the table particularly carefully when:

- a curve looks flatter or noisier than expected
- a gain jump seems too large
- some X positions combine more repeated records than others
- you are trying to distinguish spread from uncertainty on the aggregated mean

## Runtime actions

The plugin exposes runtime helpers through the **Plugins** menu, including actions such as:

- updating results
- resetting the plot view
- showing all curves
- copying selected table content
- copying the plot image

## Interpretation checklist

Before trusting a reported trend, verify:

- X matches the variable intentionally swept during acquisition
- Y matches the quantity you actually want to compare
- the uncertainty mode reflects the intended interpretation
- the gain reference choice matches the intended baseline
- the visible series correspond to the intended operating subsets
- upstream metadata and measurement values were already valid
- the result table supports the visual impression from the plot

## Mathematical appendix

This appendix keeps the defining equations close to the operational guidance.

### Aggregated uncertainty from existing per-record uncertainties

When the plugin receives one uncertainty value per contributing record, it combines them as:

\[
\sigma_{\bar{y}} = \frac{\sqrt{\sum_{i=1}^{N} e_i^2}}{N}
\]

where \(e_i\) is the uncertainty associated with record \(i\).

### Gain uncertainty propagation

When gain uncertainty is enabled, the plugin uses first-order propagation:

\[
\sigma_{g_i}
=
\left| g_i \right|
\sqrt{
\left(\frac{\sigma_i}{y_i}\right)^2
+
\left(\frac{\sigma_{\text{ref}}}{y_{\text{ref}}}\right)^2
}
\]

### Linear-fit goodness of fit

For the fit overlay, the coefficient of determination is reported as:

\[
R^2 = 1 - \frac{SS_{	ext{res}}}{SS_{	ext{tot}}}
\]

with:

- \(SS_{	ext{res}} = \sum_i (y_i - \hat{y}_i)^2\)
- \(SS_{	ext{tot}} = \sum_i (y_i - \bar{y})^2\)

## Related pages

- [Analysis Workflow](../analysis-workflow.md)
- [Measure Workflow](../measure-workflow.md)
- [Concepts and Limits](../concepts-and-limits.md)
