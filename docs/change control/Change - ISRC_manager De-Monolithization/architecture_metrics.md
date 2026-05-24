# Architecture Metrics

This file is the mandatory planning record for architecture metrics captured at major de-monolithization gates. Phase 0 must initialize the first gate baseline before implementation starts. Later phase handoffs must update this file when the phase changes architecture metrics or establishes a new gate baseline.

This planning-remediation pass created the required structure only; it did not implement metric scripts or CI gates.

## Required Metrics
- `ISRC_manager.py` LOC
- `App` LOC while it still exists
- compatibility alias count
- root import count
- module LOC over warning threshold
- module LOC over mandatory split threshold
- import cycle count
- package parity status
- tests still using root imports

## Thresholds
- module warning threshold: 1200 LOC
- module mandatory split threshold: 2500 LOC

## Gate Records
Add one entry per major gate:

```text
## <Gate / Phase Name> — <YYYY-MM-DD HH:MM TZ>
- ISRC_manager.py LOC:
- App LOC:
- compatibility alias count:
- root import count:
- module LOC over warning threshold:
- module LOC over mandatory split threshold:
- import cycle count:
- package parity status:
- tests still using root imports:
- notes / exceptions:
```

## Plan 1 Phase 1 — 2026-05-24 20:58 CEST
- ISRC_manager.py LOC: 42,854
- App LOC: 26,543
- compatibility alias count: 4 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 29 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 10 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 1 added modules inside existing `isrc_manager` package only
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_app_bootstrap.py`, `tests/test_theme_builder.py`, `tests/test_update_ui_integration.py`, `tests/test_migration_integration.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Phase 1 reduced `ISRC_manager.py` by moving logging and prompt helper implementations to focused modules. New modules are below warning threshold.

## Plan 1 Phase 0 — 2026-05-24 21:08 CEST
- ISRC_manager.py LOC: 42,854
- App LOC: 26,543
- compatibility alias count: 4 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 30 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: valid; 25 package entries match 25 tracked package directories
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Phase 0 reconciled package parity after the already-applied Phase 1 logging/helper changes and added the planned `isrc_manager.tracks` package scaffold.

## Plan 1 Phase 2 — 2026-05-24 21:12 CEST
- ISRC_manager.py LOC: 40,654
- App LOC: 26,543
- compatibility alias count: 12 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 30 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 2 added modules inside existing `isrc_manager.media`
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Audio visualizer widgets/loaders now live in `isrc_manager.media.waveform` and `isrc_manager.media.audio_visualization`; both extracted modules remain below the warning threshold.

## Plan 1 Phase 3 — 2026-05-24 21:21 CEST
- ISRC_manager.py LOC: 36,831
- App LOC: 26,543
- compatibility alias count: 31 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 30 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 3 added a module inside existing `isrc_manager.media`
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Media preview dialogs and preload helpers now live in `isrc_manager.media.preview_dialogs`. The new module is 3,963 LOC and is therefore above the mandatory split threshold; this is recorded as a mini-monolith risk for later media/controller decomposition. The module delegates visualization to `media.audio_visualization`/`media.waveform`, playback to `LiveEqualizerPlayer`, and export execution to existing App callbacks, so it does not own the full visualization/preload/playback/export media stack.

## Plan 1 Phase 4 — 2026-05-24 21:25 CEST
- ISRC_manager.py LOC: 36,323
- App LOC: 26,543
- compatibility alias count: 36 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 30 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 4 added a module inside the existing `isrc_manager` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Live catalog cleanup and manager panel classes now live in `isrc_manager.catalog_managers`. The extracted module is 554 LOC and below the warning threshold. `CatalogManagersDialog` and `_CatalogLicenseesPane` remain in `ISRC_manager.py` for the Phase 5/Phase 6 dead-code and legacy-license audits.

## Plan 1 Phase 5 — 2026-05-24 21:29 CEST
- ISRC_manager.py LOC: 35,988
- App LOC: 26,543
- compatibility alias count: 36 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 30 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 5 did not add or remove packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Deleted dead `_ManageArtistsDialog`, `_ManageAlbumsDialog`, and `CatalogManagersDialog` after audit. Updated demo/docs references away from the deleted modal dialog. Compatibility alias count did not change because the deleted dialogs were not inventoried aliases.

