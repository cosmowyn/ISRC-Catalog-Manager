# Engineering Plan 1 — Non-App Class Extraction and Compatibility Stabilization

## Summary
This plan removes all non-`App` top-level classes from `ISRC_manager.py`, or deletes them if audit confirms they are dead. The goal is to drain the monolith of dialogs, panels, widgets, visualizers, and helper classes while preserving runtime behavior through stable compatibility aliases and host seams.

This plan does **not** decompose `App` beyond narrowly required compatibility work. `App` remains temporarily in `ISRC_manager.py` as a migration facade.

## Current Repository Baseline
This plan was originally scaffolded on 2026-04-20. The live codebase has changed materially since then:

- `ISRC_manager.py` is now 42,952 lines.
- `App` is still local to `ISRC_manager.py` and is now 26,541 lines.
- The original non-`App` classes are still local to `ISRC_manager.py`; Plan 1 extraction has not been applied yet.
- New non-`App` top-level classes were added after the original plan:
  - `_AlbumTrackOrderingTable`
  - `AlbumTrackOrderingDialog`
  - `_HiDpiArtworkLabel`
  - `_AudioPreviewPreloadBridge`
  - `_AudioPreviewPreloadCancelled`
  - `_AudioPreviewPreparedMedia`
  - `_AudioPreviewPreloadTask`
  - `_AudioPreviewPreloadResult`
  - `_AudioPreviewTrackLoadTask`
  - `_AudioPreviewTrackLoadResult`
  - `StereoPeakMeterWidget`
  - `SpectrumGraphWidget`
- New media preview/helper functions were also added and must move with their owning dialog or widget:
  - `_audio_preview_detect_mime_from_bytes`
  - `_audio_preview_suffix_for_mime`
  - `_audio_preview_fetch_source_for_preload`
  - `_audio_preview_write_preload_temp_file`
  - `_audio_preview_artwork_payload_for_snapshot`
  - `_audio_preview_track_queue_items_for_service`
  - `_audio_preview_state_for_preload_task`
  - `_build_audio_preview_preload`
  - `_build_audio_preview_track_load`
  - `load_audio_harmonic_frames`
  - `load_audio_peak_meter_frames`
  - `load_audio_spectrum_frames`
- `isrc_manager/media/waveform_cache.py`, `isrc_manager/media/equalizer.py`, `isrc_manager/media/equalizer_player.py`, and `isrc_manager/media/bookmarks.py` now exist and should be treated as existing media infrastructure, not extraction targets.
- The current `pyproject.toml` package list matches tracked `isrc_manager/**/__init__.py` packages; Phase 0 should preserve that parity and add only newly created packages.
- Tests still import several extracted candidates through the root `ISRC_manager` module, especially `ApplicationSettingsDialog`, `AlbumEntryDialog`, `EditDialog`, `WaveformWidget`, `SpectrumGraphWidget`, `StereoPeakMeterWidget`, and audio frame loader helpers. Root compatibility aliases are therefore required during the migration.
- Legacy license browser/workspace actions are no longer exposed by the shell, and tests assert that they remain hidden. That makes deletion the default outcome for the legacy license UI unless a fresh audit finds an external compatibility need.
- `open_catalog_managers_dialog()` now redirects to diagnostics cleanup, but `CatalogManagersPanel` and its dock factory still exist. Treat the old dialog as likely dead and the panel/panes as live-or-quarantined until Phase 4/5 audit confirms.

## Mandatory Architecture Governance
The follow-up enforcement plan is a mandatory governance layer for Plan 1. Every phase must apply
its compatibility, dependency, package-boundary, import-cycle, and module-size checks before the
phase is considered complete.

Plan 1 must maintain:

- `compatibility_inventory.md`
- `architecture_metrics.md` where a phase changes architecture metrics or establishes a gate baseline
- phase handoffs under `phase execution handoffs/`
- `Milestones.md`

