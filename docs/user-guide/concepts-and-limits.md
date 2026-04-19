# Concepts and Limits

Use this page to establish the model behind the app before working tab by tab.

FrameLab is a TIFF-centric calibration and exploratory analysis tool. It turns image collections into comparable per-image metrics, then lets analysis plugins reorganize those metrics against acquisition variables such as exposure or iris position. It is intentionally useful for practical engineering studies, but it is not a substitute for a full radiometric calibration pipeline.

## Workflow model

A reliable mental model is:

```text
workflow scope -> TIFF files -> metadata per image -> metric image -> per-image statistics -> analysis-plugin curves and tables
```

The app does not create physical meaning on its own. It helps you preserve metadata context, compute repeatable image-level quantities, and inspect those quantities consistently.

## Workflow hierarchy concepts

For most work, the primary profile is **Calibration**. Its logical hierarchy is:

```text
workspace -> camera -> campaign -> session -> acquisition
```

The **Trials** profile uses:

```text
workspace -> trial -> camera -> session -> acquisition
```

The trials profile exists, but it should still be treated as experimental.

### Camera

A **camera** is the long-lived asset level.

### Campaign

A **campaign** is one coherent calibration effort. A campaign may span multiple days and is the right place for cross-session outputs and derived products.

### Session

A **session** is one stable setup block. Split sessions when the setup changes meaningfully. Multiple sessions on the same day are supported.

### Acquisition

An **acquisition** is one capture block with one intent and one acquisition datacard context. Keep acquisitions semantically narrow.

## Core vocabulary

### Dataset

A **dataset** is the currently scanned folder context. All normalization, grouping, row ordering, measurement tables, and analysis-plugin inputs are built from that currently loaded population.

### Scope

A **scope** is the workflow node currently driving the Data, Measure, and Analyze pages. Depending on what you opened, the scope may be:

- the full workspace
- one camera subtree
- one campaign subtree
- one session
- one acquisition

Always verify the current scope before interpreting results.

### Row

A **row** is one loaded image record. A row can carry:

- file identity and folder context
- path-derived metadata
- hierarchical JSON-derived metadata
- measurement-stage quantities such as max pixel, saturation count, mean/std/SEM, and `DN/ms`
- grouping information used for table organization and downstream operator review

### Group

A **group** is a table-level cluster built from the currently selected grouping field. Current behavior is exact rather than fuzzy:

- grouping is only available for the fields exposed in the UI
- token matching is string-based
- when grouping is **None**, every row belongs to group `1`
- when grouping is by a field, non-empty tokens are sorted and assigned group ids starting at `1`
- missing or empty grouping values become group `0`

Grouping is primarily for operator organization and pre-analysis sanity checking. It does not rewrite metadata and it is not an arbitrary query system.

### Plugin

A **plugin** is an extension point loaded at startup. In the current shipped app, plugins appear in three roles:

- **data plugins**, such as **Session Manager (Legacy)** and **Acquisition Datacard Wizard**
- **measure plugins**, such as **Background Correction**
- **analysis plugins**, such as **Intensity Trend Explorer**

Use startup selection to decide which plugins exist in the session at all. Use runtime plugin controls or the **Plugins** menu only for plugins that were already enabled at launch.

## Metadata concepts

The app can resolve metadata from more than one source. That choice matters because measurement interpretation and analysis curves depend on the resolved values, not merely on file names.

### Path metadata

**Path metadata** means values inferred from the file name or folder names. Typical examples include:

- exposure parsed from a file name or parent folder
- iris position parsed from a parent folder, grandparent folder, or file stem
- parent and grandparent folder labels

Path metadata is useful when the dataset layout already encodes the experiment cleanly and consistently.

### Acquisition JSON metadata

The UI label **Acquisition JSON** refers to the hierarchical metadata stack anchored at the selected acquisition root. In the current implementation, that stack can combine:

- acquisition defaults and frame-targeted overrides from `acquisition_datacard.json`
- inherited session defaults from `session_datacard.json`
- inherited campaign defaults and instrument defaults from `campaign_datacard.json`
- inherited workflow-node metadata from `.framelab/nodecard.json`
- effective acquisition-wide eBUS-backed baseline values for mapped canonical fields when one readable root-level `.pvcfg` snapshot exists and the field mapping marks those fields as eBUS-managed

So the UI still says **Acquisition JSON**, but the runtime source can be a layered context rather than one standalone file.

### Defaults and overrides

Inside the acquisition datacard, the supported semantic model is:

- **defaults** define inherited baseline metadata
- **overrides** replace only the fields explicitly provided for targeted frames or frame ranges
- blank fields mean **do not set anything here**
- blank fields do **not** erase inherited values

Operationally:

- keep stable acquisition-wide values in **Defaults**
- use frame mapping only for metadata that truly varies by frame or frame block

### Metadata-source fallback

When **Acquisition JSON** is selected, the app still falls back to path-derived iris or exposure values if the hierarchical JSON stack does not supply them. In the table, that fallback is marked through source fields such as `path_fallback` rather than being silently treated as fully authored JSON metadata.

