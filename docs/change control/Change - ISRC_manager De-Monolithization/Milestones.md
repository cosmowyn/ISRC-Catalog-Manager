# Milestones

## Pre-Implementation Plan Hardening

Completion timestamp: 2026-05-24 20:32:38 CEST
Status: Completed

Files changed:

- `Engineering Plan 1 - Non-App Class Extraction and Compatibility Stabilization.md`
- `Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- Plan 1 phase prompt markdown files
- Plan 2 phase prompt markdown files
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/Pre-Implementation Plan Hardening handoff.md`
- `Milestones.md`

Summary:

- Made architecture enforcement mandatory for Plan 1 and Plan 2.
- Made compatibility inventory mandatory from Plan 1 Phase 0.
- Added compatibility alias deprecation, migration target, inventory, and removal-phase requirements.
- Added the Plan 1 Completion Gate and Plan 2 Entry Gate.
- Hardened Plan 2 Phase 21 into a zero-debt cleanup gate.
- Split Plan 2 Phase 19 into named focused subphases.
- Strengthened dead-code deletion audits for Plan 1 Phase 5 and Phase 6.
- Added media anti-monolith gates for Plan 1 Phase 3 and Plan 2 Phase 19D.
- Clarified Plan 1 Phase 8 settings boundaries.
- Added architecture metrics tracking placeholder and handoff requirements.

Exception references:

- None.

## Exceptions

No `PRE.*` exceptions are recorded for this milestone.

## Plan 1 Phase 1 - Logging and Prompt Helpers

Completion timestamp: 2026-05-24 21:00:06 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/app_logging.py`
- `isrc_manager/app_prompts.py`
- `tests/test_app_logging.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 1 handoff.md`
- `Milestones.md`

Summary:

- Moved structured JSON trace logging formatter implementation into `isrc_manager/app_logging.py`.
- Moved standalone app prompt helper implementations into `isrc_manager/app_prompts.py`.
- Preserved required temporary root compatibility aliases.
- Added focused logging formatter coverage.
- Updated compatibility inventory and architecture metrics.

Compatibility inventory status:

- Changed; four active Phase 1 aliases were added with target paths and planned Plan 2 Phase 21 removal.

Architecture metrics status:

- Changed; Plan 1 Phase 1 metrics were recorded.

Exception references:

- None. No `P1.1.*` exceptions are recorded for this milestone.

## Plan 1 Phase 0 - Packaging and Compatibility Gate

Completion timestamp: 2026-05-24 21:08:14 CEST
Status: Completed

Files changed:

- `pyproject.toml`
- `isrc_manager/tracks/__init__.py`
- `phase0_baseline_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 0 handoff.md`
- `Milestones.md`

Summary:

- Audited package parity between tracked `isrc_manager/**/__init__.py` packages and `pyproject.toml`.
- Added the planned `isrc_manager.tracks` package scaffold and package-list entry.
- Recorded the current `ISRC_manager.py` top-level class/function baseline.
- Confirmed compatibility inventory schema and architecture metrics artifacts exist.

Compatibility inventory status:

- Unchanged by Phase 0; existing Phase 1 active aliases remain inventoried.

Architecture metrics status:

- Changed; Plan 1 Phase 0 reconciliation metrics were recorded.

Exception references:

- None. No `P1.0.*` exceptions are recorded for this milestone.

## Plan 1 Phase 1 - Ordered Reconciliation

Completion timestamp: 2026-05-24 21:09:58 CEST
Status: Completed

Files changed:

- `phase execution handoffs/P1 Phase 1 handoff.md`
- `Milestones.md`

Summary:

- Re-verified the already-applied Phase 1 logging/helper extraction after executing Phase 0.
- Confirmed Phase 1 remains scoped to logging and prompt helpers.
- Confirmed compatibility aliases and validation still pass after the Phase 0 package scaffold.

Compatibility inventory status:

- Unchanged; four active Phase 1 aliases remain inventoried.

Architecture metrics status:

- Unchanged; no new Phase 1 metrics were required beyond the existing Phase 1 metrics record.

Exception references:

- None. No `P1.1.*` exceptions are recorded for this reconciliation.

## Plan 1 Phase 2 - Audio Visualizer Extraction

Completion timestamp: 2026-05-24 21:12:40 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/media/waveform.py`
- `isrc_manager/media/audio_visualization.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 2 handoff.md`
- `Milestones.md`

