# Engineering Plan 2 — App Decomposition and Final Entry-Facade Reduction

## Summary
This plan deconstructs `App` by responsibility, moving workflow, controller, service, settings, diagnostics, layout, media, and catalog orchestration logic out of `ISRC_manager.py`. The goal is to reduce `ISRC_manager.py` into a thin entry facade and move the lean shell to `isrc_manager.main_window`.

This plan should only begin after the updated Plan 1 is complete.

## Current Repository Baseline
This plan was originally scaffolded on 2026-04-20 and last touched on 2026-04-27. The live codebase has changed materially since then:

- `ISRC_manager.py` is now 42,952 lines.
- `App` is still local to `ISRC_manager.py` and is now 26,541 lines.
- Plan 1 has not yet removed the remaining non-`App` classes, so Plan 2 must still wait.
- Some Plan 2-style support modules already exist and must be reused:
  - `isrc_manager/main_window_shell.py` already builds menus, the action ribbon toolbar shell, the profiles toolbar, and workspace docks.
  - `isrc_manager/catalog_table/controller.py` already owns selection, cell-target, proxy/source, and context-menu selection helpers.
  - `isrc_manager/services/profiles.py` already provides `ProfileWorkflowService`.
  - `isrc_manager/services/session.py` already provides session/database coordination primitives.
  - `isrc_manager/tasks/app_services.py` already provides `BackgroundAppServiceFactory` and `BackgroundAppServiceBundle` for worker-thread service graphs.
  - `isrc_manager/app_dialogs.py` already owns `DiagnosticsDialog`, `ApplicationStorageAdminDialog`, `ActionRibbonDialog`, and related general app dialogs.
  - `isrc_manager/update_checker.py`, `isrc_manager/update_installer.py`, and `isrc_manager/update_handoff.py` already own update primitives while `App` still orchestrates update workflow.
  - `isrc_manager/theme_builder.py` and settings transfer services already own substantial theme/settings support.
  - `isrc_manager/app_sounds.py` now owns app sound constants/normalization while `App` still wires playback.
  - `isrc_manager/media/waveform_cache.py`, `isrc_manager/media/equalizer.py`, `isrc_manager/media/equalizer_player.py`, and `isrc_manager/media/bookmarks.py` now own major media-player support.
  - `isrc_manager/isrc_registry.py` now owns application-wide ISRC registry primitives while `App` still orchestrates registration/generation UI flows.
  - `isrc_manager/promo_codes/*` now exists and adds a new feature family.
- The original target module names remain useful, but future phases must avoid creating parallel modules that duplicate these existing responsibilities.

## Mandatory Architecture Governance
The follow-up enforcement plan is a mandatory governance layer for Plan 2. Plan 2 may not begin
until the Plan 2 Entry Gate passes, and the campaign may not close until the Phase 21 zero-debt gate
passes.

Plan 2 must maintain:

- `compatibility_inventory.md`
- `architecture_metrics.md`
- phase handoffs under `phase execution handoffs/`
- `Milestones.md`

## Goals
- Split `App` by responsibility family
- Turn `App` into a temporary shell facade with delegated controllers/services
- Move the lean shell into `isrc_manager/main_window.py`
- Reduce `ISRC_manager.py` to entry/bootstrap glue
- Remove temporary compatibility aliases once no longer needed
- Reach under 10k lines in `ISRC_manager.py`, ideally far below that
- Final ideal target: under ~200 lines

## In Scope
- `App._init_services` and foreground service graph wiring
- profile/database session logic
- startup progress/loading feedback and post-ready startup tasks
- diagnostics and application storage logic
- application update check, release-notes, install, and updater-handoff logic
- theme/settings/history retention/app sound logic
- layout and action ribbon logic
- catalog workflow logic
- custom field workflow logic
- media-player, preview-host, waveform-cache orchestration, bookmark, equalizer, and audio export routing logic that remains in `App` after Plan 1
- application-wide ISRC registry/generation orchestration
- feature workflow command families
- final `App` move
- final compatibility cleanup

