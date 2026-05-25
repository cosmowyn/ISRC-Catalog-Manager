# AGENTS.md

## Purpose

This file defines working rules for AI coding agents, Codex sessions, and automated refactoring assistants working on **ISRC Catalog Manager / Music Catalog Manager**.

The project is a local-first PySide6 desktop application for music catalog, repertoire, rights, contracts, media, authenticity, import/export, diagnostics, history, and recovery workflows.

Agents must treat this as a serious product-grade desktop application, not as a throwaway script.

---

# Project Baseline

## Runtime

- Target Python: **3.14.4**
- Supported test/runtime target: **Python 3.14.4 only**
- GUI toolkit: **PySide6**
- Database: **SQLite**
- Local-first architecture
- Headless test mode: `QT_QPA_PLATFORM=offscreen`

Do not reintroduce legacy Python-version compatibility unless explicitly requested.

---

# Current Architecture Facts

## Root entrypoint

`ISRC_manager.py` is intentionally a thin entry facade.

Do not treat it as the active monolith.

It should remain limited to:

- importing the application entrypoint
- exposing `main()`
- CLI/script bootstrap glue

Do not add feature logic, compatibility aliases, dialogs, services, or controllers back into `ISRC_manager.py`.

## Main application shell

`isrc_manager/main_window.py` is the active GUI composition shell and application host.

It may own:

- `QMainWindow` lifecycle
- high-level GUI composition
- menus
- toolbars
- dock/widget wiring
- application startup/shutdown routing
- QAction command routing
- shared UI references

It should not grow new feature-specific business logic.

When possible, move workflow orchestration into focused controllers and keep `main_window.py` as a composition root and command router.

---

# Architectural Direction

Use this dependency direction:

```text
UI / dialogs / widgets
↓
feature controllers / workflow orchestration
↓
services / repositories
↓
domain logic / data models
```

## Preferred module responsibilities

### UI modules

May contain:

- PySide widgets
- dialog layout
- local widget behaviour
- signal wiring local to the widget/dialog

Should not contain:

- database mutation logic
- broad business rules
- import/export policy decisions
- storage migration decisions
- registry/code-generation policy

### Controllers

May contain:

- workflow orchestration
- command handling
- coordination between UI host and services
- background task submission
- user-prompt routing through narrow host interfaces

Should not contain:

- raw SQL unless explicitly part of that controller’s responsibility
- broad widget construction
- unrelated feature families
- direct imports from root `ISRC_manager`

### Services

May contain:

- persistence operations
- business operations
- validation workflows
- import/export processing
- history/storage/registry operations

Should not import Qt widgets.

### Domain modules

May contain:

- pure logic
- data models
- parsing
- normalization
- validation
- deterministic transformations

Should not import GUI code.

---

# Main Window Modularisation Rules

The main window may remain a GUI shell, but feature workflows should be extracted when they become large or independently testable.

Good extraction targets include:

- backup / restore / integrity orchestration
- storage conversion workflows
- catalog table layout/state handling
- update workflow orchestration
- settings workflow orchestration
- media playback/export orchestration
- import/export repair workflows
- diagnostics/report orchestration
- registry generation/sync orchestration

Do not create fake modularity through:

- `main_window_part1.py`
- `main_window_part2.py`
- vague `helpers.py`
- vague `utils.py`
- broad mixin dumping grounds
- giant `AppHostEverything` protocols

Use focused modules and focused protocols instead.

Example:

```python
class App(QMainWindow):
    def backup_database(self):
        self.backup_restore_controller.create_backup()
```

Preferred controller style:

```python
class BackupRestoreController:
    def __init__(self, host: BackupRestoreHost, service: DatabaseMaintenanceService):
        self.host = host
        self.service = service
```

Preferred protocol style:

```python
class BackupRestoreHost(Protocol):
    current_db_path: Path
    backups_dir: Path

    def submit_background_task(...): ...
    def show_info(...): ...
    def show_error(...): ...
    def refresh_history_actions(...): ...
```

Keep host protocols small and feature-specific.

---

# Import Rules

