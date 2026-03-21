# CI Test Suite Decomposition Handoff

Date: 2026-03-21

## Status

This handoff documents the implemented CI and test-suite decomposition pass for the repository baseline at commit `cfed199`.

The goals of this pass were met in a narrowly scoped way:

- the active `Black format check` red gate was cleared without broad formatting churn
- the worst monolithic test modules were split into subsystem-focused files
- shard ownership moved into `tests/ci_groups.py` as an explicit source of truth
- the old duplicate full-suite coverage rerun was removed in favor of shard-based aggregation
- the full discovered suite remains at `402` tests
- one intentionally broad `ui-app-workflows` shard remains to preserve cross-subsystem app-shell coverage

This pass deliberately stopped short of moving every companion test into a subpackage. The main monoliths were decomposed first, then CI grouping and validation were rebuilt around the new taxonomy.

## Original CI Pain Points

The repository’s CI shape had three core problems:

1. one giant `unittest discover` run was used for both Python test jobs
2. the coverage job reran the entire suite again under instrumentation
3. failures landed in large catch-all buckets, so the job name rarely identified the subsystem at fault

The baseline evidence came from the March 21, 2026 run and attached logs:

- `Tests (3.13)` ran `402` tests in `6086.219s`
- `Tests (3.10)` ran `402` tests in `6123.424s`
- `Coverage` ran `402` tests in `7681.805s`

That made the suite both slow and opaque. Even when it passed, a real regression would have been hard to localize because a single test failure was hidden inside a full-suite dot stream.

## Confirmed CI Findings

The current repo-aligned evidence points to two separate truths:

- the active red gate in the baseline run was `Black format check`
- the broader CI reliability issue was runtime and diagnosability, not a confirmed failing test suite

The `Schema migration failed: boom` trace in the test logs is expected coverage of an error path in `tests/test_app_shell_integration.py`, not a failing assertion. The repeated Qt offscreen `propagateSizeHints()` lines are also noise, not the root cause.

The actual structural issue was the CI layout in [`.github/workflows/ci.yml`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/.github/workflows/ci.yml), which ran the same full suite repeatedly instead of separating responsibilities. The March 21, 2026 run confirmed:

- the current failure was formatting, not a broken test suite
- the repeat full-suite execution across `Tests (3.10)`, `Tests (3.13)`, and `Coverage` was the main reliability and diagnosability problem
- the suite needed shard boundaries that map to subsystems, not one monolithic `discover` bucket

## Monolithic Test Areas Before Refactor

The worst monoliths were not just large; they crossed subsystem boundaries in ways that made failures hard to interpret.

- legacy `tests/test_app_shell_integration.py`: startup, storage migration, profiles, selection, workspace docks, layout persistence, editors, and GS1 dialog surfaces in one class
- legacy `tests/test_exchange_service.py`: JSON, CSV, XLSX, package round-trips, merge behavior, normalization, and custom-field mapping in one class
- legacy `tests/test_history_manager.py`: settings undo/redo, snapshots, file effects, recovery repair, and helper rollback behavior in one class
- legacy `tests/test_contract_rights_asset_services.py`: contracts, rights, assets, and dialog validation in one class
- legacy `tests/test_search_and_repertoire_exchange.py`: search relationships and repertoire exchange in one class
- legacy `tests/test_schema_service.py`: current schema checks and multiple migration eras in one class

These files were the first decomposition targets because a failure in any one of them gave almost no signal about which subsystem had regressed.

## New Test Structure Introduced

The new structure is taxonomy-driven rather than file-count-driven.

New packages introduced:

- `tests/app/`
- `tests/exchange/`
- `tests/history/`
- `tests/database/`
- `tests/catalog/`
- `tests/integration/`

Shared support modules were added to keep the split low-churn while preserving assertion intent:

- `tests/app/_app_shell_support.py`
- `tests/exchange/_support.py`
- `tests/exchange/_repertoire_exchange_support.py`
- `tests/history/_support.py`
- `tests/database/_schema_support.py`
- `tests/catalog/_contract_rights_asset_support.py`

The support modules hold the shared setup and `case_*` implementations. Focused wrapper modules expose the real `test_*` methods for discovery, which keeps the discovered count stable while making failure locations far more specific.

