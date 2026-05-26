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

## 4.2) Coverage implementation update - 2026-05-25 21:02:13 UTC

This pass continued Batch A from the prior handoff and expanded behavioural coverage for the
media waveform stack without production-code changes.

### Tests expanded in this batch

- `tests/test_media_waveform_clusters.py`
  - adds PCM fixture coverage for 8-bit, 24-bit, and 32-bit WAV paths across waveform,
    waveform-cache, harmonic, peak-meter, and spectrum loaders.
  - covers waveform widget edge events, bookmark deduplication, cached-preview fallback selection,
    render paths, palette-change invalidation, and live harmonic drawing.
  - covers stereo peak-meter and spectrum graph edge states, equalizer response routing, context-menu
    actions, release/fade state transitions, and render helpers.
  - covers deterministic ffmpeg, audioread, and Qt decoder fallbacks using fake subprocess and
    decoder objects instead of real multimedia devices.
  - covers waveform-cache schema/delete paths, stale-cache inspection branches, service fast-return
    and failed-render cleanup, source fingerprinting, color analysis, path generation, and resampling
    helpers.

### Focused coverage results from this batch

Narrow media-only report:

- `isrc_manager/media/audio_visualization.py`: `83%`
- `isrc_manager/media/waveform.py`: `85%`
- `isrc_manager/media/waveform_cache.py`: `88%`
- combined targeted media report: `85%`

Full-suite JSON report after this batch:

- total branch-aware coverage: `78.5829%` displayed as `79%`
- statement coverage: `82.5509%` displayed as `83%`
- branch coverage: `65.3993%` displayed as `65%`
- `isrc_manager/media/audio_visualization.py`: `85.3041%` displayed as `85%`
- `isrc_manager/media/waveform.py`: `86.0324%` displayed as `86%`
- `isrc_manager/media/waveform_cache.py`: `90.5253%` displayed as `91%`

### Validation commands run in this batch

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/test_media_waveform_clusters.py
```

- result: `18 passed`

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/test_media_waveform_clusters.py \
  --cov=isrc_manager.media.waveform \
  --cov=isrc_manager.media.audio_visualization \
  --cov=isrc_manager.media.waveform_cache \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=json:coverage-media.json \
  --cov-fail-under=0
```

- result: `18 passed`
- targeted coverage result: `85%`

```bash
.venv/bin/python -m ruff check tests/test_media_waveform_clusters.py
.venv/bin/python -m black --check tests/test_media_waveform_clusters.py
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
```

- result: passed

```bash
.venv/bin/python -m coverage erase
rm -rf htmlcov coverage.xml coverage.json coverage-media.json
QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY'
from scipy import signal  # noqa: F401
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

- result: `1776 passed`, `777 warnings`, `54 subtests passed`
- full coverage result: `79%`

### Remaining highest-impact coverage gaps

The refreshed full-suite report still shows the 95% target as In Progress. The largest missing-line
contributors are now:

- `isrc_manager/main_window.py`: `1333` missing lines
- `isrc_manager/contract_templates/dialogs.py`: `864` missing lines
- `isrc_manager/media/preview_dialogs.py`: `524` missing lines
- `isrc_manager/tracks/edit_dialog.py`: `415` missing lines
- `isrc_manager/history/manager.py`: `301` missing lines
- `isrc_manager/contract_templates/export_service.py`: `261` missing lines
- `isrc_manager/code_registry/service.py`: `247` missing lines
- `isrc_manager/application_settings_dialog.py`: `208` missing lines
- `isrc_manager/media/equalizer.py`: `204` missing lines
- `isrc_manager/contract_templates/service.py`: `194` missing lines

### Next recommended coverage batches

- Batch B: `contract_templates/export_service.py` and `contract_templates/service.py` with
  document/rendering/validation fixtures and failure-path coverage.
- Batch C: `code_registry/service.py`, `history/manager.py`, and `storage_admin.py` with
  database-backed service tests.
- Batch D: `media/preview_dialogs.py`, `tracks/edit_dialog.py`, and the largest remaining
  `main_window.py` command-routing paths via focused headless Qt tests.

## 4.3) Coverage implementation update - 2026-05-25 21:26:50 UTC

This pass continued the recommended Batch B/C service work without production-code changes. It
added behavioural tests for deterministic export rendering boundaries, managed draft storage,
draft registry assignment conflicts, legacy code-registry fallback reads, generation validation,
backup deletion cleanup, and explicit history file-restore recovery errors.

### Tests expanded in this batch

- `tests/contract_templates/test_export_service.py`
  - covers `QtWebEngineHtmlPdfAdapter` success, missing-source, load-failure, PDF print-failure,
    missing-output, timer, event-loop, and base-URL paths with fake Qt/WebEngine collaborators.
- `tests/contract_templates/test_revision_service.py`
  - covers draft working-file set/load/clear behaviour, managed-storage path validation, missing
    working paths, and draft registry assignment reuse/conflict/integrity branches.
- `tests/test_code_registry_service.py`
  - covers manual-category generation rejection, SHA/sequential mismatch validation, blank entry
    lookup, unused-entry filtering, legacy `ExternalCatalogIdentifiers` reads/suggestions, and
    no-op initialization before registry schema tables exist.
- `tests/history/_support.py` and `tests/history/test_history_recovery.py`
  - covers backup registration errors, backup sidecar/companion deletion, missing backup deletion
    errors, and `HistoryRecoveryError` paths for malformed or missing file-state artifacts.

### Full-suite coverage results from this batch

The refreshed full-suite report remains below the 95% branch-aware target:

- total branch-aware coverage: `78.7701%` displayed as `79%`
- statement coverage: `82.7131%` displayed as `83%`
- branch coverage: `65.6689%` displayed as `66%`
- missing lines: `12357`
- missing branches: `7386`

Improved modules from the full-suite JSON:

- `isrc_manager/contract_templates/export_service.py`: `74.2245%` displayed as `74%`
  - previous: `69.0547%`, `261` missing lines, `158` missing branches
  - current: `209` missing lines, `140` missing branches
- `isrc_manager/contract_templates/service.py`: `78.7681%` displayed as `79%`
  - previous: `74.9275%`, `194` missing lines, `152` missing branches
  - current: `156` missing lines, `137` missing branches
- `isrc_manager/code_registry/service.py`: `68.3740%` displayed as `68%`
  - previous: `65.5285%`, `247` missing lines, `177` missing branches
  - current: `230` missing lines, `159` missing branches
- `isrc_manager/history/manager.py`: `78.7603%` displayed as `79%`
  - previous: `78.2401%`, `301` missing lines, `201` missing branches
  - current: `294` missing lines, `196` missing branches

The current report is preserved locally in:

- `coverage.json`
- `htmlcov/`

### Validation commands run in this batch

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/contract_templates/test_export_service.py tests/contract_templates/test_revision_service.py
```

- result: `37 passed`, `4 subtests passed`

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/test_code_registry_service.py
```

- result: `28 passed`

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/history/test_history_recovery.py
```

- result: `5 passed`

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/contract_templates/test_export_service.py tests/contract_templates/test_revision_service.py tests/test_code_registry_service.py
```

- result: `65 passed`, `4 subtests passed`

```bash
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check tests/contract_templates/test_export_service.py tests/contract_templates/test_revision_service.py tests/test_code_registry_service.py tests/history/_support.py tests/history/test_history_recovery.py
.venv/bin/python -m black --check tests/contract_templates/test_export_service.py tests/contract_templates/test_revision_service.py tests/test_code_registry_service.py tests/history/_support.py tests/history/test_history_recovery.py
```

- result: passed

```bash
.venv/bin/python -m coverage erase
QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY'
from scipy import signal  # noqa: F401
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

- result: `1783 passed`, `785 warnings`, `54 subtests passed`
- full coverage result: `79%`

### Remaining highest-impact coverage gaps

The 95% gate could not be reached safely in this pass because the remaining gap is dominated by
large GUI/workflow surfaces and branch-heavy services that require meaningful scenario tests. The
largest missing-line contributors are now:

- `isrc_manager/main_window.py`: `1333` missing lines
- `isrc_manager/contract_templates/dialogs.py`: `864` missing lines
- `isrc_manager/media/preview_dialogs.py`: `524` missing lines
- `isrc_manager/tracks/edit_dialog.py`: `415` missing lines
- `isrc_manager/history/manager.py`: `294` missing lines
- `isrc_manager/code_registry/service.py`: `230` missing lines
- `isrc_manager/contract_templates/export_service.py`: `209` missing lines
- `isrc_manager/application_settings_dialog.py`: `208` missing lines
- `isrc_manager/media/equalizer.py`: `204` missing lines
- `isrc_manager/code_registry/workspace.py`: `180` missing lines

### Next recommended coverage batches

- Batch D1: headless Qt coverage for `contract_templates/dialogs.py`,
  `media/preview_dialogs.py`, and `tracks/edit_dialog.py`, with dialogs, file pickers, message
  boxes, and worker boundaries patched.
- Batch D2: continue service/controller coverage for `history/manager.py`,
  `code_registry/service.py`, and `code_registry/workspace.py`.
- Batch D3: target `media/equalizer.py`, `application_settings_dialog.py`, and selected
  `main_window.py` command-routing paths only where user-visible workflows can be asserted.

## 4.4) Coverage implementation update - 2026-05-25 21:57:09 UTC

This continuation pushed the measured `--cov=isrc_manager` package further through behavioural
tests for audio preview preload workflows, track edit dialog decision logic, application settings
fallbacks, equalizer helpers/widgets, main-window helper workflows, and contract-template workspace
layout compaction.

Tests added or expanded in this continuation:

- `tests/test_media_preview_preload.py`
  - managed custom audio source resolution, track-service source fallback, preload-state metadata,
    decode/cancel cleanup, and waiting-preload cache/fallback branches.
- `tests/tracks/test_edit_dialog_behaviors.py`
  - bulk edit application decisions, album-art ownership hints/deduplication, party-backed artist
    fallback labels, media display fallbacks, BUMA work resolution, and album shared-field deltas.
- `tests/test_application_settings_dialog_behaviors.py`
  - smart history-budget math/source selection, profile database discovery, owner-party payload
    fallback, party-backed artist resolution, and history retention mode detection.
- `tests/test_media_equalizer_coverage.py`
  - settings load/save fallback handling, ffmpeg/soundfile failure paths, response helper branches,
    and headless Qt equalizer curve/panning widget state transitions.
- `tests/test_main_window_helpers.py`
  - help-file refresh, log rendering, selection scope fallbacks, hidden-column settings parsing,
    header-label ordering, and catalog track-choice fallbacks.
- `tests/contract_templates/test_workspace_layout_helpers.py`
  - dock workspace group ordering, gap detection, rebuild/split direction, floating feature flags,
    and dock order hints.

### Full-suite coverage results from this continuation

The refreshed full-suite report remains below the 95% branch-aware target:

- total branch-aware coverage: `79.5174%` displayed as `80%`
- statement coverage: `83.3790%` displayed as `83%`
- branch coverage: `66.6868%` displayed as `67%`
- missing lines: `11881`
- missing branches: `7167`

Improved modules from the full-suite JSON:

- `isrc_manager/main_window.py`: `70.8914%` displayed as `71%`
  - previous: `67.7690%`, `1333` missing lines, `587` missing branches
  - current: `1202` missing lines, `532` missing branches
- `isrc_manager/contract_templates/dialogs.py`: `74.3142%` displayed as `74%`
  - previous: `72.7972%`, `864` missing lines, `445` missing branches
  - current: `817` missing lines, `419` missing branches
- `isrc_manager/media/preview_dialogs.py`: `80.4046%` displayed as `80%`
  - previous: `75.72%`, `524` missing lines, `280` missing branches
  - current: `412` missing lines, `237` missing branches
- `isrc_manager/tracks/edit_dialog.py`: `69.0306%` displayed as `69%`
  - previous: `58.75%`, `415` missing lines, `219` missing branches
  - current: `319` missing lines, `157` missing branches
- `isrc_manager/application_settings_dialog.py`: `79.2851%` displayed as `79%`
  - previous: `71.13%`, `208` missing lines, `107` missing branches
  - current: `150` missing lines, `76` missing branches
- `isrc_manager/media/equalizer.py`: `74.3848%` displayed as `74%`
  - previous: `70.36%`, `204` missing lines, `61` missing branches
  - current: `171` missing lines, `58` missing branches

The current report is preserved locally in:

- `coverage.json`
- `htmlcov/`

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_media_preview_preload.py tests/tracks/test_edit_dialog_behaviors.py tests/test_application_settings_dialog_behaviors.py tests/test_media_equalizer_coverage.py tests/test_main_window_helpers.py tests/contract_templates/test_workspace_layout_helpers.py --no-cov
```

- result: `47 passed`

```bash
python3 -m black tests/test_media_preview_preload.py tests/tracks/test_edit_dialog_behaviors.py tests/test_application_settings_dialog_behaviors.py tests/test_media_equalizer_coverage.py tests/test_main_window_helpers.py tests/contract_templates/test_workspace_layout_helpers.py
```

- result: passed after reformatting touched tests

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  --cov=isrc_manager \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=json \
  --cov-fail-under=0
```

- result: `1813 passed`, `784 warnings`, `54 subtests passed`
- full coverage result: `79.5174%`

### Remaining blocker to 95%

The 95% gate could not be reached safely in this pursuit because the remaining gap is still
`11881` missing lines and `7167` missing branches. The largest blockers are branch-heavy GUI shells,
dialog workspaces, and broad service/controller workflows that require realistic headless Qt and
database scenario tests. Reaching 95% from here would require thousands more covered line/branch
slots; doing that safely cannot be achieved by a small continuation without either superficial tests
or broad exclusions, both of which remain forbidden.

Largest remaining low-coverage modules by combined missing line/branch slots:

1. `isrc_manager/main_window.py` - `1202` missing lines, `532` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `817` missing lines, `419` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `412` missing lines, `237` missing branches
4. `isrc_manager/history/manager.py` - `294` missing lines, `196` missing branches
5. `isrc_manager/tracks/edit_dialog.py` - `319` missing lines, `157` missing branches
6. `isrc_manager/code_registry/service.py` - `230` missing lines, `159` missing branches
7. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
8. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
9. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
10. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches

### Next recommended coverage batch

- Batch E1: continue `main_window.py` by extracting or directly testing real helper/controller
  workflow branches for backup/restore, clipboard export, hidden column persistence, GS1 routing,
  catalog choices, and storage conversion callbacks.
- Batch E2: continue `contract_templates/dialogs.py` with headless tests around workspace panel
  administrative actions, fill-form refresh/save flows, revision/draft deletion and activation,
  registry selector generation, and manual widget construction.
- Batch E3: deepen `media/preview_dialogs.py` and `tracks/edit_dialog.py` around active load
  result handling, source loading, cache eviction, file picker/message-box branches, and save
  workflows using fake hosts/services.
- Batch E4: continue services: `history/manager.py`, `code_registry/service.py`,
  `contract_templates/export_service.py`, `contract_templates/service.py`, and
  `exchange/service.py` error/conflict/recovery branches.

## 4.5) Coverage implementation update - 2026-05-25 22:27:37 UTC

This continuation kept coverage measurement scoped to `--cov=isrc_manager` and added behavioural
service tests in the requested low-UI priority area. It also fixed one real production bug discovered
by the tests: `QualityDashboardService.export_csv()` and `export_json()` attempted to serialize
slotted `QualityIssue` dataclasses through `issue.__dict__`, which raises `AttributeError`. The
service now uses `dataclasses.asdict()` for those exports.

Starting checkpoint for this continuation:

- total branch-aware coverage: `79.5174%` displayed as `80%`
- statement coverage: `83.3790%` displayed as `83%`
- branch coverage: `66.6868%` displayed as `67%`
- missing lines: `11881`
- missing branches: `7167`

Final measured checkpoint after the required 95% gate attempt:

- total branch-aware coverage: `79.8832%` displayed as `80%`
- statement coverage: `83.6898%` displayed as `84%`
- branch coverage: `67.2353%` displayed as `67%`
- missing lines: `11659`
- missing branches: `7049`

Tests added or expanded in this continuation:

- `tests/test_quality_service.py`
  - quality CSV/JSON export serialization, scoped derived-value regeneration, scoped date
    normalization, relink-media no-root/existing/unmatched/scoped repair branches, normalize-date
    parser edge cases, and unknown fix rejection.
- `tests/test_release_service.py`
  - release family classification, duplicate/invalid add-track handling, missing-release delete
    errors, matching/upsert decisions, artwork storage conversion round-trips, artwork fetch
    missing-data failures, and artwork source validation errors.
- `tests/test_code_registry_service.py`
  - assignment target search for track/release/contract owners, assignment rejection for missing or
    wrong owners, busy contract destination errors, catalog ensure generation, stale internal
    realignment, external catalog preservation, and unsupported/missing owner errors.

Improved modules from the full-suite JSON:

- `isrc_manager/quality/service.py`: `69.18%` to `87.52%`
  - missing lines: `118` to `37`
  - missing branches: `99` to `51`
- `isrc_manager/releases/service.py`: `74.11%` to `87.75%`
  - missing lines: `100` to `44`
  - missing branches: `67` to `35`
- `isrc_manager/code_registry/service.py`: `68.37%` to `78.37%`
  - missing lines: `230` to `145`
  - missing branches: `159` to `121`