## Plan 1 Phase 6 — 2026-05-24 21:32 CEST
- ISRC_manager.py LOC: 34,740
- App LOC: 26,543
- compatibility alias count: 36 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 30 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 6 did not add or remove packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Deleted dead legacy license UI classes after audit. Backend license services, schema, exchange, storage, and migration code remain intact. Compatibility alias count did not change because the deleted license UI classes were not inventoried aliases.

## Plan 1 Phase 7 — 2026-05-24 21:37 CEST
- ISRC_manager.py LOC: 30,973
- App LOC: 26,543
- compatibility alias count: 37 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 31 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 12 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 7 added a module inside the existing `isrc_manager` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: `ApplicationSettingsDialog` now lives in `isrc_manager.application_settings_dialog`. The extracted module is 3,929 LOC and above the mandatory split threshold; this is expected for the whole-move phase and is carried into the Phase 8 internal health pass.

## Plan 1 Phase 8 — 2026-05-24 21:43 CEST
- ISRC_manager.py LOC: 30,973
- App LOC: 26,543
- compatibility alias count: 37 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 32 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 8 added support modules inside the existing `isrc_manager` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Split UI-only settings dialog helpers into `isrc_manager.application_settings_theme` and `isrc_manager.application_settings_gs1`. `application_settings_dialog.py` is now 1,892 LOC, `application_settings_theme.py` is 1,688 LOC, and `application_settings_gs1.py` is 422 LOC. The mandatory split count decreased by one; the warning count increased because the former single mandatory-threshold module is now two warning-threshold modules.

## Plan 1 Phase 9 — 2026-05-24 21:49 CEST
- ISRC_manager.py LOC: 30,981
- App LOC: 26,543
- compatibility alias count: 37 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 32 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 9 added `isrc_manager.tracks.host_protocols` inside the existing `isrc_manager.tracks` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Added album and track editor host protocols only. No dialog moved and no compatibility alias changed. The new protocol module is 72 LOC and below the warning threshold.

## Plan 1 Phase 10 — 2026-05-24 21:53 CEST
- ISRC_manager.py LOC: 29,443
- App LOC: 26,541
- compatibility alias count: 41 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 33 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 10 added modules inside the existing `isrc_manager.tracks` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Moved album entry and album ordering dialog classes to `isrc_manager.tracks.album_entry_dialog` and `isrc_manager.tracks.album_ordering_dialog`. `album_entry_dialog.py` is 1,374 LOC and above the warning threshold but below the mandatory split threshold; `album_ordering_dialog.py` is 251 LOC.

## Plan 1 Phase 11 — 2026-05-24 21:57 CEST
- ISRC_manager.py LOC: 29,443
- App LOC: 26,541
- compatibility alias count: 41 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 33 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 11 only updated `isrc_manager.tracks.host_protocols`
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Expanded `TrackEditorHost` to cover the full current `EditDialog` host surface, including save-flow host calls made through `parentWidget()`. No dialog moved and no compatibility alias changed.

## Plan 1 Phase 12 — 2026-05-24 21:59 CEST
- ISRC_manager.py LOC: 27,292
- App LOC: 26,541
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 34 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: not measured; no import-cycle checker is implemented yet
- package parity status: unchanged; Phase 12 added `isrc_manager.tracks.edit_dialog` inside the existing `isrc_manager.tracks` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Moved `EditDialog` to `isrc_manager.tracks.edit_dialog` and preserved `ISRC_manager.EditDialog` as an inventoried temporary alias. `edit_dialog.py` is 2,206 LOC and above the warning threshold but below the mandatory split threshold.

## Plan 1 Completion Gate / Plan 2 Entry Baseline — 2026-05-24 22:06 CEST
- ISRC_manager.py LOC: 27,292
- App LOC: 26,541
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 34 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by an AST import graph baseline
- package parity status: valid; 25 pyproject packages match 25 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Plan 1 Completion Gate passed and Plan 2 Entry Gate baselines were recorded. Static import-cycle components: `isrc_manager.media.waveform_cache` <-> `isrc_manager.services.tracks`; `isrc_manager.contract_templates.html_support` <-> `isrc_manager.contract_templates.ingestion`; `isrc_manager.tags.catalog` <-> `isrc_manager.tags.service`.

