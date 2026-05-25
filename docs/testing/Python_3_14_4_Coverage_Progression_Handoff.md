# Python 3.14.4 Coverage Progression Handoff

Date: 2026-05-25

## Purpose

This handoff checkpoints the Python 3.14.4 QA coverage progression before the next coverage implementation batch. The current repository state includes the environment/bootstrap stabilization work, substantial behavioural test additions, and the coverage-accounting correction that removed duplicate uppercase package measurement.

## Current checkpoint state

- Python target: Python 3.14.4 only.
- Test framework: pytest with pytest-cov branch coverage.
- Coverage measurement target: `isrc_manager` only.
- Root facade: `ISRC_manager.py` remains a thin entrypoint facade.
- Deprecated/root feature imports: no new uppercase/root feature-import tests were added for coverage accounting.
- Coverage-accounting mismatch: resolved by removing `--cov=ISRC_manager` from active coverage commands.
- Generated coverage artifacts: `coverage.json`, `coverage.xml`, `.coverage*`, and `htmlcov/` should not be committed as source artifacts.

## Recent validation results

Commands run in the prepared virtual environment:

```bash
.venv/bin/python -m coverage erase
rm -rf htmlcov coverage.xml coverage.json
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Compileall: passed.
- Full pytest: `1768 passed`, `54 subtests passed`, `776 warnings`.
- Coverage JSON accounting check: `upper_count=0`, `lower_count=242`.
- Total branch-aware coverage: `77.8818%` displayed as `78%`.
- Statement coverage: `81.9157%` displayed as `82%`.
- Branch coverage: `64.4789%` displayed as `64%`.
- Ruff: passed.
- Black: passed after formatting four test files.
- Mypy: passed.

## Coverage progression summary

The project moved from a misleading low aggregate caused partly by duplicate uppercase-path accounting to a real lowercase-package measurement of approximately 78%. The current gap to the 95% gate is now genuine test coverage work, not an environment or coverage-path accounting problem.

The completed coverage work focused on meaningful behavioural tests across services, controllers, media helpers, forensics/authenticity helpers, import/repair logic, settings transfer, update helpers, and UI-adjacent units where headless-safe seams were available.

## Important coverage-accounting rule

Do not reintroduce this command pattern:

```bash
--cov=isrc_manager --cov=ISRC_manager
```

Use this pattern instead:

```bash
--cov=isrc_manager
```

The uppercase `ISRC_manager` path overlaps the same physical project source tree and causes duplicate 0% accounting entries. If the root facade needs smoke coverage, test the facade behaviour directly without measuring the uppercase package tree as a second source target.

## Files and areas changed in this checkpoint

Configuration and documentation:

- `pyproject.toml`
- `Makefile`
- `README.md`
- `AGENTS.md`
- `.gitignore`
- `requirements-dev.txt`
- `docs/testing/Python_3_14_4_Test_Coverage_Audit.md`
- `docs/testing/Python_3_14_4_Coverage_Progression_Handoff.md`

Representative modified or added tests:

- `tests/test_app_bootstrap.py`
- `tests/test_authenticity_controller.py`
- `tests/test_authenticity_dialogs.py`
- `tests/test_authenticity_init.py`
- `tests/test_code_registry_service.py`
- `tests/test_database_admin_service.py`
- `tests/test_forensics_controller.py`
- `tests/test_forensics_dialogs.py`
- `tests/test_forensics_service_units.py`
- `tests/test_forensics_watermark.py`
- `tests/test_forensics_watermark_coverage.py`
- `tests/test_import_repair_queue.py`
- `tests/test_media_equalizer.py`
- `tests/test_media_equalizer_coverage.py`
- `tests/test_media_equalizer_player.py`
- `tests/test_media_equalizer_widgets.py`
- `tests/test_promo_codes_dialogs.py`
- `tests/test_promo_codes_service.py`
- `tests/test_selection_scope.py`
- `tests/test_settings_transfer_service.py`
- `tests/test_sqlite_utils.py`
- `tests/test_update_installer.py`
- `tests/test_updater_helper.py`

## Remaining high-value coverage targets

The next coverage batches should prioritize large missing-line clusters and high-risk behaviour rather than broad import coverage.

Recommended next modules:

1. `isrc_manager/main_window.py`
2. `isrc_manager/contract_templates/dialogs.py`
3. `isrc_manager/media/preview_dialogs.py`
4. `isrc_manager/tracks/edit_dialog.py`
5. `isrc_manager/history/manager.py`
6. `isrc_manager/media/waveform.py`
7. `isrc_manager/contract_templates/export_service.py`
8. `isrc_manager/code_registry/service.py`
9. `isrc_manager/application_settings_dialog.py`
10. `isrc_manager/qss_autocomplete.py`
11. `isrc_manager/quality/service.py`
12. `isrc_manager/releases/controller.py`
13. `isrc_manager/releases/dialogs.py`
14. `isrc_manager/releases/service.py`
15. `isrc_manager/services/tracks.py`

## Suggested next batch strategy

1. Start with service/helper modules that still have clear branch gaps and low UI coupling.
2. Add headless-safe dialog/controller tests only where the UI behaviour is directly meaningful.
3. Keep mocking at external boundaries: file dialogs, message boxes, long-running workers, filesystem IO, process launch, and network/update checks.
4. Avoid root `ISRC_manager` imports except for a narrow root-facade smoke test if explicitly needed.
5. Keep coverage exclusions narrow and documented; do not omit entire source packages.

## Next validation command set

Use this command sequence after the next batch:

```bash
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

If the 95% gate still fails, rerun pytest with `--cov-fail-under=0`, preserve the report locally, and update `docs/testing/Python_3_14_4_Test_Coverage_Audit.md` with the next exact uncovered-module map.

## Checkpoint recommendation

Commit this state before continuing. The next coverage phase can then focus only on genuine remaining coverage gaps with a clean baseline and without mixing coverage-accounting/configuration work into the next test implementation batch.