Summary:

- Moved waveform widget/rendering and waveform peak loading to `isrc_manager.media.waveform`.
- Moved spectrum/peak-meter widgets and audio frame loaders to `isrc_manager.media.audio_visualization`.
- Preserved temporary root compatibility imports for current preview/test callers.

Compatibility inventory status:

- Changed; eight active Phase 2 aliases were added with target paths and planned Plan 2 Phase 21 removal.

Architecture metrics status:

- Changed; Plan 1 Phase 2 metrics were recorded.

Exception references:

- None. No `P1.2.*` exceptions are recorded for this milestone.

## Plan 1 Phase 3 - Media Preview Dialogs

Completion timestamp: 2026-05-24 21:21:44 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/media/preview_dialogs.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 3 handoff.md`
- `Milestones.md`

Summary:

- Moved image preview, artwork label, audio preview dialog, preload/result classes, and audio preview helper functions to `isrc_manager.media.preview_dialogs`.
- Preserved temporary root compatibility imports for current App construction seams and root app-shell import compatibility.
- Preserved media responsibility separation by reusing waveform/visualizer, equalizer player, waveform cache, bookmark, and App export callback infrastructure.

Compatibility inventory status:

- Changed; 19 active Phase 3 aliases were added with target paths and planned Plan 2 Phase 21 removal. Phase 2 visualizer rows were updated to reflect that preview dialogs now import target media modules directly.

Architecture metrics status:

- Changed; Plan 1 Phase 3 metrics were recorded. `isrc_manager/media/preview_dialogs.py` is above the mandatory split threshold and is documented as a tracked mini-monolith risk.

Exception references:

- None. No `P1.3.*` exceptions are recorded for this milestone.

## Plan 1 Phase 4 - Live Catalog Manager Panels

Completion timestamp: 2026-05-24 21:25:56 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/catalog_managers.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 4 handoff.md`
- `Milestones.md`

Summary:

- Moved live artist/album catalog cleanup panes and live catalog manager/diagnostics cleanup panels to `isrc_manager.catalog_managers`.
- Preserved temporary root compatibility imports for App factories, local dialog compatibility, and the remaining legacy license pane inheritance seam.
- Left `CatalogManagersDialog` and `_CatalogLicenseesPane` in `ISRC_manager.py` for the Phase 5 and Phase 6 decision gates.

Compatibility inventory status:

- Changed; five active Phase 4 aliases were added with target paths and planned Plan 2 Phase 21 removal.

Architecture metrics status:

- Changed; Plan 1 Phase 4 metrics were recorded. The new `isrc_manager/catalog_managers.py` module is below the warning threshold.

Exception references:

- None. No `P1.4.*` exceptions are recorded for this milestone.

## Plan 1 Phase 5 - Dead Catalog Dialog Audit

Completion timestamp: 2026-05-24 21:29:56 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/catalog_managers.py`
- `demo/capture_demo_screenshots.py`
- `README.md`
- `docs/README.md`
- `docs/catalog-workspace-workflows.md`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 5 handoff.md`
- `Milestones.md`

Summary:

- Completed the required dead-code audit for `_ManageArtistsDialog`, `_ManageAlbumsDialog`, and `CatalogManagersDialog`.
- Deleted all three targeted dead dialogs after confirming no live runtime, test, command/action, menu/ribbon/workspace, persisted layout/action, database migration, or remaining external script/tool need.
- Updated the demo screenshot capture and current docs to use/describe Diagnostics Catalog Cleanup instead of the deleted modal dialog.

Compatibility inventory status:

- Changed without alias count change; the Phase 4 `CatalogManagersPanel` row now records that `CatalogManagersDialog` was deleted in Phase 5.

Architecture metrics status:

- Changed; Plan 1 Phase 5 metrics were recorded.

Exception references:

- None. No `P1.5.*` exceptions are recorded for this milestone.

## Plan 1 Phase 6 - Legacy License UI Decision Gate