## Measurement concepts

The **Measure** workflow computes per-image quantities from the current **metric image**. The metric image is:

- the raw image when background subtraction is off or no compatible reference exists
- the background-corrected image when subtraction is enabled and a compatible reference is available

This distinction matters because saturation counts, max pixel, min non-zero, Top-K, ROI statistics, normalization scale, and downstream analysis inputs all follow the metric image, not necessarily the raw TIFF values.

### Digital Number (DN)

**DN** means the numeric image intensity stored in the TIFF-derived image data. Mean intensity, peak intensity, ROI intensity, and Top-K intensity are all intensity quantities expressed in DN unless explicitly normalized. DN is not a physical radiometric unit by itself.

### Saturated-pixel count

The app counts how many pixels satisfy:

```text
pixel >= threshold
```

That count is evaluated on the current metric image, so active background subtraction can change it.

### Mean intensity modes

The app supports three mean-mode states:

- **Disabled**: no average-based metric is produced
- **Top-K Mean**: uses the brightest `K` pixels in the metric image
- **ROI Mean**: uses only pixels inside the current ROI rectangle

These modes answer different questions. Choose the mode that matches the signal definition you actually want to compare.

### Standard deviation and SEM

For average-based modes, the app also reports:

- **standard deviation (std)**: spread of the contributing pixels
- **standard error of the mean (SEM)**: `std / sqrt(N)`

These values are part of the measurement result and are also passed into analysis plugins when relevant.

### DN/ms

When valid exposure metadata exists, the app computes a rate-like quantity from the active mean metric:

```text
DN/ms = mean_intensity / exposure_ms
```

Dividing the measured intensity by exposure time normalizes the result by integration duration, allowing first-order comparison across images acquired with different exposure settings. `DN/ms` is useful for comparison of relative trends, especially across exposure or iris studies. It is not, by itself, a radiometric quantity and should not be treated as proof of constant scene radiance, detector linearity, or invariant optical throughput.

### Normalization

When normalization is enabled, intensity-like values are divided by the current dataset normalization scale:

```text
normalized_value = value / current_dataset_max_pixel
```

In the current implementation, that scale is the maximum value in the current measure-stage **max pixel** array. Because that array follows the active metric image, background subtraction can change the normalization divisor. Important consequences:

- normalization does **not** rewrite TIFF source data on disk
- normalization does affect displayed intensity-derived values
- normalization also affects the intensity-derived values passed into analysis plugins, including mean/std/SEM and `DN/ms`-related values
- normalization is dataset-relative, so loading a different dataset can change the divisor

### Background subtraction

Background subtraction changes the metric image used for measurement:

```text
metric_image = image - background
```

Optional negative clipping can then force negative residuals back to zero. This is not a cosmetic display effect. It changes the quantities later used for table metrics, normalization scale, and analysis-plugin inputs.

## Analysis concepts

Analysis plugins do not invent raw measurements. They reorganize, aggregate, and visualize quantities that already came from the measurement stage.

### Curve

A **curve** is a series built from rows that share a secondary grouping context chosen by the plugin. For example, one curve may represent one exposure while X varies by iris, or one iris condition while X varies by exposure.

### Point aggregation

When multiple records share the same X value inside one curve, the plugin can aggregate them into one plotted point. That plotted point is a summary of the contributing records, not a direct copy of any one row.

### Gain

In gain modes, the plotted value is relative to a reference point:

```text
gain = y / y_ref
```

Gain is therefore a relative quantity. It describes change with respect to a reference operating point, not absolute signal magnitude.

### Error bars

Error bars depend on the selected plugin mode and available uncertainty source. They can reflect direct spread, SEM, or propagated uncertainty derived from upstream measurement-stage values. A clean plot with small error bars is only meaningful if metadata source, measurement mode, normalization state, and background handling were already correct upstream.

## What this app is good for

FrameLab is well suited to:

- exposure sweeps
- iris sweeps
- fixed-ROI comparisons across conditions
- bright-region trend inspection
- metadata verification before deeper analysis
- workflow-structured calibration datasets
- acquisition/session/campaign datacard workflows
- eBUS snapshot inspection and approved canonical overrides
- practical engineering plots for calibration and exploratory work

## What this app is not doing by itself

FrameLab is **not**, by itself:

- a full radiometric calibration package
- a substitute for detector responsivity calibration
- a substitute for scene-radiance estimation
- proof of physical linearity just because a plot looks linear
- proof that metadata is correct just because the scan succeeded
- proof that a background reference was valid for every image in the dataset

Treat the app as a structured measurement-and-analysis environment, not as an automatic source of physical truth.

## Operator mindset

A reliable operating order is:

1. verify workflow profile and dataset scope
2. verify dataset identity and scan population
3. verify metadata source and resolved values
4. verify measurement mode, threshold, normalization, ROI, and background state
5. only then interpret curves, gain, or overlays

When the output matters, read the table and the plot together.
