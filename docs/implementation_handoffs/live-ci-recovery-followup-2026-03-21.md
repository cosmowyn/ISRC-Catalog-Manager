# Live CI Recovery Follow-Up

Date: 2026-03-21

## Purpose

This document records the live GitHub Actions follow-up that happened after the initial CI timeout and sharding refactor.

It exists as a separate history note so future maintainers can see:

- what failed only after the earlier CI refactor landed on `main`
- which fixes were workflow-only versus test-structure fixes
- which live runs proved each fix
- what still remains worth watching

This follow-up should be read alongside:

- [ci-test-suite-decomposition.md](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/ci-test-suite-decomposition.md)
- [test-timeout-and-hang-diagnostics.md](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/test-timeout-and-hang-diagnostics.md)

## Live Failures Observed After The Timeout Refactor

After commit `e56161a` (`Enforce bounded CI test timeouts`) landed, the live `main` run `23381028368` exposed four real CI problems:

- `Tests (catalog-services / py3.10)` failed
- `Tests (catalog-services / py3.13)` failed
- `Tests (exchange-import / py3.13)` failed
- `Tests (history-storage-migration / py3.13)` failed

At that point `Tests (ui-app-workflows / py3.13)` had not yet finished, so the immediate focus was the four already-red shards.

## Root Causes Confirmed From Live CI

### 1. Qt runtime misclassification on supposed no-Qt shards

The two `catalog-services` shards and the `exchange-import` shard were all failing in real test execution because those groups still imported application code paths that reached `PySide6.QtGui`.

The concrete live import failure was:

- `ImportError: libEGL.so.1: cannot open shared object file`

The import chains varied slightly by module, but the common pattern was:

- grouped test imports reached `isrc_manager/blob_icons.py`
- `blob_icons.py` imports `PySide6.QtGui`
- the workflow had intentionally skipped Qt runtime installation for those shards

This was not a timeout problem. It was a CI shard environment classification problem.

### 2. Hidden coverage artifacts were not being uploaded

`Tests (history-storage-migration / py3.13)` passed grouped test execution but failed its artifact upload step because the workflow used:

- artifact path: `.coverage*`

GitHub Actions artifact uploads ignore hidden files by default. The live failure was:

- `No files were found with the provided path: .coverage*`

Again, this was not a test failure. It was a workflow artifact-handling bug.

### 3. The remaining real timeout was concentrated in one app-shell startup module

After the workflow-only fixes landed, live run `23381103818` showed that the first three shards were healthy and the remaining failure was in:

- `Tests (ui-app-workflows / py3.13)`

That failure came from one module-level timeout:

- `tests.app.test_app_shell_startup_and_storage`

The live timeout happened while running:

- `test_startup_status_messages_cover_real_bootstrap_phases_and_ready_boundary`

Important nuance:

- the test was not truly hanging forever
- the module was too coarse and too cumulatively expensive under covered GitHub runner execution
- the existing `300s` per-module timeout was doing its job by surfacing the real hotspot

## Fixes Applied

### Fix 1: correct shard runtime setup and coverage upload

Commit:

- `22a617e` `Fix CI shard runtime setup`

Changes:

- enabled Qt runtime installation for:
  - `catalog-services / py3.10`
  - `catalog-services / py3.13`
  - `exchange-import / py3.13`
- enabled hidden-file upload for coverage artifacts:
  - `include-hidden-files: true`

Effect:

- the three non-UI shard failures disappeared
- the history shard coverage upload issue disappeared
- the workflow then exposed the remaining real UI/startup timeout cleanly

### Fix 2: split the startup-and-storage app-shell monolith

Commit:

- `c5c28c0` `Split app-shell startup tests for CI stability`

Changes:

- removed the coarse wrapper module:
  - [test_app_shell_startup_and_storage.py](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_startup_and_storage.py)
- replaced it with three focused modules:
  - [test_app_shell_startup_core.py](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_startup_core.py)
  - [test_app_shell_storage_migration_prompts.py](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_storage_migration_prompts.py)
  - [test_app_shell_storage_root_transitions.py](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_storage_root_transitions.py)
