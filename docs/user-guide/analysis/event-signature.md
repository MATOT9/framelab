# Event Signature

**Event Signature** is an analysis plugin for plotting one point per loaded frame. Use it when an acquisition captures an event over time and you want to inspect the response shape directly.

The plugin does not remeasure images. It uses values already prepared by **Data** and **Measure**.

## Before using this plugin

Confirm the following first:

- the intended acquisition scope was scanned
- the image metrics table has valid max-pixel values
- ROI Top-K was computed in **Measure** if you plan to use **ROI Top-K**
- filename UTC timestamps are present if you plan to use **elapsed time [s]**

UTC timestamp filenames should contain a token like:

```text
YYYYMMDD_HHMMSS_mmmZ
```

For example:

```text
00000000_20260419_183326_086Z_w1280_h720_pMono12Packed.bin
```

## Controls

### X Axis

| Option | Meaning |
| --- | --- |
| **Frame Index** | Plot against the resolved frame index. If frame metadata is missing, the plugin uses the row order from the current analysis context. |
| **elapsed time [s]** | Plot against elapsed seconds derived from filename UTC timestamps. This option appears only when elapsed-time metadata is available. |

Elapsed time uses the first valid timestamp in the loaded scope as `0.000 s`. The app does not reorder frames by timestamp; it preserves the loaded scope order.

### Y Axis

| Option | Meaning |
| --- | --- |
| **Max Pixel** | Uses the per-image max-pixel metric from the Measure stage. |
| **ROI Top-K** | Uses the existing ROI Top-K mean values computed by the Measure stage. |

If ROI Top-K has not been computed, the plugin remains available but the ROI Top-K plot has no points.

## Reading the output

The result table and plot show the same point set:

- use the table to confirm exact frame index, elapsed time, and metric values
- use the plot to inspect event shape, peak timing, and decay or recovery behavior

When elapsed time is unavailable, use **Frame Index**. Do not treat frame index as physical time unless the acquisition cadence is known and stable.

## Related pages

- [Data Workflow](../data-workflow.md)
- [Measure Workflow](../measure-workflow.md)
- [Analysis Workflow](../analysis-workflow.md)