Plan 2 may not begin until the Plan 1 Completion Gate in this document passes.

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
- `_AlbumTrackOrderingTable`
- `AlbumTrackOrderingDialog`
- `_AlbumTrackSection`
- `AlbumEntryDialog`
- `EditDialog`
- `_ImagePreviewDialog`
- `_HiDpiArtworkLabel`
- `_AudioPreviewPreloadBridge`
- `_AudioPreviewPreloadCancelled`
- `_AudioPreviewPreparedMedia`
- `_AudioPreviewPreloadTask`
- `_AudioPreviewPreloadResult`
- `_AudioPreviewTrackLoadTask`
- `_AudioPreviewTrackLoadResult`
- `_AudioPreviewDialog`
- `StereoPeakMeterWidget`
- `WaveformWidget`
- `SpectrumGraphWidget`
- `OscilloscopeWidget` compatibility alias
- media preview/helper functions listed in the current baseline
- waveform/audio analysis helper functions listed in the current baseline

## Out of Scope
- Major `App` responsibility extraction
- Main shell/controller decomposition
- Final move of `App` into `isrc_manager.main_window`
- Broad workflow/controller extraction from `App`
- Final compatibility-alias cleanup
- Moving existing service modules such as waveform cache, equalizer, bookmarks, or background task services unless directly required for imports

## Target Structure
Use or create:

- `isrc_manager/app_logging.py`
- `isrc_manager/application_settings_dialog.py`
- `isrc_manager/catalog_managers.py`
- `isrc_manager/licenses/dialogs.py` only if legacy license compatibility is proven necessary
- `isrc_manager/tracks/__init__.py`
- `isrc_manager/tracks/album_entry_dialog.py`
- `isrc_manager/tracks/album_ordering_dialog.py`
- `isrc_manager/tracks/edit_dialog.py`
- `isrc_manager/tracks/host_protocols.py`
- `isrc_manager/media/waveform.py`
- `isrc_manager/media/audio_visualization.py`
- `isrc_manager/media/preview_dialogs.py`

If new packages such as `isrc_manager.tracks` or `isrc_manager.licenses` are created, add them to the explicit package list in `pyproject.toml`.

## Governing Rules
- Prefer deleting dead code over relocating it
- Preserve root compatibility imports for moved live classes and root-tested helpers
- Compatibility aliases are explicitly temporary. Every alias must have a target import path, a planned removal phase, dependent runtime callers/tests listed in `compatibility_inventory.md`, and a deprecation warning or documented reason why warning is not technically safe yet.
- No compatibility alias may be added, changed, migrated, or removed unless `compatibility_inventory.md` is updated in the same phase.
- No compatibility alias may remain without a planned removal phase.
- Use host protocols instead of importing `App` into extracted dialogs
- Do not widen scope into `App` controller decomposition
- Keep extracted modules cohesive and reasonably small
- Reuse existing media infrastructure (`waveform_cache`, `equalizer`, `equalizer_player`, `bookmarks`) instead of duplicating it
- If a moved class creates a new oversized file, schedule later decomposition rather than blocking extraction

## Phases and Batches

### Phase 0 — Packaging and Compatibility Gate
**Goal**
- fix `pyproject.toml` package parity
- define root alias policy
- ensure new packages are visible to packaging/runtime
- record the current top-level class/function inventory as the migration baseline
- create `compatibility_inventory.md`
- create or initialize `architecture_metrics.md` as a planning gate record

**In scope**
- package list audit
- `__init__.py` parity
- compatibility import policy
- test import audit for root `ISRC_manager` references
- compatibility inventory fields:
  - alias source
  - alias target
  - owning phase
  - dependent runtime callers
  - dependent tests
  - deprecation warning status
  - migration target path
  - planned removal phase
  - current status: `planned`, `active`, `migrated`, or `removed`
  - notes / exception references

**Out of scope**
- moving classes

**Validation**
- packaging config includes all live packages
- `compatibility_inventory.md` exists and contains the required headings/schema before aliases are added
- every known/planned root compatibility alias has a planned removal phase or is explicitly marked planned for later inventory population before implementation
- compile/import sanity passes