- updated [ci_groups.py](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/ci_groups.py) to point `ui-app-workflows` at the three new modules instead of the old catch-all file

Why this was the right fix:

- it preserved the same 13 tests
- it kept the discovered suite at `402`
- it made the timeout boundary meaningful again
- it reduced the chance that one slow startup/storage concern would consume an entire module budget

This was intentionally better than simply inflating the timeout, because the repo already had a good module-level timeout policy. The problem was the module boundary, not the timeout mechanism.

## Local Validation Performed During The Follow-Up

The follow-up changes were validated locally before the second push.

Passed:

- `python3 -m tests.ci_groups ui-app-workflows --verify`
- `python3 -m black --check tests/app/test_app_shell_startup_core.py tests/app/test_app_shell_storage_migration_prompts.py tests/app/test_app_shell_storage_root_transitions.py tests/ci_groups.py`
- `python3 -m ruff check tests/app/test_app_shell_startup_core.py tests/app/test_app_shell_storage_migration_prompts.py tests/app/test_app_shell_storage_root_transitions.py tests/ci_groups.py`
- `python3 -m unittest tests.app.test_app_shell_startup_core tests.app.test_app_shell_storage_migration_prompts tests.app.test_app_shell_storage_root_transitions -v`

The high-risk shard-style covered run also passed:

- `python3 -m tests.run_group --module tests.app.test_app_shell_layout_persistence --module tests.app.test_app_shell_profiles_and_selection --module tests.app.test_app_shell_startup_core --module tests.app.test_app_shell_storage_migration_prompts --module tests.app.test_app_shell_storage_root_transitions --module-timeout-seconds 300 --group-timeout-seconds 1800 --coverage --verbosity 1`

Notable local result:

- the split startup/storage modules completed in roughly `9s`, `12s`, and `7s` respectively under that shard-style covered run

That was a strong signal that the old `test_app_shell_startup_and_storage` wrapper had become an unhealthy timeout boundary.

## Live Verification Runs

### Intermediate run after workflow-only fix

Run:

- `23381103818`

Outcome:

- `catalog-services / py3.10`: passed
- `catalog-services / py3.13`: passed
- `exchange-import / py3.13`: passed
- `history-storage-migration / py3.13`: passed
- `ui-app-workflows / py3.13`: failed

This was the run that proved the remaining issue was isolated to the app-shell startup/storage module split.

### Final green run

Run:

- `23381462296`
- URL: `https://github.com/cosmowyn/ISRC-Catalog-Manager/actions/runs/23381462296`

Outcome:

- all test shards passed
- `Coverage report` passed
- overall workflow conclusion: `success`

Notable detail:

- `Tests (ui-app-workflows / py3.13)` completed successfully in `8m35s`

This was the critical live confirmation that the split fixed the remaining real shard failure without weakening coverage.

## What This Follow-Up Proves

This sequence is important because it shows three different classes of CI problems were all present at once:

1. shard environment classification mistakes
2. artifact upload configuration mistakes
3. a legitimate timeout boundary problem in a still-too-broad app-shell startup module

The final green state came from addressing each class directly instead of treating them all as generic “timeouts.”

## Remaining Things To Watch

The live workflow is green, but these items are still worth monitoring:

- `ui-app-workflows` remains the heaviest shard by far
- future app-shell startup tests should avoid being recombined into one broad startup/storage module
- the GitHub Actions logs still show non-blocking Node 20 deprecation warnings for artifact actions

The Node warnings did not block the run and were not part of the failure sequence fixed here, but they should eventually be cleaned up in a separate maintenance pass.

## Recommendation For Future Agents

If `ui-app-workflows` regresses again:

- check the slowest module summary from `tests.run_group` first
- prefer tightening module boundaries before raising timeouts
- keep startup/status/storage tests separated by concern
- treat workflow setup failures, artifact failures, and real test timeouts as separate categories until proven otherwise

Most importantly:

- do not collapse the new startup/storage modules back into a single catch-all wrapper

That would erase the exact diagnostic boundary that made the final live failure actionable.
