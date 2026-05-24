# Compatibility Inventory

This inventory is mandatory from Plan 1 Phase 0 onward. It tracks every temporary compatibility alias, root re-export, deprecated wrapper, and migration shim introduced or removed during the de-monolithization campaign.

No compatibility alias may be added unless it is recorded here in the same phase. No compatibility alias may remain without a planned removal phase.

## Status Values
- `planned`
- `active`
- `migrated`
- `removed`

## Required Fields
Each inventory row must include:

- alias source
- alias target
- owning phase
- dependent runtime callers
- dependent tests
- deprecation warning status
- migration target path
- planned removal phase
- current status
- notes / exception references

## Inventory
| Alias source | Alias target | Owning phase | Dependent runtime callers | Dependent tests | Deprecation warning status | Migration target path | Planned removal phase | Current status | Notes / exception references |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Phase Handoff Rules
Every phase handoff must state:

- whether this inventory changed
- which aliases were added, changed, migrated, or removed
- whether any alias lacks a deprecation warning and why warning is not technically safe yet
- whether every active alias has a planned removal phase
- whether any tests or runtime callers still depend on root compatibility imports

## Final Gate Rule
At final campaign completion, this inventory must be empty or contain only historical entries marked `removed`.