## Plan 2 Phase 13 — 2026-05-24 22:10 CEST
- ISRC_manager.py LOC: 26,942
- App LOC: 26,187
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 34 modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; Phase 13 added a module inside the existing `isrc_manager` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Foreground/UI-thread service construction now lives in `isrc_manager.app_services`. Worker-thread service bundle wiring remains in `isrc_manager.tasks.app_services`. Import-cycle component count did not increase.

## Plan 2 Phase 14 — 2026-05-24 22:17 CEST
- ISRC_manager.py LOC: 26,173
- App LOC: 25,417
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 34 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; Phase 14 added a module inside the existing `isrc_manager` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Profile selection, profile CRUD, storage-root transition, database preparation/open/close, and profile activation orchestration now live in `isrc_manager.profile_session`. `profile_session.py` is 945 LOC and below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 15 — 2026-05-24 22:24 CEST
- ISRC_manager.py LOC: 24,572
- App LOC: 23,814
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 34 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: changed and valid; 26 pyproject packages match 26 filesystem packages after adding `isrc_manager.diagnostics`
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Diagnostics report assembly now lives in `isrc_manager.diagnostics.report`; diagnostics repair and application-storage async orchestration now live in `isrc_manager.diagnostics.controller`. `diagnostics/report.py` is 1,195 LOC and `diagnostics/controller.py` is 704 LOC, both below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 16 — 2026-05-24 22:35 CEST
- ISRC_manager.py LOC: 23,274
- App LOC: 22,513
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 34 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; Phase 16 added modules inside the existing `isrc_manager` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Theme load/apply/save logic now lives in `isrc_manager.theme_controller`; settings current/apply/import/export logic now lives in `isrc_manager.settings_controller`; history retention and storage-budget orchestration now lives in `isrc_manager.history_retention_controller`; app sound/startup sound orchestration now lives in `isrc_manager.app_sound_controller`. New module sizes are 206 LOC, 400 LOC, 445 LOC, and 858 LOC respectively, all below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 17 — 2026-05-24 22:49 CEST
- ISRC_manager.py LOC: 21,317
- App LOC: 20,555
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; Phase 17 added modules inside the existing `isrc_manager` package
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Named layout persistence, dock-state persistence, workspace layout restore, and view panel visibility orchestration now live in `isrc_manager.main_window_layout`. Action ribbon registry, configuration, persistence, context menu, and customizer orchestration now live in `isrc_manager.action_ribbon`. `main_window_layout.py` is 1,579 LOC and above the warning threshold but below the mandatory split threshold; this is recorded as a module-size risk for later shell cleanup. `action_ribbon.py` is 862 LOC and below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 18 — 2026-05-24 23:01 CEST
- ISRC_manager.py LOC: 18,846
- App LOC: 18,080
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: changed and valid; 27 pyproject packages match 27 filesystem packages after adding `isrc_manager.custom_fields`
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Catalog dataset refresh/search/count/duration orchestration now lives in `isrc_manager.catalog_table.workflow`; catalog context-menu orchestration now lives in `isrc_manager.catalog_table.context_menu`; catalog media/blob routing and standard-media helpers now live in `isrc_manager.catalog_table.media_routing`; custom-field catalog workflow now lives in `isrc_manager.custom_fields.controller`; application ISRC registry/generation orchestration now lives in `isrc_manager.isrc_registry_controller`. New Phase 18 module sizes are 1,142 LOC, 463 LOC, 566 LOC, 436 LOC, and 359 LOC respectively; `workflow.py` is below but near the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 19A — 2026-05-24 23:15 CEST
- ISRC_manager.py LOC: 17,204
- App LOC: 16,436
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Release Browser orchestration now lives in `isrc_manager.releases.controller`; Work Manager and governed-track workflow orchestration now lives in `isrc_manager.works.controller`. New Phase 19A module sizes are 864 LOC and 1,042 LOC respectively, both below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 19B — 2026-05-24 23:27 CEST
- ISRC_manager.py LOC: 15,370
- App LOC: 14,597
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Core catalog exchange import/export orchestration now lives in `isrc_manager.exchange.controller`; master transfer orchestration now lives in `isrc_manager.exchange.master_transfer_controller`; repertoire exchange orchestration now lives in `isrc_manager.exchange.repertoire_controller`; track import repair queue orchestration now lives in `isrc_manager.exchange.repair_queue_controller`; catalog XML import/export orchestration now lives in `isrc_manager.exchange.catalog_xml_controller`. New Phase 19B module sizes are 695 LOC, 598 LOC, 380 LOC, 219 LOC, and 187 LOC respectively, all below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 19C — 2026-05-24 23:45 CEST
- ISRC_manager.py LOC: 14,557
- App LOC: 13,783
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Tag import, dropped-audio metadata import, catalog tag-data helpers, album metadata autofill, and embedded catalog-metadata helper orchestration now live in `isrc_manager.tags.metadata_controller`. The new controller is 905 LOC and below the warning threshold. Audio copy export and playback/media orchestration remain for Phase 19D to preserve the media architecture split. Import-cycle component count did not increase.