Completion timestamp: 2026-05-24 21:32:43 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 6 handoff.md`
- `Milestones.md`

Summary:

- Completed the required audit for `LicenseUploadDialog`, `LicensesBrowserPanel`, `LicensesBrowserDialog`, `LicenseeManagerDialog`, and `_CatalogLicenseesPane`.
- Deleted the targeted hidden legacy license UI classes after confirming no live runtime, test, documentation/example, command/action, menu/ribbon/workspace, persisted layout/action, database migration, or external script/tool need.
- Left backend license services, storage, schema, exchange, and migration code intact.

Compatibility inventory status:

- Changed without alias count change; the Phase 4 `_CatalogManagerPaneBase` row now records that `_CatalogLicenseesPane` was deleted in Phase 6.

Architecture metrics status:

- Changed; Plan 1 Phase 6 metrics were recorded.

Exception references:

- None. No `P1.6.*` exceptions are recorded for this milestone.

## Plan 1 Phase 7 - Settings Dialog Whole Move

Completion timestamp: 2026-05-24 21:37:49 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/application_settings_dialog.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 7 handoff.md`
- `Milestones.md`

Summary:

- Moved `ApplicationSettingsDialog` as a whole to `isrc_manager.application_settings_dialog`.
- Preserved the temporary root compatibility import for App and tests.
- Avoided internal settings decomposition, leaving module-health decisions for Phase 8.

Compatibility inventory status:

- Changed; one active Phase 7 alias was added with target path and planned Plan 2 Phase 21 removal.

Architecture metrics status:

- Changed; Plan 1 Phase 7 metrics were recorded. The extracted settings dialog module is above the mandatory split threshold and is explicitly carried into Phase 8.

Exception references:

- None. No `P1.7.*` exceptions are recorded for this milestone.

## Plan 1 Phase 8 - Settings Dialog Internal Health Pass

Completion timestamp: 2026-05-24 21:43:03 CEST
Status: Completed

Files changed:

- `isrc_manager/application_settings_dialog.py`
- `isrc_manager/application_settings_theme.py`
- `isrc_manager/application_settings_gs1.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 8 handoff.md`
- `Milestones.md`

Summary:

- Split UI-only theme/QSS/blob-icon settings helpers into `ApplicationSettingsThemeMixin`.
- Split UI-only GS1 template/contract option helpers into `ApplicationSettingsGs1Mixin`.
- Reduced `isrc_manager/application_settings_dialog.py` below the mandatory split threshold without introducing settings workflow controllers.

Compatibility inventory status:

- Changed without alias count change; the Phase 7 `ApplicationSettingsDialog` row now records the Phase 8 internal mixin split.

Architecture metrics status:

- Changed; Plan 1 Phase 8 metrics were recorded. Mandatory-threshold module count decreased by one.

Exception references:

- None. No `P1.8.*` exceptions are recorded for this milestone.

## Plan 1 Phase 9 - Album and Track Editor Host Seams

Completion timestamp: 2026-05-24 21:49:05 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/tracks/host_protocols.py`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 9 handoff.md`
- `Milestones.md`

Summary:

- Added `AlbumEditorHost` and `TrackEditorHost` protocols in `isrc_manager.tracks.host_protocols`.
- Updated album ordering, album entry, album track section, and edit dialog host annotations to use the new protocols.
- Preserved runtime behavior; no dialogs were moved and no App decomposition was performed.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 9.

Architecture metrics status:

- Changed; Plan 1 Phase 9 metrics were recorded. The new host protocol module is below the warning threshold.

Exception references:

- None. No `P1.9.*` exceptions are recorded for this milestone.

## Plan 1 Phase 10 - Album Dialog Extraction

Completion timestamp: 2026-05-24 21:53:59 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/tracks/album_entry_dialog.py`
- `isrc_manager/tracks/album_ordering_dialog.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 10 handoff.md`
- `Milestones.md`

Summary:

- Moved `_AlbumTrackSection` and `AlbumEntryDialog` to `isrc_manager.tracks.album_entry_dialog`.
- Moved `_AlbumTrackOrderingTable` and `AlbumTrackOrderingDialog` to `isrc_manager.tracks.album_ordering_dialog`.
- Preserved root compatibility imports for App call sites and existing tests.

Compatibility inventory status:

- Changed; four active Phase 10 aliases were added with target paths, warning status, dependent caller/test notes, and planned Plan 2 Phase 21 removal.

Architecture metrics status:

- Changed; Plan 1 Phase 10 metrics were recorded. `album_entry_dialog.py` is above the warning threshold and below the mandatory split threshold.

Exception references:

- None. No `P1.10.*` exceptions are recorded for this milestone.

## Plan 1 Phase 11 - Track Editor Final Seam Check

Completion timestamp: 2026-05-24 21:57:23 CEST
Status: Completed

Files changed:

- `isrc_manager/tracks/host_protocols.py`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 11 handoff.md`
- `Milestones.md`