Implemented focused modules:

- app shell:
  - `tests/app/test_app_shell_startup_and_storage.py`
  - `tests/app/test_app_shell_profiles_and_selection.py`
  - `tests/app/test_app_shell_workspace_docks.py`
  - `tests/app/test_app_shell_layout_persistence.py`
  - `tests/app/test_app_shell_editor_surfaces.py`
- exchange:
  - `tests/exchange/test_exchange_json.py`
  - `tests/exchange/test_exchange_package.py`
  - `tests/exchange/test_exchange_csv_inspection.py`
  - `tests/exchange/test_exchange_csv_import.py`
  - `tests/exchange/test_exchange_xlsx_import.py`
  - `tests/exchange/test_exchange_normalization.py`
  - `tests/exchange/test_exchange_merge_mode.py`
  - `tests/exchange/test_exchange_custom_fields.py`
  - `tests/exchange/test_repertoire_exchange_service.py`
- history:
  - `tests/history/test_history_settings.py`
  - `tests/history/test_history_tracks.py`
  - `tests/history/test_history_snapshots.py`
  - `tests/history/test_history_file_effects.py`
  - `tests/history/test_history_recovery.py`
  - `tests/history/test_history_action_helpers.py`
- catalog:
  - `tests/catalog/test_contract_service.py`
  - `tests/catalog/test_contract_dialogs.py`
  - `tests/catalog/test_rights_service.py`
  - `tests/catalog/test_asset_service.py`
- database:
  - `tests/database/test_schema_current_target.py`
  - `tests/database/test_schema_migrations_12_14.py`
  - `tests/database/test_schema_migrations_20_24.py`
- integration:
  - `tests/integration/test_global_search_relationships.py`

The most important structural rule remains unchanged: `ui-app-workflows` stays intentionally broad enough to preserve real app-shell and workspace interactions that only show up when the full shell is exercised together.

## CI Workflow Grouping Changes

The workflow was reshaped from a monolithic suite into a small set of explicit shards in [`.github/workflows/ci.yml`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/.github/workflows/ci.yml).

The shard plan is:

- `catalog-services` on Python `3.10` without Qt runtime libraries and without coverage
- `catalog-services` on Python `3.13` without Qt runtime libraries and with coverage enabled
- `exchange-import` on Python `3.13` without Qt runtime libraries and with coverage enabled
- `history-storage-migration` on Python `3.13` with Qt runtime libraries and with coverage enabled
- `ui-app-workflows` on Python `3.13` with Qt runtime libraries and with coverage enabled
- a separate `coverage-report` job that combines shard artifacts and emits `coverage.xml`

The rationale is straightforward:

- pure service tests should stay on both supported Python versions where that matters most
- Qt-heavy UI and app-shell tests should not pay for an unnecessary second Python matrix
- coverage should be combined, not recomputed from scratch
- shard names should make failure localization obvious in CI output

`tests/ci_groups.py` is now the authoritative ownership map. It provides:

- `BASELINE_TEST_COUNT = 402`
- explicit module membership for each shard
- duplicate-membership detection
- discovered-but-ungrouped detection
- grouped-but-missing-on-disk detection
- grouped test count parity checks against discovery
- a `--verify` entrypoint that CI runs before each shard executes

Current grouped counts after the split:

- `catalog-services`: `102` tests
- `exchange-import`: `80` tests
- `history-storage-migration`: `76` tests
- `ui-app-workflows`: `144` tests

The workflow also now:

- cancels superseded branch runs via workflow `concurrency`
- installs Qt runtime libraries only on the Qt-requiring shards
- uploads uniquely named coverage data per shard
- combines coverage artifacts in a dedicated `coverage-report` job instead of rerunning the whole suite

## Rationale For The New Categorization

The grouping follows the repo’s real subsystem boundaries rather than arbitrary test size.

That matters because the codebase already has clear functional seams:

- app shell and startup
- exchange import/export
- history and recovery
- database schema and migration
- catalog services
- cross-subsystem integration flows

Splitting by those seams makes the CI output answer a useful question immediately: “which subsystem failed?” It also keeps the inevitable long-running UI shard intentionally visible instead of hiding it inside a generic full-suite bucket.