## Out of Scope
- Re-extracting classes already completed in Plan 1
- UI redesign
- Unrelated architectural cleanup outside monolith reduction
- New feature work
- Rewriting existing service modules when delegation is sufficient

## Target Structure
Use or create, reusing existing modules where noted:

- `isrc_manager/main_window.py`
- `isrc_manager/main_window_shell.py` (existing; split only if it remains too broad)
- `isrc_manager/app_services.py` for foreground/UI-thread service wiring
- `isrc_manager/tasks/app_services.py` (existing background-worker service factory; do not merge foreground wiring into it)
- `isrc_manager/profile_session.py`
- `isrc_manager/main_window_layout.py`
- `isrc_manager/action_ribbon.py`
- `isrc_manager/diagnostics/report.py`
- `isrc_manager/diagnostics/controller.py`
- `isrc_manager/update_controller.py`
- `isrc_manager/theme_controller.py`
- `isrc_manager/settings_controller.py`
- `isrc_manager/history_retention_controller.py`
- `isrc_manager/startup_controller.py`
- `isrc_manager/app_sound_controller.py`
- `isrc_manager/catalog_table/workflow.py`
- `isrc_manager/catalog_table/context_menu.py`
- `isrc_manager/catalog_table/media_routing.py`
- `isrc_manager/custom_fields/controller.py`
- `isrc_manager/isrc_registry_controller.py`
- `isrc_manager/media/player_controller.py`
- `isrc_manager/media/export_controller.py`
- feature-family controller modules under existing packages where appropriate, including `promo_codes`, `releases`, `works`, `exchange`, `tags`, `media`, `authenticity`, `quality`, `contract_templates`, `rights`, `assets`, `parties`, and `updates`

If new packages such as `isrc_manager.diagnostics` or `isrc_manager.custom_fields` are created, add them to the explicit package list in `pyproject.toml`.

## Governing Rules
- Move one responsibility family at a time
- Keep `App` runnable after every batch
- Prefer delegation before relocation
- Reuse existing controller/service modules before creating new abstractions
- Do not mix unrelated workflow families in one batch
- Preserve user-visible behavior
- Remove compatibility aliases only after callers/tests no longer depend on them
- Every compatibility alias is temporary, deprecated or explicitly documented as unsafe to warn yet, inventoried in `compatibility_inventory.md`, assigned a target import path, and assigned a planned removal phase.
- Any phase that creates, changes, migrates, or removes compatibility aliases must update `compatibility_inventory.md`.
- Any phase that creates new packages/modules must consider packaging visibility, dependency direction, and module-size thresholds before completion.
- Avoid replacing the root monolith with multiple oversized controller monoliths
- Keep foreground service wiring separate from `tasks.app_services` background worker wiring

## Phases and Batches

## Plan 2 Entry Gate
Plan 2 may not begin until this gate passes:

- Plan 1 Completion Gate passed
- Plan 1 final handoff exists
- `compatibility_inventory.md` exists and is current
- root import count baseline exists
- compatibility alias count baseline exists
- import-cycle baseline exists
- module LOC baseline exists
- `ISRC_manager.py` line-count baseline exists
- `App` LOC baseline exists while `App` still exists
- tests still relying on root imports are listed
- package parity status is recorded
- no Plan 2 work starts while non-`App` Plan 1 extraction remains incomplete

### Phase 13 — Foreground Service Container
**Goal**
- move `App._init_services` and related foreground service construction into a foreground container
- create `isrc_manager/app_services.py` only for UI-thread services
- keep `isrc_manager/tasks/app_services.py` focused on worker-thread service bundle recreation

**Validation**
- service initialization still works
- startup smoke tests pass
- background task tests still prove worker bundles are separate