Summary:

- Verified the current `EditDialog` host dependencies against `TrackEditorHost`.
- Expanded `TrackEditorHost` to include the full host surface required by current single-track and bulk-edit save flows.
- Left `EditDialog` in `ISRC_manager.py` for Phase 12.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 11.

Architecture metrics status:

- Changed; Plan 1 Phase 11 metrics were recorded. No module crossed a new threshold.

Exception references:

- None. No `P1.11.*` exceptions are recorded for this milestone.

## Plan 1 Phase 12 - Edit Dialog Extraction

Completion timestamp: 2026-05-24 21:59:34 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/tracks/edit_dialog.py`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P1 Phase 12 handoff.md`
- `Milestones.md`

Summary:

- Moved `EditDialog` to `isrc_manager.tracks.edit_dialog`.
- Preserved `ISRC_manager.EditDialog` as an inventoried temporary compatibility import.
- Confirmed the Plan 1 Completion Gate is explicitly scheduled as the next required step before Plan 2.

Compatibility inventory status:

- Changed; one active Phase 12 alias was added with target path, warning status, dependent caller/test notes, and planned Plan 2 Phase 21 removal.

Architecture metrics status:

- Changed; Plan 1 Phase 12 metrics were recorded. `edit_dialog.py` is above the warning threshold and below the mandatory split threshold.

Exception references:

- None. No `P1.12.*` exceptions are recorded for this milestone.

## Plan 1 Completion Gate and Plan 2 Entry Gate

Completion timestamp: 2026-05-24 22:06:25 CEST
Status: Completed

Files changed:

- `architecture_metrics.md`
- `phase execution handoffs/Plan 1 Completion Gate handoff.md`
- `phase execution handoffs/Plan 2 Entry Gate handoff.md`
- `Milestones.md`

Summary:

- Evaluated and passed the Plan 1 Completion Gate.
- Created the Plan 1 final handoff required before Plan 2.
- Evaluated and passed the Plan 2 Entry Gate.
- Recorded Plan 2 entry baselines for root imports, aliases, import cycles, module LOC thresholds, `ISRC_manager.py` LOC, `App` LOC, package parity, and tests still relying on root imports.

Compatibility inventory status:

- Current and unchanged by the gates. Active alias count remains 42, with all aliases assigned planned Plan 2 Phase 21 removal.

Architecture metrics status:

- Changed; the Plan 1 Completion Gate / Plan 2 Entry Baseline record was appended.

Exception references:

- None. No gate exceptions are recorded.

## Plan 2 Phase 13 - Foreground Service Container

Completion timestamp: 2026-05-24 22:10:57 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/app_services.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 13 handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.app_services` for foreground/UI-thread service construction.
- Changed `App._init_services` to delegate to `initialize_foreground_services(self)`.
- Moved foreground exchange/search/tag/quality/GS1 service construction out of `App._refresh_audio_conversion_action_states` and into `configure_foreground_exchange_services(self)`.
- Kept `isrc_manager.tasks.app_services` focused on worker-thread service bundle recreation.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 13.

Architecture metrics status:

- Changed; Plan 2 Phase 13 metrics were recorded. `ISRC_manager.py` is now 26,942 LOC and `App` is now 26,187 LOC.

Exception references:

- None. No `P2.13.*` exceptions are recorded for this milestone.

## Plan 2 Phase 14 - Profile, Storage, and Session Controller

Completion timestamp: 2026-05-24 22:17:40 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/profile_session.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 14 handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.profile_session` for profile, storage-root, and database-session orchestration.
- Changed App profile/session/storage methods into thin delegation shims.
- Moved profile selection, profile CRUD, storage-root transition, startup migration prompts, database preparation/open/close, and profile activation orchestration out of `App`.
- Preserved stable App entry points for current runtime call sites and app-shell tests.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 14. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 14 metrics were recorded. `ISRC_manager.py` is now 26,173 LOC, `App` is now 25,417 LOC, and `profile_session.py` is 945 LOC.

Exception references:

- None. No `P2.14.*` exceptions are recorded for this milestone.

## Plan 2 Phase 15 - Diagnostics Report and Controller