### Phase 1 — Logging and Prompt Helpers
**Goal**
- move `_JsonLogFormatter`
- move any clearly standalone prompt/helper code discovered during batch if truly leaf-level

**Validation**
- logging still initializes correctly
- no runtime behavior change

### Phase 2 — Audio Visualizer Extraction
**Goal**
- move `WaveformWidget`
- move `SpectrumGraphWidget`, `OscilloscopeWidget`, and `StereoPeakMeterWidget`
- move `load_wav_peaks()`
- move `load_audio_harmonic_frames()`, `load_audio_peak_meter_frames()`, and `load_audio_spectrum_frames()`
- preserve root compatibility aliases for tests and callers

**Validation**
- focused media/widget tests
- audio frame loader tests from `tests/app/_app_shell_support.py`
- compile/import sanity

### Phase 3 — Media Preview Dialogs
**Goal**
- move `_ImagePreviewDialog`
- move `_HiDpiArtworkLabel`
- move `_AudioPreviewDialog`
- move audio preview preload/result classes and helper functions with the dialog
- add `MediaPreviewHost` seam if needed
- keep integration with existing waveform cache, equalizer player, bookmarks, artwork export, queue, and navigation behavior
- enforce media architecture separation:
  - visualization
  - preparation/preload
  - playback
  - export

**Rule**
- no single media module may own all four media responsibilities
- media preview extraction must not become a new media platform monolith
- existing media infrastructure must be reused rather than duplicated

**Validation**
- preview dialogs still open/function
- navigation/export callbacks still behave
- media-player UI workflow tests still pass
- media responsibility boundaries are documented in the phase handoff

### Phase 4 — Live Catalog Manager Panels
**Goal**
- move catalog manager pane/panel classes that are actually live
- decide whether `CatalogManagersPanel` should remain a workspace dock implementation, be folded into diagnostics cleanup, or be deleted after call-site audit

**Validation**
- catalog manager or diagnostics cleanup surfaces still open
- admin actions still function

### Phase 5 — Dead Catalog Dialog Audit
**Goal**
- decide whether `_ManageArtistsDialog`, `_ManageAlbumsDialog`, and `CatalogManagersDialog` are dead
- account for the current redirect from `open_catalog_managers_dialog()` to diagnostics cleanup
- delete if dead
- relocate only if proven needed

**Required audit coverage**
- runtime call paths
- tests
- documentation/examples
- root compatibility imports
- command/action registries
- menu/ribbon/workspace registrations
- string-based dynamic lookups
- persisted layout/action references
- database migration references, if applicable
- external script/tool references inside the repository

Deletion is allowed only when the audit confirms no live or compatibility need. If a compatibility
need exists, quarantine is allowed only when safe and justified.

**Validation**
- no live call path broken
- audit documented in handoff

### Phase 6 — Legacy License UI Decision Gate
**Goal**
- audit `LicenseUploadDialog`, `LicensesBrowserPanel`, `LicensesBrowserDialog`, `LicenseeManagerDialog`, and `_CatalogLicenseesPane`
- use the current shell tests asserting legacy license browser actions are hidden as evidence
- delete if dead
- quarantine to `licenses/dialogs.py` only if real compatibility need exists

**Required audit coverage**
- runtime call paths
- tests
- documentation/examples
- root compatibility imports
- command/action registries
- menu/ribbon/workspace registrations
- string-based dynamic lookups
- persisted layout/action references
- database migration references, if applicable
- external script/tool references inside the repository

Deletion is allowed only when the audit confirms no live or compatibility need. Broken legacy code
must not be silently preserved.

**Validation**
- audit complete
- legacy license browser remains unexposed unless a deliberate product decision reverses that
- broken legacy code is not silently preserved without reason

### Phase 7 — Settings Dialog Whole Move
**Goal**
- move `ApplicationSettingsDialog` as-is first
- preserve compatibility alias
- avoid internal decomposition in this batch except what is required to move safely

**Validation**
- settings dialog opens
- theme/settings/GS1/QSS autocomplete related tests pass

