# Modularization Strategy

## Goal

Split the current monolith into logical modules without changing runtime behavior, database shape, settings keys, file layout, or user workflows.

This plan is based on the current codebase as of March 16, 2026.

## Current Shape

- The repository is still functionally centered on [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py), which is now about 15,200 lines.
- Auxiliary files are mostly packaging/build support:
  - [`build.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/build.py)
  - [`icon_factory.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/icon_factory.py)
- The main window class `App` contains 131 methods and currently owns UI construction, database lifecycle, schema migrations, CRUD operations, import/export, blob handling, preview logic, backup/restore, and profile/settings workflows.
- The entry path is now slightly thinner than before: startup orchestration is delegated through [`isrc_manager/app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_bootstrap.py), which preserves the real launch behavior while giving tests and coverage a measurable seam.

## Responsibility Clusters In The Monolith

These are the natural seams already present in [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py):

- Bootstrap, paths, settings, validators, formatters: lines 47-258
- Reusable dialogs/widgets:
  - custom columns, draggable hint, date picker, sorting item, spin box, artist/album managers: lines 268-751
  - license dialogs: lines 752-1322
  - edit dialog, audio preview, waveform widget: lines 5406-6201
- Main window construction and menu wiring: lines 1323-1771
- Identity/profile switching: lines 1781-2032
- Database open/init/profile KV/migrations/audit: lines 2046-2687
- Table/combo/search helpers: lines 2695-3078
- Track CRUD and ISRC generation: lines 3084-3337
- XML export/import: lines 3338-3869
- Registration/settings dialogs: lines 3870-4024
- Table view preferences and panel toggles: lines 4025-4192
- Custom fields, blob storage, preview/export, context menu: lines 4193-5379
- License actions inside `App`: lines 5380-5403

## Main Coupling Problems

The main maintenance pain is not just file length. It is that the main window currently mixes four layers in the same methods:

1. Qt widget orchestration
2. Domain rules
3. SQLite access and migrations
4. Filesystem/media operations

Examples:

- [`App.save`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L3143) validates input, generates ISRCs, creates related records, writes SQL, commits, audits, refreshes UI, and shows dialogs.
- [`App.import_from_xml`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L3573) parses XML, validates schema, maps custom fields, runs transactions, writes SQL, logs, and prompts the user.
- [`App.__init__`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L1329) builds the entire application shell, menus, toolbar, form, search bar, table, settings integration, and signal wiring in one constructor.

## Existing Cleanup Signals Worth Preserving During The Split

These are not reasons to rewrite behavior, but they are useful markers for extraction boundaries:

- Duplicate methods exist inside `App`:
  - `cf_fetch_blob`
  - `cf_export_blob`
- Several helpers are referenced but not defined in the file:
  - `_get_track_title`
  - `_sanitize_filename`
  - `cf_blob_size`
  - `_tmp_path` on `_AudioPreviewDialog.closeEvent`
- Several dialog classes are already largely self-contained and can be moved first with minimal risk.

## Recommended Target Package Layout

Do not split into dozens of tiny files. Aim for a package with clear boundaries and a thin entry script.

Suggested structure:

```text
ISRC-Catalog-Manager/
  ISRC_manager.py                  # thin compatibility entrypoint
  isrc_manager/
    __init__.py
    bootstrap.py
    constants.py
    paths.py
    settings.py
    logging_config.py
    domain/
      __init__.py
      codes.py                     # ISRC/ISWC/UPC validation + normalization
      timecode.py                  # hh:mm:ss helpers
      models.py                    # dataclasses for Track, CustomFieldDef, License
    db/
      __init__.py
      connection.py
      schema.py
      migrations.py
      profile_store.py
      audit.py
      repositories/
        tracks.py
        artists.py
        albums.py
        custom_fields.py
        licenses.py
        settings_repo.py
    services/
      __init__.py
      tracks.py
      import_export.py
      backup_restore.py
      media_blobs.py
      license_files.py
      profile_manager.py
    ui/
      __init__.py
      main_window.py
      dialogs/
        custom_columns.py
        date_picker.py
        edit_track.py
        license_upload.py
        licenses_browser.py
        licensee_manager.py
        manage_artists.py
        manage_albums.py
      widgets/
        draggable_label.py
        sort_item.py
        two_digit_spinbox.py
        waveform.py
        audio_preview.py
      sections/
        menus.py
        profile_toolbar.py
        add_track_panel.py
        tracks_table.py
```

Recent extractions already align with this direction. The repertoire layer now lives in focused packages such as `isrc_manager.works`, `isrc_manager.parties`, `isrc_manager.contracts`, `isrc_manager.rights`, `isrc_manager.assets`, and `isrc_manager.search`. See [`docs/repertoire_knowledge_system.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/repertoire_knowledge_system.md) for the current data model and service boundaries.

## Dependency Direction

Keep the dependencies one-way:

`ui -> services -> db/repositories -> domain`

Rules:

- UI modules may call services.
- Services may call repositories and domain helpers.
- Repositories should not show dialogs or touch Qt widgets.
- Domain helpers should not know about Qt or SQLite.

This direction is what keeps the split maintainable once the initial extraction is done.

## Staged Refactor Plan

### Stage 0: Freeze behavior before moving code

Before refactoring, create a lightweight safety net.

Minimum coverage:

- create/open profile DB
- generate ISRC with same prefix/artist code rules
- create/edit/delete track
- round-trip custom field definitions and values
- XML export/import round trip
- license upload/edit/delete
- backup/restore and integrity check

This baseline is now in place and has been extended with:

