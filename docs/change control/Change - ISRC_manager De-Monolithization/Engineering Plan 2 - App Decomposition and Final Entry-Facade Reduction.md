# Engineering Plan 2 — App Decomposition and Final Entry-Facade Reduction

## Summary
This plan deconstructs `App` by responsibility, moving workflow, controller, service, settings, diagnostics, layout, and catalog orchestration logic out of `ISRC_manager.py`. The goal is to reduce `ISRC_manager.py` into a thin entry facade and move the lean shell to `isrc_manager.main_window`.

This plan should only begin after Plan 1 is complete.

## Goals
- Split `App` by responsibility family
- Turn `App` into a temporary shell facade with delegated controllers/services
- Move the lean shell into `isrc_manager/main_window.py`
- Reduce `ISRC_manager.py` to entry/bootstrap glue
- Remove temporary compatibility aliases once no longer needed
- Reach under 10k lines in `ISRC_manager.py`, ideally far below that
- Final ideal target: under ~200 lines

## In Scope
- `App._init_services` and service graph wiring
- profile/database session logic
- diagnostics and application storage logic
- application update check, release-notes, install, and updater-handoff logic
- theme/settings/history retention logic
- layout and action ribbon logic
- catalog workflow logic
- feature workflow command families
- final `App` move
- final compatibility cleanup

## Out of Scope
- Re-extracting classes already completed in Plan 1
- UI redesign
- Unrelated architectural cleanup outside monolith reduction
- New feature work

## Target Structure
Use or create:

- `isrc_manager/main_window.py`
- `isrc_manager/app_services.py`
- `isrc_manager/profile_session.py`
- `isrc_manager/main_window_layout.py`
- `isrc_manager/action_ribbon.py`
- `isrc_manager/diagnostics/report.py`
- `isrc_manager/diagnostics/controller.py`
- `isrc_manager/update_controller.py`
- `isrc_manager/theme_controller.py`
- `isrc_manager/settings_controller.py`
- `isrc_manager/history_retention_controller.py`
- `isrc_manager/catalog_table/workflow.py`
- `isrc_manager/catalog_table/context_menu.py`
- `isrc_manager/custom_fields/controller.py`

And feature-family modules under existing packages where appropriate.

## Governing Rules
- Move one responsibility family at a time
- Keep `App` runnable after every batch
- Prefer delegation before relocation
- Do not mix unrelated workflow families in one batch
- Preserve user-visible behavior
- Remove compatibility aliases only after callers/tests no longer depend on them
- Avoid replacing the root monolith with multiple oversized controller monoliths

## Phases and Batches

### Phase 13 — Foreground Service Container
**Goal**
- move `App._init_services` and related foreground service construction into `app_services.py`

**Validation**
- service initialization still works
- startup smoke tests pass

### Phase 14 — Profile and Session Controller
**Goal**
- move profile selection, profile CRUD, DB preparation/open/close/session activation into `profile_session.py`

**Validation**
- profile switching and DB open/close flows still work

### Phase 15 — Diagnostics Report and Controller
**Goal**
- move diagnostics data assembly and repair/application storage flows into diagnostics modules

**Validation**
- diagnostics dialog/report/storage flows still function
- application storage admin still reports and cleans update backups/cache artifacts

### Phase 16 — Theme, Settings, and History Retention Controllers
**Goal**
- move:
  - theme load/apply/save
  - settings current/apply logic
  - history retention and storage budget logic

**Validation**
- settings and theme tests pass
- history/storage flows remain stable

### Phase 17 — Layout and Action Ribbon Controllers
**Goal**
- move named layouts, dock state persistence, ribbon registry/configuration, and view toggle logic

**Validation**
- layouts restore correctly
- ribbon still behaves correctly

### Phase 18 — Catalog Workflow Controller
**Goal**
- move dataset refresh, search/filter/count/duration, context-menu orchestration, custom field control, media/blob routing

**Validation**
- catalog behavior unchanged
- focused catalog workflow tests pass

### Phase 19 — Feature Workflow Controllers
**Goal**
- move feature command families one package at a time:
  - releases
  - works
  - exchange
  - import/export
  - tags
  - audio
  - authenticity
  - quality
  - updates

**Rule**
- one family per run if needed
- never combine all in one batch

**Validation**
- focused feature tests per family
- campaign gates at checkpoints

### Phase 20 — Lean App Move
**Goal**
- move lean `App` to `isrc_manager/main_window.py`
- make `ISRC_manager.py` import `App` and expose `main()`

**Validation**
- startup entrypoint still works
- shell still launches correctly

### Phase 21 — Final Compatibility Cleanup
**Goal**
- remove temporary root aliases
- remove final dead wrappers
- reduce `ISRC_manager.py` to true entry-facade state

**Validation**
- broad regression rerun
- no temporary migration glue remains without purpose

## Success Criteria
By the end of Plan 2:
- `App` no longer owns non-shell responsibility clusters
- `ISRC_manager.py` is under 10k lines, ideally under 200
- `ISRC_manager.py` contains only:
  - entrypoint imports
  - bootstrap glue
  - `main()`
  - temporary compatibility aliases only if absolutely still required
- final ideal state: no local classes in `ISRC_manager.py`

## Risks
- `App` responsibilities may be more entangled than expected
- catalog workflow extraction may sprawl if not split tightly
- theme/settings/history may hide shared state assumptions
- feature workflow families may require many temporary shims
- campaign fatigue may lead to alias accumulation if cleanup is delayed too long

## Campaign Gates
Run broader gates at checkpoints rather than every batch:
- compile sanity
- focused touched-area tests
- grouped UI-app workflow tests
- grouped catalog/exchange/history-storage gates as relevant

## Final End-State
### Intermediate acceptable state
- `ISRC_manager.py` contains entrypoint code plus a small number of temporary compatibility imports

### Final ideal state
- `ISRC_manager.py` contains only:
  - `from isrc_manager.main_window import App`
  - `main()`
  - bootstrap/run glue

## Final Recommendation
Implement these two plans strictly in order:

1. **Plan 1:** remove all non-`App` classes and establish compatibility seams
2. **Plan 2:** decompose `App`, move the lean shell, and collapse `ISRC_manager.py` into the entry facade