### Phase 14 — Profile, Storage, and Session Controller
**Goal**
- move profile selection, profile CRUD, DB preparation/open/close/session activation into `profile_session.py`
- build on existing `ProfileWorkflowService` and session/database helpers
- include storage-root transition, startup profile loading, and migration prompt orchestration that currently lives in `App`

**Validation**
- profile switching and DB open/close flows still work
- storage root transition tests still pass

### Phase 15 — Diagnostics Report and Controller
**Goal**
- move diagnostics data assembly and repair/application storage flows into diagnostics modules
- keep `app_dialogs.py` as the dialog/UI home unless a separate UI extraction is justified
- move `_build_diagnostics_report`, storage audit, storage cleanup, and repair orchestration out of `App`

**Validation**
- diagnostics dialog/report/storage flows still function
- application storage admin still reports and cleans update backups/cache artifacts

### Phase 16 — Theme, Settings, History Retention, and App Sound Controllers
**Goal**
- move:
  - theme load/apply/save
  - settings current/apply logic
  - history retention and storage budget logic
  - app sound/startup sound settings and playback orchestration
- reuse `theme_builder.py`, settings transfer services, and `app_sounds.py`

**Validation**
- settings and theme tests pass
- QSS autocomplete/theme builder tests pass
- history/storage flows remain stable
- startup sound tests remain stable

### Phase 17 — Layout, Workspace Shell, and Action Ribbon Controllers
**Goal**
- move named layouts, dock state persistence, ribbon registry/configuration, and view toggle logic
- reuse existing `main_window_shell.py` as the current shell-composition module
- split `main_window_shell.py` into `main_window_layout.py` and `action_ribbon.py` only where it reduces coupling

**Validation**
- layouts restore correctly
- ribbon still behaves correctly
- shell conversion tests still pass

### Phase 18 — Catalog Workflow Controller
**Goal**
- move dataset refresh, search/filter/count/duration, context-menu orchestration, custom field control, media/blob routing, and ISRC registry/generation orchestration
- build on existing `CatalogTableController` instead of duplicating selection/cell-target logic

**Validation**
- catalog behavior unchanged
- focused catalog workflow tests pass
- ISRC registry tests remain stable

### Phase 19A — Releases and Works Workflow Controllers
**Goal**
- move release and work workflow orchestration out of `App`

**Validation**
- focused release/work tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 19B — Exchange, Master Transfer, Import, and Export Controllers
**Goal**
- move exchange, master transfer, import, and export orchestration out of `App`

**Validation**
- focused exchange/import/export tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 19C — Tags and Metadata Workflow Controllers
**Goal**
- move tag and metadata workflow orchestration out of `App`

**Validation**
- focused tag/metadata tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 19D — Media Player, Bookmarks, Equalizer, Waveform Cache Orchestration, and Audio Export Controllers
**Goal**
- move media player, media bookmark, equalizer, waveform cache orchestration, and audio export workflow logic out of `App`
- keep preview dialogs in their Plan 1 media UI modules; do not pull preview dialogs back into controller modules

**Media architecture gate**
- media responsibilities remain separated into visualization, preparation/preload, playback, and export
- no single media module owns all four responsibilities
- existing waveform cache, equalizer, equalizer player, and bookmarks infrastructure is reused rather than duplicated
- controller extraction does not become a new media platform monolith

**Validation**
- focused media-player/audio workflow tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 19E — Audio Conversion, Watermarking, Authenticity, and Provenance Controllers
**Goal**
- move audio conversion, watermarking, authenticity, and provenance orchestration out of `App`

**Validation**
- focused audio/authenticity/provenance tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 19F — Quality Workflow Controllers
**Goal**
- move quality dashboard workflow orchestration out of `App`

**Validation**
- focused quality tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 19G — Update Workflow Controller Finalization
**Goal**
- move update check, release notes, install, and updater handoff orchestration out of `App`

**Validation**
- focused update workflow tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 19H — Promo Code Workflow Controllers
**Goal**
- move promo code workflow orchestration out of `App`