### Phase 8 — Settings Dialog Internal Health Pass
**Goal**
- reduce risk of a new mini-monolith
- account for the expanded theme builder, storage budget, app sound, and QSS autocomplete settings now wired into the dialog
- split internal tabs/panels/controllers only if still justified after extraction

**Allowed**
- split UI tabs/panels
- reduce local dialog module size
- isolate UI-only helpers

**Not allowed**
- broad settings architecture redesign
- permanent settings workflow ownership
- long-lived settings/theme/history/app-sound workflow controllers
- controller extraction that belongs to Plan 2 Phase 16
- `App` responsibility decomposition

**Validation**
- same as Phase 7
- module health improved

### Phase 9 — Album and Track Editor Host Seams
**Goal**
- introduce `AlbumEditorHost`
- introduce `TrackEditorHost`
- prepare album entry, album ordering, and track editor extraction without moving dialogs yet

**Validation**
- no runtime behavior change
- compile/tests green

### Phase 10 — Album Dialog Extraction
**Goal**
- move `_AlbumTrackSection` and `AlbumEntryDialog` together
- move `_AlbumTrackOrderingTable` and `AlbumTrackOrderingDialog` in the same album-family batch unless risk justifies a separate preliminary commit
- preserve compatibility aliases

**Validation**
- add-album / track creation workflows still function
- album track ordering workflow still functions
- host seams work

### Phase 11 — Track Editor Final Seam Check
**Goal**
- verify `TrackEditorHost` covers the currently expanded editor behavior before moving `EditDialog`
- add any missing protocol methods without moving feature workflow logic out of `App`

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

## Plan 1 Completion Gate
Plan 1 is not complete, and Plan 2 may not begin, until this gate passes:

- no non-`App` dialogs, panels, widgets, visualizers, preview dialogs, or extracted helper functions remain locally defined in `ISRC_manager.py`
- moved classes/functions import from their feature modules
- deleted legacy UI decisions are documented
- host protocols introduced during Plan 1 are documented
- `compatibility_inventory.md` is current
- every remaining root alias is inventoried, deprecated, and assigned a removal phase
- no extracted module imports `App`
- no new circular imports are introduced
- package list / `__init__.py` parity remains valid
- compile/import sanity passes
- focused UI/media/settings/editor smoke checks pass according to the relevant phase handoffs
- Plan 1 final handoff exists and records compatibility inventory status, architecture metric status, and remaining root import/test migration work

## Success Criteria
By the end of Plan 1:
- all non-`App` top-level classes are extracted or deleted
- all top-level helper functions that belong to moved dialogs/widgets are extracted with their owners
- `ISRC_manager.py` no longer contains dialogs/panels/widgets/visualizers except temporary compatibility glue
- any remaining root compatibility aliases are inventoried, deprecated, assigned a removal phase, and explicitly carried into Plan 2 cleanup
- app behavior remains unchanged
- monolith line count is materially reduced
- the only major monolith remaining is `App`

## Risks
- settings dialog may become a new mini-monolith
- media preview extraction is now much larger than the original plan because preload tasks, artwork, spectrum, peak meter, queue, and export behavior were added after planning
- track dialogs are strongly coupled to `App`
- legacy license UI may be broken and misleading
- catalog manager panel/dialog state is ambiguous because diagnostics replaced the public entry point while dock factories remain
- packaging may lag behind extracted packages
- compatibility aliases may linger too long if not tracked carefully

## Handoff Rule
At the end of Plan 1, produce a handoff that explicitly lists:
- which extracted classes/functions still rely on compatibility aliases
- compatibility inventory change status
- root alias additions/removals
- deprecated wrapper additions/removals
- which dead-code audits resulted in deletion
- which host protocols now exist
- which current root-tested imports still need follow-up test migration
- architecture boundary observations
- package parity impact
- import-cycle risk observations
- module-size / mini-monolith risk observations
- confirmation that no phase created permanent migration glue
- confirmation that each new compatibility alias has target path, deprecation policy, removal phase, and inventory entry
- what still remains inside `App`