## Plan 2 Phase 19D — 2026-05-24 23:51 CEST
- ISRC_manager.py LOC: 12,862
- App LOC: 12,083
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Waveform cache orchestration now lives in `isrc_manager.media.waveform_cache_controller`; media player and preview-opening orchestration now lives in `isrc_manager.media.player_controller`; media and catalog audio export orchestration now lives in `isrc_manager.media.export_controller`. New module sizes are 132 LOC, 668 LOC, and 1,175 LOC respectively, all below the warning threshold. Existing visualization, preview/preload, equalizer player, equalizer dialog/settings, bookmark, and waveform cache infrastructure remains reused in the established media modules. Import-cycle component count did not increase.

## Plan 2 Phase 19E — 2026-05-24 23:56 CEST
- ISRC_manager.py LOC: 11,597
- App LOC: 10,815
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Audio conversion and managed derivative export orchestration now lives in `isrc_manager.media.conversion_controller`; forensic watermark export/inspection orchestration now lives in `isrc_manager.forensics.controller`; audio authenticity key/export/provenance/verification orchestration now lives in `isrc_manager.authenticity.controller`. New module sizes are 658 LOC, 258 LOC, and 524 LOC respectively, all below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 19F — 2026-05-24 23:59 CEST
- ISRC_manager.py LOC: 11,536
- App LOC: 10,753
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Quality dashboard open/reuse, background scan, apply-fix, and issue-routing orchestration now lives in `isrc_manager.quality.controller`. The new controller is 97 LOC and below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 19G — 2026-05-25 00:03 CEST
- ISRC_manager.py LOC: 11,126
- App LOC: 10,342
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Update backup/cache handoff, startup/manual update checks, update-available prompts, release notes, install preparation, and helper launch orchestration now live in `isrc_manager.update_controller`. The new controller is 596 LOC and below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 19H — 2026-05-25 00:05 CEST
- ISRC_manager.py LOC: 10,934
- App LOC: 10,149
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Promo Code Ledger panel/dock creation, opening, Bandcamp CSV import, ledger update, and panel refresh orchestration now lives in `isrc_manager.promo_codes.controller`. The new controller is 242 LOC and below the warning threshold. Import-cycle component count did not increase.

## Plan 2 Phase 19I — 2026-05-25 00:14 CEST
- ISRC_manager.py LOC: 9,780
- App LOC: 8,990
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: Party manager, owner-party bootstrap, party exchange import/export, artist-party choice helpers, and owner-registration redirection now live in `isrc_manager.parties.controller`; contract manager history operations now live in `isrc_manager.contracts.controller`; contract-template workspace orchestration now lives in `isrc_manager.contract_templates.controller`; rights matrix orchestration now lives in `isrc_manager.rights.controller`; asset registry orchestration now lives in `isrc_manager.assets.controller`. New controller sizes are 1,141 LOC, 125 LOC, 63 LOC, 56 LOC, and 56 LOC respectively; only the party controller is near the warning threshold and remains under it. Import-cycle component count did not increase.

