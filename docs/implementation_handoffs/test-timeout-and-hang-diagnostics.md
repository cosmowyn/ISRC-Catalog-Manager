# Test Timeout And Hang Diagnostics Handoff

Date: 2026-03-21

## Original Long-Running / Hanging Pain Points

This repository had two overlapping reliability problems:

- the old full-suite CI jobs tolerated extremely long runtime before surfacing anything actionable
- the new shard layout still delegated execution to broad `unittest` commands, so a stalled module could hide inside a whole shard

The repo-aligned March 21, 2026 baseline had already shown the scale of the problem:

- `Tests (3.13)` ran for `6086.219s`
- `Tests (3.10)` ran for `6123.424s`
- `Coverage` ran for `7681.805s`

Those durations were too large for this application and too opaque for diagnosis.

The live `main` run for commit `351aa33` on March 21, 2026 exposed the next layer of issues:

- `Tests (catalog-services / py3.10)` failed in `Verify grouped test ownership`
- `Tests (catalog-services / py3.13)` failed in `Verify grouped test ownership`
- `Tests (exchange-import / py3.13)` failed in `Verify grouped test ownership`
- `Tests (history-storage-migration / py3.13)` passed verification but failed in `Run grouped tests`
- `Tests (ui-app-workflows / py3.13)` remained the clearly heavy shard

Direct job-log inspection showed that the history shard failure was not a test failure. It was:

- `mv: cannot stat '.coverage': No such file or directory`

That happened because the workflow was using coverage parallel mode while still expecting a single `.coverage` file.

## Timeout Strategy Chosen

The timeout strategy is intentionally layered and practical for `unittest`:

1. keep grouped ownership verification static and import-free
2. run grouped tests one module at a time
3. execute each module in its own subprocess
4. enforce a hard timeout inside the module subprocess with `faulthandler.dump_traceback_later(..., exit=True)`
5. enforce an outer module timeout in the parent runner
6. enforce a whole-group budget in the runner
7. keep a tighter GitHub Actions job timeout as the final safety net

This gives three useful properties:

- hangs fail fast instead of consuming an entire shard budget
- the active module is printed before each run
- Python stack traces are emitted when a module exceeds its bound

## Where Timeouts Are Enforced

### `tests/ci_groups.py`

`tests/ci_groups.py` now verifies grouped ownership statically by parsing test files with `ast` instead of importing the grouped modules.

This fixed a real CI problem:

- no-Qt shards were importing Qt-heavy modules from `ui-app-workflows` during verification
- verification itself could therefore fail before the shard even reached its own test modules

The file still enforces:

- the `402`-test baseline
- grouped count parity with discovered tests
- duplicate group assignment detection
- stale module detection
- discovered-but-ungrouped module detection

### `tests/run_module.py`

`tests/run_module.py` is the per-module execution boundary.

It:

- loads a single unittest module
- enables `faulthandler` for all threads
- arms a hard timeout for that active module only
- prints module start/end markers and elapsed time

If a module stalls, the child process exits with a traceback instead of continuing indefinitely.

### `tests/run_group.py`

`tests/run_group.py` is now the CI shard entrypoint.

It:

- resolves a shard to explicit test modules
- prints the currently running module before execution
- runs each module in a separate subprocess
- applies per-module and per-group budgets
- supports coverage mode without falling back to a monolithic coverage rerun
- prints the slowest modules in the run summary

The parent runner also has its own subprocess timeout guard, so a child that fails to exit after its own bound is still cut off.

### GitHub Actions

`.github/workflows/ci.yml` now enforces:

- `PYTHONFAULTHANDLER=1`
- `PYTHONUNBUFFERED=1`
- explicit shard budgets
- explicit job timeouts
- grouped execution only through `tests.run_group`

Current shard budgets:

- `catalog-services`: `120s/module`, `600s/group`, `15` job minutes
- `exchange-import`: `180s/module`, `900s/group`, `20` job minutes
- `history-storage-migration`: `180s/module`, `900s/group`, `20` job minutes
- `ui-app-workflows`: `300s/module`, `2400s/group`, `45` job minutes

Coverage now runs through the grouped runner as well, and CI uploads `.coverage*` instead of assuming a single `.coverage` file.

## Tests / Groups Refactored

The direct wait/stall cleanup in this pass was focused and limited to tests with real hang risk:

- `tests/qt_test_helpers.py`
- `tests/test_task_manager.py`
- `tests/test_background_app_services.py`
- `tests/test_db_access.py`
- `tests/app/_app_shell_support.py`

### `tests/qt_test_helpers.py`

Added bounded helpers:

- `pump_events(...)`
- `wait_for(...)`
- `join_thread_or_fail(...)`

These helpers make timeouts explicit and reusable instead of relying on silent `join(timeout=...)` or open-ended event pumping.

### `tests/test_task_manager.py`

Refactored away from passive event-loop waiting.

Key changes:

- use `threading.Event` for task completion
- wait with bounded polling through `wait_for(...)`
- cancel any still-running task contexts in `tearDown()`
- fail explicitly if teardown cleanup does not complete

### `tests/test_background_app_services.py`

Refactored the background bundle tests to:

- wait on explicit completion events
- cancel any still-running task contexts in `tearDown()`
- fail explicitly if cleanup threads or tasks remain active
- use `join_thread_or_fail(...)` for bounded thread shutdown

### `tests/test_db_access.py`

Refined lock-order assertions to avoid silent thread joins.

The test now:

- coordinates access with thread events
- uses bounded joins with explicit failure messages