Completion timestamp: 2026-05-24 22:24:51 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `pyproject.toml`
- `isrc_manager/diagnostics/__init__.py`
- `isrc_manager/diagnostics/report.py`
- `isrc_manager/diagnostics/controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 15 handoff.md`
- `Milestones.md`

Summary:

- Added the `isrc_manager.diagnostics` package and registered it in package metadata.
- Moved diagnostics report and application storage audit payload assembly to `isrc_manager.diagnostics.report`.
- Moved diagnostics repair and application storage async orchestration to `isrc_manager.diagnostics.controller`.
- Preserved `DiagnosticsDialog` and `ApplicationStorageAdminDialog` in `isrc_manager.app_dialogs`.
- Preserved stable App entry points through thin delegation shims.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 15. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 15 metrics were recorded. `ISRC_manager.py` is now 24,572 LOC, `App` is now 23,814 LOC, and package parity is valid at 26/26 after adding `isrc_manager.diagnostics`.

Exception references:

- None. No `P2.15.*` exceptions are recorded for this milestone.

## Plan 2 Phase 16 - Theme, Settings, History Retention, and App Sound Controllers

Completion timestamp: 2026-05-24 22:35:32 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/app_sound_controller.py`
- `isrc_manager/theme_builder.py`
- `isrc_manager/history_retention_controller.py`
- `isrc_manager/settings_controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 16 handoff.md`
- `Milestones.md`

Summary:

- Added focused controllers for app sound, theme application, history retention/storage-budget orchestration, and settings current/apply/import/export flows.
- Changed the matching `App` methods into thin delegation shims.
- Reused the existing `theme_builder.py`, settings transfer services, and `app_sounds.py` infrastructure without moving adjacent layout, ribbon, catalog, or feature-family workflows.
- Preserved stable runtime entry points for existing UI and tests.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 16. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 16 metrics were recorded. `ISRC_manager.py` is now 23,274 LOC, `App` is now 22,513 LOC, and the four new controller modules are all below the 1,200 LOC warning threshold.

Exception references:

- None. No `P2.16.*` exceptions are recorded for this milestone.

## Plan 2 Phase 17 - Layout, Workspace Shell, and Action Ribbon Controllers

Completion timestamp: 2026-05-24 22:49:43 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/main_window_layout.py`
- `isrc_manager/action_ribbon.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 17 handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.main_window_layout` for named layout persistence, dock-state persistence, workspace layout restoration, saved layout UI hooks, and view panel visibility orchestration.
- Added `isrc_manager.action_ribbon` for action ribbon registry, configuration, persistence, context menu, profile/action ribbon visibility, and customizer orchestration.
- Changed the matching `App` methods into thin delegation shims.
- Preserved the existing `main_window_shell.py` shell-composition role and reused its current menu/toolbar/dock construction flow.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 17. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 17 metrics were recorded. `ISRC_manager.py` is now 21,317 LOC, `App` is now 20,555 LOC, and import-cycle count remains at the baseline of 3. `main_window_layout.py` is 1,579 LOC, above the warning threshold but below the mandatory split threshold.

Exception references:

- None. No `P2.17.*` exceptions are recorded for this milestone.

## Plan 2 Phase 18 - Catalog Workflow Controller

Completion timestamp: 2026-05-24 23:01:06 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/isrc_registry_controller.py`
- `isrc_manager/catalog_table/workflow.py`
- `isrc_manager/catalog_table/context_menu.py`
- `isrc_manager/catalog_table/media_routing.py`
- `isrc_manager/custom_fields/__init__.py`
- `pyproject.toml`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 18 handoff.md`
- `Milestones.md`

Summary:

- Added focused modules for catalog table workflow, catalog context-menu orchestration, catalog media/blob routing, custom-field catalog workflow, and application ISRC registry/generation orchestration.
- Changed the matching `App` methods into thin delegation shims.
- Kept `CatalogTableController` as the selection/proxy/cell-target authority.
- Added `isrc_manager.custom_fields` to the explicit package list.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 18. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 18 metrics were recorded. `ISRC_manager.py` is now 18,846 LOC, `App` is now 18,080 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.18.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19A - Releases and Works Workflow Controllers

