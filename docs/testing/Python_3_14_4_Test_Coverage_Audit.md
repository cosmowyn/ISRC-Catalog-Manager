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

- `pyproject.toml` now includes pytest-cov settings with `--cov-branch` and `--cov-fail-under=95` in test addopts.
- no `tox.ini` or `noxfile.py` files exist in this repository.
- existing grouped-test infrastructure (`tests/ci_groups.py`, `tests/run_group.py`) is still functionally oriented around module-level grouped execution and has not been migrated in this pass.

## 3) Baseline inventory and gap map

### Files and modules checked

- `tests/ci_groups.py`:
  - `discovered_test_count()` baseline is `467` tests (hard-coded `BASELINE_TEST_COUNT`) and active grouped execution path currently validates membership.
- Historic coverage artifact (existing `coverage.xml`) was used for a static gap signal only (not from a fully healthy current run).

### Gap map

- Untested modules:
  - none detected in the available coverage artifact (line coverage present for all discovered covered files).
- Undertested modules:
  - `134` modules below `95%` line coverage.
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
  - not currently measurable from command output because coverage runtime in this environment is blocked before execution; legacy artifact reports branch-rate `0.0` (branch tracking did not run).
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

2. `python3 -m compileall ISRC_manager.py isrc_manager tests`
   - result: `passed`

3. `python3 -m pytest --cov=isrc_manager --cov=ISRC_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-fail-under=95`
   - result: command failed before run because coverage CLI arguments are unrecognized without `pytest-cov` plugin installed.

4. `python3 -m pytest`
   - result: command failed due the same missing `pytest-cov` addopts registered in `pyproject.toml`.

5. `python3 -m pytest --override-ini addopts= tests/test_python_314_compatibility.py`
   - result: failed during collection/import
   - first representative error:
     - `ModuleNotFoundError: No module named 'PySide6'`

6. `python3 -m ruff check build.py isrc_manager scripts tests`
   - result: failed (`No module named ruff`).

7. `python3 -m black --check build.py isrc_manager scripts tests`
   - result: failed (`No module named black`).

8. `python3 -m mypy`
   - result: failed (`No module named mypy`).

## 5) Remaining follow-up actions

- install runtime and dev dependencies in a dedicated environment, then rerun full coverage:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e .[dev]
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
