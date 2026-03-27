# Truthful Startup / Profile Progress Reporting

## Previous Fake Milestone Model Found

Startup and profile loading were still anchored to hardcoded `StartupPhase` percentages:

- `RESTORING_WORKSPACE = 95`
- `LOADING_CATALOG = 98`
- `READY = 100`

That meant the splash could sit near the end while the actual long-running work was still happening inside:

- workspace restoration
- catalog dataset loading
- catalog UI apply/finalization
- profile database preparation/open

The old controller also mapped `set_phase(...)` directly to percent, so progress was phase-based rather than work-based.

## Real Startup / Profile Tasks Identified

### Startup

1. resolve storage layout
2. initialize settings and identity
3. select/open the startup profile
4. prepare the profile database
5. open the live database and load services
6. finalize the main shell
7. restore workspace layout
8. load catalog dataset
9. apply catalog dataset to the UI and finalize readiness

### Profile Switch

1. select/open the target profile
2. prepare the profile database
3. open the live database and load services
4. rebuild headers/profile selectors
5. load catalog dataset
6. apply catalog dataset to the UI and finalize readiness

## Long-Running Tasks Broken Into Real Substeps

### Database Preparation

- open database session
- initialize required tables
- run schema migrations/checks
- close session and mark prepared

### Workspace Restore

- restore main window geometry
- restore saved dock layout
- apply saved workspace visibility
- refresh dock placement defaults
- materialize visible lazy dock panels one by one
- persist restored visibility state
- queue geometry/dock-state saves

### Catalog Worker Load

- load active custom fields
- inspect Work schema columns
- load catalog track rows
- load custom-field values
- load Artist lookup values
- load Album lookup values
- load UPC lookup values
- load Genre lookup values
- load catalog-number lookup values
- finalize the dataset payload

### Catalog UI Apply

- rebuild headers
- populate catalog rows in batches
- apply lookup values
- resize columns
- update count/duration
- recompute blob/media badges in batches
- restore saved header/view state
- restore focus/profile selection/sort
- refresh generated fields and history state

## New Total-Progress Model

The old phase-percent model was replaced with a shared weighted task/subtask tracker in:

- `isrc_manager/startup_progress.py`

The new model:

- keeps the existing `StartupPhase` names as task labels
- assigns weighted ranges to real task groups
- lets each long-running task report internal completion using local substeps
- keeps progress monotonic
- caps non-terminal phases below `100`
- only reaches `100` through explicit terminal completion

Startup uses one tracker bound to the existing startup feedback controller.
Profile switching creates the same tracker type for the runtime loading feedback.

## How Current Task Reporting Now Works

- `set_phase(...)` is now status-only and no longer drives fake percent jumps.
- `report_progress(...)` on the splash controller carries the real percent.
- startup/profile code now reports:
  - discrete completed startup tasks
  - database-prepare substeps
  - open-database substeps
  - workspace-restore substeps
  - catalog worker progress
  - catalog UI-apply progress

For catalog loading specifically:

- worker-side dataset build reports real progress
- UI-side apply/finalization reports real progress before readiness/completion
- row application and blob-badge recomputation now update in batches so the splash continues moving during the heavy UI tail

## How 100% Correctness Is Enforced

- `StartupSplashController.finish()` now forces `100`, not `int(StartupPhase.READY)`.
- `StartupProgressTracker` clamps non-ready phases below `100`.
- startup only finishes after:
  - workspace restore is complete
  - catalog refresh has reached terminal UI-applied completion
- profile loading only finishes after:
  - database prep is complete
  - `open_database()` is complete
  - catalog refresh has reached terminal UI-applied completion

This means the splash/loading feedback can no longer hit `100%` while the long-running startup/profile work is still unfinished.

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/startup_progress.py`
- `isrc_manager/startup_splash.py`
- `isrc_manager/services/catalog_reads.py`
- `tests/test_startup_splash.py`
- `tests/test_app_bootstrap.py`
- `tests/app/_app_shell_support.py`
- `docs/implementation_handoffs/truthful-startup-profile-progress-reporting.md`

## Tests Added / Updated

- updated startup splash controller tests for:
  - real `100` on finish
  - suspend/resume preserving reported progress
  - monotonic `report_progress(...)`
- updated app-shell startup/profile loading tests for:
  - ordered real task boundaries instead of fixed milestone tails
  - monotonic progress updates
  - readiness/finish only after real completion

Validation run:

- `python3 -m unittest tests.test_startup_splash tests.test_app_bootstrap`
- `python3 -m unittest tests.app.test_app_shell_startup_core tests.app.test_app_shell_profiles_and_selection`
- `python3 -m unittest tests.app.test_app_shell_workspace_docks`
- `python3 -m black --check ISRC_manager.py isrc_manager/startup_progress.py isrc_manager/startup_splash.py isrc_manager/services/catalog_reads.py tests/test_startup_splash.py tests/app/_app_shell_support.py tests/test_app_bootstrap.py`

## Remaining Limitations / Next Bottlenecks

- The catalog row query itself is still one SQL fetch step; progress advances before and after that real query, but not during SQLite execution.
- `_init_services()` is still reported as one bounded service-load step even though some internal probes may be expensive.
- The splash now stays truthful through the long visible tail, but the next candidate for finer breakdown would be deeper service initialization if that becomes the new bottleneck.