### `tests/app/_app_shell_support.py`

This helper remains the main runtime-heavy area, but teardown is now safer:

- background tasks are cancelled before close/reopen cleanup
- teardown waits for background task shutdown with a bounded helper
- event pumping is centralized through `pump_events(...)`

The helper intentionally does not force extra visibility waits during startup anymore. An earlier attempt to do that changed UI state and caused legitimate app-shell assertions to fail, so the final version kept the cleanup improvement and removed the state-changing waits.

## Suspected Root Causes Found

The concrete root causes identified in this pass were:

- broad shard execution hid the active module and let stalls consume large budgets
- import-based grouped verification caused no-Qt shards to evaluate unrelated Qt-heavy modules
- coverage handling assumed a single `.coverage` file even though parallel mode writes `.coverage.*`
- async/background tests used passive waiting patterns that obscured real stalls
- `ui-app-workflows` repeatedly boots the full app shell and is therefore still the dominant runtime bucket

The forced-timeout probe showed one representative hot path clearly:

- when `tests.app.test_app_shell_startup_and_storage` was given a `1s` module timeout, the dumped traceback showed it inside `ISRC_manager.py` `_apply_theme` during `App()` setup

That is useful future profiling evidence, even though the module normally passes under the real `300s` limit.

## Remaining Suspicious Areas

The main suspicious area is still `ui-app-workflows`.

Measured local module runtimes in this pass were:

- `tests.app.test_app_shell_startup_and_storage`: about `102s`
- `tests.app.test_app_shell_layout_persistence`: about `57s`
- `tests.app.test_app_shell_workspace_docks`: about `32s`

That makes the shard diagnosable, but still expensive.

Other notes:

- the `Schema migration failed: boom` traceback in the startup/storage tests is expected error-path coverage, not a regression
- the March 21, 2026 live CI failures in no-Qt shards should be addressed by the static `ci_groups` verification in this pass
- the March 21, 2026 history shard failure should be addressed by the coverage artifact fix in this pass

## Validation Performed

### Group verification

Passed:

- `python3 -m tests.ci_groups catalog-services --verify`
- `python3 -m tests.ci_groups exchange-import --verify`
- `python3 -m tests.ci_groups history-storage-migration --verify`
- `python3 -m tests.ci_groups ui-app-workflows --verify`

Static grouped counts:

- discovered total: `402`
- `catalog-services`: `102`
- `exchange-import`: `80`
- `history-storage-migration`: `76`
- `ui-app-workflows`: `144`

### Refactored async / thread tests

Passed:

- `python3 -m unittest tests.test_db_access tests.test_task_manager tests.test_background_app_services -v`

### New grouped runner on real shards

Passed:

- `python3 -m tests.run_group catalog-services --verify --module-timeout-seconds 120 --group-timeout-seconds 600`
- `python3 -m tests.run_group exchange-import --verify --module-timeout-seconds 180 --group-timeout-seconds 900`
- `python3 -m tests.run_group history-storage-migration --verify --module-timeout-seconds 180 --group-timeout-seconds 900`

### Heavy app-shell modules

Passed:

- `python3 -m tests.run_group --module tests.app.test_app_shell_startup_and_storage --module-timeout-seconds 300 --group-timeout-seconds 300`
- `python3 -m tests.run_group --module tests.app.test_app_shell_layout_persistence --module tests.app.test_app_shell_workspace_docks --module-timeout-seconds 300 --group-timeout-seconds 300`

### Fail-fast timeout probe

Passed as an intentional failure check:

- `python3 -m tests.run_group --module tests.app.test_app_shell_startup_and_storage --module-timeout-seconds 1 --group-timeout-seconds 10`

Observed behavior:

- failed in about `1.27s`
- printed the active module name
- dumped a Python traceback showing where the module was executing

### Coverage mechanics

Validated:

- `python3 -m tests.run_group <group> --coverage ...` for `catalog-services`, `exchange-import`, `history-storage-migration`
- `python3 -m tests.run_group --module tests.test_task_manager --module tests.test_background_app_services --coverage ...`
- `python3 -m coverage combine`
- `python3 -m coverage report --fail-under=0`
- `python3 -m coverage xml --fail-under=0`

Important note:

- the local partial-coverage run reported `69%`, below the repo `fail-under=80`, because it intentionally did not include the full `ui-app-workflows` shard
- the coverage aggregation mechanics are confirmed, but the final threshold still needs CI confirmation with all coverage shards included

### Static gates

Passed:

- `python3 -m ruff check build.py isrc_manager tests`
- `python3 -m black --check build.py isrc_manager tests`
- `python3 -m mypy`
- `python3 -m unittest tests.test_build_requirements -v`

## Future Recommendations For Keeping Runtime Bounded

- Keep `tests.run_group` as the only CI entrypoint for grouped test shards.
- Do not reintroduce raw `python -m unittest -v "${test_modules[@]}"` shard execution.
- Do not reintroduce import-based grouped verification in `tests.ci_groups.py`.
- Treat any module that approaches its timeout budget as a refactor target, not as a reason to immediately raise the timeout.
- Keep new async tests on explicit completion events plus bounded helpers such as `wait_for(...)` and `join_thread_or_fail(...)`.
- Keep `ui-app-workflows` under observation. It is bounded now, but still heavy.
- If future profiling shows one or two repeat offenders inside `ui-app-workflows`, split that shard only along real subsystem boundaries, not arbitrary file-count balancing.
- Do not re-monolithize coverage by adding another full-suite coverage rerun on top of the shards. The grouped coverage runner is the correct direction.
