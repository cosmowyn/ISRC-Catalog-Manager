# Python 3.14.4 Test Coverage Audit

## Scope

- Project: ISRC Catalog Manager
- Target runtime: Python `3.14.4`
- Objective: remove legacy Python-version compatibility burden from QA surface and enforce/measure pytest-based validation with branch coverage on Python `3.14.4` only.

## 1) Version-targeted cleanup status

### Confirmed removed / migrated

- `pyproject.toml`
  - `requires-python` set to `>=3.14.4`
  - classifiers reduced to `3.14` only
  - Python-version conditional dependency markers removed
  - pytest + coverage tooling pinned under dev dependencies
- `.github/workflows/ci.yml`
  - all matrix axes now use only `3.14.4`
  - removed legacy 3.10/3.13 test shard combinations
- `.github/workflows/version-bump.yml`
  - target Python version now `3.14.4`
- `.github/workflows/release-build.yml`
  - target Python version now `3.14.4`
- `requirements.txt` / `pyproject.toml`
  - runtime dependency markers for `numpy`/`scipy` removed and pinned directly
- `tests/test_python_314_compatibility.py`
  - assertions migrated from legacy minimum-version expectations to exact Python `3.14.4` expectations
  - workflow pin assertions aligned to CI/test-time expectations
- `Makefile`
  - test invocation updated from `unittest` discovery to `pytest`
- Legacy command in CI smoke step changed from `python -m unittest ...` to `python -m pytest -q ...`

### Legacy Python-version test artifacts to delete

- No additional legacy-version-only tests were found after migration of the Python compatibility test file.

### Legacy Python-version tests to migrate

- `tests/test_python_314_compatibility.py` (migrated in-place):
  - removed conditional skip-style checks
  - now validates exact 3.14.4 compatibility intent and pinned-runtime expectations.

## 2) Current test tooling and gate alignment

- `pyproject.toml` now includes pytest-cov settings with `--cov=isrc_manager`, `--cov-branch`, and `--cov-fail-under=95` in test addopts.
- Coverage measurement intentionally targets the lowercase `isrc_manager` package once. The uppercase `ISRC_manager` package path overlaps the same physical source tree in this checkout and must not be added as a second `--cov` target, because doing so creates duplicate 0% entries and encourages legacy import-path tests.
- `pyproject.toml` `[project].dependencies` includes runtime blockers needed by test collection (`PySide6`, `openpyxl`) and migration checks (`numpy`, `scipy`, `cryptography`), so runtime bootstrap installs them.
- `[project].optional-dependencies.dev` includes `pytest`, `pytest-cov`, `ruff`, `black`, `mypy`, and `coverage`, matching the documented test/tooling requirements.
- `requirements-dev.txt` is retained as a compatibility shortcut and now delegates to the canonical bootstrap:
  - `-r requirements.txt`
  - `-e .[dev]`.
- no `tox.ini` or `noxfile.py` files exist in this repository.
- existing grouped-test infrastructure (`tests/ci_groups.py`, `tests/run_group.py`) is still functionally oriented around module-level grouped execution and has not been migrated in this pass.
- `tests.run_group` executes `coverage run --parallel-mode` over `tests.run_module` (unittest-backed), so the runtime-only `pytest-cov` blocker does not affect CI shard execution.

## 2.1) Headless/UI execution standard

- repository CI and local recommendation now treat Qt UI tests as headless via `QT_QPA_PLATFORM=offscreen` for both direct `pytest` commands and grouped command paths.

## 3) Baseline inventory and gap map

### Files and modules checked

- `tests/ci_groups.py`:
  - `discovered_test_count()` baseline is `467` tests (hard-coded `BASELINE_TEST_COUNT`) and active grouped execution path currently validates membership.
- Historic coverage artifact (existing `coverage.xml`) was used for a static gap signal only (not from a fully healthy current run).

### Gap map

- Untested modules:
  - none detected in the available coverage run (line coverage present for all discovered covered files).
- Undertested modules:
  - `134` modules below `95%` line coverage in the latest full run.
  - Representative low-coverage modules in the artifact:
    - `app_bootstrap.py` (0.936)
    - `assets/service.py` (0.839)
    - `authenticity/__init__.py` (0.692)
    - `authenticity/dialogs.py` (0.634)
    - `exchange/repair_dialogs.py` (0.106)
    - `forensics/dialogs.py` (0.120)
    - `media/equalizer.py` (0.192)
    - `promo_codes/service.py` (0.135)
    - `selection_scope.py` (0.555)
    - `services/sqlite_utils.py` (0.556)
- Missing branch coverage:
  - measured with branch-aware collection, but 95% branch/line threshold is still unmet by the current suite.
- Legacy tests to delete:
  - none.
- Legacy tests to migrate:
  - `tests/test_python_314_compatibility.py` (completed in this pass).
- High-risk code paths without coverage (based on artifact):
  - `exchange/repair_dialogs.py` (~0.106)
  - `promo_codes/dialogs.py` (~0.107)
  - `forensics/dialogs.py` (~0.120)
  - `media/equalizer.py` (~0.192)
  - `media/equalizer_player.py` (~0.539)
  - `forensics/watermark.py` (~0.642)
  - `services/import_repair_queue.py` (~0.667)

## 4) Validation execution log (environment-local)

Executed in the current environment:

1. `python3 --version`
   - output: `Python 3.14.4`

2. `python3 -m pip install -r requirements.txt`
   - result: `success`

3. `python3 -m pip install -e '.[dev]'`
   - result: `success`

4. `python3 -m compileall ISRC_manager.py isrc_manager tests`
   - result: `passed`

