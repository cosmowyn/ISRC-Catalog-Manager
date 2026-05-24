# Follow-Up Engineering Plan — Compatibility Debt Elimination and Architectural Enforcement

This follow-up plan exists to ensure the decomposition campaign does **not** end with:
- permanent compatibility aliases
- migrated legacy architecture
- controller monoliths
- hidden circular dependencies
- stale deprecated APIs
- “temporary” migration glue that survives indefinitely

The objective of this plan is to ensure the repository reaches a **true post-monolith architecture state** with:
- enforced boundaries
- fully migrated imports
- removed deprecated entrypoints
- measurable architectural integrity
- stable long-term maintainability

This document supplements:
- Engineering Plan 1
- Engineering Plan 2

This document is a **mandatory governance layer** for Engineering Plan 1 and Engineering Plan 2.
It is not optional, and it is not merely a parallel cleanup track. Its checks must be applied as
phase gates throughout the campaign.

The de-monolithization campaign is not complete until the final completion gate in this document
passes. Any phase that creates, changes, or removes compatibility aliases must update
`compatibility_inventory.md`. Any phase that creates new packages or modules must consider package
visibility, dependency direction, module boundaries, and module-size risk before the phase can be
marked complete.

---

# Goals

## Primary Goals
- eliminate all temporary compatibility aliases
- remove all deprecated root imports
- prevent architecture regression during decomposition
- prevent controller/service monolith replacement
- eliminate hidden circular dependency patterns
- enforce clean layering boundaries
- ensure all legacy code paths are either migrated or deleted
- guarantee no “temporary migration state” survives final release

## Mandatory Campaign Artifacts
The following planning/governance artifacts are required:

- `compatibility_inventory.md`
- `architecture_metrics.md`
- phase handoffs under `phase execution handoffs/`
- `Milestones.md`

Phase handoffs and milestone entries must state whether the compatibility inventory and architecture
metrics changed. If a phase does not change either artifact, the handoff must explicitly say so.

## Phase Gate Application
These enforcement checks apply at the following points:

- Phase 0 creates the initial compatibility inventory.
- Every Plan 1 phase updates the inventory if aliases, wrappers, or root re-exports are added,
  changed, migrated, or removed.
- Plan 1 cannot close until the Plan 1 Completion Gate passes.
- Plan 2 cannot begin until the Plan 2 Entry Gate passes.
- Every Plan 2 phase updates architecture metrics when module boundaries, line counts, root imports,
  aliases, or import-cycle risk change.
- Phase 21 cannot close until the zero-debt final cleanup gate passes.

---

# Final Mandatory End-State

At final completion:

## `ISRC_manager.py` MUST contain ONLY:
- bootstrap imports
- `main()`
- startup glue

## Forbidden at final completion:
- compatibility aliases
- deprecated wrappers
- root re-exports
- temporary migration shims
- transitional protocol adapters
- legacy fallback imports
- dead feature gates

---

# Architectural Enforcement Rules

These rules become repository-wide engineering constraints.

---

## Rule 1 — No New Root Imports

### Forbidden
```python
from ISRC_manager import EditDialog
```

### Required
```python
from isrc_manager.tracks.edit_dialog import EditDialog
```

## Enforcement
Add CI validation:
- fail build on new root `ISRC_manager` imports outside explicitly allowed compatibility modules

---

## Rule 2 — Compatibility Imports Are Temporary

Every compatibility alias MUST:
- contain a deprecation warning, or document why warning is not technically safe yet
- include removal target phase
- include migration target path
- list dependent runtime callers and tests in `compatibility_inventory.md`
- have current status recorded as `planned`, `active`, `migrated`, or `removed`

Example:

