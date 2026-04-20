# Engineering Plan 1 — Non-App Class Extraction and Compatibility Stabilization

## Summary
This plan removes all non-`App` top-level classes from `ISRC_manager.py`, or deletes them if audit confirms they are dead. The goal is to drain the monolith of dialogs, panels, widgets, and helper classes while preserving runtime behavior through stable compatibility aliases and host seams.

This plan does **not** decompose `App` beyond narrowly required compatibility work. `App` remains temporarily in `ISRC_manager.py` as a migration facade.

## Goals
- Remove non-`App` classes from `ISRC_manager.py`
- Keep the application runnable after every batch
- Preserve stable root imports during migration
- Delete dead legacy UI instead of relocating it if no real usage exists
- Prepare clean extraction seams for later `App` decomposition
- End Plan 1 with `ISRC_manager.py` containing essentially:
  - `App`
  - entry/bootstrap glue
  - temporary compatibility aliases only

## In Scope
- `_JsonLogFormatter`
- `ApplicationSettingsDialog`
- `_ManageArtistsDialog`
- `_ManageAlbumsDialog`
- `LicenseUploadDialog`
- `LicensesBrowserPanel`
- `LicensesBrowserDialog`
- `LicenseeManagerDialog`
- `_CatalogManagerPaneBase`
- `_CatalogArtistsPane`
- `_CatalogAlbumsPane`
- `DiagnosticsCatalogCleanupPanel`
- `_CatalogLicenseesPane`
- `CatalogManagersPanel`
- `CatalogManagersDialog`
- `_AlbumTrackSection`
- `AlbumEntryDialog`
- `EditDialog`
- `_ImagePreviewDialog`
- `_AudioPreviewDialog`
- `WaveformWidget`

## Out of Scope
- Major `App` responsibility extraction
- Main shell/controller decomposition
- Final move of `App` into `isrc_manager.main_window`
- Broad workflow/controller extraction from `App`
- Final compatibility-alias cleanup

## Target Structure
Use or create:

- `isrc_manager/app_logging.py`
- `isrc_manager/application_settings_dialog.py`
- `isrc_manager/catalog_managers.py`
- `isrc_manager/licenses/dialogs.py`
- `isrc_manager/tracks/album_entry_dialog.py`
- `isrc_manager/tracks/edit_dialog.py`
- `isrc_manager/tracks/host_protocols.py`
- `isrc_manager/media/waveform.py`
- `isrc_manager/media/preview_dialogs.py`

## Governing Rules
- Prefer deleting dead code over relocating it
- Preserve root compatibility imports for moved live classes
- Use host protocols instead of importing `App` into extracted dialogs
- Do not widen scope into `App` controller decomposition
- Keep extracted modules cohesive and reasonably small
- If a moved class creates a new oversized file, schedule later decomposition rather than blocking extraction

## Phases and Batches

### Phase 0 — Packaging and Compatibility Gate
**Goal**
- fix `pyproject.toml` package parity
- define root alias policy
- ensure new packages are visible to packaging/runtime

**In scope**
- package list audit
- `__init__.py` parity
- compatibility import policy

**Out of scope**
- moving classes

**Validation**
- packaging config includes all live packages
- compile/import sanity passes

### Phase 1 — Logging and Prompt Helpers
**Goal**
- move `_JsonLogFormatter`
- move any clearly standalone prompt/helper code discovered during batch if truly leaf-level

**Validation**
- logging still initializes correctly
- no runtime behavior change

### Phase 2 — Waveform Extraction
**Goal**
- move `WaveformWidget`
- move `load_wav_peaks()` with it

**Validation**
- focused media/widget tests
- compile/import sanity

### Phase 3 — Media Preview Dialogs
**Goal**
- move `_ImagePreviewDialog`
- move `_AudioPreviewDialog`
- add `MediaPreviewHost` seam if needed

**Validation**
- preview dialogs still open/function
- navigation/export callbacks still behave

### Phase 4 — Live Catalog Manager Panels
**Goal**
- move catalog manager pane/panel classes that are actually live

**Validation**
- catalog manager surfaces still open
- admin actions still function

### Phase 5 — Dead Catalog Dialog Audit
**Goal**
- decide whether `_ManageArtistsDialog`, `_ManageAlbumsDialog`, `CatalogManagersDialog` are dead
- delete if dead
- relocate only if proven needed

**Validation**
- no live call path broken
- audit documented in handoff

### Phase 6 — Legacy License UI Decision Gate
**Goal**
- audit `LicenseUploadDialog`, `LicensesBrowserPanel`, `LicensesBrowserDialog`, `LicenseeManagerDialog`, `_CatalogLicenseesPane`
- delete if dead
- quarantine to `licenses/dialogs.py` only if real compatibility need exists

**Validation**
- audit complete
- broken legacy code not silently preserved without reason

### Phase 7 — Settings Dialog Whole Move
**Goal**
- move `ApplicationSettingsDialog` as-is first
- preserve compatibility alias
- avoid internal decomposition in this batch except what is required to move safely

**Validation**
- settings dialog opens
- theme/settings/GS1 related tests pass

### Phase 8 — Settings Dialog Internal Health Pass
**Goal**
- reduce risk of a new mini-monolith
- split internal tabs/panels/controllers only if still justified after extraction

**Validation**
- same as Phase 7
- module health improved

### Phase 9 — Album Editor Host Seam
**Goal**
- introduce `AlbumEditorHost`
- prepare extraction without moving dialog yet

**Validation**
- no runtime behavior change
- compile/tests green

### Phase 10 — Album Entry Extraction
**Goal**
- move `_AlbumTrackSection` and `AlbumEntryDialog` together
- preserve compatibility alias

**Validation**
- add-album / track creation workflows still function
- host seam works

### Phase 11 — Track Editor Host Seam
**Goal**
- introduce `TrackEditorHost`

**Validation**
- no runtime behavior change
- compile/tests green

### Phase 12 — Edit Dialog Extraction
**Goal**
- move `EditDialog`
- preserve compatibility alias

**Validation**
- edit and bulk edit workflows still function
- focused editor tests pass

## Success Criteria
By the end of Plan 1:
- all non-`App` top-level classes are extracted or deleted
- `ISRC_manager.py` no longer contains dialogs/panels/widgets except temporary compatibility glue
- root compatibility aliases exist where needed
- app behavior remains unchanged
- monolith line count is materially reduced
- the only major monolith remaining is `App`

## Risks
- settings dialog may become a new mini-monolith
- track dialogs are strongly coupled to `App`
- legacy license UI may be broken and misleading
- packaging may lag behind extracted packages
- compatibility aliases may linger too long if not tracked carefully

## Handoff Rule
At the end of Plan 1, produce a handoff that explicitly lists:
- which extracted classes still rely on compatibility aliases
- which dead-code audits resulted in deletion
- which host protocols now exist
- what still remains inside `App`
