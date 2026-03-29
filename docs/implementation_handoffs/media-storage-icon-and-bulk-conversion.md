# Media Storage Icon And Bulk Conversion

## 1. Prior Media-Icon And Storage-State Behavior

- Media badge icons were global and only distinguished `audio`, `audio_lossy`, and `image`.
- Standard-media badge rendering already had access to `storage_mode`, but the icon resolver ignored it.
- Custom blob-field badge rendering did not request `include_storage_details=True`, so managed-file vs database-backed custom blobs were visually indistinguishable.
- Storage conversion was wired only from the existing `Storage` submenu in the catalog-table context menu, but each action targeted only the clicked row.
- Standard-media and custom-blob storage conversion both ran synchronously on the UI thread through `_run_snapshot_history_action(...)`, followed by a blocking `refresh_table_preserve_view(...)`.

## 2. New Icon Differentiation Added

- Global blob-icon settings now distinguish:
  - `audio_managed`
  - `audio_database`
  - `audio_lossy_managed`
  - `audio_lossy_database`
  - `image_managed`
  - `image_database`
- Standard-media badge resolution now derives the icon kind from both media type and `storage_mode`.
- Custom blob-field badge resolution now requests storage details and chooses the inherited global icon from the field type plus `storage_mode`.
- Tooltips now surface storage state explicitly with `Managed-file storage` or `Database storage`.
- Existing profiles remain compatible because legacy `audio`, `audio_lossy`, and `image` settings are still accepted as load-time fallbacks and are expanded into the new storage-aware keys.

## 3. Theme Customization Changes

- The existing blob-icon customization subsystem was extended instead of replaced.
- `BlobIconSettingsService` persists the new storage-aware keys in `app_kv`.
- The Application Settings Blob Icons page now exposes separate editors for managed/database audio, managed/database lossy audio, and managed/database image badges.
- The Blob Icons preview tab now shows both managed-file and database-backed preview rows instead of one generic audio row and one generic image row.
- Custom-column icon overrides were left on the existing single-override model.
  - Inherited custom blob columns now pick up the new storage-aware global icons.
  - A custom column with its own explicit override still uses that override for both storage modes.

## 4. Bulk Storage-Conversion Selection Logic

- No new context-menu item was added.
- The existing `Storage` submenu in the catalog-table context menu is still the single entry point.
- The submenu now follows the existing effective-selection rule already used elsewhere in the table:
  - if the clicked row is part of the current selection, act on the full selection
  - otherwise collapse to the clicked row
- Action labels are now selection-aware:
  - all managed selection: `Store selection in database`
  - all database selection: `Store selection as managed file`
  - mixed selection: both actions are shown
  - single-track cases keep the existing singular labels
- Mixed selections do not fail just because some tracks already match the chosen target.
  - already-matching tracks are skipped
  - only opposite-mode tracks are converted
  - tracks with no stored media in the focused column are skipped and reported

## 5. Worker-Thread And Progress Integration

- Storage conversion now runs through `_submit_background_bundle_task(...)` with `kind="write"` for both:
  - standard media
  - custom blob fields
- The real conversion logic is still reused from:
  - `TrackService.convert_media_storage_mode(...)`
  - `CustomFieldValueService.convert_storage_mode(...)`
- The background worker now performs real staged work:
  - collect the selected tracks
  - classify current storage modes
  - convert each eligible track through the real service logic
  - capture and record snapshot history
- Worker progress intentionally stops at `96%`.
- Final UI-thread completion happens in `on_success_before_cleanup(...)`:
  - commit the foreground connection
  - refresh the catalog table and media badges
  - refresh history actions
  - emit `100%` only after the UI is actually updated

## 6. Files Changed

- `ISRC_manager.py`
- `isrc_manager/blob_icons.py`
- `tests/test_blob_icons.py`
- `tests/test_theme_builder.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `docs/implementation_handoffs/media-storage-icon-and-bulk-conversion.md`

## 7. Tests Added Or Updated

- Updated blob-icon tests to cover the new storage-aware key shape and compatibility fallback behavior.
- Updated theme-builder tests to cover the expanded editor set and preview rows.
- Added app-shell cases for:
  - distinct managed/database audio icons
  - distinct managed/database album-art icons
  - distinct managed/database inherited custom-blob icons
  - multi-selection storage-menu labels
  - mixed-selection conversion skip behavior
  - background-task routing for both standard and custom storage conversion
  - worker-progress vs final UI-completion progress behavior

## 8. Risks And Caveats

- The current environment can run the blob-icon, theme-builder, track-service, and custom-field-service test modules successfully.
- The app-shell GUI suite currently crashes during `App` startup in this environment before it reaches the new editor-surface cases.
  - The observed crash is a PySide segmentation fault during application initialization, not a feature-specific assertion failure.
  - The new app-shell coverage remains in the repository, but full execution of that suite still depends on stabilizing the existing GUI test startup path.
- Explicit custom-column icon overrides remain single-icon overrides, so they do not automatically differentiate managed vs database storage unless the column inherits the global defaults.

## 9. Explicit Outcome Statement

Storage conversion now supports dynamic multi-selection from the existing `Storage` submenu, converts through the managed background-task system instead of the UI thread, and reports truthful staged progress where `100%` is only reached after final UI refresh and completion work is done.