No broad coverage exclusions, skips, xfails, root uppercase feature imports, or `--cov=ISRC_manager`
entries were added. No testability seams were added.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_quality_service.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_release_service.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_code_registry_service.py --no-cov
.venv/bin/python -m black isrc_manager/quality/service.py tests/test_quality_service.py tests/test_release_service.py tests/test_code_registry_service.py
.venv/bin/python -m coverage erase && rm -rf htmlcov coverage.xml coverage.json && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m coverage erase && rm -rf htmlcov coverage.xml coverage.json && .venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
git diff --check
```

Observed result:

- Focused quality service tests: `20 passed`.
- Focused release service tests: `18 passed`.
- Focused code-registry service tests: `31 passed`.
- Compileall: passed.
- Full pytest with `--cov-fail-under=0`: `1833 passed`, `775 warnings`, `54 subtests passed`.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `79.8832%`, below the required 95% gate (`1833 passed`, `777 warnings`,
  `54 subtests passed`).
- Ruff: passed after fixing one import-order issue in `tests/test_quality_service.py`.
- Black check: passed.
- Mypy: passed.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining blocker to 95%

The 95% gate remains unreachable in this continuation without large additional batches. The exact
remaining gap is `11659` missing lines and `7049` missing branches. With the current measured
denominator (`71483` statements plus `21514` branches), reaching 95% would require approximately
`14059` additional covered line/branch slots if no new production code were added. The blocker is
therefore not a single failing test or tool problem; it is the amount of unexercised real behaviour
left in large GUI/workflow and branch-heavy service modules.

Largest remaining low-coverage modules by missing branches:

1. `isrc_manager/main_window.py` - `1202` missing lines, `532` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `817` missing lines, `419` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `412` missing lines, `237` missing branches
4. `isrc_manager/history/manager.py` - `294` missing lines, `196` missing branches
5. `isrc_manager/tracks/edit_dialog.py` - `319` missing lines, `157` missing branches
6. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
7. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
8. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
9. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
10. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches

### Next recommended coverage batch

- Batch F1: `history/manager.py` recovery repair, invariant enforcement, replay/apply payload
  rollback/error paths, snapshot archive restore, and artifact-root scrubbing.
- Batch F2: `services/tracks.py` media metadata maps, storage conversion failures, album-group
  conflict snapshots, unused managed-media cleanup, and album metadata propagation.
- Batch F3: `contract_templates/export_service.py` catalog value resolution, payload replacement,
  preview pruning/materialization, PDF renderer fallback, and DOCX placeholder replacement errors.
- Batch F4: headless Qt workflow batches for `main_window.py`, `contract_templates/dialogs.py`,
  `media/preview_dialogs.py`, and `tracks/edit_dialog.py`, using fake hosts/services and patched
  modal/file picker boundaries.

## 4.6) Coverage implementation update - 2026-05-26 05:20:15 UTC

This continuation started with `history/manager.py` as requested, then used current coverage evidence
to add small, behavioural headless-safe batches in the next largest workflow surfaces:
`tracks/edit_dialog.py`, `media/preview_dialogs.py`, and `contract_templates/dialogs.py`. No
production code was changed in this continuation.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `79.8832%` displayed as `80%`
- statement coverage: `83.6898%` displayed as `84%`
- branch coverage: `67.2353%` displayed as `67%`
- missing lines: `11659`
- missing branches: `7049`

Final measured checkpoint after this batch's required 95% gate attempt:

- total branch-aware coverage: `80.5198%` displayed as `81%`
- statement coverage: `84.2648%` displayed as `84%`
- branch coverage: `68.0766%` displayed as `68%`
- missing lines: `11248`
- missing branches: `6868`

Tests added or expanded in this continuation:

- `tests/history/*`
  - recovery-state repair for moved sidecars, orphan conflicts, dangling snapshot references,
    missing snapshot archives, corrupted snapshot boundaries, rollback after side-effect failure,
    file-state directory rejection, and missing-track/event-recording error paths.
- `tests/tracks/test_edit_dialog_behaviors.py`
  - single and bulk save validation/cancellation/success/rollback workflows, propagated and
    non-propagated history actions, media picker/clear/copy helpers, album-art ownership guards,
    GS1 dialog launch failures, routing, and bulk changed-field payload/audit paths.
- `tests/test_media_preview_preload.py`
  - custom audio missing-row/missing-blob paths, owned-temp cleanup failures, preload state failure,
    late cancellation after waveform/spectrum phases, cancelled preload handoff, empty prepared
    media, and owned-prepared disposal on decode cancellation.
- `tests/contract_templates/test_workspace_layout_helpers.py`
  - workspace layout serialization/deserialization, dock-area normalization, dock visibility maps,
    saved-topology detection, and floating-transition hook safety.

Improved modules from the refreshed full-suite JSON:

- `isrc_manager/history/manager.py`: `78.76%` to `86.69%`
  - missing lines: `294` to `176`
  - missing branches: `196` to `131`
- `isrc_manager/tracks/edit_dialog.py`: `69.03%` to `92.19%`
  - missing lines: `319` to `62`
  - missing branches: `157` to `58`
- `isrc_manager/media/preview_dialogs.py`: `80.40%` to `81.04%`
  - missing lines: `412` to `398`
  - missing branches: `237` to `230`
- `isrc_manager/contract_templates/dialogs.py`: `74.31%` to `74.94%`
  - missing lines: `817` to `796`
  - missing branches: `419` to `410`

No broad coverage exclusions, skips, xfails, root uppercase feature imports, or `--cov=ISRC_manager`
entries were added. No new production testability seams were added.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/history --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/tracks/test_edit_dialog_behaviors.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_media_preview_preload.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_workspace_layout_helpers.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/history tests/tracks/test_edit_dialog_behaviors.py tests/test_media_preview_preload.py tests/contract_templates/test_workspace_layout_helpers.py --no-cov
.venv/bin/python -m black tests/history/_support.py tests/history/test_history_recovery.py tests/history/test_history_snapshots.py tests/history/test_history_settings.py tests/history/test_history_tracks.py tests/history/test_history_action_helpers.py tests/history/test_history_file_effects.py tests/tracks/test_edit_dialog_behaviors.py tests/test_media_preview_preload.py tests/contract_templates/test_workspace_layout_helpers.py
.venv/bin/python -m coverage erase && rm -rf htmlcov coverage.json && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Focused history tests: `42 passed`.
- Focused track edit dialog tests: `10 passed`.
- Focused media preview preload tests: `13 passed`.
- Focused contract-template workspace layout tests: `5 passed`.
- Combined focused workflow suite: `70 passed`.
- Full pytest with `--cov-fail-under=0`: `1853 passed`, `785 warnings`, `54 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `80.5198%`, below the required 95% gate (`1853 passed`, `785 warnings`,
  `54 subtests passed`).
- Ruff: passed after fixing one import-order issue in
  `tests/contract_templates/test_workspace_layout_helpers.py`.
- Black check: passed.
- Mypy: passed.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional large behavioural batches. The exact remaining gap is
`11248` missing lines and `6868` missing branches. With the current measured denominator (`71483`
statements plus `21514` branches), reaching 95% would require roughly `13467` additional covered
line/branch slots if no new production code were added.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1202` missing lines, `532` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `796` missing lines, `410` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `398` missing lines, `230` missing branches
4. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
5. `isrc_manager/history/manager.py` - `176` missing lines, `131` missing branches
6. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
7. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
8. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
9. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
10. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches

Recommended next batch:

- Batch G1: `main_window.py` fake-host controller/helper workflows for backup/restore routing,
  catalog choices, GS1 routing, clipboard/media routing, and storage conversion callbacks.
- Batch G2: `contract_templates/dialogs.py` workspace panel actions around draft save/export/delete,
  revision activation/rescan/rebind, selector generation, and modal/failure branches.
- Batch G3: continue `media/preview_dialogs.py` active load result handling, source loading,
  preload cache eviction, artwork preview, bookmark, and volume/equalizer state branches.
- Batch G4: continue `history/manager.py` with deeper cleanup/retention compaction and snapshot
  archive restore branches that were not reached by this continuation.

## 4.7) Coverage implementation update - 2026-05-26 05:45:51 UTC

This continuation used the refreshed coverage evidence from the prior history-first batch. Because
`history/manager.py` had already moved from `78.76%` to `86.69%` in the validated 4.6 checkpoint,
the safest next high-value workflow target was `main_window.py`, which remained the largest combined
line/branch gap. The batch stayed at the composition-shell and helper boundary: it used fake
controllers, fake settings/profile stores, patched message boxes, and headless Qt widgets without
launching the full application window.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `80.5198%` displayed as `81%`
- statement coverage: `84.2648%` displayed as `84%`
- branch coverage: `68.0766%` displayed as `68%`
- missing lines: `11248`
- missing branches: `6868`

Final measured checkpoint after the required 95% gate attempt:

- total branch-aware coverage: `80.6757%` displayed as `81%`
- statement coverage: `84.4285%` displayed as `84%`
- branch coverage: `68.2067%` displayed as `68%`
- missing lines: `11131`
- missing branches: `6840`

Tests added or expanded in this continuation:

- `tests/test_main_window_helpers.py`
  - help dialog modal/non-modal routing, local-path open failures, top-chrome boundary handling,
    artist-code migration/defaulting/settings paths, background runtime setup, status-bar task
    messages, database task preparation error paths, background task error presentation, scaled
    progress callbacks, and composition-shell delegation to sound, update, diagnostics, theme,
    settings, history-retention, profile-session, foreground-service, and audio-conversion
    controllers.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/main_window.py`: `70.8914%` to `73.3591%`
  - missing lines: `1202` to `1084`
  - missing branches: `532` to `503`

No broad coverage exclusions, skips, xfails, root uppercase feature imports, or `--cov=ISRC_manager`
entries were added. No production code or new testability seams were added in this continuation.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov
.venv/bin/python -m black tests/test_main_window_helpers.py
.venv/bin/python -m ruff check tests/test_main_window_helpers.py
.venv/bin/python -m coverage erase && rm -rf htmlcov coverage.json && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused main-window helper tests: `8 passed`.
- Full pytest with coverage fail-under disabled: `1856 passed`, `784 warnings`,
  `54 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `80.6757%`, below the 95% gate (`1856 passed`, `785 warnings`,
  `54 subtests passed`).
- Full branch-aware coverage after the required 95% gate attempt: `80.6757%` displayed as `81%`.
- Statement coverage: `84.4285%` displayed as `84%`.
- Branch coverage: `68.2067%` displayed as `68%`.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is
`11131` missing lines and `6840` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `13322` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1084` missing lines, `503` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `796` missing lines, `410` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `398` missing lines, `230` missing branches
4. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
5. `isrc_manager/history/manager.py` - `176` missing lines, `131` missing branches
6. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
7. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
8. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
9. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
10. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches

Recommended next batch:

- Batch H1: continue `main_window.py` with backup/restore, catalog choice, GS1, clipboard/media
  routing, and storage-conversion workflow branches that require more specific fake hosts.
- Batch H2: `contract_templates/dialogs.py` draft save/export/delete, revision activation/rescan,
  placeholder rebind, selector generation, and modal/failure branches.
- Batch H3: `media/preview_dialogs.py` active load result, source loading, preload cache eviction,
  artwork/bookmark/volume/equalizer branches.
- Batch H4: deeper `history/manager.py` cleanup, retention, compaction, missing-file, and snapshot
  archive restore branches.

## 4.8) Coverage implementation update - 2026-05-26 06:11:06 UTC

This continuation used the latest full-suite gap map and targeted the second-largest remaining
cluster, `contract_templates/dialogs.py`. The batch deepened behavioural coverage around the
contract-template dockable workspace host and live HTML fill-preview controller. It stayed
headless-safe by using real Qt dock widgets/labels/scroll areas for local widget state, and fake
panel/export/template services only at file-system and preview-materialization boundaries.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `80.6757%` displayed as `81%`
- statement coverage: `84.4285%` displayed as `84%`
- branch coverage: `68.2067%` displayed as `68%`
- missing lines: `11131`
- missing branches: `6840`

Final measured checkpoint from the full-suite `--cov-fail-under=0` run:

- total branch-aware coverage: `80.8284%` displayed as `81%`
- statement coverage: `84.5684%` displayed as `85%`
- branch coverage: `68.4020%` displayed as `68%`
- missing lines: `11031`
- missing branches: `6798`

Tests added or expanded in this continuation:

- `tests/contract_templates/test_workspace_layout_helpers.py`
  - real `_DockableWorkspaceTab` lock/unlock, pending-state compatibility, layout normalization,
    capture fallback, reset, scroll-content repair, menu synchronization, dock registration
    recovery, saved visibility restoration, move/float/hide commands, layout-event ignore reasons,
    compaction branching, title-bar menu state, drag-to-float, and context-menu routing.
  - `_FillHtmlPreviewController` initialization, stale status updates, pending/active temp-tree
    cleanup, non-JSON payload keys, runtime preview source failure/signature fallback, no-view and
    no-revision refresh skips, materialization success, load rejection cleanup, materialization
    failure, stale pending replacement, race cleanup, ignored load completions, and delete-tree
    exception swallowing.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/contract_templates/dialogs.py`: `74.9377%` to `77.8470%`
  - missing lines: `796` to `697`
  - missing branches: `410` to `369`

No broad coverage exclusions, skips, xfails, root uppercase feature imports, or `--cov=ISRC_manager`
entries were added. No production code or new testability seams were added in this continuation.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_workspace_layout_helpers.py --no-cov
.venv/bin/python -m black tests/contract_templates/test_workspace_layout_helpers.py
.venv/bin/python -m ruff check tests/contract_templates/test_workspace_layout_helpers.py
.venv/bin/python -m coverage erase && rm -rf htmlcov coverage.json && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused contract-template workspace helper tests: `9 passed`.
- Full pytest with coverage fail-under disabled: `1860 passed`, `784 warnings`,
  `54 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `80.8284%`, below the 95% gate (`1860 passed`, `785 warnings`,
  `54 subtests passed`).
- Full branch-aware coverage after the required 95% gate attempt: `80.8284%` displayed as `81%`.
- Statement coverage: `84.5684%` displayed as `85%`.
- Branch coverage: `68.4020%` displayed as `68%`.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is
`11031` missing lines and `6798` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `13180` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1084` missing lines, `503` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `697` missing lines, `369` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `398` missing lines, `230` missing branches
4. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
5. `isrc_manager/history/manager.py` - `176` missing lines, `131` missing branches
6. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
7. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
8. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
9. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
10. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches

Recommended next batch:

- Batch I1: continue `main_window.py` backup/restore, catalog choice, GS1, clipboard/media routing,
  and storage-conversion callback workflows.
- Batch I2: continue `contract_templates/dialogs.py` with draft save/export/delete, revision
  activation/rescan, placeholder rebind, selector generation, and modal/failure branches outside
  the workspace-layout host.
- Batch I3: `media/preview_dialogs.py` active load result, source loading, preload cache eviction,
  artwork/bookmark/volume/equalizer branches.
- Batch I4: deeper `history/manager.py` cleanup, retention, compaction, missing-file, and snapshot
  archive restore branches.

## 4.9) Coverage implementation update - 2026-05-26 06:43:48 UTC

This continuation used the latest validated gap evidence after the contract-template dialog batch.
`history/manager.py` remained a worthwhile future target, but it had already moved to `86.6927%`,
while `media/preview_dialogs.py` was the next safer high-value GUI workflow cluster with a larger
combined line/branch gap. The batch therefore targeted `media/preview_dialogs.py` with headless-safe
behavioural tests around image preview gestures/export, HiDPI artwork label behaviour, audio preview
transport state, album scope, equalizer propagation, bookmarks, and play-next routing.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `80.8284%` displayed as `81%`
- statement coverage: `84.5684%` displayed as `85%`
- branch coverage: `68.4020%` displayed as `68%`
- missing lines: `11031`
- missing branches: `6798`

Final measured checkpoint from the required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `80.9908%` displayed as `81%`
- statement coverage: `84.7166%` displayed as `85%`
- branch coverage: `68.6111%` displayed as `69%`
- missing lines: `10925`
- missing branches: `6753`

Tests added or expanded in this continuation:

- `tests/test_media_preview_preload.py`
  - `_ImagePreviewDialog` invalid/valid image loading, fit/explicit zoom, Ctrl-wheel, native zoom,
    pinch gestures, double-click reset, export picker payloads, empty-image no-op export, and
    `_HiDpiArtworkLabel` target sizing, activation, and clear behaviour.
  - `_AudioPreviewDialog` loop/shuffle/auto-advance button synchronization, album-scope title
    fallback and track ordering, album menu rebuilds, equalizer settings propagation/dialog reuse,
    bookmark load/failure/menu/add/remove/clear paths, and play-next placeholder/current/next-track
    routing with fake app services and real headless Qt widgets.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/media/preview_dialogs.py`: `81.0386%` to `85.5374%`
  - missing lines: `398` to `293`
  - missing branches: `230` to `186`

No broad coverage exclusions, skips, xfails, root uppercase feature imports, `--cov=ISRC_manager`
entries, production-code edits, or new testability seams were added in this continuation.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_media_preview_preload.py --no-cov
.venv/bin/python -m black tests/test_media_preview_preload.py
.venv/bin/python -m ruff check tests/test_media_preview_preload.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Focused media preview tests: `15 passed`.
- Full pytest with coverage fail-under disabled: `1862 passed`, `785 warnings`,
  `54 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `80.9908%`, below the 95% gate (`1862 passed`, `784 warnings`,
  `54 subtests passed`).
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is
`10925` missing lines and `6753` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `13029` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1084` missing lines, `503` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `697` missing lines, `369` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
4. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
5. `isrc_manager/history/manager.py` - `176` missing lines, `131` missing branches
6. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
7. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
8. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
9. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
10. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches

Remaining `media/preview_dialogs.py` gaps are now concentrated in line/branch clusters around
image-preview show/resize/paint fallback paths (`199-399`), audio icon and transport button
construction/fallback paths (`1533-1809`), active audio load/preload/cache/waveform orchestration
(`2701-3457`), and artwork context-menu/export, volume/gain, navigation/end-of-media, visualization,
and cleanup branches (`3522-3903`).

Recommended next batch:

- Batch J1: continue `main_window.py` backup/restore, catalog choice, GS1, clipboard/media routing,
  and storage-conversion callback workflows.
- Batch J2: continue `contract_templates/dialogs.py` draft save/export/delete, revision activation,
  rescan/rebind, selector generation, and modal/failure branches outside the workspace host.
- Batch J3: continue `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch J4: deeper `history/manager.py` cleanup, retention, compaction, missing-file, and snapshot
  archive restore branches.

## 4.10) Coverage implementation update - 2026-05-26 07:06:35 UTC

This continuation returned to `history/manager.py` as requested for the recovery-heavy coverage
campaign. The batch targeted behavioural recovery and corrupted-state paths that were still visible
in the coverage report: snapshot-action rollback cleanup failure handling, history invariant repair,
dangling snapshot references, corrupted sidecars and inferred metadata, artifact quarantine scrubbing,
managed-file clone/restore rollback boundaries, and setting-payload validation/fallback branches.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `80.9908%` displayed as `81%`
- statement coverage: `84.7166%` displayed as `85%`
- branch coverage: `68.6111%` displayed as `69%`
- missing lines: `10925`
- missing branches: `6753`

Final measured checkpoint from the required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `81.1123%` displayed as `81%`
- statement coverage: `84.8202%` displayed as `85%`
- branch coverage: `68.7924%` displayed as `69%`
- missing lines: `10851`
- missing branches: `6714`

Tests added or expanded in this continuation:

- `tests/history/test_history_recovery.py`
  - snapshot restore-as-action preserves the original recording failure when rollback restore and
    cleanup both fail.
  - recovery repair clears stale history heads, normalizes corrupted non-state reversible rows,
    re-links children around event rows, and disables dangling snapshot references.
  - recovery metadata helpers tolerate corrupted/non-dict sidecars and infer snapshot/backup
    metadata from orphan files and asset directories.
  - artifact quarantine scrubs nested snapshot IDs and artifact-root paths from payload, inverse,
    and redo JSON while rehoming the current history head.
  - managed-state clone/restore boundaries cover missing managed roots, stale clone destinations,
    missing snapshot asset directories, and aggregated external rollback errors.
  - setting payload application covers legacy identity, artist code, theme-library JSON, SENA/BTW/
    BUMA fields, owner-party clearing, invalid theme payloads, and unknown-key failures.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/history/manager.py`: `86.6927%` to `91.6775%`
  - missing lines: `176` to `101`
  - missing branches: `131` to `91`

No broad coverage exclusions, skips, xfails, root uppercase feature imports, `--cov=ISRC_manager`
entries, production-code edits, or new testability seams were added in this continuation.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/history/test_history_recovery.py --no-cov
.venv/bin/python -m black tests/history/test_history_recovery.py
.venv/bin/python -m ruff check tests/history/test_history_recovery.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Focused history recovery tests: `15 passed`.
- Full pytest with coverage fail-under disabled: `1868 passed`, `785 warnings`,
  `54 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.1123%`, below the 95% gate (`1868 passed`, `716 warnings`,
  `54 subtests passed`).
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is
`10851` missing lines and `6714` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `12916` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1084` missing lines, `503` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `697` missing lines, `369` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
4. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
5. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
6. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
7. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
8. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
9. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
10. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches

Remaining `history/manager.py` gaps are now smaller and concentrated around redo-plan boundary
failures (`738`, `794-802`), snapshot replay failure rollback and low-level inverse dispatch
branches (`1420-1532`, `1627-1669`), snapshot restore and insert failure boundaries
(`1715-1867`), deeper undo-tree normalization/bootstrap branches (`1962-2251`), sidecar write
failure swallowing and archive gaps (`2332-2595`), snapshot-protection/quarantine/path exception
branches (`2651-2909`), serialization/coalescing/update errors (`3133-3172`), and timestamp helpers
(`3210`).

Recommended next batch:

- Batch K1: continue `main_window.py` backup/restore, catalog choice, GS1, clipboard/media routing,
  and storage-conversion callback workflows.
- Batch K2: continue `contract_templates/dialogs.py` draft save/export/delete, revision activation,
  rescan/rebind, selector generation, and modal/failure branches outside the workspace host.
- Batch K3: continue `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch K4: finish the compact remaining `history/manager.py` redo-plan/replay rollback/sidecar
  failure branches once the larger GUI/workflow gaps have moved.

## 4.11) Coverage implementation update - 2026-05-26 07:21:51 UTC

This continuation used the refreshed 4.10 coverage evidence to target `main_window.py`, which had
become the largest remaining combined line/branch gap after the recovery-heavy history batch. The
tests stayed headless-safe and exercised startup/runtime workflow helpers directly with fake
feedback controllers, fake message boxes, and narrow object seams instead of launching a brittle
full-window flow.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `81.1123%` displayed as `81%`
- statement coverage: `84.8202%` displayed as `85%`
- branch coverage: `68.7924%` displayed as `69%`
- missing lines: `10851`
- missing branches: `6714`

Final measured checkpoint from the required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `81.2166%` displayed as `81%`
- statement coverage: `84.9209%` displayed as `85%`
- branch coverage: `68.9086%` displayed as `69%`
- missing lines: `10779`
- missing branches: `6689`

Tests added or expanded in this continuation:

- `tests/test_main_window_helpers.py`
  - startup feedback tracker paths for phase changes, weighted progress, tracker callbacks,
    fallback status reporting, completed-feedback no-ops, and storage startup progress draining.
  - startup splash suspend/resume boundaries, including controller exceptions that must still
    drain Qt events.
  - runtime loading-feedback helpers for phase/status/progress fallbacks, invalid progress input,
    tracker delegation, finish failure swallowing, and feedback creation without a full app shell.
  - startup-ready gating across workspace, catalog refresh, waveform cache, signal emission, and
    modal startup message box suspend/resume behaviour with fake `QMessageBox` instances.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/main_window.py`: `73.3591%` to `75.0210%`
  - missing lines: `1084` to `1011`
  - missing branches: `503` to `477`

No production-code edits, broad coverage exclusions, skips, xfails, root uppercase feature imports,
`--cov=ISRC_manager` entries, or new GUI timing sleeps were added in this continuation.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov
.venv/bin/python -m black tests/test_main_window_helpers.py
.venv/bin/python -m ruff check tests/test_main_window_helpers.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Focused main-window helper tests: `10 passed`.
- Full pytest with coverage fail-under disabled: `1870 passed`, `784 warnings`,
  `54 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.2166%`, below the 95% gate (`1870 passed`, `775 warnings`,
  `54 subtests passed`).
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is
`10779` missing lines and `6689` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `12817` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1011` missing lines, `477` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `697` missing lines, `369` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
4. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
5. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
6. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
7. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
8. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
9. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
10. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches

Remaining `main_window.py` gaps are still concentrated around the Qt message filter and full App
bootstrap branches (`719-736`, `1012-1013`), remaining startup feedback error/no-op fallbacks
(`1194`, `1242-1262`, `1377-1382`), and much larger workflow clusters in backup/restore,
catalog/media routing, GS1/storage conversion, menu/dock wiring, diagnostics, update, and
settings/action dispatch paths.

Recommended next batch:

- Batch L1: continue `main_window.py` backup/restore, catalog/media routing, GS1/storage conversion,
  and settings/action dispatch workflow helpers with fake controllers and prompt services.
- Batch L2: continue `contract_templates/dialogs.py` draft save/export/delete, revision activation,
  rescan/rebind, selector generation, and modal/failure branches outside the workspace host.
- Batch L3: continue `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch L4: finish the compact remaining `history/manager.py` redo-plan/replay rollback/sidecar
  failure branches once the larger GUI/workflow gaps have moved.

## 4.12) Coverage implementation update - 2026-05-26 07:50:04 UTC

This continuation targeted `contract_templates/dialogs.py`, the second-largest remaining GUI/workflow
gap. The batch focused on behavioural failure and no-profile paths in the contract-template workspace
panel: empty service states, draft save validation failures, rollback-delete failure handling, draft
load failures, export failures and warning paths, latest-PDF no-op/open-failure paths, and safe status
updates for headless GUI workflows.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `81.2166%` displayed as `81%`
- statement coverage: `84.9209%` displayed as `85%`
- branch coverage: `68.9086%` displayed as `69%`
- missing lines: `10779`
- missing branches: `6689`

Final measured checkpoint from the required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `81.3080%` displayed as `81%`
- statement coverage: `85.0160%` displayed as `85%`
- branch coverage: `68.9876%` displayed as `69%`
- missing lines: `10711`
- missing branches: `6672`

Tests added or expanded in this continuation:

- `tests/contract_templates/test_dialogs.py`
  - profileless workspace services keep the symbol, fill, export, preview, and admin tabs in safe
    empty states with actionable status text instead of assuming a loaded profile.
  - draft save failure paths cover registry validation rejection, registry assignment failure after
    draft creation, rollback deletion failure swallowing, warning prompts, and retained failed draft
    evidence.
  - draft load/export/open paths cover no selected draft, missing revision during load, missing export
    service, PDF export exception prompts, export warning text, no retained PDF artifact, and failed
    external open status.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/contract_templates/dialogs.py`: `77.8470%` to `79.6135%`
  - missing lines: `697` to `629`
  - missing branches: `369` to `352`

No production-code edits, broad coverage exclusions, skips, xfails, root uppercase feature imports,
`--cov=ISRC_manager` entries, or brittle full-window flows were added in this continuation. Message
boxes and external file opening were mocked as external boundaries.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py -k "profileless_services or draft_save_failure or load_export_preview" --no-cov
.venv/bin/python -m black tests/contract_templates/test_dialogs.py
.venv/bin/python -m ruff check tests/contract_templates/test_dialogs.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Focused contract-template dialog tests: `3 passed`, `66 deselected`.
- Full contract-template dialog test module: `69 passed`.
- Full pytest with coverage fail-under disabled: `1873 passed`, `769 warnings`,
  `54 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.3080%`, below the 95% gate (`1873 passed`, `785 warnings`,
  `54 subtests passed`).
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is
`10711` missing lines and `6672` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `12734` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1011` missing lines, `477` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `629` missing lines, `352` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
4. `isrc_manager/contract_templates/export_service.py` - `209` missing lines, `140` missing branches
5. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
6. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
7. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
8. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
9. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
10. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches

Remaining `contract_templates/dialogs.py` gaps are concentrated around interactive HTML preview
zoom/fit fallback branches (`318-589`), dock restore/repair geometry and scroll-content recovery
(`1031-1476`), preview runtime rebuild/disposal edge cases (`2203-2271`), import/admin action
branches (`3025-3751`, `4486+`), form-definition error and warning variants (`3910-3982`), and
additional admin draft/archive/delete/artifact action prompts and failure paths.

Recommended next batch:

- Batch M1: continue `main_window.py` backup/restore, catalog/media routing, GS1/storage conversion,
  and settings/action dispatch workflow helpers with fake controllers and prompt services.
- Batch M2: continue `contract_templates/dialogs.py` admin action/delete/archive/artifact prompts,
  import cancellation/failure, form-definition error variants, and remaining preview rebuild/fallback
  branches.
- Batch M3: continue `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch M4: target `contract_templates/export_service.py` and `contract_templates/service.py` with
  transaction, missing-file, registry-conflict, PDF/HTML conversion, cleanup, and rollback tests.

## 4.13) Coverage implementation update - 2026-05-26 08:12:26 UTC

This continuation targeted `contract_templates/export_service.py` after the refreshed coverage
evidence showed it was the safest high-value non-GUI workflow target in the top remaining gaps. The
batch focused on behavioural export and preview workflows rather than constructor/import checks:
WebEngine load/print/missing-output failures, missing draft/revision/template states, unsupported
normalization, duplicate control and stale catalog selection paths, missing collaborator services,
registry service boundaries, HTML preview source/prune failures, DOCX replacement recovery, managed
artifact storage failures, and Pages/PDF fallback paths.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `81.3080%` displayed as `81%`
- statement coverage: `85.0160%` displayed as `85%`
- branch coverage: `68.9876%` displayed as `69%`
- missing lines: `10711`
- missing branches: `6672`

Final measured checkpoint from this continuation's required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `81.5714%` displayed as `82%`
- statement coverage: `85.2203%` displayed as `85%`
- branch coverage: `69.4478%` displayed as `69%`
- missing lines: `10565`
- missing branches: `6573`

Tests added or expanded in this continuation:

- `tests/contract_templates/test_export_service.py`
  - deterministic Qt WebEngine adapter tests for file load failure, HTML load failure, print failure,
    missing output, timeout guard, view creation, and base URL resolution.
  - export workflow failures for missing drafts, missing revisions, missing templates, and revisions
    that cannot be normalized into HTML working drafts.
  - payload resolution boundaries for duplicate numbers, removed catalog symbols, missing selections,
    iterated duplicate placeholders, and stale selected records.
  - catalog/registry boundary errors for missing owner settings reads, unavailable track/release/work/
    contract/party/right/asset/custom services, missing records, unsupported namespaces, and missing
    code registry services.
  - HTML preview synchronization/materialization failures and preview session pruning with bad keep
    paths.
  - DOCX replacement recovery for split placeholders and corrupted DOCX parts, plus render helper
    formatting, managed artifact storage failures, unsupported source formats, Pages availability
    failures, and HTML fallback PDF rendering.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/contract_templates/export_service.py`: `74.2245%` to `91.8759%`
  - missing lines: `209` to `65`
  - missing branches: `140` to `45`

Remaining `contract_templates/export_service.py` gaps are now concentrated around owner blank-value
aggregation lines (`416-419`, `478-487`), a few low-level path/timeout guard branches (`165`, `229`),
registry-generation no-selection branches (`745`, `750-756`), unavailable or missing work/right/asset
record variants (`774-812`), direct registry value generation/category error branches (`864-903`),
HTML preview clone fallback branches (`1103-1170`), draft storage/export HTML error branches
(`1305-1376`), Pages conversion temporary-file branches (`1436-1456`), and DOCX paragraph layout
fallback branches (`1496`, `1528`, `1542`).

No production-code edits, broad coverage exclusions, skips, xfails, root uppercase feature imports,
`--cov=ISRC_manager` entries, or brittle full-window flows were added in this continuation.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_export_service.py --no-cov
.venv/bin/python -m black tests/contract_templates/test_export_service.py
.venv/bin/python -m ruff check tests/contract_templates/test_export_service.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_export_service.py --cov=isrc_manager.contract_templates.export_service --cov-branch --cov-report=term-missing --cov-fail-under=0
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Focused export-service module tests: `31 passed`, `24 subtests passed`.
- Export-service focused coverage command: `31 passed`, `1 warning`, `24 subtests passed`; module
  coverage reached `91.8759%`.
- Full pytest with coverage fail-under disabled: `1879 passed`, `786 warnings`, `74 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.5714%`, below the 95% gate (`1879 passed`, `781 warnings`,
  `74 subtests passed`).
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `10565`
missing lines and `6573` missing branches. At the current denominator (`71483` statements plus
`21514` branches), roughly `12491` additional line/branch slots would need to be covered to reach
95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1011` missing lines, `477` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `629` missing lines, `352` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `291` missing lines, `185` missing branches
4. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
5. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
6. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches

Recommended next batch:

- Batch N1: continue `main_window.py` backup/restore, catalog/media routing, GS1/storage conversion,
  diagnostics, update, and settings/action dispatch workflow helpers with fake controllers and prompt
  services.
- Batch N2: continue `contract_templates/dialogs.py` admin action/delete/archive/artifact prompts,
  import cancellation/failure, form-definition error variants, and remaining preview rebuild/fallback
  branches.
- Batch N3: continue `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch N4: target `contract_templates/service.py` with transaction, missing-file, source package,
  registry-conflict, cleanup, and rollback tests now that export service moved below the largest-gap
  set.

## 4.14) Coverage implementation update - 2026-05-26 08:43:39 UTC

This continuation returned to `history/manager.py` as requested, using the refreshed coverage report
from the previous validated checkpoint. The batch focused on behavioural recovery and replay paths
rather than low-level import or constructor checks: snapshot replay failure rollback, file side-effect
rollback, missing snapshot/action payload failures, artifact/archive metadata repair boundaries,
sidecar write/reload failures, stale head cleanup, bootstrap decisions, JSON/path helpers, and
external-state no-op recovery.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `81.5714%` displayed as `82%`
- statement coverage: `85.2203%` displayed as `85%`
- branch coverage: `69.4478%` displayed as `69%`
- missing lines: `10565`
- missing branches: `6573`

Final measured checkpoint from this continuation's required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `81.6715%` displayed as `82%`
- statement coverage: `85.3042%` displayed as `85%`
- branch coverage: `69.6012%` displayed as `70%`
- missing lines: `10505`
- missing branches: `6540`

Tests added or expanded in this continuation:

- `tests/history/test_history_recovery.py`
  - added a local `HistoryEntry` factory for direct replay-path assertions without full-window or
    root-entrypoint involvement.
  - snapshot replay boundary tests for no-op snapshot entries, missing snapshot IDs, unknown action
    payloads, file-write restore payloads, missing snapshot action redo/undo payloads, and snapshot
    side-effect no-op/file restore behaviour.
  - rollback failure tests proving `_replay_entry` preserves the original restore error while still
    attempting file-state and snapshot-state rollback cleanup.
  - recovery artifact metadata tests for missing paths, invalid state shapes, archived snapshot path
    resolution, root normalization, integer collection, inferred snapshot manifests, and empty
    external-state restoration.
  - snapshot/backup persistence tests for explicit IDs, fetch/reload failure propagation, and
    sidecar write failures that must not poison database insertion.
  - invariant/bootstrap/helper boundary tests for stale `HistoryHead` cleanup, history-table
    readiness guards, status bootstrap decisions, setting-bundle coalescing negatives,
    JSON/path-loading fallbacks, and timestamp formatting.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/history/manager.py`: `91.6775%` to `95.8821%`
  - statement coverage: `93.7228%` to `97.5140%`
  - branch coverage: `86.9628%` to `92.1203%`
  - missing lines: `101` to `40`
  - missing branches: `91` to `55`

Remaining `history/manager.py` gaps after this batch:

- missing lines: `738`, `794`, `800`, `802`, `1420`, `1493-1495`, `1715-1716`,
  `1730`, `1733`, `1765`, `2122`, `2165`, `2176`, `2194`, `2216`, `2332-2339`,
  `2472`, `2651`, `2818`, `2821`, `2893-2894`, `2900-2903`, `2907-2909`, `3025`.
- missing branches are concentrated around early transaction/backup guards (`356`, `737-799`),
  status/coalescing/bootstrap fallbacks (`1054`, `1094`, `1175`, `1185`, `1419-1489`),
  snapshot archive and side-effect edge exits (`1729-1765`, `1974-2215`), cleanup/path loop
  boundaries (`2332-2472`), external-state manifest branches (`2618-2655`), and late invariant/
  repair bookkeeping branches (`2772-3025`).

No production-code edits, broad coverage exclusions, skips, xfails, root uppercase feature imports,
`--cov=ISRC_manager` entries, or brittle full-window flows were added in this continuation.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/history/test_history_recovery.py
.venv/bin/python -m ruff check tests/history/test_history_recovery.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/history/test_history_recovery.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/history --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/history --cov=isrc_manager.history.manager --cov-branch --cov-report=term-missing --cov-report=json:coverage-history-manager.json --cov-fail-under=0
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Focused recovery test file: `20 passed`, `4 subtests passed`.
- Full history package without coverage: `53 passed`, `4 subtests passed`.
- Focused history-manager coverage command: `53 passed`, `1 warning`, `4 subtests passed`; local
  focused module coverage reached `93.6714%`.
- Full pytest with coverage fail-under disabled: `1884 passed`, `767 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.6715%`, below the 95% gate (`1884 passed`, `767 warnings`,
  `78 subtests passed`).
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `10505`
missing lines and `6540` missing branches. At the current denominator (`71483` statements plus
`21514` branches), roughly `12396` additional line/branch slots would need to be covered to reach
95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `1011` missing lines, `477` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `629` missing lines, `352` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
4. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
5. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
6. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches

Recommended next batch:

- Batch O1: continue `main_window.py` backup/restore, catalog/media routing, GS1/storage conversion,
  diagnostics, update, and settings/action dispatch workflow helpers with fake controllers and prompt
  services.
- Batch O2: continue `contract_templates/dialogs.py` admin action/delete/archive/artifact prompts,
  import cancellation/failure, form-definition error variants, and remaining preview rebuild/fallback
  branches.
- Batch O3: continue `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch O4: target `contract_templates/service.py`, `exchange/service.py`, or
  `code_registry/service.py` with transaction, missing-file, source package, registry-conflict,
  cleanup, and rollback tests.

## 4.15) Coverage implementation update - 2026-05-26 09:16:02 UTC

This continuation used the validated `history/manager.py` checkpoint as the baseline, then moved to
the next largest and safest workflow target: history-adjacent helpers in `isrc_manager/main_window.py`.
The batch added behavioural tests around rollback, restore, prompt, background-task, and candidate
selection flows using fake managers, fake dialogs, and direct helper invocations instead of brittle
full-window UI automation.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `81.6715%` displayed as `82%`
- statement coverage: `85.3042%` displayed as `85%`
- branch coverage: `69.6012%` displayed as `70%`
- missing lines: `10505`
- missing branches: `6540`
- `isrc_manager/main_window.py`: `75.0210%`, with `1011` missing lines and `477`
  missing branches

Final measured checkpoint from this continuation's required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `81.8370%` displayed as `82%`
- statement coverage: `85.4609%` displayed as `85%`
- branch coverage: `69.7964%` displayed as `70%`
- missing lines: `10393`
- missing branches: `6498`
- `isrc_manager/main_window.py`: `77.6398%`, with `898` missing lines and `434`
  missing branches

Tests added or expanded in this continuation:

- `tests/test_main_window_helpers.py`
  - Qt message filter coverage for multimedia/font filtering, previous-handler forwarding,
    stderr fallback, and the already-installed early return.
  - setting-bundle and file-history action workflows covering unchanged no-op paths, capture/record
    success paths, mutation failure rollback, restore failure logging, callable labels, and payload
    factories.
  - undo/redo candidate selection across session history and profile history, including invalid
    timestamps, preferred direction selection, no-candidate exits, profile open/reload/delete, and
    exception reporting.
  - manual snapshot, snapshot deletion, backup deletion, snapshot restore, and history-dialog flows
    covering missing managers, prompt cancellation, denied background-task budget, success callbacks,
    and error callbacks.

Improved module coverage from the refreshed full-suite JSON:

- `isrc_manager/main_window.py`: `75.0210%` to `77.6398%`
  - statement coverage: now `81.3034%`
  - branch coverage: now `62.3917%`
  - missing lines: `1011` to `898`
  - missing branches: `477` to `434`

Remaining `main_window.py` gaps after this batch:

- early remaining missing lines begin at `1012`, `1013`, `1062`, `1194`, `1204`,
  `1205`, `1242`, `1248`, `1249`, `1256`, `1257`, `1262`, `1377-1382`,
  `1504`, `1601-1603`, `1609-1610`, `1639-1640`, `1668`, `1684`, `1696-1697`,
  `1720`, `1876`, `1879`, `1887`, `1900-1902`, `1921`, `1985`, `2035`,
  `2338`, `2341`, `2610`, `2692-2693`, `2796`, `2849-2850`, `2877`, `2880`,
  `2899`, `2988-2991`, `3024-3026`, `3042-3043`, `3140-3141`, `3184`,
  `3212-3213`, `3218-3219`, `3237`, `3261-3262`, `3277-3278`, `3282-3283`,
  `3300-3302`, `3309`, `3328-3329`, `3348-3349`, `3352-3353`, `3360`,
  `3407-3408`, `3410`, `3417-3424`, `3428`, `3430-3431`, and `3433`.
- remaining branch gaps are still concentrated around startup and settings guards
  (`1059->1065`, `1066->-1046`, `1122->-1118`, `1151->1156`, `1161->1166`,
  `1177->1183`, `1193->1194`, `1208->-1185`, `1222->1227`, `1241->1242`),
  action routing and dialog/update fallbacks, backup/restore and storage conversion workflows,
  catalog/media dispatch, diagnostics/report flows, and shutdown/history cleanup boundaries.

No production-code edits, broad coverage exclusions, skips, xfails, root uppercase feature imports,
`--cov=ISRC_manager` entries, or brittle full-window flows were added in this continuation.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/test_main_window_helpers.py
.venv/bin/python -m ruff check tests/test_main_window_helpers.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --cov=isrc_manager.main_window --cov-branch --cov-report=term-missing --cov-report=json:coverage-main-window-helper.json --cov-fail-under=0
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused main-window helper test file: `14 passed`.
- Focused main-window helper coverage command: `14 passed`.
- Full pytest with coverage fail-under disabled: `1888 passed`, `775 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.8370%`, below the 95% gate (`1888 passed`, `775 warnings`,
  `78 subtests passed`).
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`; the temporary
  focused `coverage-main-window-helper.json` artifact was removed.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `10393`
missing lines and `6498` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `12242` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `898` missing lines, `434` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `629` missing lines, `352` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
4. `isrc_manager/code_registry/workspace.py` - `180` missing lines, `60` missing branches
5. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
6. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
7. `isrc_manager/media/equalizer.py` - `171` missing lines, `58` missing branches
8. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches
11. `isrc_manager/contract_templates/service.py` - `156` missing lines, `137` missing branches
12. `isrc_manager/releases/dialogs.py` - `155` missing lines, `66` missing branches
13. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
14. `isrc_manager/application_settings_dialog.py` - `150` missing lines, `76` missing branches

Recommended next batch:

- Batch P1: continue `main_window.py` backup/restore, catalog/media routing, GS1/storage
  conversion, diagnostics, update, settings/action dispatch, and shutdown cleanup workflows with
  fake controllers, fake prompt services, and narrow helper assertions.
- Batch P2: continue `contract_templates/dialogs.py` admin action/delete/archive/artifact prompts,
  import cancellation/failure, form-definition error variants, and remaining preview rebuild/fallback
  branches.
- Batch P3: continue `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch P4: target `code_registry/workspace.py`, `contract_templates/service.py`,
  `exchange/service.py`, or `authenticity/service.py` with transaction, missing-file,
  registry-conflict, cleanup, and rollback tests.

## 4.16) Coverage implementation update - 2026-05-26 09:54:11 UTC

This continuation used coverage evidence from the validated history and main-window checkpoints.
`isrc_manager/history/manager.py` had already been raised to `95.8821%`, so the safer higher-value
target was `isrc_manager/contract_templates/dialogs.py`, then the second-largest remaining
GUI/workflow gap. The batch added headless behavioural workflow tests around admin import, revision
management, template mutation, draft, snapshot, artifact, selector-registry, manual-field, failure,
cancel, no-profile, and no-selection paths.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `81.8370%` displayed as `82%`
- statement coverage: `85.4609%` displayed as `85%`
- branch coverage: `69.7964%` displayed as `70%`
- missing lines: `10393`
- missing branches: `6498`
- `isrc_manager/contract_templates/dialogs.py`: `79.6135%`, with `629` missing lines and
  `352` missing branches

Implementation checkpoint before the final widget-branch fill test:

- total branch-aware coverage: `82.1984%` displayed as `82%`
- statement coverage: `85.8176%`
- branch coverage: `70.1729%`
- missing lines: `10138`
- missing branches: `6417`
- `isrc_manager/contract_templates/dialogs.py`: `86.4505%`, with `378` missing lines and
  `274` missing branches

Final measured checkpoint from this continuation's required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `82.3113%` displayed as `82%`
- statement coverage: `85.9225%` displayed as `86%`
- branch coverage: `70.3124%` displayed as `70%`
- missing lines: `10063`
- missing branches: `6387`
- `isrc_manager/contract_templates/dialogs.py`: `88.7157%`, with `301` missing lines and
  `242` missing branches

Tests added or expanded in this continuation:

- `tests/contract_templates/test_dialogs.py`
  - `test_admin_import_and_revision_workflows_cover_cancel_failure_and_success_paths`
    covers no-profile warnings, file-picker cancellation, input cancellation, create/import
    failures, successful DOCX import, revision cancellation, revision failure, revision success, and
    no-template guards.
  - `test_admin_template_mutation_actions_cover_confirm_archive_duplicate_and_delete_paths`
    covers duplicate failure/success, archive failure/success, restore/archive state transitions,
    destructive confirmation cancellation, delete-template failure, delete-with-files success, and
    no-selection duplicate guards.
  - `test_admin_revision_draft_and_artifact_actions_cover_lifecycle_error_paths`
    covers rescan/rebind/activate failure and success paths, missing-revision draft open warnings,
    export failure/success via fake export services, draft archive/restore, artifact open failure,
    artifact delete cancel/failure/success, and no-artifact guards.
  - `test_admin_draft_delete_actions_cover_confirmation_file_and_failure_paths`
    covers draft record delete cancellation, service failure, unmanaged-artifact safety warnings,
    record delete success, and no-selection guards.
  - `test_admin_actions_cover_profileless_and_no_selection_guardrails`
    covers broad admin action warning/info guardrails when services or selected rows are absent.
  - `test_fill_registry_generation_and_manual_widget_branches_cover_guardrails`
    covers selector-registry unavailable reasons, contract/track registry generation success,
    unsupported selector warnings, generated selector widgets, auto-field registry warnings,
    manual option widgets, date format combo synchronization, and text fallback widgets.

Improved module and aggregate coverage from the refreshed full-suite JSON:

- aggregate branch-aware coverage: `81.8370%` to `82.3113%`
  - statement coverage: `85.4609%` to `85.9225%`
  - branch coverage: `69.7964%` to `70.3124%`
  - missing lines: `10393` to `10063`
  - missing branches: `6498` to `6387`
- `isrc_manager/contract_templates/dialogs.py`: `79.6135%` to `88.7157%`
  - statement coverage: now `91.8605%`
  - branch coverage: now `78.2765%`
  - missing lines: `629` to `301`
  - missing branches: `352` to `242`

Remaining `contract_templates/dialogs.py` gaps after this batch:

- interactive HTML preview lifecycle and fallback internals, with missing lines around
  `318`, `386`, `412`, `441-488`, and `537-589`.
- workspace/dock layout and optional section branches around `1031`, `1172-1376`, `1412`,
  `1428`, `1473`, and `1476`.
- advanced admin workflow edge cases around `1660-1706`, `1959`, `1966`, `2203-2308`,
  `2405`, `2423`, `2777-2825`, and `3025-3070`.
- admin table selection fallbacks around `4806`, `4812`, `4815-4816`, `4840`, `4849`,
  `4858`, `4867`, `4908`, and `4956`.
- fill-form read/write, selector, and clipboard edge cases around `5202-5990`, `6050-6052`,
  `6181`, `6241-6256`, `6413`, `6415`, `6439`, and `6442`.

No production-code edits, broad coverage exclusions, skips, xfails, root uppercase feature imports,
`--cov=ISRC_manager` entries, or brittle full-window flows were added in this continuation.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/contract_templates/test_dialogs.py
.venv/bin/python -m ruff check tests/contract_templates/test_dialogs.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_admin_import_and_revision_workflows_cover_cancel_failure_and_success_paths tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_admin_template_mutation_actions_cover_confirm_archive_duplicate_and_delete_paths tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_admin_revision_draft_and_artifact_actions_cover_lifecycle_error_paths tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_admin_draft_delete_actions_cover_confirmation_file_and_failure_paths --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_admin_actions_cover_profileless_and_no_selection_guardrails --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_fill_registry_generation_and_manual_widget_branches_cover_guardrails --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused admin import/mutation/revision/draft delete tests: `4 passed`.
- Focused profileless/no-selection guardrail test: `1 passed`.
- Focused fill registry/manual widget test: `1 passed`.
- Full contract-template dialog test file: `75 passed`.
- Full pytest with coverage fail-under disabled: `1894 passed`, `775 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `82.3113%`, below the 95% gate (`1894 passed`, `775 warnings`,
  `78 subtests passed`).
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `10063`
missing lines and `6387` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `11801` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `898` missing lines, `434` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `301` missing lines, `242` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
4. `isrc_manager/contract_templates/service.py` - `154` missing lines, `136` missing branches
5. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
6. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
11. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
12. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
13. `isrc_manager/exchange/master_transfer.py` - `135` missing lines, `110` missing branches
14. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches

Recommended next batch:

- Batch Q1: continue `main_window.py` backup/restore, catalog/media routing, GS1/storage
  conversion, diagnostics, update, settings/action dispatch, and shutdown cleanup workflows with
  fake controllers and prompt services.
- Batch Q2: continue `contract_templates/dialogs.py` interactive HTML preview, workspace/dock
  layout, advanced admin edges, admin table fallbacks, fill-form read/write, selector, and clipboard
  branches.
- Batch Q3: target `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch Q4: target `contract_templates/service.py`, `exchange/service.py`,
  `code_registry/service.py`, or `authenticity/service.py` with transaction, missing-file,
  registry-conflict, cleanup, and rollback tests.

## 4.17) Coverage implementation update - 2026-05-26 10:21:08 UTC

This continuation stayed on `isrc_manager/contract_templates/dialogs.py` because the previous batch
left a compact, high-value fill-workflow helper cluster with real branch gaps. The added tests cover
draft selection and export readiness, HTML-preview state synchronization, widget read/write
semantics, indexed selector rebuilding, symbol detail refresh, manual placeholder preview guardrails,
registry-generation failure paths, and clipboard no-op guards.

Starting checkpoint from the previous validated full-suite JSON:

- total branch-aware coverage: `82.3113%` displayed as `82%`
- statement coverage: `85.9225%` displayed as `86%`
- branch coverage: `70.3124%` displayed as `70%`
- missing lines: `10063`
- missing branches: `6387`
- `isrc_manager/contract_templates/dialogs.py`: `88.7157%`, with `301` missing lines and
  `242` missing branches

Final measured checkpoint from this continuation's required full-suite `--cov-fail-under=95` run:

- total branch-aware coverage: `82.4489%` displayed as `82%`
- statement coverage: `86.0233%` displayed as `86%`
- branch coverage: `70.5727%` displayed as `71%`
- missing lines: `9991`
- missing branches: `6331`
- `isrc_manager/contract_templates/dialogs.py`: `91.3342%`, with `230` missing lines and
  `187` missing branches

Tests added or expanded in this continuation:

- `tests/contract_templates/test_dialogs.py`
  - expanded `test_fill_registry_generation_and_manual_widget_branches_cover_guardrails` for release
    registry service availability, selector-click forwarding, registry service absence, contract
    service absence, and auto-field registry success tooltip branches.
  - added `test_fill_draft_selection_export_and_preview_helper_edges` for combo absence/invalid data,
    successful admin draft open into the fill tab, draft-name defaults, storage-mode fallback, export
    status, latest PDF artifact lookup, clean/dirty export-draft readiness, and suspended/current HTML
    preview refresh states.
  - added `test_fill_widget_state_symbol_details_and_manual_helper_edges` for selector/manual widget
    resets, indexed selector counts and rebuild preservation, widget read/write semantics, date format
    synchronization, dirty-state preview refresh, symbol table fallback/selection, detail-panel
    rendering, manual symbol preview errors, fill combo change guards, draft change guards, and
    clipboard no-op paths.

Improved module and aggregate coverage from the refreshed full-suite JSON:

- aggregate branch-aware coverage: `82.3113%` to `82.4489%`
  - statement coverage: `85.9225%` to `86.0233%`
  - branch coverage: `70.3124%` to `70.5727%`
  - missing lines: `10063` to `9991`
  - missing branches: `6387` to `6331`
- `isrc_manager/contract_templates/dialogs.py`: `88.7157%` to `91.3342%`
  - statement coverage: now `93.7804%`
  - branch coverage: now `83.2136%`
  - missing lines: `301` to `230`
  - missing branches: `242` to `187`

Remaining `contract_templates/dialogs.py` gaps after this batch:

- interactive HTML preview and native input handling around `318`, `386`, `412`, `441-488`,
  `537-589`, plus early event branches `817-828`.
- dock/workspace layout state, restore, repair, and command edges around `1031`, `1172-1376`,
  `1412`, `1428`, `1473`, `1476`, `1524-1525`, and nearby branch arcs.
- advanced admin and import/revision edge cases around `1660-1706`, `1959-1966`, `2203-2308`,
  `2405`, `2423`, `2777-2825`, `3025-3070`, `3365-3371`, and `3451-4486`.
- admin table selection and source-path fallback edges around `4806`, `4812`, `4815-4816`,
  `4840`, `4849`, `4858`, `4867`, `4908`, `4956`, `5061-5095`.
- remaining fill-form edges are now narrow: draft delete-with-files cancellation/success refresh
  (`5311`, `5322-5324`), admin change handlers (`5397`, `5402`, `5413-5416`), table-selection
  absent-service guards (`5422`, `5425`), restore-selection item gaps (`5879`), and fallback
  placeholder branches (`6413`, `6415`).

No production-code edits, broad coverage exclusions, skips, xfails, root uppercase feature imports,
`--cov=ISRC_manager` entries, or brittle full-window flows were added in this continuation.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/contract_templates/test_dialogs.py
.venv/bin/python -m ruff check tests/contract_templates/test_dialogs.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_fill_draft_selection_export_and_preview_helper_edges tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_fill_widget_state_symbol_details_and_manual_helper_edges --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_fill_registry_generation_and_manual_widget_branches_cover_guardrails tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_fill_draft_selection_export_and_preview_helper_edges tests/contract_templates/test_dialogs.py::ContractTemplateWorkspacePanelBehaviorTests::test_fill_widget_state_symbol_details_and_manual_helper_edges --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused new fill helper tests: `2 passed`.
- Focused registry/fill helper trio: `3 passed`.
- Full contract-template dialog test file, isolated: `77 passed`.
- Full pytest with coverage fail-under disabled: `1896 passed`, `775 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `82.4489%`, below the 95% gate (`1896 passed`, `784 warnings`,
  `78 subtests passed`).
- Refreshed full coverage report preserved locally in `coverage.json` and `htmlcov/`.

An earlier full `tests/contract_templates/test_dialogs.py --no-cov` run was launched concurrently
with a second copy of the same Qt/WebEngine-heavy file and hit the known HTML-preview timing wait.
The same command was rerun in isolation and passed (`77 passed`); the isolated result is the
validation result for this checkpoint.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `9991`
missing lines and `6331` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `11673` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `898` missing lines, `434` missing branches
2. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
3. `isrc_manager/contract_templates/dialogs.py` - `230` missing lines, `187` missing branches
4. `isrc_manager/contract_templates/service.py` - `154` missing lines, `136` missing branches
5. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
6. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
11. `isrc_manager/storage_admin.py` - `148` missing lines, `103` missing branches
12. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
13. `isrc_manager/exchange/master_transfer.py` - `135` missing lines, `110` missing branches
14. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches

Recommended next batch:

- Batch R1: move back to `main_window.py` for backup/restore, catalog/media routing, GS1/storage
  conversion, diagnostics, update, settings/action dispatch, and shutdown cleanup workflows.
- Batch R2: target `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch R3: continue `contract_templates/dialogs.py` layout/repair/interactive-preview/admin-table
  branches, now that fill-form helpers have been substantially reduced.
- Batch R4: target `contract_templates/service.py`, `exchange/service.py`,
  `code_registry/service.py`, or `authenticity/service.py` with transaction, missing-file,
  registry-conflict, cleanup, and rollback tests.

## 4.18) Coverage implementation update - 2026-05-26 10:52:16 UTC

This continuation used the 4.17 coverage evidence to move back to
`isrc_manager/main_window.py`, which was the largest remaining line/branch gap and had compact
workflow clusters around database maintenance, album ordering, editor routing, and GS1 metadata
dialogs. The tests stayed headless-safe by using an unconstructed `App` instance with fake
message boxes, file dialogs, background task runners, database maintenance services, track
services, and dialog classes. No production-code edits were made.

### Before

Authoritative baseline from the previous full-suite `coverage.json`:

- Full branch-aware coverage: `82.4489%` displayed as `82%`.
- Statement coverage: `86.0233%` displayed as `86%`.
- Branch coverage: `70.5727%` displayed as `71%`.
- Covered/missing lines: `61492` covered, `9991` missing.
- Covered/missing branches: `15183` covered, `6331` missing.
- `isrc_manager/main_window.py`: `77.6398%`, with `898` missing lines and `434`
  missing branches.

### Tests added

Added the following behavioural workflow tests in `tests/test_main_window_helpers.py`:

- `test_main_window_database_maintenance_workflows_record_history_and_recover`
  - Covers missing-current-db backup guard, successful backup history recording, backup error
    callback routing, integrity verification event/audit recording, restore cancel/no-confirm
    paths, successful restore with safety-copy backup and snapshot action recording, worker error
    recovery, and restore finalization rollback via safety copy.
- `test_main_window_album_track_ordering_dialog_covers_noop_and_reorder_paths`
  - Covers no-profile and invalid-selection guards, album lookup failure, selected track not in an
    album group, dialog rejection, unchanged sequential order no-op, successful reorder worker
    mutation/history/progress/refresh/status paths, and missing reordered-track failure.
- `test_main_window_editor_and_gs1_routing_cover_selection_and_dialog_failures`
  - Covers edit dialog success and `ValueError`, selected-editor bool/no-selection/invalid-explicit
    branches, selected and explicit batch routing, GS1 no-selection/invalid-selection guards, GS1
    dialog success and `ValueError`, and catalog cell edit routing when a track id is missing or
    resolved.

These tests exercise real `App` methods and nested worker callbacks while replacing only external
boundaries such as dialogs, message boxes, background task submission, and service dependencies.

### After

Final authoritative coverage after the required `--cov-fail-under=95` run refreshed
`coverage.json`:

- Full branch-aware coverage: `82.7263%` displayed as `83%`.
- Statement coverage: `86.3142%` displayed as `86%`.
- Branch coverage: `70.8051%` displayed as `71%`.
- Covered/missing lines: `61700` covered, `9783` missing.
- Covered/missing branches: `15233` covered, `6281` missing.
- `isrc_manager/main_window.py`: `77.6398%` to `81.9708%`
  (`898` to `690` missing lines, `434` to `384` missing branches).
- Aggregate delta: `+0.2774` coverage points, `208` fewer missing lines, and `50` fewer
  missing branches.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/test_main_window_helpers.py
.venv/bin/python -m ruff check tests/test_main_window_helpers.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py::test_main_window_database_maintenance_workflows_record_history_and_recover tests/test_main_window_helpers.py::test_main_window_album_track_ordering_dialog_covers_noop_and_reorder_paths --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py::test_main_window_editor_and_gs1_routing_cover_selection_and_dialog_failures --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused database-maintenance and album-ordering tests: `2 passed`.
- Full main-window helper file after the first addition: `16 passed`.
- First full pytest with coverage fail-under disabled: `1898 passed`, `758 warnings`,
  `78 subtests passed`.
- Focused editor/GS1 routing test: `1 passed`.
- Full main-window helper file after the second addition: `17 passed`.
- Second full pytest with coverage fail-under disabled: `1899 passed`, `690 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `82.7263%`, below the 95% gate (`1899 passed`, `783 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `9783`
missing lines and `6281` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `11415` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `690` missing lines, `384` missing branches
2. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
3. `isrc_manager/contract_templates/dialogs.py` - `230` missing lines, `187` missing branches
4. `isrc_manager/contract_templates/service.py` - `154` missing lines, `136` missing branches
5. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
6. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
11. `isrc_manager/storage_admin.py` - `148` missing lines, `103` missing branches
12. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches

Recommended next batch:

- Batch S1: continue `main_window.py` around clipboard copy, duplicate track-number warnings,
  bulk audio/artwork attach, storage conversion submission, custom-field export/blob attachment,
  and delete workflow branches.
- Batch S2: target `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch S3: target `contract_templates/service.py`, `exchange/service.py`,
  `code_registry/service.py`, or `authenticity/service.py` with transaction, missing-file,
  registry-conflict, cleanup, and rollback tests.

## 4.19) Coverage implementation update - 2026-05-26 11:13:46 UTC

This continuation used the refreshed 4.18 coverage evidence before selecting the next batch target.
`isrc_manager/history/manager.py` was rechecked first because it was the original preferred starting
point, but the latest full-suite report showed it already at `95.8821%`, with `40` missing lines and
`55` missing branches. The safer, higher-value target remained `isrc_manager/main_window.py`, which
was still the largest combined line/branch gap and had compact helper/workflow paths identified by
the prior checkpoint.

No production-code changes were made in this continuation.

### Before

Authoritative baseline from checkpoint 4.18:

- Full branch-aware coverage: `82.7263%` displayed as `83%`.
- Statement coverage: `86.3142%` displayed as `86%`.
- Branch coverage: `70.8051%` displayed as `71%`.
- Covered/missing lines: `61700` covered, `9783` missing.
- Covered/missing branches: `15233` covered, `6281` missing.
- `isrc_manager/main_window.py`: `81.9708%`, with `690` missing lines and `384`
  missing branches.
- `isrc_manager/history/manager.py`: `95.8821%`, with `40` missing lines and `55`
  missing branches.

### Tests added

Added the following behavioural workflow tests in `tests/test_main_window_helpers.py`:

- `test_main_window_media_attach_helpers_cover_validation_matching_and_artwork_payloads`
  - Covers audio-duration widget application, media file picker cancellation/selection,
    duplicate-track-number warnings, candidate matching across exact/stem/track-number paths,
    missing/non-file media guards, album-art attachment planning, add-track media-source routing,
    and effective artwork payload fallback/override behaviour.
- `test_main_window_clipboard_helper_covers_empty_select_all_headers_and_sparse_cells`
  - Covers clipboard export with no model, select-all fallback copying all rows/headers, sparse
    selected indexes, empty cells, and empty-selection short-circuit behaviour.

These tests exercise real `App` helper methods while replacing only external boundaries such as
message boxes, file dialogs, clipboard setup, and lightweight service/widget dependencies.

### After

Final authoritative coverage after the required `--cov-fail-under=95` run refreshed
`coverage.json`:

- Full branch-aware coverage: `82.9156%` displayed as `83%`.
- Statement coverage: `86.4723%` displayed as `86%`.
- Branch coverage: `71.0979%` displayed as `71%`.
- Covered/missing lines: `61813` covered, `9670` missing.
- Covered/missing branches: `15296` covered, `6218` missing.
- `isrc_manager/main_window.py`: `81.9708%` to `84.9589%`
  (`690` to `576` missing lines, `384` to `320` missing branches).
- Aggregate delta: `+0.1893` coverage points, `113` fewer missing lines, and `63` fewer
  missing branches.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/test_main_window_helpers.py
.venv/bin/python -m ruff check tests/test_main_window_helpers.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py::test_main_window_media_attach_helpers_cover_validation_matching_and_artwork_payloads --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py::test_main_window_clipboard_helper_covers_empty_select_all_headers_and_sparse_cells tests/test_main_window_helpers.py::test_main_window_media_attach_helpers_cover_validation_matching_and_artwork_payloads --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused media-attach helper test: `1 passed`.
- Full main-window helper file after the media-attach addition: `18 passed`.
- Focused media-attach plus clipboard helper tests: `2 passed`.
- Full main-window helper file after the clipboard addition: `19 passed`.
- Full pytest with coverage fail-under disabled: `1901 passed`, `785 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `82.9156%`, below the 95% gate (`1901 passed`, `758 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `9670`
missing lines and `6218` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `11239` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `576` missing lines, `320` missing branches
2. `isrc_manager/media/preview_dialogs.py` - `293` missing lines, `186` missing branches
3. `isrc_manager/contract_templates/dialogs.py` - `230` missing lines, `187` missing branches
4. `isrc_manager/contract_templates/service.py` - `154` missing lines, `136` missing branches
5. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
6. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
7. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
8. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
11. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
12. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches

Recommended next batch:

- Batch T1: continue `main_window.py` around storage conversion submission, custom-field
  export/blob attachment, delete workflow branches, shutdown cleanup, and settings/update routing.
- Batch T2: target `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch T3: target `contract_templates/service.py`, `exchange/service.py`,
  `code_registry/service.py`, or `authenticity/service.py` with transaction, missing-file,
  registry-conflict, cleanup, and rollback tests.

## 4.20) Coverage implementation update - 2026-05-26 11:53:29 UTC

This continuation checked the requested `isrc_manager/history/manager.py` starting point against the
current full-suite evidence first. It was still already above the gate at `95.8821%`, with `40`
missing lines and `55` missing branches, while `isrc_manager/main_window.py` and
`isrc_manager/media/preview_dialogs.py` had much larger workflow gaps with safe fake-host seams.
The batch therefore continued with those higher-value GUI/workflow targets. No production-code
changes were made.

### Before

Authoritative baseline from checkpoint 4.19:

- Full branch-aware coverage: `82.9156%` displayed as `83%`.
- Statement coverage: `86.4723%` displayed as `86%`.
- Branch coverage: `71.0979%` displayed as `71%`.
- Covered/missing lines: `61813` covered, `9670` missing.
- Covered/missing branches: `15296` covered, `6218` missing.
- `isrc_manager/main_window.py`: `84.9589%`, with `576` missing lines and `320`
  missing branches.
- `isrc_manager/media/preview_dialogs.py`: `85.5374%`, with `293` missing lines and
  `186` missing branches.
- `isrc_manager/history/manager.py`: `95.8821%`, with `40` missing lines and `55`
  missing branches.

### Tests added

Added the following behavioural workflow tests:

- `tests/test_main_window_helpers.py::test_main_window_key_and_drop_event_routing_cover_handled_paths`
  - Covers delete, escape, enter-save, zoom event-filter, drag/drop accept/routing, and table
    space-preview paths through real `App` methods with fake event objects.
- `tests/test_main_window_helpers.py::test_main_window_storage_conversion_blob_export_and_badge_workflows`
  - Covers custom blob export and attach workflows, cancellation, prompt handling, background
    success/failure, attach rollback, storage-mode classification, conversion worker
    success/failure, commit-error, callback, badge, icon, tooltip, default-name, and track-list
    branches.
- `tests/test_main_window_helpers.py::test_main_window_table_header_layout_visibility_and_state_workflows`
  - Covers table settings prefixes, header-manager binding, header spec fallback/default-hidden
    behaviour, toggle/reorder success and failure, state save/load errors, action sync, and column
    visibility menu routing.
- `tests/test_media_preview_preload.py::test_audio_preview_dialog_active_load_cache_raw_and_submission_paths`
  - Covers cached preview application, waiting-preload fallback, inline active-load callback
    submission, track preview cache/inflight/fresh-load paths, raw preview cancellation, eviction,
    and state application.
- `tests/test_media_preview_preload.py::test_audio_preview_dialog_result_cache_cleanup_and_source_loading_paths`
  - Covers ignored, cancelled, stale, error, missing-state, success, and apply-fail active-load
    results, media disposal, preload cancellation with retained keys, cache/budget eviction, and
    prepared/raw audio-source loading.

These tests exercise workflow behaviour through narrow seams while replacing external dialogs,
message boxes, background task submission, file IO boundaries, and media services with deterministic
fakes.

### After

Final authoritative coverage after the required `--cov-fail-under=95` run refreshed
`coverage.json`:

- Full branch-aware coverage: `83.2328%` displayed as `83%`.
- Statement coverage: `86.7801%` displayed as `87%`.
- Branch coverage: `71.4465%` displayed as `71%`.
- Covered/missing lines: `62033` covered, `9450` missing.
- Covered/missing branches: `15371` covered, `6143` missing.
- `isrc_manager/main_window.py`: `84.9589%` to `87.7119%`
  (`576` to `457` missing lines, `320` to `275` missing branches).
- `isrc_manager/media/preview_dialogs.py`: `85.5374%` to `89.4626%`
  (`293` to `193` missing lines, `186` to `156` missing branches).
- Aggregate delta: `+0.3172` coverage points, `220` fewer missing lines, and `75` fewer
  missing branches.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/test_main_window_helpers.py
.venv/bin/python -m ruff check tests/test_main_window_helpers.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py::test_main_window_key_and_drop_event_routing_cover_handled_paths tests/test_main_window_helpers.py::test_main_window_storage_conversion_blob_export_and_badge_workflows --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py::test_main_window_table_header_layout_visibility_and_state_workflows --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov
.venv/bin/python -m black tests/test_media_preview_preload.py
.venv/bin/python -m ruff check tests/test_media_preview_preload.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_media_preview_preload.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py tests/test_media_preview_preload.py --no-cov
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused key/drop plus storage/blob workflow tests: `2 passed`.
- Focused table header/layout workflow test: `1 passed`.
- Full main-window helper file: `22 passed`.
- Full media preview preload file: `17 passed`.
- Combined touched helper files: `39 passed`.
- Full pytest with coverage fail-under disabled: `1906 passed`, `775 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `83.2328%`, below the 95% gate (`1906 passed`, `716 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `9450`
missing lines and `6143` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `10944` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `457` missing lines, `275` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `230` missing lines, `187` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `193` missing lines, `156` missing branches
4. `isrc_manager/contract_templates/service.py` - `154` missing lines, `136` missing branches
5. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
6. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
7. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
8. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
11. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
12. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches

Recommended next batch:

- Batch U1: continue `main_window.py` around delete workflow, shutdown cleanup, settings/update
  routing, diagnostics, bulk operations, and remaining storage conversion callbacks.
- Batch U2: continue `media/preview_dialogs.py` around artwork context menu/export, volume/gain,
  visualization release, preload cache boundary cases, and raw-source failures.
- Batch U3: target `contract_templates/dialogs.py` layout/repair/interactive-preview/admin-table
  branches, or move to `contract_templates/service.py`, `exchange/service.py`,
  `code_registry/service.py`, and `authenticity/service.py` transaction and rollback paths.

## 4.21) Coverage implementation update - 2026-05-26 12:10:56 UTC

This continuation targeted `isrc_manager/tracks/edit_dialog.py`, a named priority module that was
still below the gate at `92.1926%` despite strong statement coverage. The remaining gap was mostly
branch-heavy dialog construction, bulk-edit UI state, media hint, focus routing, missing-record,
menu, rollback, and commit-failure behaviour. No production-code changes were made.

### Before

Authoritative baseline from checkpoint 4.20:

- Full branch-aware coverage: `83.2328%` displayed as `83%`.
- Statement coverage: `86.7801%` displayed as `87%`.
- Branch coverage: `71.4465%` displayed as `71%`.
- Covered/missing lines: `62033` covered, `9450` missing.
- Covered/missing branches: `15371` covered, `6143` missing.
- `isrc_manager/tracks/edit_dialog.py`: `92.1926%`, with `62` missing lines and `58`
  missing branches.
- `isrc_manager/history/manager.py`: `95.8821%`, with `40` missing lines and `55`
  missing branches.

### Tests added

Added the following behavioural workflow tests in `tests/tracks/test_edit_dialog_behaviors.py`:

- `test_edit_dialog_constructor_covers_single_and_bulk_layout_branches`
  - Covers actual headless `EditDialog` construction for single and bulk edit modes, duplicate/blank
    combo source handling, managed database media display, BUMA work-managed read-only state, mixed
    bulk track/release/length notes, locked bulk media controls, shared artwork master hints, and
    same-value locked bulk length/date branches.
- `test_edit_dialog_remaining_helper_edges_cover_empty_missing_and_menu_paths`
  - Covers invalid/empty batch-id normalization, missing bulk snapshots, missing track service
    fallback, combo empty-current selection, bulk artist text fallbacks, artist authority refresh,
    broken line-edit focus fallback, disabled/missing-tab focus targets, database artwork display,
    owner-target filtering, one/many/no artwork master menu paths, fake menu execution, album-art
    controls, bulk state no-op branches, focus-target registration, and mixed media apply behaviour.
- `test_edit_dialog_remaining_constructor_focus_hint_and_commit_edges`
  - Covers no-saved-audio construction tooltip, initial-focus application, preferred focus widgets
    with direct and fallback line edits, successful focus routing, linked-work fallback when the
    registration number is blank, duplicate shared-art hint deduplication, and swallowed commit
    failures in single and bulk update success callbacks.

These tests use real PySide widgets where the behaviour depends on widget state and deterministic
fakes for profile services, message boxes, storage choices, history helpers, and background task
submission.

### After

Final authoritative coverage after the required `--cov-fail-under=95` run refreshed
`coverage.json`:

- Full branch-aware coverage: `83.3446%` displayed as `83%`.
- Statement coverage: `86.8668%` displayed as `87%`.
- Branch coverage: `71.6417%` displayed as `72%`.
- Covered/missing lines: `62095` covered, `9388` missing.
- Covered/missing branches: `15413` covered, `6101` missing.
- `isrc_manager/tracks/edit_dialog.py`: `92.1926%` to `98.0481%`
  (`62` to `8` missing lines, `58` to `22` missing branches).
- Aggregate delta: `+0.1118` coverage points, `62` fewer missing lines, and `42` fewer missing
  branches.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/tracks/test_edit_dialog_behaviors.py
.venv/bin/python -m ruff check tests/tracks/test_edit_dialog_behaviors.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/tracks/test_edit_dialog_behaviors.py --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/tracks/test_edit_dialog_behaviors.py --cov=isrc_manager.tracks.edit_dialog --cov-branch --cov-report=term-missing --cov-report=json:coverage-edit-dialog.json --cov-fail-under=0 -q
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Full edit-dialog behaviour file: `13 passed`.
- Targeted edit-dialog coverage check: `13 passed`; `isrc_manager/tracks/edit_dialog.py` measured
  `98%` in that isolated report.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `83.3446%`, below the 95% gate (`1909 passed`, `763 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `9388`
missing lines and `6101` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `10840` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `457` missing lines, `275` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `230` missing lines, `187` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `193` missing lines, `156` missing branches
4. `isrc_manager/contract_templates/service.py` - `154` missing lines, `136` missing branches
5. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
6. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
7. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
8. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
9. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
10. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
11. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
12. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches

Recommended next batch:

- Batch V1: return to `main_window.py` delete workflow, shutdown cleanup, settings/update routing,
  diagnostics, bulk operations, and remaining storage conversion callbacks.
- Batch V2: continue `contract_templates/dialogs.py` layout/repair/interactive-preview/admin-table
  branches, or target `contract_templates/service.py` transaction and revision-state branches.
- Batch V3: continue `media/preview_dialogs.py` around artwork export/context menus, volume/gain,
  visualization release, raw-source failures, and cache boundary cases.

## 4.22) Coverage implementation update - 2026-05-26 12:43:39 UTC

This continuation targeted `isrc_manager/contract_templates/service.py`, which was the largest
non-GUI service gap after the previous checkpoint. The batch added behavioural persistence and file
workflow coverage for template/revision guardrails, corrupted import state, managed-file cleanup,
storage conversion, placeholder inventory replacement, draft payload recovery, snapshot/artifact
cleanup, and template deletion cleanup. It also fixed a narrow production bug where corrupt HTML ZIP
archives leaked `zipfile.BadZipFile` instead of the contract-template ingestion error.

### Before

Authoritative baseline from checkpoint 4.21:

- Full branch-aware coverage: `83.3446%` displayed as `83%`.
- Statement coverage: `86.8668%` displayed as `87%`.
- Branch coverage: `71.6417%` displayed as `72%`.
- Covered/missing lines: `62095` covered, `9388` missing.
- Covered/missing branches: `15413` covered, `6101` missing.
- `isrc_manager/contract_templates/service.py`: `78.9855%`, with `154` missing lines and
  `136` missing branches.
- `isrc_manager/contract_templates/html_support.py`: `66.7832%`, with `62` missing lines and
  `33` missing branches.

### Tests and fix added

Added the following behavioural workflow tests in `tests/contract_templates/test_revision_service.py`:

- `test_template_revision_guardrails_assets_and_bad_imports_are_rolled_back`
  - Covers missing template/revision/source guards, corrupt HTML ZIP scan/import rollback, archived
    template listing, archived duplicate propagation, and revision asset normalization with blank
    asset payloads skipped.
- `test_revision_storage_html_resolution_and_inventory_edge_paths`
  - Covers missing revision lookup, unsupported scan dispatch, Pages conversion success/failure,
    corrupted database/blob state, missing managed revision files, revision storage conversion,
    HTML revision conversion rejection, unsupported HTML normalization, unavailable Pages
    normalization, Pages suffix coercion, HTML root resolution, docx/pages HTML support probes,
    placeholder inventory rollback, deduped placeholder occurrence counts, and binding replacement.
- `test_draft_payload_working_file_snapshot_artifact_and_delete_edges`
  - Covers draft update, archive/unarchive, list filtering, draft storage conversion, missing draft
    guards, corrupted database payloads, missing managed draft payloads, missing working files,
    relative managed working paths, unconfigured storage, resolved snapshots, output artifacts,
    artifact deletion, and draft deletion cleanup.
- `test_delete_template_removes_managed_sources_drafts_and_output_artifacts`
  - Covers full template deletion cleanup for managed HTML source bundles, draft payloads, working
    HTML trees, resolved snapshots, output artifacts, and repeated-delete guards.

Production fix:

- `isrc_manager/contract_templates/html_support.py` now converts unreadable ZIP archives from path
  and byte inputs into `ContractTemplateIngestionError`, preserving the service boundary used by
  scan/import workflows.

### After

Final authoritative coverage after the required `--cov-fail-under=95` run refreshed
`coverage.json`:

- Full branch-aware coverage: `83.5038%` displayed as `84%`.
- Statement coverage: `86.9840%` displayed as `87%`.
- Branch coverage: `71.9392%` displayed as `72%`.
- Covered/missing lines: `62184` covered, `9305` missing.
- Covered/missing branches: `15477` covered, `6037` missing.
- `isrc_manager/contract_templates/service.py`: `78.9855%` to `89.4928%`
  (`154` to `74` missing lines, `136` to `71` missing branches).
- `isrc_manager/contract_templates/html_support.py`: `66.7832%` to `68.4932%`
  (`62` to `59` missing lines, `33` missing branches unchanged after the added ZIP-error
  handling).
- Aggregate delta: `+0.1591` coverage points, `83` fewer missing lines, and `64` fewer missing
  branches. The production ZIP-error fix added six measured statements, so covered lines increased
  by `89`.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black isrc_manager/contract_templates/html_support.py tests/contract_templates/test_revision_service.py
.venv/bin/python -m ruff check isrc_manager/contract_templates/html_support.py tests/contract_templates/test_revision_service.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_revision_service.py --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_revision_service.py --cov=isrc_manager.contract_templates.service --cov=isrc_manager.contract_templates.html_support --cov-branch --cov-report=term-missing --cov-report=json:coverage-contract-template-service.json --cov-fail-under=0 -q
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused revision-service file: `16 passed`.
- Targeted service/html-support coverage check: `16 passed`; isolated report measured
  `isrc_manager/contract_templates/service.py` at `87.5362%`, while the final full-suite report
  measured the module at `89.4928%` with existing coverage combined.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `83.5038%`, below the 95% gate (`1913 passed`, `784 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in `coverage.json` and `htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The remaining measured gap is `9305`
missing lines and `6037` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `10692` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `457` missing lines, `275` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `230` missing lines, `187` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `193` missing lines, `156` missing branches
4. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
5. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
6. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
9. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
10. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
11. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
12. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches

Recommended next batch:

- Batch W1: return to `main_window.py` delete workflow, shutdown cleanup, settings/update routing,
  diagnostics, bulk operations, and remaining storage conversion callbacks.
- Batch W2: continue `contract_templates/dialogs.py` layout/repair/interactive-preview/admin-table
  branches now that the backing service has stronger behavioural coverage.
- Batch W3: continue `media/preview_dialogs.py` around artwork export/context menus, volume/gain,
  visualization release, raw-source failures, and cache boundary cases.

## 4.23) Coverage implementation update - 2026-05-26 13:00:49 UTC

This continuation targeted `isrc_manager/contract_templates/dialogs.py`, the largest focused GUI
workflow gap after `main_window.py`. `history/manager.py` was re-checked first as the requested
starting point, but the latest full coverage evidence already measured it above the module gate at
`95.8821%` overall (`97.5140%` statements, `92.1203%` branches), so the safer high-value target was
the contract template workspace/dialog host.

### Before

Authoritative baseline from checkpoint 4.22:

- Full branch-aware coverage: `83.5038%` displayed as `84%`.
- Statement coverage: `86.9840%` displayed as `87%`.
- Branch coverage: `71.9392%` displayed as `72%`.
- Covered/missing lines: `62184` covered, `9305` missing.
- Covered/missing branches: `15477` covered, `6037` missing.
- `isrc_manager/contract_templates/dialogs.py`: `91.3342%`, with `230` missing lines and
  `187` missing branches.
- `isrc_manager/history/manager.py`: `95.8821%`, with `40` missing lines and `55` missing
  branches.

### Tests added

Added headless-safe behavioural workflow tests in `tests/contract_templates/test_dialogs.py`:

- `test_workspace_host_layout_recovery_edges_cover_pending_and_normalizer_paths`
  - Exercises layout normalization reentrancy guards, failing normalizers, not-ready restore
    deferral, pending-state reuse, transient restore churn, legacy layout-version rejection, and
    dock-name compatibility rejection.
- `test_workspace_host_apply_pending_state_handles_missing_visibility_and_restore_errors`
  - Exercises pending layout restore with missing visibility metadata, `restoreState` failure
    recovery, pending-state cleanup, and panel action re-enablement.
- `test_workspace_host_compaction_resize_and_panel_runtime_edge_paths`
  - Exercises import/symbol layout reset no-ops when hosts are absent, visible-dock resize
    filtering and size clamping, floating-dock show hooks, HTML preview runtime cleanup with
    failing widget/layout calls, unavailable web-engine fallback paths, missing preview layout,
    no-view zoom handling, rebuild coalescing, and missing preview-host rebuild guards.

No production code changed in this continuation.

### After

Final authoritative coverage from the clean incremental full-suite run with `--cov-fail-under=0`:

- Full branch-aware coverage: `83.5489%` displayed as `84%`.
- Statement coverage: `87.0232%` displayed as `87%`.
- Branch coverage: `72.0043%` displayed as `72%`.
- Covered/missing lines: `62212` covered, `9277` missing.
- Covered/missing branches: `15491` covered, `6023` missing.
- `isrc_manager/contract_templates/dialogs.py`: `91.3342%` to `92.2070%`
  (`230` to `202` missing lines, `187` to `173` missing branches).
- `isrc_manager/history/manager.py`: remained `95.8821%` (`40` missing lines, `55` missing
  branches).
- Aggregate delta from checkpoint 4.22: `+0.0452` coverage points, `28` fewer missing lines, and
  `14` fewer missing branches.

The strict required gate was also run with `--cov-fail-under=95` before the clean incremental run.
The test body passed, then the command exited `1` because total coverage was still below 95%.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/contract_templates/test_dialogs.py
.venv/bin/python -m ruff check tests/contract_templates/test_dialogs.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py --cov=isrc_manager.contract_templates.dialogs --cov-branch --cov-report=term-missing --cov-report=json:coverage-contract-template-dialogs.json --cov-fail-under=0 -q
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
```

Observed result:

- Focused dialog file: passed.
- Targeted dialog coverage check: passed; isolated report measured
  `isrc_manager/contract_templates/dialogs.py` at `86.9285%`.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage remained below the 95% gate (`1916 passed`, `779 warnings`,
  `78 subtests passed`).
- Incremental full pytest with `--cov-fail-under=0`: passed (`1916 passed`, `768 warnings`,
  `78 subtests passed`) and refreshed `coverage.json`/`htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The latest preserved full report has
`9277` missing lines and `6023` missing branches. At the current denominator (`71489` statements
plus `21514` branches), `10650` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `457` missing lines, `275` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `202` missing lines, `173` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `193` missing lines, `156` missing branches
4. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
5. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
6. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
9. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
10. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
11. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
12. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches

Remaining `contract_templates/dialogs.py` gaps after this batch are concentrated around:

- interactive HTML preview view branches near lines `318-589`,
- workspace/action state and dock menu edges near lines `1240-1476`,
- preview runtime fallback paths near lines `2232-2308`,
- fill/admin workflow failure and selection branches near lines `3365-5425`,
- late preview/fill cleanup tails near lines `5879`, `6413`, and `6415`.

Recommended next batch:

- Batch X1: target `main_window.py` with narrow app-host/controller seams for delete workflow,
  shutdown cleanup, settings/update routing, diagnostics, bulk operations, and storage conversion
  callbacks.
- Batch X2: continue `contract_templates/dialogs.py` around interactive preview view branches,
  workspace action state, and fill/admin workflow selection/failure paths.
- Batch X3: target `media/preview_dialogs.py` around artwork export/context menus, volume/gain,
  visualization release, raw-source failures, and cache boundary cases.

## 4.24) Coverage implementation update - 2026-05-26 13:35:02 UTC

This continuation targeted `isrc_manager/main_window.py`, the largest remaining combined
line/branch gap. `history/manager.py` was checked again first as the requested starting point, but
the latest full coverage evidence still measures it above the module gate at `95.8821%` overall
(`97.5140%` statements, `92.1203%` branches). The higher-value workflow batch was therefore the
main-window host helpers and command-routing surfaces.

### Before

Authoritative baseline from checkpoint 4.23:

- Full branch-aware coverage: `83.5489%` displayed as `84%`.
- Statement coverage: `87.0232%` displayed as `87%`.
- Branch coverage: `72.0043%` displayed as `72%`.
- Covered/missing lines: `62212` covered, `9277` missing.
- Covered/missing branches: `15491` covered, `6023` missing.
- `isrc_manager/main_window.py`: `87.7119%`, with `457` missing lines and `275` missing
  branches.
- `isrc_manager/history/manager.py`: `95.8821%`, with `40` missing lines and `55` missing
  branches.

### Tests added

Expanded headless-safe behavioural workflow coverage in `tests/test_main_window_helpers.py`:

- `test_first_launch_close_workspace_and_add_track_guard_workflows`
  - Exercises first-launch settings prompt routing, background-task close guards, catalog manager
    no-profile diagnostics, workspace panel refresh/configuration, code registry/global-search
    profile guards, history cleanup dialog routing, diagnostics panel profile branches, add-data
    widget factories, add-track entry wiring, artist lookup, and media file filter/format helpers.
- `test_startup_feedback_logging_and_trace_edge_paths`
  - Exercises startup feedback controller reporting, loading feedback progress/status fallbacks,
    startup completion fallbacks, bootstrap log buffer flushing, logging handler cleanup failures,
    trace field normalization, trace context reserved-field handling, disabled trace logging, and
    structured log buffering/configured output paths.
- `test_background_task_submission_wrappers_cover_profile_lock_bundle_and_audit_paths`
  - Exercises profile-required task rejection, write-lock task submission, cancellation checks,
    worker progress completion callbacks, background bundle context handling, and schema audit
    callback success/failure paths.
- `test_table_layout_history_hint_and_resize_edge_paths`
  - Exercises table layout history suspension, refresh-after-history-change recovery paths, saved
    hint application, header reorder/resize history routing, signal bind/unbind failure handling,
    and compact row/column mode toggles.

The existing log-viewer helper test was also extended to cover a missing logs directory. No
production code changed in this continuation.

### After

Final authoritative coverage from the clean incremental full-suite run with `--cov-fail-under=0`:

- Full branch-aware coverage: `83.6844%` displayed as `84%`.
- Statement coverage: `87.1477%` displayed as `87%`.
- Branch coverage: `72.1763%` displayed as `72%`.
- Covered/missing lines: `62301` covered, `9188` missing.
- Covered/missing branches: `15528` covered, `5986` missing.
- `isrc_manager/main_window.py`: `89.8103%`
  (`457` to `368` missing lines, `275` to `239` missing branches).
- `isrc_manager/history/manager.py`: remained `95.8821%` (`40` missing lines, `55` missing
  branches).
- Aggregate delta from checkpoint 4.23: `+0.1355` coverage points, `89` fewer missing lines, and
  `37` fewer missing branches.

The strict required gate was also run with `--cov-fail-under=95` before the clean incremental run.
The test body passed, then the command exited `1` because total coverage was still below 95%.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/test_main_window_helpers.py
.venv/bin/python -m ruff check tests/test_main_window_helpers.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov -q
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
```

Observed result:

- Focused main-window helper file: passed (`26 passed`).
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage remained below the 95% gate (`1920 passed`, `768 warnings`,
  `78 subtests passed`).
- Incremental full pytest with `--cov-fail-under=0`: passed (`1920 passed`, `776 warnings`,
  `78 subtests passed`) and refreshed `coverage.json`/`htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The latest preserved full report has
`9188` missing lines and `5986` missing branches. At the current denominator (`71489` statements
plus `21514` branches), `10524` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `368` missing lines, `239` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `202` missing lines, `173` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `193` missing lines, `155` missing branches
4. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
5. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
6. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
9. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
10. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
11. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
12. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches

Remaining `main_window.py` gaps after this batch are concentrated around:

- startup/profile edge paths near lines `1012-1504`,
- search/filter/import/export and task-routing branches near lines `1876-3237`,
- diagnostics/settings/history command routing near lines `3467-4556`,
- shutdown/update/recovery callback tails near lines `4564-5704`,
- table/action state and storage conversion branches in the later GUI host methods.

Recommended next batch:

- Batch Y1: continue `main_window.py` around delete workflow, shutdown cleanup, settings/update
  routing, diagnostics, bulk operations, and storage conversion callbacks.
- Batch Y2: continue `contract_templates/dialogs.py` interactive preview, workspace action state,
  and fill/admin selection/failure branches.
- Batch Y3: target `media/preview_dialogs.py` artwork export/context menus, volume/gain,
  visualization release, raw-source failures, and cache boundary cases.

## 4.25) Coverage implementation update - 2026-05-26 13:59:51 UTC

This continuation stayed on `isrc_manager/main_window.py`, still the largest remaining combined
line/branch gap after checkpoint 4.24. The batch focused on additional headless-safe workflow seams
instead of broad window construction: shortcut routing, catalog zoom gesture handling, audit
failure handling, add-track lookup refresh, save validation exits, generated-ISRC failures, and
rollback paths.

### Before

Authoritative baseline from checkpoint 4.24:

- Full branch-aware coverage: `83.6844%` displayed as `84%`.
- Statement coverage: `87.1477%` displayed as `87%`.
- Branch coverage: `72.1763%` displayed as `72%`.
- Covered/missing lines: `62301` covered, `9188` missing.
- Covered/missing branches: `15528` covered, `5986` missing.
- `isrc_manager/main_window.py`: `89.8103%`, with `368` missing lines and `239` missing
  branches.
- `isrc_manager/history/manager.py`: `95.8821%`, with `40` missing lines and `55` missing
  branches.

### Tests added

Expanded behavioural workflow coverage in `tests/test_main_window_helpers.py`:

- `test_shortcut_zoom_audit_and_refresh_helper_edge_paths`
  - Exercises explicit shortcut registration duplicate/empty paths, disabled shortcut triggering,
    platform-aware shortcut ordering, help HTML rendering, AuditLog write/commit failure handling,
    background task status no-op routing, scaled UI progress fallbacks, edit-identity routing,
    catalog cleanup target collection, and workspace dock identity refresh.
- `test_catalog_zoom_gestures_and_add_track_lookup_edge_paths`
  - Exercises wheel/native/pinch zoom calculations and event routing, smart zoom reset, gesture
    no-op paths, saved zoom font scaling, add-track lookup refresh with duplicate/blank values,
    current-text preservation, catalog number refresh, and lazy add-track panel initialization.
- `test_save_validation_media_generation_and_rollback_paths`
  - Exercises save validation for missing title/artist, missing Work, invalid UPC/EAN, invalid
    ISWC, lossy-primary-audio cancellation, media-storage cancellation, generated-ISRC exhaustion,
    invalid generated-ISRC release, SQLite integrity rollback, and generic save rollback.

No production code changed in this continuation.

### After

Final authoritative coverage from the clean incremental full-suite run with `--cov-fail-under=0`:

- Full branch-aware coverage: `83.7919%` displayed as `84%`.
- Statement coverage: `87.2386%` displayed as `87%`.
- Branch coverage: `72.3389%` displayed as `72%`.
- Covered/missing lines: `62366` covered, `9123` missing.
- Covered/missing branches: `15563` covered, `5951` missing.
- `isrc_manager/main_window.py`: `91.5058%`
  (`368` to `303` missing lines, `239` to `203` missing branches).
- `isrc_manager/history/manager.py`: remained `95.8821%` (`40` missing lines, `55` missing
  branches).
- Aggregate delta from checkpoint 4.24: `+0.1075` coverage points, `65` fewer missing lines, and
  `35` fewer missing branches across the measured package.

The strict required gate was also run with `--cov-fail-under=95`. The test body passed, then the
command exited `1` because total coverage was still below 95%.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/test_main_window_helpers.py
.venv/bin/python -m ruff check tests/test_main_window_helpers.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_helpers.py --no-cov -q
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
```

Observed result:

- Focused main-window helper file: passed (`29 passed`).
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage remained below the 95% gate (`1923 passed`, `785 warnings`,
  `78 subtests passed`).
- Incremental full pytest with `--cov-fail-under=0`: passed (`1923 passed`, `784 warnings`,
  `78 subtests passed`) and refreshed `coverage.json`/`htmlcov/`.

### Remaining gap to 95%

The 95% target still requires additional behavioural batches. The latest preserved full report has
`9123` missing lines and `5951` missing branches. At the current denominator (`71489` statements
plus `21514` branches), `10424` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `303` missing lines, `203` missing branches
2. `isrc_manager/contract_templates/dialogs.py` - `202` missing lines, `173` missing branches
3. `isrc_manager/media/preview_dialogs.py` - `193` missing lines, `156` missing branches
4. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
5. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
6. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
7. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
8. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
9. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
10. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
11. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
12. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches

Remaining `main_window.py` gaps after this batch are concentrated around:

- startup/profile edge paths near lines `1012-1759`,
- history/dialog and background routing branches near lines `3184-4238`,
- command delegation/action-ribbon wrapper tails near lines `4322-4507`,
- track editor, GS1, conversion, and bulk media workflow branches near lines `5811-6719`,
- storage conversion/update/recovery callback tails in later GUI host methods.

Recommended next batch:

- Batch Z1: continue `main_window.py` around track editor/GS1 fallbacks, bulk media workflows,
  storage conversion callbacks, update/recovery shutdown tails, and remaining action-ribbon paths.
- Batch Z2: continue `contract_templates/dialogs.py` interactive preview, workspace action state,
  and fill/admin selection/failure branches.
- Batch Z3: target `media/preview_dialogs.py` artwork export/context menus, volume/gain,
  visualization release, raw-source failures, and cache boundary cases.

## Checkpoint 4.26 - 2026-05-26 14:23 UTC

This batch pivoted from `history/manager.py` after the latest coverage evidence showed that module
already above the module-level gate (`95.8821%`). The safer high-value target was
`isrc_manager/contract_templates/dialogs.py`, which still had a large GUI/workflow gap. No
production code changed.

### Tests added

Expanded behavioural workflow coverage in `tests/contract_templates/test_dialogs.py`:

- `test_html_preview_fit_fallbacks_measurement_failures_and_scroll_helpers`
  - Covers invalid zoom-owner normalization, non-fit scheduling no-ops, reset-to-fit fallback
    scheduling, fit application when already at target zoom, measurement callback failures,
    fallback content-size failures, retry/finalize behaviour after repeated measurement misses,
    wheel step dominance, JavaScript scroll routing, and native zoom-state reset.
- `test_fill_title_bar_menu_and_drag_guard_edges`
  - Covers locked/unlocked dock menu state, disabled floating when a dock disallows it, safe drag
    gating, event-position fallbacks, and release-event passthrough behaviour.
- `test_workspace_host_layout_integrity_repairs_scroll_boundary_states`
  - Covers exposed central-canvas detection boundaries, no-dock and non-widget central cases,
    visible scroll-content repair, swallowed repair exceptions, missing scroll content, and layout
    integrity failure for unrecoverable synthetic dock content.
- `test_fill_form_refresh_handles_empty_revision_and_corrupted_definition_states`
  - Covers fill refresh with no fill tab initialized, no templates, a selected template with no
    revisions, and corrupted form-definition construction.
- `test_fill_draft_create_and_html_sync_failures_keep_user_in_draft_context`
  - Covers draft database-create failure and saved-draft HTML working-copy synchronization failure
    without collapsing the user out of the current fill workflow.

### Coverage delta

Authoritative before baseline from checkpoint 4.25:

- Full branch-aware coverage: `83.7919%`.
- Statement coverage: `87.2386%`.
- Branch coverage: `72.3389%`.
- Covered/missing lines: `62366` covered, `9123` missing.
- Covered/missing branches: `15563` covered, `5951` missing.
- `isrc_manager/contract_templates/dialogs.py`: `92.2070%`, with `202` missing lines and `173`
  missing branches.

Authoritative after baseline from the latest full-suite run:

- Full branch-aware coverage: `83.9102%` displayed as `84%`.
- Statement coverage: `87.3519%` displayed as `87%`.
- Branch coverage: `72.4737%` displayed as `72%`.
- Covered/missing lines: `62447` covered, `9042` missing.
- Covered/missing branches: `15592` covered, `5922` missing.
- `isrc_manager/contract_templates/dialogs.py`: `94.4929%`
  (`202` to `121` missing lines, `173` to `144` missing branches).
- Aggregate delta from checkpoint 4.25: `+0.1183` coverage points, `81` fewer missing lines, and
  `29` fewer missing branches across the measured package.

The strict required gate was also run with `--cov-fail-under=95`. The test body passed, then the
command exited `1` because total coverage was still below 95%.

### Validation commands run in this continuation

```bash
.venv/bin/python -m black tests/contract_templates/test_dialogs.py
.venv/bin/python -m ruff check tests/contract_templates/test_dialogs.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py --no-cov -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py --cov=isrc_manager.contract_templates.dialogs --cov-branch --cov-report=term-missing --cov-report=json:coverage-contract-dialogs.json --cov-fail-under=0 -q
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused contract-template dialog file: passed (`86 passed`).
- Focused coverage probe: passed (`86 passed`) but was used only as a quick sanity check because
  repository coverage configuration still reports the wider measured package for that invocation.
  The temporary `coverage-contract-dialogs.json` probe artifact was removed.
- Compileall: passed.
- Ruff: passed.
- Black check: passed.
- mypy: passed.
- Incremental full pytest with `--cov-fail-under=0`: passed (`1928 passed`, `726 warnings`,
  `78 subtests passed`) and refreshed `coverage.json`/`htmlcov/`.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1` because
  coverage remained below the 95% gate (`1928 passed`, `768 warnings`, `78 subtests passed`;
  `83.91%` total coverage).

### Remaining gap to 95%

The latest full report has `9042` missing lines and `5922` missing branches. At the current
denominator (`71489` statements plus `21514` branches), `10314` additional line/branch slots would
need to be covered to reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `303` missing lines, `203` missing branches
2. `isrc_manager/media/preview_dialogs.py` - `193` missing lines, `156` missing branches
3. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
4. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
5. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
6. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
7. `isrc_manager/contract_templates/dialogs.py` - `121` missing lines, `144` missing branches
8. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
9. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
10. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
11. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
12. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches

Recommended next batch:

- Batch AA1: return to `main_window.py` for the largest remaining GUI host gaps, especially
  track editor/GS1 fallbacks, bulk media workflows, storage conversion callbacks,
  update/recovery shutdown tails, and action-ribbon routing.
- Batch AA2: target `media/preview_dialogs.py` for artwork export/context menu branches,
  volume/gain handling, visualization release, raw-source failures, and cache boundary cases.
- Batch AA3: continue `contract_templates/dialogs.py` only after the bigger remaining modules,
  focusing on admin table/button fallbacks, export/open/delete failure paths, WebEngine-unavailable
  preview setup, and restore-layout branches still listed in `coverage.json`.

## Checkpoint 4.27 - 2026-05-26 15:16 UTC

This batch continued the coverage campaign with `isrc_manager/media/preview_dialogs.py`. The
previous checkpoint already confirmed `history/manager.py` above the local module gate, while the
fresh full coverage report still showed `media/preview_dialogs.py` as the second-largest combined
GUI/workflow gap. No production code changed.

### Tests added or expanded

Expanded behavioural workflow coverage in `tests/test_media_preview_preload.py`:

- `test_audio_preview_preload_workers_cover_late_cancel_and_cleanup_failures`
  - Covers source fetch close-failure cleanup, preload-state close-failure cleanup, late
    cancellation after metadata fetch, duplicate preload cancellation checks, prepared-media
    disposal after state cancellation, and owned-source cleanup failure swallowing.
- `test_audio_preview_track_load_close_and_decode_cancel_edges`
  - Covers track-load connection close failures and cancellation after decode completes.
- `test_audio_preview_dialog_icon_menu_logging_and_selection_edge_guards`
  - Covers Windows PATH setup, media icon/window-icon fallback paths, invalid palette fallbacks,
    iconless button fallback text, media-stage guard returns, preload logging failure swallowing,
    empty/missing control guards, invalid album/bookmark/play-next data, and cached-state fallback
    application.
- `test_audio_preview_dialog_preload_cache_waveform_navigation_and_cleanup_edges`
  - Covers ignored preload results, disabled preload disposal, track-load result disposal guards,
    bridge-shutdown disposal, temp-file removal hazards, cached waveform rendering with no peaks,
    export-action filtering, artwork preview open/no-op paths, shuffle/order boundaries,
    navigation boundaries, end-of-media playlist restart, and reset-source exception swallowing.
- Expanded existing image and equalizer tests for image zoom ownership/event-filter paths and
  equalizer dialog synchronization after a dialog already exists.

### Coverage delta

Authoritative before baseline from checkpoint 4.26:

- Full branch-aware coverage: `83.9102%`.
- Statement coverage: `87.3519%`.
- Branch coverage: `72.4737%`.
- Covered/missing lines: `62447` covered, `9042` missing.
- Covered/missing branches: `15592` covered, `5922` missing.
- `isrc_manager/media/preview_dialogs.py`: `89.4626%`, with `193` missing lines and `156`
  missing branches.

Authoritative after baseline from the latest strict full-suite run:

- Full branch-aware coverage: `84.1338%` displayed as `84%`.
- Statement coverage: `87.5351%` displayed as `88%`.
- Branch coverage: `72.8316%` displayed as `73%`.
- Covered/missing lines: `62578` covered, `8911` missing.
- Covered/missing branches: `15669` covered, `5845` missing.
- `isrc_manager/media/preview_dialogs.py`: `95.7428%`
  (`193` to `62` missing lines, `156` to `79` missing branches).
- Aggregate delta from checkpoint 4.26: `+0.2236` coverage points, `131` fewer missing lines, and
  `77` fewer missing branches across the measured package.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_media_preview_preload.py --no-cov -q
.venv/bin/python -m ruff check tests/test_media_preview_preload.py --fix
.venv/bin/python -m black tests/test_media_preview_preload.py
.venv/bin/python -m ruff check tests/test_media_preview_preload.py
.venv/bin/python -m black --check tests/test_media_preview_preload.py
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
```

Observed result:

- Focused media preview file: passed (`21 passed`).
- Focused Ruff and Black checks for the touched test file: passed.
- mypy: passed.
- Incremental full pytest with `--cov-fail-under=0`: passed (`1932 passed`, `738 warnings`,
  `78 subtests passed`) and refreshed `coverage.json`/`htmlcov/`.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1` because
  coverage remained below the 95% gate (`1932 passed`, `784 warnings`, `78 subtests passed`;
  `84.13%` total coverage).

### Remaining gap to 95%

The latest full report has `8911` missing lines and `5845` missing branches. At the current
denominator (`71489` statements plus `21514` branches), `10106` additional line/branch slots would
need to be covered to reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `303` missing lines, `203` missing branches
2. `isrc_manager/exchange/service.py` - `169` missing lines, `118` missing branches
3. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
4. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
5. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
6. `isrc_manager/contract_templates/dialogs.py` - `121` missing lines, `144` missing branches
7. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
8. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
9. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
10. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
11. `isrc_manager/media/preview_dialogs.py` - `62` missing lines, `79` missing branches
12. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches

Remaining `media/preview_dialogs.py` line gaps are now concentrated at:

```text
287, 394, 398, 399, 858, 2088, 2360, 2395, 2496, 2497, 2583, 2584,
2877, 3086, 3087, 3150, 3160, 3161, 3162, 3163, 3228, 3229, 3257,
3258, 3409, 3421, 3443, 3537-3544, 3546-3547, 3589, 3604, 3609-3610,
3652-3653, 3659-3660, 3664-3668, 3677, 3680, 3719, 3751, 3769-3770,
3854-3856, 3900-3903
```

Remaining `media/preview_dialogs.py` branch gaps are mostly around pinch/paint fallbacks, remaining
icon/init branch variants, equalizer/bookmark provider edges, cached-state queue alternatives,
visualization release/timer paths, artwork context-menu sender variants, and close/change event
tails.

Recommended next batch:

- Batch AB1: return to `main_window.py` for the largest remaining GUI host gaps, especially
  track editor/GS1 fallbacks, bulk media workflows, storage conversion callbacks,
  update/recovery shutdown tails, and action-ribbon routing.
- Batch AB2: target `exchange/service.py` transaction/import failure and rollback branches.
- Batch AB3: follow with `conversion/dialogs.py` or `works/dialogs.py` using headless-safe dialog
  fakes and prompt/file-picker seams.

## Checkpoint 4.28 - Exchange Service Package/Import Edge Workflows

Timestamp: `2026-05-26 15:18:58 UTC`

This batch followed the checkpoint 4.27 recommendation to target
`isrc_manager/exchange/service.py`, the largest non-main-window service/workflow gap. No production
code changed. The added tests exercise real exchange workflows through the migrated SQLite fixture,
with narrow fake media services only at file/asset boundaries that are intentionally hard to make
fail deterministically through public APIs.

### Tests added

Added behavioural workflow coverage in `tests/exchange/_support.py` and exposed it through the
existing exchange wrappers:

- `case_package_helper_edges_cover_missing_media_and_schema_boundaries`
  - Covers package helper boundary handling for empty/duplicate names and warnings, missing
    Tracks/Works schema fallbacks, ownership-interest publisher precedence over contributor
    fallback publishers, effective media path lookup, absolute/relative package media resolution,
    database-backed packaged track media, stored-path fallback byte fetch, missing track media
    warning cleanup, invalid/missing release artwork rows, release artwork fallback byte packaging,
    unsupported JSON/package schemas, missing package manifests, unsafe ZIP paths, directory member
    extraction, and direct packaged-media recovery without an index.
- `case_inspection_import_source_and_identifier_edges_are_recoverable`
  - Covers CSV dialect fallback after sniffer failure, CSV/XLSX/package inspection cancellation
    hooks, package warnings for non-media ZIPs, identifier-review staging for contract/license/hash
    imports, package/non-package import source directory resolution, CSV/XLSX/package dry-run import
    cancellation hooks, text/title normalization boundaries, invalid track-length boundaries,
    missing/relative media source resolution, identifier classification bucket counters, unsupported
    unbound identifiers, and dry-run external identifier staging.

### Coverage delta

Authoritative before baseline from checkpoint 4.27:

- Full branch-aware coverage: `84.1338%`.
- Statement coverage: `87.5351%`.
- Branch coverage: `72.8316%`.
- Covered/missing lines: `62578` covered, `8911` missing.
- Covered/missing branches: `15669` covered, `5845` missing.
- `isrc_manager/exchange/service.py`: `81.4839%`, with `169` missing lines and `118`
  missing branches.

Authoritative after baseline from the latest strict full-suite run:

- Full branch-aware coverage: `84.3027%` displayed as `84%`.
- Statement coverage: `87.6680%` displayed as `88%`.
- Branch coverage: `73.1198%` displayed as `73%`.
- Covered/missing lines: `62673` covered, `8816` missing.
- Covered/missing branches: `15731` covered, `5783` missing.
- `isrc_manager/exchange/service.py`: `91.6129%`
  (`169` to `74` missing lines, `118` to `56` missing branches).
- Aggregate delta from checkpoint 4.27: `+0.1688` coverage points, `95` fewer missing lines, and
  `62` fewer missing branches across the measured package.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/exchange/test_exchange_package.py tests/exchange/test_exchange_csv_inspection.py -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/exchange/test_exchange_package.py tests/exchange/test_exchange_csv_inspection.py -q --no-cov
.venv/bin/python -m ruff check tests/exchange/_support.py tests/exchange/test_exchange_package.py tests/exchange/test_exchange_csv_inspection.py
.venv/bin/python -m black --check tests/exchange/_support.py tests/exchange/test_exchange_package.py tests/exchange/test_exchange_csv_inspection.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- The first focused exchange pytest invocation completed the `18` selected tests, then exited `1`
  only because the repo-level default coverage plugin enforced the global 95% gate on a narrow
  subset.
- Focused exchange pytest with `--no-cov`: passed (`18 passed`).
- Focused Ruff and Black checks for the touched exchange test files: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1` because
  coverage remained below the 95% gate (`1934 passed`, `775 warnings`, `78 subtests passed`;
  `84.30%` total coverage).
- Compileall, full Ruff, full Black check, and mypy: passed.

### Remaining gap to 95%

The latest full report has `8816` missing lines and `5783` missing branches. At the current
denominator (`71489` statements plus `21514` branches), `9949` additional line/branch slots would
need to be covered to reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `303` missing lines, `203` missing branches
2. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
3. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
4. `isrc_manager/code_registry/service.py` - `145` missing lines, `121` missing branches
5. `isrc_manager/contract_templates/dialogs.py` - `121` missing lines, `144` missing branches
6. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
7. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
8. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
9. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
10. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches
11. `isrc_manager/exchange/master_transfer.py` - `135` missing lines, `110` missing branches
12. `isrc_manager/code_registry/workspace.py` - `180` missing lines, `60` missing branches

Remaining `exchange/service.py` line gaps are now concentrated at:

```text
594-596, 713, 724-740, 745-763, 804-805, 1154, 1181, 1189,
1239, 1247, 1404, 1418, 1430, 1436, 1442-1443, 1515,
1534-1535, 1537, 1540-1541, 1573, 1582, 1680, 2006, 2013,
2108, 2149-2150, 2175, 2265, 2273, 2284-2286, 2319, 2333,
2378, 2385, 2404, 2434, 2445, 2493, 2527
```

Remaining `exchange/service.py` branch gaps are mostly around export CSV/XLSX direct writer paths,
JSON inspection cancellation, supported-target duplicate edge branches, repair queue update
branches, XML import custom-field conflict/missing-field branches, release upsert matching
alternatives, and transaction rollback/failure paths in `_import_rows`.

Recommended next batch:

- Batch AC1: target `main_window.py` only if the test can stay controller-like and avoid brittle
  full-window interaction.
- Batch AC2: target `code_registry/service.py` or `authenticity/service.py` for service-level
  behavioural gains with fewer GUI constraints.
- Batch AC3: return to `exchange/service.py` for import rollback, XML conflict, repair-queue update,
  and export CSV/XLSX direct writer branches.

## Checkpoint 4.29 - Code Registry Workflow Edge Coverage

Timestamp: `2026-05-26 15:38:12 UTC`

This batch rechecked the originally preferred `isrc_manager/history/manager.py` target before
choosing the next module. The latest full coverage report showed `history/manager.py` already above
the local module gate at `95.8821%` branch-aware coverage (`40` missing lines and `55` missing
branches), while `isrc_manager/code_registry/service.py` still carried one of the largest
service-level line/branch gaps at `78.3740%` (`145` missing lines and `121` missing branches).
The batch therefore used the documented "safer and higher value" exception and targeted code
registry workflow behavior instead of adding marginal history-manager tests.

No production code changed. The added tests use the existing SQLite-backed service fixture and
exercise real registry/category/owner persistence paths, with narrow temporary seams only for
otherwise nondeterministic SHA collision/reload failures and for legacy/minimal schema variants.

### Tests added

Expanded `tests/test_code_registry_service.py` with behavioural workflow coverage for:

- Assignment target discovery across tracks, releases, and contracts, including search filters,
  wrong-owner rejection, missing-owner rejection, and busy-destination protection.
- Catalog value assurance for missing internal values, stale stored values, imported external text,
  external identifier links, unsupported owner kinds, and missing owners.
- Category/listing boundaries for inactive categories, manual categories, unsupported automatic
  generation, blank lookup values, filtered entry listings, choice labels, transaction rollback, and
  delete failure rollback through a database trigger.
- Identifier resolution and assignment boundaries for inferred internal/external modes,
  missing/wrong-category registry entries, missing/wrong-category external identifiers,
  unsupported owner/category combinations, internal/external conflict guards, minimal schema
  external-storage rejection, empty assignment clearing, and missing external table fallback paths.
- Capture/generation failure paths for empty values, invalid SHA values, SHA capture with an
  existing cursor, existing SHA reuse, malformed internal catalog values, missing sequential
  prefixes, bad canonical prefixes, unsupported sequence numbers, sequence exhaustion, SHA collision
  retry, and generated SHA reload failure.
- External identifier reclassification and legacy schema paths, including mismatch/retained
  statuses, promote-missing failure, legacy external catalog upsert updates, unsupported legacy
  non-catalog upsert rejection, legacy external record reads, and legacy external promotion into an
  internal registry entry with shadow-state cleanup.

### Coverage delta

Authoritative before baseline from checkpoint 4.28:

- Full branch-aware coverage: `84.3027%`.
- Statement coverage: `87.6680%`.
- Branch coverage: `73.1198%`.
- Covered/missing lines: `62673` covered, `8816` missing.
- Covered/missing branches: `15731` covered, `5783` missing.
- `isrc_manager/code_registry/service.py`: `78.3740%`, with `145` missing lines and `121`
  missing branches.

Authoritative after baseline from the latest passing full-suite coverage report:

- Full branch-aware coverage: `84.4790%` displayed as `84%`.
- Statement coverage: `87.8009%` displayed as `88%`.
- Branch coverage: `73.4406%` displayed as `73%`.
- Covered/missing lines: `62768` covered, `8721` missing.
- Covered/missing branches: `15800` covered, `5714` missing.
- `isrc_manager/code_registry/service.py`: `91.3821%`
  (`145` to `52` missing lines, `121` to `54` missing branches).
- Aggregate delta from checkpoint 4.28: `+0.1763` coverage points, `95` fewer missing lines, and
  `69` fewer missing branches across the measured package.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_code_registry_service.py -q --no-cov
.venv/bin/python -m ruff check tests/test_code_registry_service.py
.venv/bin/python -m black --check tests/test_code_registry_service.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=95
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
```

Observed result:

- Focused code-registry pytest with `--no-cov`: passed (`35 passed`).
- Focused Ruff and Black checks for `tests/test_code_registry_service.py`: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed and produced an intermediate
  coverage report, then command exited `1` because coverage remains below the global 95% gate.
- Passing full pytest/coverage run with `--cov-fail-under=0`: passed (`1938 passed`,
  `728 warnings`, `78 subtests passed`; `84.48%` total coverage).
- Compileall, full Ruff, full Black check, mypy, and `git diff --check`: passed.

### Remaining gap to 95%

The latest full report has `8721` missing lines and `5714` missing branches. At the current
denominator (`71489` statements plus `21514` branches), `9785` additional line/branch slots would
need to be covered to reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `303` missing lines, `203` missing branches
2. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
3. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
4. `isrc_manager/contract_templates/dialogs.py` - `121` missing lines, `144` missing branches
5. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
6. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
7. `isrc_manager/storage_admin.py` - `148` missing lines, `103` missing branches
8. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
9. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches
10. `isrc_manager/exchange/master_transfer.py` - `135` missing lines, `110` missing branches
11. `isrc_manager/code_registry/workspace.py` - `180` missing lines, `60` missing branches
12. `isrc_manager/media/equalizer.py` - `171` missing lines, `58` missing branches

Remaining `code_registry/service.py` line gaps are now concentrated at:

```text
457, 686, 692, 743, 952, 1127, 1149, 1260, 1284, 1430,
1432, 1434, 1601, 1666, 1668, 1670, 1847, 1913, 1918,
1919, 1942, 2021, 2027, 2064, 2077, 2081-2084, 2087,
2157, 2178-2181, 2250, 2355, 2422, 2567, 2597-2598,
2605, 2609, 2615, 2618, 2620, 2625, 2636, 2724, 2746,
2751, 2765
```

Remaining `code_registry/service.py` branch gaps are mostly around rare category-selection
alternatives, legacy/external identifier listing variants, contract/license/hash owner assignment
tails, deletion/reclassification alternatives, and final promotion/listing fallback branches.

Recommended next batch:

- Batch AD1: target `authenticity/service.py`, `storage_admin.py`, or `services/tracks.py` for
  another service-level workflow batch before returning to GUI-heavy modules.
- Batch AD2: target `conversion/dialogs.py` or `works/dialogs.py` only with headless-safe dialog
  tests, fake file/prompt services, and direct widget state assertions.
- Batch AD3: target `main_window.py` only through narrow command-routing/controller seams, avoiding
  brittle full-window flows.

## Checkpoint 4.30 - Contract Template Dialog Layout/Admin Edge Coverage

Timestamp: `2026-05-26 16:09:30 UTC`

This stop-point batch targeted `isrc_manager/contract_templates/dialogs.py`, one of the largest
remaining user-prioritized GUI/workflow gaps. It added headless-safe behavioural tests against the
existing `ContractTemplateWorkspacePanel` fixture. No production code changed.

The tests intentionally avoid brittle full-window click flows. They exercise dialog/workspace
methods with real Qt widgets and SQLite-backed services where practical, while mocking only user
prompt/file-picker boundaries and a ZIP import service path to keep package ingestion out of this
GUI-specific test.

### Tests added

Expanded `tests/contract_templates/test_dialogs.py` with:

- `test_workspace_host_layout_recovery_and_registration_boundaries`
  - Covers compatible empty pending state, exposed-canvas false paths, hidden/missing scroll-area
    content readiness, layout-integrity failure branches, unrecoverable restore reset fallback,
    ignored floating transitions for unregistered/already-matching docks, dock-layout event guard
    paths, and multi-group area rebuild behavior.
- `test_workspace_panel_refresh_selection_and_preview_edge_helpers`
  - Covers unknown tab normalization, current-tab fallback, refresh routing for all workspace tabs,
    suppressed tab-change refresh during restore, validator exception swallowing during stabilize,
    deleted-window layout notification, inactive symbol/fill refresh no-ops, profileless draft
    refresh, stale loaded-draft cleanup, editable payload preview refresh, clear-preview fallback,
    export-without-draft status, WebEngine-unavailable preview status, symbol copy no-ops, invalid
    table selection IDs, blank/chosen file dialog path normalization, and suspended admin-change
    handlers.
- `test_admin_zip_import_revision_and_delete_success_failure_edges`
  - Covers ZIP template import and ZIP revision import dispatching to
    `import_html_package_from_path`, record-only template deletion success, delete-with-files
    failure status/warning behavior, and draft delete-with-files success without modal leakage.

### Coverage delta

Authoritative before baseline from checkpoint 4.29:

- Full branch-aware coverage: `84.4790%`.
- Statement coverage: `87.8009%`.
- Branch coverage: `73.4406%`.
- Covered/missing lines: `62768` covered, `8721` missing.
- Covered/missing branches: `15800` covered, `5714` missing.
- `isrc_manager/contract_templates/dialogs.py`: `94.4929%`, with `121` missing lines and `144`
  missing branches.

Authoritative after baseline from the latest passing full-suite coverage report:

- Full branch-aware coverage: `84.5768%` displayed as `85%`.
- Statement coverage: `87.8807%` displayed as `88%`.
- Branch coverage: `73.5986%` displayed as `74%`.
- Covered/missing lines: `62825` covered, `8664` missing.
- Covered/missing branches: `15834` covered, `5680` missing.
- `isrc_manager/contract_templates/dialogs.py`: `96.4464%`
  (`121` to `62` missing lines, `144` to `109` missing branches).
- Aggregate delta from checkpoint 4.29: `+0.0978` coverage points, `57` fewer missing lines, and
  `34` fewer missing branches across the measured package.

### Validation commands run in this continuation

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py -q --no-cov -k "workspace_host_layout_recovery_and_registration_boundaries or workspace_panel_refresh_selection_and_preview_edge_helpers or admin_zip_import_revision_and_delete_success_failure_edges"
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/contract_templates/test_dialogs.py -q --no-cov
.venv/bin/python -m ruff check tests/contract_templates/test_dialogs.py
.venv/bin/python -m black --check tests/contract_templates/test_dialogs.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=0
```

Observed result:

- Focused new-test selection: passed (`3 passed`).
- Full contract-template dialog test file: passed (`88 passed`).
- Touched-file Ruff and Black checks: passed after formatting.
- Full pytest/coverage with `--cov-fail-under=0`: passed (`1941 passed`, `774 warnings`,
  `78 subtests passed`; `84.58%` total coverage).

The strict `--cov-fail-under=95` gate and full compile/Ruff/Black/mypy validation were not rerun
after this final stop-point batch because the session was stopped for handoff. The latest full
coverage evidence proves the 95% gate is still incomplete, not globally blocked.

### Remaining gap to 95%

The latest full report has `8664` missing lines and `5680` missing branches. At the current
denominator (`71489` statements plus `21514` branches), `9694` additional line/branch slots would
need to be covered to reach 95% without adding production code.

Largest remaining combined line/branch gaps:

1. `isrc_manager/main_window.py` - `303` missing lines, `203` missing branches
2. `isrc_manager/conversion/dialogs.py` - `177` missing lines, `94` missing branches
3. `isrc_manager/works/dialogs.py` - `175` missing lines, `91` missing branches
4. `isrc_manager/authenticity/service.py` - `164` missing lines, `99` missing branches
5. `isrc_manager/qss_autocomplete.py` - `151` missing lines, `105` missing branches
6. `isrc_manager/storage_admin.py` - `149` missing lines, `104` missing branches
7. `isrc_manager/services/tracks.py` - `130` missing lines, `118` missing branches
8. `isrc_manager/parties/controller.py` - `157` missing lines, `88` missing branches
9. `isrc_manager/exchange/master_transfer.py` - `135` missing lines, `110` missing branches
10. `isrc_manager/code_registry/workspace.py` - `180` missing lines, `60` missing branches
11. `isrc_manager/media/equalizer.py` - `171` missing lines, `58` missing branches
12. `isrc_manager/application_settings_dialog.py` - `150` missing lines, `76` missing branches

Remaining `contract_templates/dialogs.py` line gaps are now concentrated at:

```text
441-442, 1240, 1310, 1325, 1412, 1428, 1660, 1959, 1966,
2232-2234, 2240, 2307-2308, 2423, 2824-2825, 3069-3070,
3365, 3369-3371, 3451, 3486, 3516-3517, 3671, 3978, 3982,
4194, 4250, 4253-4254, 4317, 4352, 4356, 4358, 4363, 4449,
4486, 4617, 4664, 4675, 4806, 4812, 4840, 4849, 4867, 5084,
5311, 5413-5416, 5422, 5425, 5879, 6413, 6415
```

Recommended next session:

- Batch AE1: target `conversion/dialogs.py` or `works/dialogs.py` with focused headless dialog
  tests; both have low branch coverage and large remaining gaps.
- Batch AE2: target `authenticity/service.py`, `storage_admin.py`, or `services/tracks.py` for
  service-level branch/error-path coverage that avoids broad GUI setup.
- Batch AE3: target `main_window.py` only through narrow command-routing/controller seams and fake
  prompt/workers; it remains the single largest gap.
