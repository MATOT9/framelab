# Developer Guide

Use this section to maintain, extend, or package the FrameLab codebase.

The goal of this guide is not only to describe which files exist. It is to document lifecycle, state ownership, subsystem boundaries, and extension contracts so changes can be made without breaking the operator-facing workflows.

## Recommended reading order

1. [Architecture](architecture.md)
2. [Plugin System](plugin-system.md)
3. [Datacard System](datacard-system.md)
4. [eBUS Config Integration](ebus-config-integration.md)
5. [UI Structure](ui-structure.md)
6. [Packaging](packaging.md)

## What each page answers

- [Architecture](architecture.md): startup flow, runtime data flow, metadata layering, and shared state ownership.
- [Plugin System](plugin-system.md): manifest discovery, dependency closure, registration, runtime contracts, and built-in plugin patterns.
- [Datacard System](datacard-system.md): acquisition/session/campaign metadata layering, defaults/overrides semantics, eBUS-managed fields, and payload normalization.
- [eBUS Config Integration](ebus-config-integration.md): raw snapshot discovery, effective override semantics, catalog policy, and compare behavior.
- [UI Structure](ui-structure.md): host-shell ownership, mixin boundaries, dialog-style plugins, and worker/UI-thread rules.
- [Packaging](packaging.md): runtime assets, docs bundling, validation steps, and release-sensitive path contracts.

## Maintenance principles

Treat the app as five interacting layers:

1. startup and plugin enablement
2. dataset and metadata intake
3. measurement runtime
4. analysis-plugin consumption
5. offline docs/help packaging

If a behavior crosses those boundaries, document and test the contract explicitly rather than hiding the dependency in ad hoc UI code.

## Current feature areas worth knowing

The current shipped build includes:

- hierarchical metadata resolution across acquisition, session, and campaign datacards
- session-level acquisition management
- eBUS snapshot discovery, compare, and canonical override integration
- background-correction tooling as a measure-page plugin
- analysis plugins that consume a prepared `AnalysisContext` rather than raw host state

Use that list as a reminder that the codebase is broader than a TIFF table plus one plotting page.