## Plan 2 Phase 20 — 2026-05-25 00:20 CEST
- ISRC_manager.py LOC: 56
- App LOC: 8,990 in `isrc_manager/main_window.py`
- compatibility alias count: 42 active entries in `compatibility_inventory.md`
- root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 37 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 13 package modules at or above 2,500 LOC
- import cycle count: 3 static `isrc_manager` import-cycle components detected by the same AST import graph baseline
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: `tests/test_history_budget_hooks.py`, `tests/test_qss_autocomplete.py`, `tests/test_shortcut_ordering.py`, `tests/test_update_ui_integration.py`, `tests/test_app_bootstrap.py`, `tests/test_migration_integration.py`, `tests/test_theme_builder.py`, `tests/app/_app_shell_support.py`
- notes / exceptions: The lean `App` body moved from `ISRC_manager.py` to `isrc_manager/main_window.py`; `ISRC_manager.py` is now a 56-line entry facade that keeps temporary root re-exports and the root `main()` patch seam for Phase 20 compatibility. `isrc_manager/main_window.py` is intentionally above the mandatory split threshold at 9,781 LOC because Phase 20 moves the lean shell as-is; Phase 21 must remove the remaining root facade aliases and wrappers before final completion. Import-cycle component count did not increase.

## Plan 2 Phase 21 — 2026-05-25 00:57 CEST
- ISRC_manager.py LOC: 25
- App LOC: 8,990 in `isrc_manager/main_window.py`
- compatibility alias count: 0 active entries; `compatibility_inventory.md` contains only historical rows marked `removed`
- root import count: 0 Python test imports; 0 `isrc_manager` package imports detected
- module LOC over warning threshold: 36 package modules at or above 1,200 LOC
- module LOC over mandatory split threshold: 12 package modules at or above 2,500 LOC
- import cycle count: 0 static `isrc_manager` import-cycle components detected by the AST import graph scan
- package parity status: unchanged and valid; 27 pyproject packages match 27 filesystem packages
- tests still using root imports: None
- notes / exceptions: Final root compatibility cleanup removed the temporary root facade aliases, root dynamic re-export behavior, root `App` re-export, root-patched test imports, and root `ISRC_manager` dynamic lookups. `ISRC_manager.py` now contains only bootstrap imports, `main()`, and `sys.exit(main())` startup glue. The previous three static import cycles were removed by introducing `contract_templates.errors`, `tags.validation`, and `media.waveform_cache_worker` boundaries. `isrc_manager/main_window.py` remains above the mandatory split threshold and keeps the inherited file-level Ruff suppression from the moved lean shell; this is not a root compatibility alias but remains a future shell-size cleanup risk.

## Final Architecture Validation Rules
- Root import and alias prevention: fail validation if `tests`, `isrc_manager`, or `ISRC_manager.py` contain root `from ISRC_manager` / `import ISRC_manager`, `sys.modules.get("ISRC_manager")`, `_DEPRECATED_ROOT_COMPATIBILITY_IMPORTS`, `globals().update`, Phase 20 compatibility comments, root dynamic re-export loops, or `__all__ = ["App", ...]`.
- Compatibility inventory prevention: fail validation if `compatibility_inventory.md` contains any row with current status `active`, `planned`, or `migrated`; final-state inventory rows must be historical `removed` entries only.
- Root facade prevention: fail validation if `ISRC_manager.py` contains anything beyond the file header, `from __future__ import annotations`, `import sys`, the bootstrap import of `isrc_manager.main_window.main`, `__all__ = ["main"]`, `main()`, and `sys.exit(main())`.
- Import-cycle prevention: fail validation unless the AST import graph scan reports `0` static `isrc_manager` import-cycle components.
- Package parity prevention: fail validation unless pyproject package entries and filesystem package directories both report 27 packages with no missing or extra entries.
- Test migration prevention: fail validation if any Python test imports the root module as code rather than referring to `ISRC_manager.py` as the entry script filename.
- Baseline validation commands: run compileall, Ruff, packaged smoke, and the broad offscreen pytest suite before accepting final cleanup.
- Future CI implementation should automate these checks without reintroducing compatibility aliases or root import shims.

## CI / Tooling Notes
Future implementation may add scripts or CI checks to collect or enforce these metrics. Phase 21 specifies the final architecture validation rules above; they are documented here but are not yet implemented as CI/build configuration.
