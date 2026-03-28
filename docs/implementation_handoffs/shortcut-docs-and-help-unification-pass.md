# Shortcut, Docs, and Help Unification Pass

## 1. Shortcut Audit Results

The application already had broad shortcut coverage for the highest-frequency catalog actions, settings, diagnostics, history, import, and export flows through the shared `main_window_shell` action builder. The remaining gaps were concentrated in:

- advanced review surfaces that had visible menu entries but no shortcut
- media-attachment actions that were menu-driven only
- authenticity tooling that was available but not keyboard-addressable
- one workspace-level global-search action that duplicated the primary action instead of reusing it
- two shortcut collisions in the existing action map:
  - `Ctrl+Alt+F` / `Cmd+Option+F`
  - `Ctrl+Alt+W` / `Cmd+Option+W`

Some controls intentionally remain without shortcuts because they are low-frequency, highly contextual, or would introduce poor mnemonic or platform conflicts.

## 2. Shortcuts Added and Why

Added shortcuts:

- `Derivative Ledger…`
  - `Ctrl+Alt+Shift+A` / `Cmd+Option+Shift+A`
  - High-value review surface for derivative governance and asset lineage.
- `Bulk Attach Audio Files…`
  - `Ctrl+Alt+U` / `Cmd+Option+U`
  - Frequent catalog-media workflow with no prior shortcut.
- `Attach Album Art File…`
  - `Ctrl+Alt+Shift+U` / `Cmd+Option+Shift+U`
  - Paired with bulk audio attach while staying distinct.
- `Verify Audio Authenticity…`
  - `Ctrl+Alt+V` / `Cmd+Option+V`
  - Important quality-control workflow.
- `Audio Authenticity Keys…`
  - `Ctrl+Alt+K` / `Cmd+Option+K`
  - Supportive but discoverable authenticity workflow.

Adjusted shortcuts to remove collisions:

- `Manage Custom Columns…`
  - moved to `Ctrl+Alt+Shift+M` / `Cmd+Option+Shift+M`
- `Edit Column Widths…`
  - moved to `Ctrl+Alt+Shift+W` / `Cmd+Option+Shift+W`

Shortcut routing cleanup:

- the workspace browse/review menu now reuses the primary `Global Search and Relationships…` action instead of exposing a separate unsynchronized action object
- the in-app help dialog now supports `Find` via the platform-standard `Ctrl+F` / `Cmd+F`

## 3. Public-Facing Docs Updated

Updated public-facing documentation sources:

- `README.md`
- `docs/README.md`
- `docs/catalog-workspace-workflows.md`
- `docs/import-and-merge-workflows.md`
- `docs/repertoire_knowledge_system.md`
- `docs/diagnostics-and-recovery.md`
- `docs/audio-authenticity-workflow.md`
- `docs/file_storage_modes.md`
- `docs/gs1_workflow.md`
- `docs/theme_builder.md`
- `docs/undo_redo_strategy.md`
- `isrc_manager/help_content.py`

The updated public docs now describe the application as a coherent current product and position in-app help as the primary user-facing manual. The companion markdown docs remain available as focused supporting material and repo-readable entry points.

## 4. Transitional Wording Patterns Removed

Public-facing docs were rewritten to remove release-note and migration-diary phrasing such as:

- `previously`
- `used to`
- `formerly`
- `now this`
- `this changed from`

Where timing language remains, it is procedural rather than transitional, for example:

- `before save`
- `before export`
- `before writes are applied`

Those phrases describe workflow sequencing, not product-history transitions.

## 5. Help Integration Strategy Chosen

The existing help system already had a stable dialog, searchable chapter list, topic routing, and HTML rendering pipeline. Instead of creating a second long-form documentation surface, this pass kept that help viewer as the single integrated manual and expanded it into a layered information architecture:

- top-level quick-scan help remains available
- deep-dive topics are grouped into structured sections
- companion docs point back to Help as the authoritative user-facing source

The chosen strategy was:

- keep one help viewer
- keep topic pages chapter-based for maintainability
- group help topics into high-level sections for scanability
- merge deep-dive README/wiki/support knowledge into those help chapters
- keep repo markdown as companion material rather than a competing manual

## 6. Which Wiki / Deep-Dive / Support Docs Were Merged Into Help

The help system absorbed and consolidated material from:

- `README.md`
- `docs/catalog-workspace-workflows.md`
- `docs/import-and-merge-workflows.md`
- `docs/repertoire_knowledge_system.md`
- `docs/diagnostics-and-recovery.md`
- `docs/audio-authenticity-workflow.md`
- `docs/file_storage_modes.md`
- `docs/gs1_workflow.md`
- `docs/theme_builder.md`
- `docs/undo_redo_strategy.md`

That material was not dumped into a single page. It was redistributed into the existing help chapter model and surfaced as layered sections with a clearer quick-start to deep-dive progression.

## 7. Resulting Help Structure

The help system now uses grouped sections:

- `Quick Start`
- `Daily Workflows`
- `Deep Dives`
- `Operations & Recovery`
- `Settings & Reference`

Additional structural improvements:

- a dedicated `Keyboard Shortcuts` help chapter
- grouped chapter rendering in the HTML contents index
- grouped chapter rendering in the help dialog navigation list
- stronger help-dialog framing that distinguishes quick guidance from deeper reference material
- platform-standard `Find` support inside the help dialog

## 8. Tests Added / Updated

Added or updated:

- `tests/app/_app_shell_support.py`
  - validates the new shortcut coverage for help, media, and workspace actions
  - validates workspace global-search action reuse
- `tests/app/test_app_shell_startup_core.py`
  - surfaces the shortcut coverage case in startup-level UI tests
- `tests/test_help_content.py`
  - validates the layered help sections
  - validates the keyboard-shortcuts help chapter
  - validates grouped help rendering
- `tests/test_public_docs.py`
  - validates public doc entry-point links
  - validates that the docs hub and README point to in-app help as the primary manual

## 9. Risks / Caveats

- The help system still routes by chapter ID rather than a deeper nested page graph. The new layered structure fits the current architecture cleanly, but future subsection-level deep links would require an additional routing enhancement.
- Public companion docs remain in the repo for readability and discoverability, but they are intentionally framed as companions to Help rather than parallel long-form manuals.
- Shortcut coverage is intentionally selective. Some contextual actions remain shortcut-free to avoid overload and platform conflicts.

## 10. Final Statement

The help system is now the integrated primary user-facing documentation surface. Public-facing docs describe the application in authoritative current-state language, the quick-scan and deep-dive layers are unified through Help, and the highest-value uncovered user-facing actions now have coherent keyboard shortcuts without introducing avoidable conflicts.