Completion timestamp: 2026-05-24 23:15:27 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/releases/controller.py`
- `isrc_manager/works/controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19A handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.releases.controller` for Release Browser creation/opening, release choice/context helpers, release create/update/add/delete/duplicate orchestration, and browser refresh routing.
- Added `isrc_manager.works.controller` for Work Manager creation/configuration/opening, governed-track context helpers, work create/update/duplicate/link/delete orchestration, and work-scoped child-track/album routes.
- Changed the matching `App` methods into thin delegation shims.
- Executed Phase 19A only; no Phase 19B-I feature workflow controller work was started.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19A. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19A metrics were recorded. `ISRC_manager.py` is now 17,204 LOC, `App` is now 16,436 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19A.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19B - Exchange, Master Transfer, Import, and Export Controllers

Completion timestamp: 2026-05-24 23:27:36 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/exchange/controller.py`
- `isrc_manager/exchange/master_transfer_controller.py`
- `isrc_manager/exchange/repertoire_controller.py`
- `isrc_manager/exchange/repair_queue_controller.py`
- `isrc_manager/exchange/catalog_xml_controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19B handoff.md`
- `Milestones.md`

Summary:

- Added focused exchange controller modules for catalog exchange import/export, master transfer, repertoire exchange, track import repair queue, and catalog XML import/export workflows.
- Changed the matching `App` methods into thin delegation shims.
- Preserved root-patched dialog, file-dialog, message-box, and history-helper seams used by the existing app-shell tests.
- Executed Phase 19B only; no Phase 19C-I feature workflow controller work was started.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19B. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19B metrics were recorded. `ISRC_manager.py` is now 15,370 LOC, `App` is now 14,597 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19B.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19C - Tags and Metadata Workflow Controllers

Completion timestamp: 2026-05-24 23:45:22 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/tags/metadata_controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19C handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.tags.metadata_controller` for tag import, dropped-audio metadata import, catalog tag-data helpers, album metadata autofill, and embedded catalog-metadata helper orchestration.
- Changed the matching `App` methods into thin delegation shims.
- Preserved root-patched dialog, message-box, and history-helper seams used by existing app-shell tests.
- Executed Phase 19C only; audio copy export, playback, bookmarks, equalizer, waveform cache, and audio export controller work remain for Phase 19D.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19C. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19C metrics were recorded. `ISRC_manager.py` is now 14,557 LOC, `App` is now 13,783 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19C.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19D - Media Player, Bookmarks, Equalizer, Waveform Cache Orchestration, and Audio Export Controllers

Completion timestamp: 2026-05-24 23:51:41 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/media/waveform_cache_worker.py`
- `isrc_manager/media/player_controller.py`
- `isrc_manager/media/export_controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19D handoff.md`
- `Milestones.md`

Summary:

- Added waveform cache service/worker queue orchestration to `isrc_manager.media.waveform_cache_worker`.
- Added `isrc_manager.media.player_controller` for media player action icon, media player opening, preview state assembly, preview navigation, and audio/image preview opening orchestration.
- Added `isrc_manager.media.export_controller` for media file export, focused media-column export, catalog audio copy export, and tagged audio export preparation.
- Changed the matching `App` methods into thin delegation shims.
- Preserved existing preview dialogs, waveform cache service/worker, equalizer dialog/settings/player, and audio bookmark infrastructure in their established media modules.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19D. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19D metrics were recorded. `ISRC_manager.py` is now 12,862 LOC, `App` is now 12,083 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19D.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19E - Audio Conversion, Watermarking, Authenticity, and Provenance Controllers

Completion timestamp: 2026-05-24 23:56:53 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/media/conversion_controller.py`
- `isrc_manager/forensics/controller.py`
- `isrc_manager/authenticity/controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19E handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.media.conversion_controller` for template conversion export, audio conversion action state, managed derivative export, external conversion, and derivative-ledger opening orchestration.
- Added `isrc_manager.forensics.controller` for forensic watermark export and forensic watermark inspection orchestration.
- Added `isrc_manager.authenticity.controller` for audio authenticity key dialog, direct-watermark master export, provenance export, and authenticity verification orchestration.
- Changed the matching `App` methods into thin delegation shims.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19E. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19E metrics were recorded. `ISRC_manager.py` is now 11,597 LOC, `App` is now 10,815 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19E.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19F - Quality Workflow Controllers

Completion timestamp: 2026-05-24 23:59:40 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/quality/controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19F handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.quality.controller` for quality dashboard open/reuse, background scan, apply-fix, and issue-routing orchestration.
- Changed the matching `App` methods into thin delegation shims.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19F. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19F metrics were recorded. `ISRC_manager.py` is now 11,536 LOC, `App` is now 10,753 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19F.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19G - Update Workflow Controller Finalization