## Do not add new root imports

Avoid:

```python
from ISRC_manager import App
from ISRC_manager import SomeDialog
```

Prefer feature-local imports:

```python
from isrc_manager.tracks.edit_dialog import EditDialog
from isrc_manager.media.equalizer import normalize_equalizer_settings
```

## Do not make controllers import concrete App

Controllers should depend on narrow host protocols or explicit dependencies, not the full `App` class.

## Avoid circular dependencies

Before adding cross-package imports, check whether the dependency direction remains clean.

If a cycle appears, stop and refactor the boundary.

---

# Testing Rules

## Test target

All tests target Python **3.14.4**.

Do not add compatibility tests for older Python versions.

## Headless Qt

Use headless Qt for GUI-related tests:

```bash
QT_QPA_PLATFORM=offscreen
```

## Test quality

Add meaningful behavioural tests.

Do not add:

- import-only tests unless import behaviour is the feature
- shallow `is not None` tests
- tests that only exercise constructors without assertions
- broad monkeypatching that hides the actual behaviour under test

Prefer testing:

- valid inputs
- invalid inputs
- empty inputs
- malformed data
- cancellation paths
- duplicate/conflict handling
- failed IO
- database rollback/transaction behaviour
- serialization/deserialization
- migration/repair decisions
- service/controller state transitions
- user-decision branches through fake prompt services

## Coverage

Coverage is expected to be branch-aware.

Measure the real application package once via `--cov=isrc_manager`. Do not add
`--cov=ISRC_manager` or uppercase-package feature imports to satisfy coverage; that path overlaps
the same physical source tree and creates duplicate 0% coverage entries. The root `ISRC_manager.py`
entry facade may be smoke-tested separately, but feature coverage belongs to `isrc_manager`.

Do not fake coverage by:

- omitting whole packages
- adding broad `# pragma: no cover`
- deleting measured code from coverage scope
- writing superficial tests only to raise numbers

Any coverage exclusion must be narrow, justified, and documented.

---

# Required Local Bootstrap

Use the canonical bootstrap:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e .[dev]
```

`requirements-dev.txt` may exist as a compatibility shortcut, but the canonical flow is runtime install plus editable dev install.

---

# Standard Validation Commands

Run relevant checks before completing a change.

## Compile

```bash
python3 -m compileall ISRC_manager.py isrc_manager tests
```

or:

```bash
make compile
```

## Full pytest / coverage

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  --cov=isrc_manager \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=json \
  --cov-fail-under=95
```

During incremental coverage work, it is acceptable to run temporarily with:

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  --cov=isrc_manager \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=json \
  --cov-fail-under=0