5. `QT_QPA_PLATFORM=offscreen python3 -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-fail-under=95`
   - result: command completed execution and failed coverage gate.
   - final coverage: `33.91%` (required `95%`)
   - test output: `1265 passed, 773 warnings, 45 subtests passed`.

6. `python3 -m ruff check build.py isrc_manager scripts tests`
   - result: `All checks passed!`

7. `python3 -m black --check build.py isrc_manager scripts tests`
   - result: `All done! ✨ 🍰 ✨`
   - files unchanged: `433`.

8. `python3 -m mypy`
   - result: `Success: no issues found in 29 source files`

9. `QT_QPA_PLATFORM=offscreen python3 -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600`
   - result: `Completed grouped test run in 73.97s`
   - module count: `50`
   - pass count: `50/50`

## 5) Remaining follow-up actions

## 4.1) Coverage implementation update - 2026-05-25 18:05:12 UTC

This pass added another focused batch of meaningful pytest coverage without production-code changes.

### Tests added in this batch

- `tests/test_forensics_service_units.py`
  - covers forensic service helpers, ledger round-trips, key ordering, lossy delivery wrapping, export success/skip/cancel/cleanup branches, and inspection resolution branches.
- `tests/test_settings_controller.py`
  - covers identity helpers, current settings collection, changed/no-op settings orchestration, settings dialog accept/cancel/error paths, bundle export/import flows, and single-setting delegation.
- `tests/test_album_ordering_dialog.py`
  - covers album ordering table row movement, drag/drop helper branches, ordered track ID extraction, and button-state behavior under headless Qt.
- `tests/test_master_transfer_controller.py`
  - covers master-transfer helper functions, manifest summary extraction, report formatting, early export/import exits, and inspection-to-import task submission.

### Focused coverage results from this batch

- `isrc_manager/forensics/service.py`: `98%`
- `isrc_manager/settings_controller.py`: `88%`
- `isrc_manager/tracks/album_ordering_dialog.py`: `83%`
- `isrc_manager/exchange/master_transfer_controller.py`: `66%`

### Validation commands run in this batch

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -o addopts='' tests/test_forensics_service_units.py tests/test_settings_controller.py tests/test_album_ordering_dialog.py tests/test_master_transfer_controller.py
```

- result: `52 passed`

```bash
.venv/bin/python -m ruff check tests/test_forensics_service_units.py tests/test_settings_controller.py tests/test_album_ordering_dialog.py tests/test_master_transfer_controller.py
```

- result: `All checks passed!`

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY'
from scipy import signal
import pytest
raise SystemExit(pytest.main([
    '--cov=isrc_manager',
    '--cov-branch',
    '--cov-report=term-missing',
    '--cov-report=html',
    '--cov-report=json',
    '--cov-fail-under=0',
]))
PY
```

- result: `1564 passed, 700 warnings, 45 subtests passed`
- coverage result: `36%`
- report artifacts refreshed: `coverage.json`, `htmlcov/`

Note: importing `scipy.signal` before starting `pytest-cov` is currently required in this local interpreter to avoid a SciPy/Numpy import-time doc-generation failure under coverage tracing (`ValueError: _CopyMode.IF_NEEDED is neither True nor False`). The tests themselves pass without that preload. This is a validation-runner environment quirk to resolve separately from application test coverage.

### Remaining highest-impact coverage gaps

The refreshed full-suite coverage report still shows the 95% target as In Progress. The largest missing-line contributors remain large UI/controller modules:

- `isrc_manager/main_window.py`: `1333` missing lines
- `isrc_manager/contract_templates/dialogs.py`: `864` missing lines
- `isrc_manager/media/preview_dialogs.py`: `585` missing lines
- `isrc_manager/tracks/edit_dialog.py`: `415` missing lines
- `isrc_manager/media/waveform.py`: `409` missing lines
- `isrc_manager/media/audio_visualization.py`: `337` missing lines
- `isrc_manager/history/manager.py`: `301` missing lines
- `isrc_manager/contract_templates/export_service.py`: `299` missing lines
- `isrc_manager/code_registry/service.py`: `265` missing lines
- `isrc_manager/media/waveform_cache.py`: `256` missing lines

### Next recommended coverage batches

- Batch A: `media/waveform.py`, `media/audio_visualization.py`, and `media/waveform_cache.py` with deterministic media/cache/service tests.
- Batch B: `contract_templates/export_service.py` and `contract_templates/service.py` with document/rendering/validation fixtures and failure-path coverage.
- Batch C: `code_registry/service.py`, `history/manager.py`, and `storage_admin.py` with database-backed service tests.
- Batch D: `main_window.py`, `contract_templates/dialogs.py`, `media/preview_dialogs.py`, and `tracks/edit_dialog.py` via focused headless Qt controller/dialog tests.

The milestone remains **In Progress**. The blocker is still meaningful test coverage volume across large application modules, not missing dependencies or a broken pytest runtime.

- Recommended reproducible bootstrap for all QA gates:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e .[dev]
```

- Recommended primary QA verification command set:

```bash
python3 -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen python3 -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-fail-under=95
python3 -m ruff check build.py isrc_manager scripts tests
python3 -m black --check build.py isrc_manager scripts tests
python3 -m mypy
```

- run grouped validation with the existing workflow command shape:

```bash
QT_QPA_PLATFORM=offscreen python3 -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600
```

- after successful catalog group execution, continue with:
  - `exchange-import`
  - `history-storage-migration`
  - `ui-app-workflows`

- only when full run completes and branch coverage thresholds are met, enforce the 95% coverage policy in CI.

- **Current milestone status:**
  - Full local coverage gate remains In Progress.
  - Blocker is a coverage-quality gap (`33.91%` vs `95%` target), not an environment/bootstrap/tooling issue.