Completion timestamp: 2026-05-25 00:03:08 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/update_controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19G handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.update_controller` for update backup/cache handoff cleanup, startup/manual update checks, update-available prompts, release notes, update install preparation, and updater helper launch orchestration.
- Changed the matching `App` methods into thin delegation shims.
- Preserved root-patched updater-helper seams used by update UI integration tests.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19G. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19G metrics were recorded. `ISRC_manager.py` is now 11,126 LOC, `App` is now 10,342 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19G.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19H - Promo Code Workflow Controllers

Completion timestamp: 2026-05-25 00:05:49 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/promo_codes/controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19H handoff.md`
- `Milestones.md`

Summary:

- Added `isrc_manager.promo_codes.controller` for Promo Code Ledger panel factory, dock creation, open route, Bandcamp CSV import, ledger update, and panel refresh orchestration.
- Changed the matching `App` methods into thin delegation shims.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19H. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19H metrics were recorded. `ISRC_manager.py` is now 10,934 LOC, `App` is now 10,149 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19H.*` exceptions are recorded for this milestone.

## Plan 2 Phase 19I - Contract Templates, Contracts, Rights, Assets, and Parties Controllers

Completion timestamp: 2026-05-25 00:14:12 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/parties/controller.py`
- `isrc_manager/contracts/controller.py`
- `isrc_manager/contract_templates/controller.py`
- `isrc_manager/rights/controller.py`
- `isrc_manager/assets/controller.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 19I handoff.md`
- `Milestones.md`

Summary:

- Added domain-specific controllers for party workflows, contract manager workflows, contract-template workspace workflows, rights matrix workflows, and asset registry workflows.
- Changed the matching `App` methods into thin delegation shims.
- Preserved root-patched app-shell test seams through lazy root attribute lookups inside the new controllers.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 19I. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 19I metrics were recorded. `ISRC_manager.py` is now 9,780 LOC, `App` is now 8,990 LOC, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.19I.*` exceptions are recorded for this milestone.

## Plan 2 Phase 20 - Lean App Move

Completion timestamp: 2026-05-25 00:20:57 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/main_window.py`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 20 handoff.md`
- `Milestones.md`

Summary:

- Moved the current lean `App` module body to `isrc_manager/main_window.py`.
- Reduced `ISRC_manager.py` to a startup/compatibility facade that exposes `App` and keeps `main()` as the project entrypoint.
- Preserved root patch/import compatibility for Phase 21 cleanup rather than removing root aliases early.

Compatibility inventory status:

- Unchanged. No aliases were added, removed, migrated, or changed during Phase 20. Active alias count remains 42.

Architecture metrics status:

- Changed; Plan 2 Phase 20 metrics were recorded. `ISRC_manager.py` is now 56 LOC, `App` is now 8,990 LOC in `isrc_manager/main_window.py`, package parity is valid at 27/27, and import-cycle count remains at the baseline of 3.

Exception references:

- None. No `P2.20.*` exceptions are recorded for this milestone.

## Plan 2 Phase 21 - Final Compatibility Cleanup

Completion timestamp: 2026-05-25 00:57:46 CEST
Status: Completed

Files changed:

- `ISRC_manager.py`
- `isrc_manager/main_window.py`
- `isrc_manager/contract_templates/__init__.py`
- `isrc_manager/contract_templates/html_support.py`
- `isrc_manager/contract_templates/ingestion.py`
- `isrc_manager/contract_templates/errors.py`
- `isrc_manager/media/waveform_cache.py`
- `isrc_manager/media/waveform_cache_worker.py`
- `isrc_manager/tags/__init__.py`
- `isrc_manager/tags/catalog.py`
- `isrc_manager/tags/service.py`
- `isrc_manager/tags/validation.py`
- P2 controller modules with root lookup cleanup
- root-importing tests migrated to `isrc_manager.main_window`
- `compatibility_inventory.md`
- `architecture_metrics.md`
- `phase execution handoffs/P2 Phase 21 handoff.md`
- `Milestones.md`

Summary:

- Removed all temporary root compatibility aliases, root dynamic re-export behavior, root `App` re-export, and root test imports.
- Reduced `ISRC_manager.py` to the final bootstrap facade with only `main()` exported.
- Marked the compatibility inventory as historical removed-only.
- Broke the three baseline static import cycles with focused module boundaries for contract-template errors, tag validation, and waveform worker orchestration.
- Added final architecture validation rules to `architecture_metrics.md`.

Compatibility inventory status:

- Changed. Active alias count is now 0. The inventory contains only historical rows marked `removed`.

Architecture metrics status:

- Changed; Plan 2 Phase 21 metrics were recorded. `ISRC_manager.py` is now 25 LOC, `App` remains 8,990 LOC in `isrc_manager/main_window.py`, package parity is valid at 27/27, and import-cycle count is now 0.

Exception references:

- None. No `P2.21.*` exceptions are recorded for this milestone.

## QA/QC Duplication Review Closure

Completion timestamp: 2026-05-25 10:57:42 CEST
Status: Completed

Files changed:

- `final QA QC/Targeted Duplication Follow-Up Report.md`
- `final QA QC/Duplicate Code Inventory.md`
- `final QA QC/Lean Codebase Remediation Plan.md`
- `final QA QC/Architecture Metrics.md`

Summary:

- Source-code changes: `None`
- Documentation-only closure completed for two targeted duplication findings.
- Validation commands attempted:
  - `python3 -m compileall ISRC_manager.py isrc_manager` (passed)
  - `QT_QPA_PLATFORM=offscreen python3 -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600` (blocked at module import during collection, missing dependency)
- Validation limitation: full pytest could not continue due missing dependencies (`PySide6` currently missing; README/docs also note `openpyxl` as required test/runtime dependency).
- Remaining environment-readiness action: install runtime/test dependencies and rerun grouped validation.

Exception references:

- `QAQC-CLOSE.1` — Missing dependency (`PySide6`; environment-readiness blocker preventing full test completion)
- `QAQC-CLOSE.2` — Additional environment readiness follow-up for complete dependency/bootstrap verification (`openpyxl` and full test-group matrix)

## Python 3.14.4 Test Coverage Audit

Completion timestamp: 2026-05-25 11:18:00 CEST
Status: In Progress (environment-readiness blocked)

Files changed:

- `requirements.txt`
- `pyproject.toml`
- `Makefile`
- `.github/workflows/ci.yml`
- `.github/workflows/version-bump.yml`
- `.github/workflows/release-build.yml`
- `tests/test_python_314_compatibility.py`
- `docs/testing/Python_3_14_4_Test_Coverage_Audit.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/final QA QC/Targeted Duplication Follow-Up Report.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/final QA QC/Duplicate Code Inventory.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/final QA QC/Lean Codebase Remediation Plan.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/final QA QC/Architecture Metrics.md`

Summary:

- Removed legacy multi-version runtime targets from CI and test-version metadata.
- Migrated version-compatibility assertions to a strict Python `3.14.4` posture.
- Added pytest-centric test command wiring in `Makefile` and updated CI smoke test invocation.
- Confirmed environment-readiness is the current blocker for full validation and 95% coverage attainment.

Validation command results:

- `python3 --version` → `Python 3.14.4`
- `python3 -m compileall ISRC_manager.py isrc_manager tests` → passed
- `python3 -m pytest` → failed (addopts requires `pytest-cov`, not installed in environment)
- `python3 -m pytest --cov=isrc_manager --cov=ISRC_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-fail-under=95` → failed (duplicate `--cov` options in this environment due missing plugin)
- `python3 -m pytest --override-ini addopts= tests/test_python_314_compatibility.py` → failed at collection due missing dependency:
  - `ModuleNotFoundError: No module named 'PySide6'`
- `python3 -m ruff check build.py isrc_manager scripts tests` → failed (`No module named ruff`)
- `python3 -m black --check build.py isrc_manager scripts tests` → failed (`No module named black`)
- `python3 -m mypy` → failed (`No module named mypy`)

Remaining environment-readiness action:

- install exact runtime/test dependencies and rerun grouped validation:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e .[dev]
QT_QPA_PLATFORM=offscreen python3 -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600
```

- continue with `exchange-import`, `history-storage-migration`, and `ui-app-workflows` once the first group passes.

Exception references:

- `QAQC-CLOSE.1` — Missing dependency (`PySide6` / `openpyxl` in full test/runtime environments) blocked import/test collection.
- `QAQC-CLOSE.2` — Toolchain dependency gap (`ruff`, `black`, `mypy`, `pytest-cov`) blocked quality + coverage commands.
