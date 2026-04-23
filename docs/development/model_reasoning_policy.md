# Model and Reasoning Policy for Codex Tasks

This guide explains how to choose a **Codex model** and **reasoning level** for tasks in this repository so you can reduce token usage without sacrificing reliability.

The key idea is simple:

- choose the **model** for capability / cost tier
- choose the **reasoning level** for how much thinking the task actually needs

Do **not** always default to the strongest model with the highest reasoning level for every task.

## Recommended default

For most normal coding work in this repo, use:

- **Model:** GPT-5.5
- **Reasoning:** medium

That should be the standard starting point for:
- normal bugfixes
- moderate feature work
- plugin work inside an existing architecture
- most multi-file Python changes

## Lightweight setting

Use this for small, low-risk, well-scoped tasks:

- **Model:** GPT-5.4-mini
- **Reasoning:** low

Good candidates:
- docs-only tasks
- small test updates
- renames
- simple UI text or label changes
- tiny glue-code updates
- one-file fixes when the target area is already known

## Hard implementation setting

Use this when the task crosses subsystem boundaries or has more ways to fail:

- **Model:** GPT-5.5
- **Reasoning:** high

Good candidates:
- multi-file bug hunts
- performance work
- cache/state bugs
- UI + backend coordination
- plugin host changes
- tasks touching Python/native boundaries

## Planning / diagnosis setting

Use this mainly for **thinking passes**, not for all implementation work:

- **Model:** GPT-5.5
- **Reasoning:** extra-high

Good candidates:
- architecture planning
- ambiguous root-cause analysis
- large refactor decomposition
- repo-wide reasoning
- deciding the safest rollout order for a difficult change

After the planning pass, drop back down to **medium** or **high** for the implementation pass.

## Simple decision rule

Use this quick filter:

- If the task is **localized, reversible, and you already know the files**, use **GPT-5.4-mini + low**.
- If the task is **normal coding with some judgment but clear scope**, use **GPT-5.5 + medium**.
- If the task is **cross-subsystem, ambiguous, or easy to break**, use **GPT-5.5 + high**.
- If the task is **repo-wide planning, root-cause analysis, or architectural decision-making**, use **GPT-5.5 + extra-high**, then switch down afterward.

## Recommended settings by task type

### Docs-only tasks
Use:
- **GPT-5.4-mini + low**

Examples:
- updating `CURRENT_STATE.md`
- tightening `README.md`
- fixing cross-links
- adding workflow or handoff documentation

Use **GPT-5.5 + medium** instead if Codex must inspect the repo and decide what should be canonical.

### Small bugfixes
Use:
- **GPT-5.5 + medium**

Examples:
- one table column not populating
- a preview flag behaving incorrectly
- a wrong signal/slot connection
- a narrow plugin wiring issue

Drop to **GPT-5.4-mini + low** only if the bug is truly small and the exact files are already known.

### Moderate feature work
Use:
- **GPT-5.5 + medium**

Examples:
- adding a new image metrics table column
- adding elapsed time parsing from filename metadata
- adding a focused plugin inside an existing plugin framework
- extending an existing metrics mode without redesigning the system

### Cross-subsystem feature work
Use:
- **GPT-5.5 + high**

Examples:
- scan flow + metadata + metrics table + plugin integration
- features involving UI, runtime state, persistence, and analysis together
- tasks that affect caching or invalidation rules
- features that may touch both Python and native backend layers

### Native/backend work
Use:
- **GPT-5.5 + high**

Examples:
- adding new native kernels
- changing Python/native metric computation boundaries
- updating bindings and native tests
- modifying ABI-sensitive structures or interfaces

Use **extra-high** only if the task first needs deep architectural diagnosis or rollout planning.

### Performance investigations
Use:
- **GPT-5.5 + high**

Examples:
- identifying why the app slows down after large scans
- understanding memory growth across preview/cache paths
- investigating hidden recomputation
- tracing worker / cache / UI-churn interactions

If the cause is still unclear after one pass, rerun the **diagnosis only** at **extra-high**.

### Architecture / refactor work
Use:
- **Planning pass:** GPT-5.5 + extra-high
- **Implementation pass:** GPT-5.5 + high or medium

Examples:
- staged-pipeline refactor planning
- task decomposition
- boundary redesign between main window and controllers/services
- plugin contract redesign
- cache/invalidation redesign

Do not keep extra-high for the whole coding session if the plan is already clear.

### Tests-only tasks
Use:
- **GPT-5.4-mini + low** for straightforward test additions
- **GPT-5.5 + medium** when test design itself is tricky

Examples:
- adding regression tests for a small bug
- updating expected values after a narrow feature change
- adding focused plugin or metrics validation

## Recommended settings for this app’s common tasks

### Add a small metrics-table column
Example:
- add ROI sum column
- add elapsed time column when metadata already exists

Use:
- **GPT-5.5 + medium**

### Add a feature touching scan + metrics table + plugin
Example:
- elapsed time from UTC filename parsing plus event-signature plugin

Use:
- **GPT-5.5 + high**

### Add a feature touching native backend
Example:
- ROI + TopK average mode plus native support and bindings

Use:
- **GPT-5.5 + high**

### Plan a staged refactor
Example:
- staged-pipeline design
- explicit metric-family state model
- targeted workers/jobs

Use:
- **Planning:** GPT-5.5 + extra-high
- **Implementation tasks:** GPT-5.5 + high or medium depending on scope

### Docs migration / repo context setup
Use:
- **GPT-5.4-mini + low** if structure is already decided
- **GPT-5.5 + medium** if Codex must inspect the repo and choose the best structure

## Practical operating policy

Add this policy to your workflow:

1. **Default to GPT-5.5 + medium**
2. **Upgrade to high** only when the task crosses boundaries or has notable ambiguity/risk
3. **Use extra-high mostly for planning/diagnosis**, not routine implementation
4. **Use mini + low** for cheap, narrow, low-risk tasks
5. For difficult tasks, split work into:
   - **Pass 1:** diagnosis + plan
   - **Pass 2:** implementation

## Suggested wording to add to prompts

### Standard model/reasoning block

```text
Model / reasoning target:
- Preferred model: GPT-5.5
- Fallback: GPT-5.4
- Reasoning effort: medium

Escalation rule:
- If the task turns out to be architecturally ambiguous or cross-subsystem in a way that blocks a safe plan, switch the diagnosis/planning pass to high or extra-high reasoning.
- Keep implementation at the lowest reasoning level that can safely complete the scoped task.
```

### Two-pass block for hard tasks

```text
Use two passes:
Pass 1: diagnosis + plan only, GPT-5.5 with extra-high reasoning.
Pass 2: implementation of the approved phase, GPT-5.5 with high or medium reasoning.
```

## Rule of thumb

Ask:

**What is the cheapest model + reasoning combination that can still do this task safely in one scoped pass?**

That should be the default mindset.

The goal is not to always maximize intelligence.
The goal is to use the **minimum sufficient reasoning** for the actual task shape.