- headless-safe startup coverage for the real desktop shell bootstrap path
- main-window construction and workspace/profile integration tests
- dialog/controller tests for release, work, and global-search workflows
- reusable Qt test helpers that keep `QApplication` lifecycle stable in CI

The remaining test gap is no longer "can we test the shell at all?" but "which additional dialog-heavy flows should be promoted from smoke coverage to behavior coverage next?"

### Stage 1: Extract pure helpers first

Move the low-risk, non-Qt business helpers out of the main file:

- path helpers
- settings bootstrap
- validators and formatters
- MIME/file helper functions

Candidate source lines: 47-258.

Why first:

- lowest coupling
- easiest to verify
- shrinks imports and mental load immediately

Status:

- partially complete
- settings bootstrap already lives in [`isrc_manager/settings.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/settings.py)
- startup orchestration now lives in [`isrc_manager/app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_bootstrap.py)
- both paths are covered by integration tests

### Stage 2: Move standalone dialogs and widgets as-is

Move the already-separated classes into `ui/dialogs` and `ui/widgets` without redesigning them yet.

Best first movers:

- [`CustomColumnsDialog`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L268)
- [`DatePickerDialog`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L490)
- [`_ManageArtistsDialog`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L566)
- [`_ManageAlbumsDialog`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L662)
- [`LicenseUploadDialog`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L752)
- [`LicensesBrowserDialog`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L873)
- [`LicenseeManagerDialog`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L1213)
- [`EditDialog`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L5406)
- [`WaveformWidget`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L5876)

Goal for this stage:

- change imports only
- keep constructor signatures the same
- keep signal behavior the same

### Stage 3: Extract database bootstrap and migrations

Move database lifecycle code out of `App` into a dedicated database layer:

- `open_database`
- `init_db`
- migration helpers
- profile KV store helpers
- audit helpers

Candidate source lines: 2046-2687.

Target design:

- `DatabaseManager` or `DatabaseSession` owns `conn`, initialization, pragmas, migrations, and auditing
- `App` receives a database object instead of directly owning raw schema logic

Important constraint:

- preserve the SQL and `PRAGMA user_version` behavior exactly during the move

### Stage 4: Introduce repositories for data access

Once DB bootstrap is isolated, move raw SQL for each entity into repositories:

- `TrackRepository`
- `ArtistRepository`
- `AlbumRepository`
- `CustomFieldRepository`
- `LicenseRepository`
- `SettingsRepository`

What moves here:

- query methods
- insert/update/delete helpers
- existence checks
- list/fetch methods for comboboxes and tables

What stays out:

- dialog prompts
- `QMessageBox`
- `QFileDialog`

### Stage 5: Extract service layer for business workflows

Create services that orchestrate repository calls and domain rules while remaining UI-agnostic.

Service candidates:

- `TrackService`
  - create track
  - update track
  - delete track
  - generate next ISRC
- `ImportExportService`
  - full export
  - selected export
  - XML import parse/validate/commit
- `BackupRestoreService`
  - backup creation
  - integrity verification
  - restore workflow internals
- `CustomFieldBlobService`
  - validate blob type
  - save/fetch/delete/export blob
- `LicenseService`
  - create/update/delete license records
  - resolve relative file paths

This stage removes the highest-value logic from `App` without changing the UI surface.

### Stage 6: Split the main window by section, not by feature rewrite

Only after the service layer exists, shrink `App.__init__` and the window methods.

Split the main window into construction helpers or section objects:

- menu builder
- profile toolbar builder
- add-track form panel
- search/table panel
- view preference wiring

Do not start here. This is more stable once logic has already moved out.

### Stage 7: Leave a thin compatibility entrypoint

Keep [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py) as a thin launcher during the transition:

- app startup
- single-instance lock
- QApplication setup
- imports of `MainWindow`

This reduces breakage while other modules settle.

## Recommended Extraction Order

This order minimizes risk:

1. Pure helpers and constants
2. Standalone dialogs/widgets
3. Database bootstrap/migrations/audit
4. Repositories
5. Services for track CRUD and ISRC generation
6. Services for import/export and backup/restore
7. Custom field blob handling
8. Main window construction split
9. Thin entrypoint cleanup

## High-Risk Areas To Delay Until Foundations Exist

Do these later, not first:

- [`App.import_from_xml`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L3573)
- [`App.backup_database`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L4837)
- [`App.restore_database`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py#L4939)
- custom field blob preview/export logic around lines 4270-5379

These methods combine UI, file I/O, transactions, and media handling, so they are better extracted after the repository and service layers exist.

## What Must Stay Stable During Refactor

To satisfy the "same functionality" goal, keep these unchanged until you intentionally version them:

- SQLite schema and migration ordering
- `QSettings` keys and settings file locations
- database, export, backup, log, and license file directories
- XML formats for full and selected export
- audit log behavior
- track creation and ISRC generation rules
- dialog wording and button flow where possible

## Suggested First Implementation Milestone

A good first milestone is:

1. Create the `isrc_manager` package
2. Move pure helpers/constants
3. Move standalone dialogs/widgets
4. Keep `App` behavior identical but update imports

That should reduce the monolith significantly without touching the most fragile workflows.

## Suggested Second Implementation Milestone

Next, extract:

1. database connection/bootstrap/migrations
2. track repositories
3. track service
4. ISRC generation logic

At that point, `App` becomes mostly a Qt coordinator instead of the owner of all business logic.

## Notes For The Actual Refactor

- Avoid mixin-heavy designs unless they are temporary.
- Prefer composition over inheritance for services and repositories.
- Prefer moving existing methods intact first, then cleaning them up once behavior is proven stable.
- Resolve the currently duplicated and missing helper functions as part of extraction, but do it behind stable interfaces so behavior does not drift.
