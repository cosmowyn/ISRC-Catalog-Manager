# Catalog Menu, Context Menu, and Dialog Cleanup

## Original Problems

- The `Catalog` menu had accumulated too many unrelated actions in one place, which made catalog navigation, audio ingest, export, authenticity, and admin-style tools feel flatter than the underlying workflows.
- The catalog row context menu mixed row actions, licensing, audio ingest/export/authenticity actions, filters, copy actions, and file/media actions in one long stack.
- Several small export/conversion surfaces were using widths that were much larger than their actual content required, especially progress dialogs and the format picker.

## Final Main Menu Structure

The `Catalog` menu is now grouped by product workflow:

1. `Workspace`
   - `Catalog Managers…`
   - `Release Browser…`
   - `Work Manager…`
   - `Party Manager…`
   - `Contract Manager…`
   - `Rights Matrix…`
   - `Asset Version Registry…`
   - `Global Search and Relationships…`
   - `Show Add Data Panel`
   - `Show Catalog Table`
2. `Legacy & Special`
   - `Legacy License Archive >`
     - `License Browser…`
     - `Migrate Legacy Licenses to Contracts…`
   - `GS1 Metadata…`
3. `Audio Ingest`
   - `Bulk Attach Audio Files…`
   - `Import Metadata from Audio Files…`
4. `Audio Export & Conversion`
   - `Export Audio Derivatives…`
   - `Convert External Audio Files…`
   - `Export Tagged Audio Copies…`
5. `Audio Authenticity`
   - `Export Authentic Masters…`
   - `Export Provenance Copies…`
   - `Export Forensic Watermarked Audio…`
   - `Inspect Forensic Watermark…`
   - `Verify Audio Authenticity…`
6. Top-level quality action
   - `Data Quality Dashboard…`

This keeps the same action objects and wiring while making the menu read like product workflows instead of an internal action dump.

## Final Context Menu Structure

The catalog row context menu is now intentionally shorter at the top level.

Top-level row actions:

- `Edit Entry`
- `GS1 Metadata…`
- `Open Primary Release…` when a primary release exists
- `Open Linked Work(s)…` when linked works exist
- `Link Selected Track(s) to Work…`
- `Delete Entry`
- `Add License to this Track…`
- `View Licenses for this Track…`
- `Audio >`

The new `Audio` submenu holds the specialized audio workflows:

- `Import Metadata from Audio Files…`
- `Export Tagged Audio Copies…`
- `Export Audio Derivatives…`
- `Export Authentic Masters…`
- `Export Provenance Copies…`
- `Export Forensic Watermarked Audio…`
- `Inspect Forensic Watermark…`
- `Verify Audio Authenticity…`

Filter, copy, preview, attach/export/delete media, and storage-mode actions still remain accessible below, but the repeated audio workflow stack is no longer competing with the row-editing actions.

`Convert External Audio Files…` was intentionally removed from the row-scoped context menu because it is not tied to the selected catalog row and was adding noise there. It is still available from the main menu and File menu.

## Renamed or Demoted Actions

Renamed for clearer user-facing language:

- `Import Tags from Audio…` -> `Import Metadata from Audio Files…`
- `Write Tags to Exported Audio…` -> `Export Tagged Audio Copies…`
- `Export Managed Audio Derivatives…` -> `Export Audio Derivatives…`
- `External Audio Conversion Utility…` -> `Convert External Audio Files…`
- `Export Watermark-Authentic Masters…` -> `Export Authentic Masters…`
- `Export Provenance-Linked Lossy Copies…` -> `Export Provenance Copies…`

Demoted:

- `Export Tagged Audio Copies…` remains available, but it is no longer exposed as a top-level Catalog action alongside the more common derivative/conversion flows. It now lives inside `Catalog > Audio Export & Conversion` and the row `Audio` submenu.

## Dialog and Progress Sizing Rules Added

### Shared progress dialogs

`isrc_manager/tasks/manager.py` now applies compact width constraints to all task progress dialogs:

- dialog width clamped to `360..500`
- label text wraps and is capped to a narrower readable width
- progress bars stay readable without stretching across the window
- cancel buttons are kept proportional

The sizing helper is reapplied after progress/status updates so long stage text wraps instead of forcing the dialog wider.

### Compact format picker

`ISRC_manager.py::_prompt_audio_conversion_format()` now uses the shared compact choice dialog from `isrc_manager/ui_common.py` instead of `QInputDialog.getItem(...)`.

That gives:

- wrapped prompt text
- bounded width
- a compact button row
- more consistent sizing across managed export, forensic export fallback, and external conversion

### Forensic export dialog

`ForensicExportDialog` now uses content-based width constraints instead of a hardcoded oversized starting width.

## Tests Added or Updated

- Updated app-shell menu tests to assert the grouped Catalog menu structure.
- Updated app-shell tests to assert `Workspace` and `Legacy & Special` submenu placement without relying on fragile live submenu wrappers.
- Updated catalog context-menu tests to assert the new `Audio` submenu shape and renamed actions.
- Added progress-dialog sizing coverage in `tests/test_task_manager.py`.
- Added shared dialog width helper coverage in `tests/test_ui_common.py`.

Focused verification run during this cleanup:

- `python3 -m unittest tests.test_task_manager tests.test_ui_common`
- `python3 -m unittest tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_catalog_menu_hides_top_level_release_creation_and_groups_legacy_tools tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_catalog_menu_hosts_panel_toggle_actions_and_preserves_existing_behavior`
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_authenticity_actions_are_present_in_catalog_and_settings_menus tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_authenticity_table_context_menu_exposes_export_actions`

## Remaining Cleanup Opportunities

- The larger preview-style dialogs such as tag preview and some authenticity inspection/report dialogs are intentionally still resizable and content-heavy. They were left mostly alone in this pass to avoid shrinking genuinely dense review surfaces too aggressively.
- If a future UI pass is planned, the next high-value target would be harmonizing the naming and help-copy around “plain conversion”, “derivative export”, “provenance copies”, and “forensic export” across help content, tooltips, and any onboarding text.