**Validation**
- focused promo code workflow tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 19I — Contract Templates, Contracts, Rights, Assets, and Parties Controllers
**Goal**
- move contract template, contract, rights, asset, and party workflow orchestration out of `App`

**Rule**
- one Phase 19 subphase per Codex run unless a later planning document explicitly authorizes a combined run
- no Phase 19 subphase may become a catch-all feature migration
- each subphase must update architecture metrics and compatibility inventory if affected

**Validation**
- focused contract/right/asset/party tests pass
- architecture metrics and compatibility inventory are updated if affected

### Phase 20 — Lean App Move
**Goal**
- move lean `App` to `isrc_manager/main_window.py`
- make `ISRC_manager.py` import `App` and expose `main()`
- keep `main_window_shell.py` or split shell helpers according to the state reached by Phase 17

**Validation**
- startup entrypoint still works
- shell still launches correctly

### Phase 21 — Final Compatibility Cleanup
**Goal**
- remove temporary root aliases
- remove final dead wrappers
- reduce `ISRC_manager.py` to true entry-facade state
- migrate all tests away from root `ISRC_manager` imports
- specify CI/architecture validation rules that prevent root alias, root import, root re-export, migration wrapper, and import-cycle reintroduction

**Validation**
- broad regression rerun
- zero compatibility aliases remain in `ISRC_manager.py`
- zero deprecated root imports remain
- zero root re-exports remain, except final bootstrap imports explicitly required for startup
- zero temporary migration wrappers remain
- zero legacy test imports from `ISRC_manager` remain
- `compatibility_inventory.md` is empty or contains only historical removed entries clearly marked as `removed`
- `ISRC_manager.py` contains only bootstrap imports, `main()`, and startup glue
- any API intended to remain public has moved to a proper package-level public module, not a root compatibility alias

## Success Criteria
By the end of Plan 2:
- `App` no longer owns non-shell responsibility clusters
- `ISRC_manager.py` is under 10k lines, ideally under 200
- `ISRC_manager.py` contains only:
  - entrypoint imports
  - bootstrap glue
  - `main()`
- zero compatibility aliases
- zero deprecated root imports
- zero temporary migration wrappers
- final ideal state: no local classes in `ISRC_manager.py`

## Risks
- `App` responsibilities are now more entangled than when the plan was drafted because media player, update, storage, theme, promo code, ISRC registry, and contract-template features expanded in the monolith
- catalog workflow extraction may sprawl if not split tightly
- theme/settings/history/app sound behavior hides shared state assumptions
- media player extraction may cross Plan 1 boundaries if preview/dialog classes are not fully moved first
- feature workflow families may require many temporary shims
- campaign fatigue may lead to alias accumulation if cleanup is delayed too long

## Campaign Gates
Run broader gates at checkpoints rather than every batch:
- compile sanity
- focused touched-area tests
- grouped UI-app workflow tests
- grouped catalog/exchange/history-storage gates as relevant
- media-player/audio workflow tests after media-controller batches
- update workflow tests after update-controller batches
- architecture metrics updates:
  - `ISRC_manager.py` LOC
  - `App` LOC while it still exists
  - compatibility alias count
  - root import count
  - module LOC over warning threshold
  - module LOC over mandatory split threshold
  - import cycle count
  - package parity status
  - tests still using root imports

## Final End-State
### Intermediate acceptable state
- `ISRC_manager.py` contains entrypoint code plus a small number of temporary compatibility imports

### Final ideal state
- `ISRC_manager.py` contains only:
  - `from isrc_manager.main_window import App`
  - `main()`
  - bootstrap/run glue
- all public APIs live in package-level modules rather than root compatibility aliases
- architecture validation rules are specified to prevent compatibility debt from returning

## Final Recommendation
Implement these two plans strictly in order:

1. **Plan 1:** remove all non-`App` classes/functions and establish compatibility seams
2. **Plan 2:** decompose `App`, move the lean shell, and collapse `ISRC_manager.py` into the entry facade