```python
from warnings import warn

warn(
    "Importing EditDialog from ISRC_manager is deprecated and "
    "will be removed after Phase 21. "
    "Use isrc_manager.tracks.edit_dialog instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

---

## Rule 3 — No QWidget Imports in Services

### Forbidden
- QWidget imports inside:
  - services
  - persistence
  - diagnostics
  - controllers

### Goal
Prevent UI/business-logic coupling.

---

## Rule 4 — No Controller-to-Controller Direct Coupling

Controllers may communicate through:
- events
- protocols
- lightweight orchestration seams

NOT direct ownership trees.

---

## Rule 5 — No New “Manager” Modules

Avoid vague architectural sinks:
- helpers.py
- utils.py
- managers.py
- misc.py
- common.py

All new modules must belong to a concrete workflow family.

---

# Dependency Layering Rules

Mandatory layering:

```text
UI
↓
workflow/controller
↓
services
↓
data/domain
```

## Forbidden
- services importing widgets
- domain importing Qt
- dialogs importing App directly
- controllers owning database primitives directly
- feature families bypassing service layers

---

# Compatibility Debt Burn-Down

## Phase A — Compatibility Inventory

Create and maintain an inventory file:

```text
compatibility_inventory.md
```

Containing:
- alias source
- alias target
- owning phase
- dependent runtime callers
- dependent tests
- deprecation warning status
- migration target path
- planned removal phase
- current status:
  - planned
  - active
  - migrated
  - removed
- notes / exception references

Rules:
- No compatibility alias may be added unless it is added to this inventory in the same phase.
- No compatibility alias may remain without a planned removal phase.
- Every phase handoff must state whether the inventory changed.
- Every milestone update must mention inventory status.
- The final campaign state requires the inventory to be empty or contain only historical removed
  entries clearly marked as `removed`.

---

## Phase B — Test Migration

All tests must migrate away from:

```python
from ISRC_manager import ...
```

toward feature-local imports.

Goal:
- remove root import dependency entirely

---

## Phase C — Runtime Caller Migration

Search and migrate:
- feature modules
- dialogs
- worker tasks
- background services
- plugins
- tools

Remove all remaining compatibility import usage.

---

## Phase D — Alias Deletion Gate

Before final release:
- compatibility inventory MUST be empty
- CI MUST fail on remaining compatibility imports

---

# Circular Dependency Prevention

## Mandatory Dependency Audit

Before each major extraction phase:
- generate import graph
- detect cycles
- document new cycles

Recommended tooling:
- pydeps
- grimp
- import-linter

---

## Hard Rule
No new dependency cycles may be introduced.

If a cycle appears:
- extraction pauses
- cycle resolved before continuation

---

# Controller Monolith Prevention

## Soft Limits

### Warning Threshold
- 1200 LOC per controller/module

### Mandatory Split Threshold
- 2500 LOC

---

## Required Internal Structure

Large controllers must split into:
- orchestration
- state
- actions
- routing
- persistence coordination

Avoid:
- single-file mega controllers

---

# Shared Mutable State Protection

## High-Risk Shared State Areas
Special care required for:
- playback state
- catalog selection state
- active profile/session
- undo/redo state
- theme propagation
- storage retention state
- background task coordination

---

## Requirement
Each shared state domain must have:
- single authoritative owner
- documented mutation boundaries
- documented lifecycle

---

# Media Architecture Stabilization

The media subsystem has expanded significantly and now represents a platform-level subsystem.

It must be separated into distinct responsibilities:

## Visualization
- waveform
- spectrum
- oscilloscope
- peak meter

## Preparation
- preload tasks
- MIME handling
- temp file creation
- analysis pipelines

## Playback
- queue
- equalizer
- bookmarks
- transport state

## Export
- routing
- rendering
- extraction

Avoid recombining these into a new media monolith.

---

# Catalog Workflow Risk Mitigation

Before catalog extraction:
- generate catalog dependency map
- identify selection authority
- identify refresh authority
- identify context-menu ownership
- identify filtering/search ownership

Goal:
prevent competing state authorities.

---

# Required CI Gates

The following CI gates are future implementation requirements. This planning pass does not implement
CI checks, but the campaign must specify them before final cleanup closes.

## Architectural Gates
- no new root imports
- no forbidden dependency directions
- no new circular imports
- compatibility inventory must shrink over time
- zero compatibility aliases at final completion
- zero root re-exports except final bootstrap imports explicitly required for startup

---

## Quality Gates
- compile sanity
- focused feature tests
- workflow regression gates
- UI smoke tests
- startup tests
- packaging verification

---

# Repository Health Metrics

Track over time:
- compatibility alias count
- root import count
- `ISRC_manager.py` LOC
- `App` LOC while it still exists
- module LOC over warning threshold
- module LOC over mandatory split threshold
- import cycle count
- package parity status
- tests still using root imports
- module fan-in/fan-out where available
- test runtime
- startup latency

Record these at major gates in:

```text
architecture_metrics.md
```

Goal:
ensure architecture actually improves rather than merely redistributing complexity.

---

# Deprecated Code Removal Policy

Deprecated code may only remain if:
- active migration is still ongoing
- callers still exist
- removal phase is documented

Otherwise:
- delete immediately

---

# Final Completion Gate

The engineering campaign is NOT complete until:

## Required
- zero compatibility aliases
- zero deprecated root imports
- zero root re-exports except final bootstrap imports explicitly required for startup
- zero temporary migration wrappers
- zero dead feature flags
- zero dependency cycles
- zero legacy import paths in tests
- all feature families migrated to final structure
- `compatibility_inventory.md` is empty or contains only historical removed entries clearly marked
  as `removed`
- `ISRC_manager.py` contains only bootstrap imports, `main()`, and startup glue
- CI/architecture validation rules are specified for preventing reintroduction of root imports,
  aliases, root re-exports, migration wrappers, and import cycles

Any API intended to remain public must live in a proper package-level public module. It must not be
kept as a root compatibility alias in `ISRC_manager.py`.

---

# Final Architectural Target

## Desired End-State
- lean entry facade
- feature-family ownership
- strict dependency layering
- isolated controllers/services
- testable workflow boundaries
- stable long-term maintainability
- no hidden monolith remnants

---

# Final Engineering Directive

Migration success is NOT measured solely by:
- reduced line count
- extracted modules
- passing tests

Migration success is measured by:
- elimination of legacy architecture
- removal of transitional compatibility debt
- enforceable long-term architectural boundaries
- prevention of monolith regrowth
- maintainable future evolution of the application