The categories were not fragmented further because over-sharding can become its own maintenance problem. The goal here was diagnosability, not a large matrix with many tiny jobs that are hard to maintain.

This pass also intentionally avoided broad companion-file moves after the main decomposition. Leaving already focused root-level tests in place kept churn controlled while still making the worst problem areas much easier to localize.

## Validation Performed

Validation completed locally for this pass:

- full test discovery
- `tests.ci_groups --verify` for each shard
- direct execution of each logical group
- shard-style coverage runs followed by `coverage combine`, `coverage report`, and `coverage xml`
- `ruff`
- `black --check`
- `mypy`
- the targeted build-requirements test

The concrete local runs were:

- `python3 -m unittest discover -s tests -p 'test_*.py'`
  - `Ran 402 tests in 1902.640s`
  - `OK`
- `python3 -m tests.ci_groups <group> --verify` for all four groups
  - all passed
- direct group execution:
  - `catalog-services`: `Ran 102 tests in 0.326s`
  - `exchange-import`: `Ran 80 tests in 0.591s`
  - `history-storage-migration`: `Ran 76 tests in 1.195s`
  - `ui-app-workflows`: `Ran 144 tests in 1899.898s`
- coverage flow:
  - `python3 -m coverage erase`
  - shard-style `coverage run --parallel-mode -m unittest ...` for all four groups
  - `python3 -m coverage combine`
  - `python3 -m coverage report`
  - `python3 -m coverage xml`
  - combined local coverage: `83%`
- static gates:
  - `python3 -m ruff check build.py isrc_manager tests`
  - `python3 -m black --check build.py isrc_manager tests`
  - `python3 -m mypy`
  - all passed after a final import-order cleanup in `tests/ci_groups.py`
- targeted build validation:
  - `python3 -m unittest tests.test_build_requirements -v`
  - `Ran 11 tests`
  - `OK`

## Flaky Or Still-Suspicious Areas

The main environment-sensitive surfaces remain the same ones that were already visible in the logs:

- Qt/offscreen app-shell tests
- startup and storage migration flows
- tests that depend on `QSettings` or temp filesystem layout
- tests that spin real event loops or use sleeps

The `ui-app-workflows` shard is the one to watch most closely. It remained the clear long pole locally:

- direct run: about `1899.898s`
- covered run: about `2439.395s`

One initial local attempt to run all four coverage shards in a single shell loop exited nonzero before the covered UI shard produced a coverage file. A follow-up isolated rerun of `ui-app-workflows` under coverage completed successfully, so this was treated as a non-reproducible local execution anomaly rather than a confirmed deterministic test failure. That makes `ui-app-workflows` the main still-suspicious area for future timing and stability observation.

## Remaining Limitations

This pass improves clarity, but it does not remove all CI cost.

- Qt runtime setup is still necessary for the UI shards
- some integration files remain intentionally broad because they verify real cross-subsystem behavior
- the new shard structure still depends on keeping the discovery map accurate as tests move
- coverage aggregation is only meaningful if shard artifacts are combined consistently

The deliberate tradeoff is better failure localization and a cleaner CI story, even if one or two shards remain heavier than the rest.

## Recommended Future Improvements

Recommended follow-up work:

- add per-shard timing visibility so the heavy bucket is obvious over time
- continue trimming accidental overlap between `ui-app-workflows` and narrower unit-style tests
- keep `tests.ci_groups.py` authoritative so new tests are placed deliberately
- consider future sub-shards only if a group repeatedly dominates runtime after this pass
- move additional already-focused companion tests into subpackages only when that improves diagnosability enough to justify churn
- keep coverage combination logic explicit and simple so the suite does not quietly drift back into a monolith

## Why This Should Not Be Re-Monolithized

The old shape hid too much information in too few jobs.

Re-monolithizing would reintroduce the same problems this pass is fixing:

- failures would once again land in a generic all-tests bucket
- runtime would stay opaque
- the coverage job would be forced to rerun the full suite again
- future maintainers would have to rediscover the subsystem boundaries by reading the code the hard way

The new structure is better because it turns the CI output into a map of the system instead of a single pass/fail block. That is the real maintenance win.
