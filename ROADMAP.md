# Roadmap

This roadmap is grounded in current repo docs, `TODO`, and inspected implementation state. It is not a product promise.

## Near Term

- Keep the documentation context layer current as code evolves.
- Stabilize pytest suite selection and reduce long-running or stalled test workflows.
- Verify the workspace-document split: preferences persist globally, while session-like UI state restores only from explicit `.framelab` files.
- Finish populating the Preferences UI with the settings that should remain global.
- Fix Trials profile folder creation and structure behavior.
- Fix known UI regressions around tab-switch lag, disappearing badges/chips, and preview-context menus.

## Workflow And Metadata

- Merge acquisition datacard and generic workflow-node metadata handling into a clearer unified mechanism.
- Continue moving remaining legacy Session Manager responsibilities into workflow-native surfaces where appropriate.
- Add setup-builder foundations: preregistered cameras, lenses, filters, and structured metadata hooks.
- Build a UI-based setup builder for experimental setups.

## Measurement And Analysis

- Continue the staged-pipeline rollout by replacing broad dynamic metric refreshes with targeted metric-family jobs and clearer task/status UX.
- Add computer last boot time calculation where it belongs in metadata or runtime context.
- Extend analysis and plugin coverage for dead pixel detection and spectral responsivity assessment.

## Image And Native Performance

- Add or complete mmap support for `.raw` loading.
- Add SIMD operations to the native backend.
- Add LTO and PGO support to native backend compilation.
- Expand RGB and Bayer support in decode and measurement paths.

## Packaging And UX

- Continue hardening the Nuitka standalone build path.
- Fix permission-sensitive cleanup around `.pyd` replacement.
- Add useful external-reference menu entries for GenICam, EMVA, and GigE Vision references.
- Improve icons, splash-screen behavior, toolbar affordances, and docking ergonomics once core behavior is stable.