```

Do not mark coverage work complete unless the required gate is met or the remaining gap is explicitly documented.

## Ruff

```bash
python3 -m ruff check build.py isrc_manager scripts tests
```

## Black

```bash
python3 -m black --check build.py isrc_manager scripts tests
```

## mypy

```bash
python3 -m mypy
```

## Grouped tests

Run affected grouped tests when touching related features:

```bash
QT_QPA_PLATFORM=offscreen python3 -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600
QT_QPA_PLATFORM=offscreen python3 -m tests.run_group exchange-import --module-timeout-seconds 120 --group-timeout-seconds 600
QT_QPA_PLATFORM=offscreen python3 -m tests.run_group history-storage-migration --module-timeout-seconds 120 --group-timeout-seconds 600
QT_QPA_PLATFORM=offscreen python3 -m tests.run_group ui-app-workflows --module-timeout-seconds 120 --group-timeout-seconds 600
```

---

# Makefile Shortcuts

The Makefile defines common QA targets.

Useful commands:

```bash
make compile
make check
make test
make coverage
make lint
make format-check
make type-check
```

Agents may use direct commands or Makefile commands, but final reports must state exactly what was run.

---

# CI Expectations

CI uses:

- Python 3.14.4
- headless Qt via `QT_QPA_PLATFORM=offscreen`
- dependency audit
- compile check
- Ruff
- Black
- mypy
- grouped test shards
- coverage artifact combination
- packaging smoke checks

Do not change CI behaviour casually.

Any CI change must preserve or improve validation strength.

---

# Documentation Expectations

When changing architecture, tests, workflows, packaging, or QA gates, update relevant documentation.

Likely locations:

```text
README.md
docs/testing/Python_3_14_4_Test_Coverage_Audit.md
docs/change control/Change - ISRC_manager De-Monolithization/
```

For architecture/refactor work, document:

- what was moved
- why the boundary was chosen
- what remains
- what tests were added
- what validation commands were run
- any known follow-up work

---

# Change Safety Rules

## General

- Keep changes focused.
- Avoid unrelated refactors.
- Do not mix broad formatting with functional changes unless explicitly requested.
- Do not introduce new features during cleanup/refactor work unless requested.
- Preserve user-visible behaviour unless fixing a documented bug.

## Production code

Production code may be changed when:

- implementing the requested feature/fix
- adding a small testability seam
- fixing a real bug discovered during tests
- removing deprecated or dead compatibility paths
- improving architecture according to the active plan

Production code should not be changed merely to make weak tests easier.

## Tests

When adding or updating tests:

- prefer feature-local imports
- avoid root `ISRC_manager` imports
- use fake hosts/services for controllers
- avoid launching the full app unless the workflow requires it
- prefer deterministic tests over timing-dependent tests
- mock file dialogs, message boxes, and external IO boundaries

---

# GUI-Specific Rules

This is a PySide6 desktop application. Do not assume GUI code can be treated like a web backend.

For UI code:

- use `QT_QPA_PLATFORM=offscreen`
- avoid screenshot tests unless explicitly required
- avoid timing-dependent sleeps
- prefer direct widget state assertions
- prefer controller/service tests for workflow logic
- mock user prompts and file pickers
- do not block tests with modal dialogs

QMessageBox, QFileDialog, QInputDialog, and long-running workers should be wrapped or patched in tests.

---

# Database and Storage Safety

Be careful with:

- SQLite schema changes
- migration logic
- history/undo/redo
- backups
- restore flows
- managed file storage
- database vs managed-file storage modes
- update handoff/backup cleanup
- import repair queues

Any change in these areas must include tests for failure and recovery paths where practical.

Never silently weaken backup, restore, or history behaviour.

---

# Media and Authenticity Safety

Be careful with:

- waveform cache
- media preview
- equalizer
- audio conversion
- metadata tagging
- authenticity manifests
- forensic watermarking
- derivative exports
- provenance sidecars

Do not merge intentionally separate systems simply because names look similar.

Known intentional separations include:

- authenticity watermarking vs forensic watermarking
- waveform cache source handles vs concrete track services

---

# Coverage Campaign Rules

The repository is moving toward high meaningful coverage.

When working on coverage:

1. Run coverage with `--cov-fail-under=0`.
2. Inspect missing lines and branches.
3. Pick compact, high-value modules first.
4. Add behavioural tests.
5. Re-run coverage.
6. Update the coverage audit document.
7. Do not mark the milestone complete unless the real threshold is met.

A good coverage improvement is one that increases confidence, not just the percentage.

---

# Preferred Workflow for Agents

For every non-trivial task:

1. Inspect the current repo state.
2. Identify the relevant modules.
3. Make a small plan.
4. Apply focused changes.
5. Add or update tests.
6. Run the narrowest relevant tests first.
7. Run broader validation as needed.
8. Update documentation if the behaviour, architecture, or workflow changed.
9. Report:
   - files changed
   - tests run
   - results
   - remaining risks
   - follow-up recommendations

Do not claim validation succeeded unless commands were actually run and passed.

---

# Final Acceptance Standards

A change is complete only when:

- the requested behaviour is implemented
- user-visible behaviour is preserved or intentionally improved
- no new root `ISRC_manager` imports are introduced
- no vague helper/mixin dumping-ground modules are introduced
- tests are meaningful
- relevant validation commands pass
- documentation is updated where needed
- remaining limitations are explicitly documented

For large refactors, partial success is acceptable only when the remaining work is documented clearly and the repository remains runnable.
