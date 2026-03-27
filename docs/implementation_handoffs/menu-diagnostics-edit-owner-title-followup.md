# Menu, Diagnostics, Edit, and Owner Title Follow-up

## Scope

This pass only changed:

- diagnostics placement for the stored Artists and Albums cleanup tools
- targeted File and Catalog menu organization
- Edit-menu exposure of an existing catalog-table edit action
- owner-driven window-title defaulting

It did not redesign the broader shell, diagnostics system, or unrelated workflow surfaces.

## Old Menu And Diagnostics Placement

- The stored Artists and Albums cleanup tools lived in the Catalog Managers workspace surface.
- That cleanup surface was exposed as a Catalog workspace tool instead of a diagnostics-adjacent maintenance tool.
- `File -> Profile Maintenance` was a top-level File sibling instead of living under `File -> Profiles`.
- `File -> Profile Maintenance -> Verify Integrity` remained in the menu even though integrity checking was already available through the integrated diagnostics surface.
- The Edit menu did not expose the existing `GS1 Metadata…` edit workflow even though it was already available from the catalog table context menu.
- Window title storage treated the title as a direct settings value, with no clear separation between an automatic default and a deliberate user override.

## New Diagnostics Integration Location

- Stored Artists and Albums cleanup now lives in `DiagnosticsDialog` as a native `Catalog Cleanup` tab beside the existing diagnostics health surface.
- The Diagnostics dialog now uses a top-level tab structure:
  - `Health`
  - `Catalog Cleanup`
- The `Catalog Cleanup` surface contains the preserved cleanup tabs:
  - `Artists`
  - `Albums`
- The old legacy route `open_catalog_managers_dialog(...)` now redirects to Diagnostics and focuses the requested cleanup tab instead of opening the old docked workspace flow.
- Catalog workspace/menu exposure for the old Catalog Managers tool was removed.

## Obsolete Menu Items Removed

- Removed `File -> Profile Maintenance -> Verify Integrity`
- Removed the obsolete `verify` action-ribbon registry entry
- Removed the old `catalog_managers` action-ribbon registry entry
- Removed `Catalog Managers…` from `Catalog -> Workspace`

## File Menu Hierarchy Changes

- `Profile Maintenance` now lives under `File -> Profiles`
- New hierarchy:
  - `File -> Profiles -> Profile Maintenance -> Backup Database`
  - `File -> Profiles -> Profile Maintenance -> Restore from Backup…`
- `Verify Integrity` is no longer present there because diagnostics already owns that responsibility

## Edit Menu Parity Changes

- Added `GS1 Metadata…` to the `Edit` menu
- The Edit menu entry reuses the existing `gs1_metadata_action`
- Routing remains shared with the existing catalog-table/context-menu workflow
- Context-sensitive behavior is preserved:
  - when no catalog row is selected, the existing selection warning still appears
  - no new edit behavior was invented for this pass

## Window-Title Defaulting Rules Implemented

The effective window title now follows this priority:

1. explicit user override
2. owner Party company name
3. application name fallback

Implementation notes:

- The application default title is now `ISRC Catalog Manager`
- Identity state now separates the raw override from the effective resolved title
- Application Settings stores a manual override only when the field is explicitly filled in
- Leaving the Window Title field blank means:
  - use the owner Party company name automatically when present
  - otherwise fall back to the application name
- The settings UI includes a `Use Automatic` button that clears the manual override
- Legacy `identity/window_title` values equal to the old auto title (`ISRC Manager`) or the new default app title are treated as non-overrides during migration
- History replay remains compatible because identity payload application accepts either `window_title_override` or older `window_title` data

## Tests Added Or Updated

- `tests/app/_app_shell_support.py`
  - added diagnostics cleanup relocation coverage
  - added File menu hierarchy coverage
  - added Edit-menu parity coverage
  - added owner/company/manual window-title defaulting coverage
  - updated workspace/menu expectations to remove Catalog Managers and Verify Integrity
- `tests/app/test_app_shell_startup_core.py`
  - added wrappers for new startup/menu/title tests
- `tests/app/test_app_shell_workspace_docks.py`
  - replaced old Catalog Managers dock tests with diagnostics cleanup dialog tests
- `tests/test_app_dialogs.py`
  - added diagnostics cleanup tab integration assertions
- `tests/test_theme_builder.py`
  - added Application Settings window-title placeholder/hint coverage
- `tests/test_settings_mutations_service.py`
  - updated identity persistence expectations for `window_title_override`
- `tests/test_help_content.py`
  - added help-content assertions for diagnostics cleanup and title defaults

Validated with:

- `python3 -m unittest tests.test_app_dialogs tests.test_theme_builder tests.test_settings_mutations_service tests.test_help_content tests.app.test_app_shell_startup_core tests.app.test_app_shell_workspace_docks`
- `python3 -m black --check ISRC_manager.py isrc_manager/constants.py isrc_manager/main_window_shell.py isrc_manager/app_dialogs.py isrc_manager/services/settings_mutations.py isrc_manager/history/manager.py isrc_manager/help_content.py tests/app/_app_shell_support.py tests/app/test_app_shell_startup_core.py tests/app/test_app_shell_workspace_docks.py tests/test_app_dialogs.py tests/test_theme_builder.py tests/test_settings_mutations_service.py tests/test_help_content.py`

## Risks And Caveats

- `open_catalog_managers_dialog(...)` is still present as a compatibility shim; it now routes into Diagnostics rather than opening the old workspace surface.
- The legacy catalog managers dock factory still exists in code, but it is no longer restored as a persistent workspace dock and is no longer exposed through the current menu model.
- Automatic title resolution refreshes when owner-linked workspace state refreshes; this is intentional so owner company naming stays authoritative unless the user has set an explicit override.
- Help text now reflects the current product model, but any external screenshots or older handoffs that still mention Catalog Managers as a workspace tool may need a future documentation sweep.

## Product Model Statement

Diagnostics placement, Edit parity, and owner-title defaults now reflect the current product model:

- diagnostics-adjacent cleanup tools live with Diagnostics
- obsolete duplicate integrity menu exposure has been removed
- Edit exposes the appropriate existing catalog-table edit action
- window title derives intelligently from user override, owner company authority, and application fallback
