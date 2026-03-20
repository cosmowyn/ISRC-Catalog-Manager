# Documentation Positioning And Capability Audit

Date: 2026-03-20

## What Was Revised

This documentation pass revised the product-facing documentation across the top-level README, the docs hub, focused workflow guides, supporting deep dives, and the in-app help source.

Updated or added files:

- [`README.md`](../../README.md)
- [`docs/README.md`](../README.md)
- [`docs/import-and-merge-workflows.md`](../import-and-merge-workflows.md)
- [`docs/catalog-workspace-workflows.md`](../catalog-workspace-workflows.md)
- [`docs/diagnostics-and-recovery.md`](../diagnostics-and-recovery.md)
- [`docs/repertoire_knowledge_system.md`](../repertoire_knowledge_system.md)
- [`docs/gs1_workflow.md`](../gs1_workflow.md)
- [`docs/file_storage_modes.md`](../file_storage_modes.md)
- [`docs/theme_builder.md`](../theme_builder.md)
- [`docs/undo_redo_strategy.md`](../undo_redo_strategy.md)
- [`isrc_manager/help_content.py`](../../isrc_manager/help_content.py)

## Major Capability Gaps In The Prior Docs

The prior docs were accurate in broad strokes, but they still made the product easy to underestimate.

The main gaps were:

- the app was still easy to read as an ISRC or track-metadata tool instead of a broader catalog and repertoire operations workspace
- import was described as a format list more than as a rule-driven reconciliation workflow
- the docked workspace was present, but its operational value as a review surface was not made clear enough
- recovery, history, backups, cleanup, diagnostics, repair, and migration existed, but they were fragmented rather than presented as one trust-and-maintenance story
- advanced features such as action ribbon customization, saved layout, search/relationship review, theme tooling, and storage-mode behavior were documented, but too easy to miss
- user-facing docs and internal/developer docs were mixed together at the top level, which made the reading path weaker for new users

## Workflows Newly Surfaced

This pass now gives concrete visibility to workflows that were previously vague or buried:

- exchange import as a preview, mapping, matching, mode-selection, and merge/update/create workflow
- CSV delimiter handling and reusable mapping presets for recurring imports
- importing structured external exports into standard fields or active `custom::<name>` text fields
- release upsert behavior during exchange import
- ZIP package round-tripping for metadata plus file-backed records with storage-mode preservation
- XML inspection, dry-run style preflight, custom-field checks, and insert-oriented import behavior
- audio tag import conflict preview and export-only tag writing
- docked workspace review across releases, works, parties, contracts, rights, assets, licenses, search, and relationship navigation
- quality-dashboard triage versus diagnostics and repair
- snapshots, backups, cleanup, trim, storage migration, and logs as one practical maintenance workflow

## Advanced Or Obscure Features Newly Surfaced

The following features now have better visibility across README, docs, or help:

- docked tabbed workspace panels
- saved workspace layout
- action ribbon customization
- global search and relationship-aware review
- managed versus database-backed attachment storage
- package import/export preserving storage mode
- legacy license migration into contracts/documents
- theme builder starter themes
- BLOB icon builder and field-specific overrides
- selector reference and QSS autocomplete
- persistent undo/redo plus snapshots and backup-aware cleanup
- staged app-data migration and history artifact repair

## Current Documentation Structure

The repo now uses a clearer three-layer product-doc structure:

1. [`README.md`](../../README.md) as the top-level product document and positioning layer
2. [`docs/README.md`](../README.md) plus focused guides as the wiki-style deep-dive layer
3. [`isrc_manager/help_content.py`](../../isrc_manager/help_content.py) as the concise in-app task manual

That structure is intended to keep overview, deep detail, and in-app guidance aligned without turning the README into an exhaustive manual.

## Remaining Under-Documented Areas

This pass materially improves the product-facing documentation, but some areas still deserve more depth later:

- repertoire exchange deserves its own focused user guide instead of living mainly inside broader exchange references
- the release browser, work manager, rights matrix, and contract manager could each support deeper task-based guides with screenshots
- quality-dashboard rules and suggested-fix behavior could be documented in more detail for advanced cleanup workflows
- asset registry and deliverable workflows deserve a dedicated guide
- application settings outside the theme system could be documented more explicitly for onboarding
- demo profile walkthroughs and cookbook-style examples would help new users learn faster

## Recommended Future Improvements

Recommended next steps:

1. Add a dedicated repertoire-exchange guide with concrete entity examples and relationship behavior.
2. Add screenshot-backed task guides for release assignment, work linking, contract review, and rights review.
3. Expand the diagnostics/recovery guide with concrete examples of repair actions and expected outcomes.
4. Add short workflow recipes that show how to handle common real-world jobs such as merging a label spreadsheet into an existing catalog or preparing a package transfer.
5. Keep revisiting the README and help text when new workflow-heavy features land so the product story stays concrete instead of drifting back toward high-level feature labels.

## Positioning Principles Used In This Pass

This pass followed a few consistent rules:

- describe what the implementation actually does, not what it might do later
- present the app as a serious local-first catalog and repertoire workspace
- lead with workflow value rather than isolated feature names
- surface advanced depth without turning the README into a wall of text
- stay explicit about current limits such as the absence of direct third-party integrations or row-by-row manual import assignment
