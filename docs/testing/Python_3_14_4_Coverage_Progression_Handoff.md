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
git diff --check
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

## Continuation checkpoint - 2026-05-25 21:02:13 UTC

The next Batch A continuation was completed after reading this handoff. It focused on
`tests/test_media_waveform_clusters.py` and added behavioural coverage for:

- PCM fixture variants across 8-bit, 24-bit, and 32-bit WAV loaders.
- waveform widget event, cached-preview, render, palette invalidation, bookmark, and live harmonic
  drawing branches.
- stereo peak-meter and spectrum graph state transitions, context-menu actions, equalizer routing,
  fade/release transitions, and render helpers.
- deterministic ffmpeg, audioread, and Qt decoder fallback paths without real multimedia devices.
- waveform-cache schema/delete, service fast-return, failed-render cleanup, stale inspection,
  fingerprinting, color analysis, resampling, and helper branches.

Validation run after this continuation:

```bash
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/test_media_waveform_clusters.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/test_media_waveform_clusters.py --cov=isrc_manager.media.waveform --cov=isrc_manager.media.audio_visualization --cov=isrc_manager.media.waveform_cache --cov-branch --cov-report=term-missing --cov-report=json:coverage-media.json --cov-fail-under=0
.venv/bin/python -m ruff check tests/test_media_waveform_clusters.py
.venv/bin/python -m black --check tests/test_media_waveform_clusters.py
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

Observed result:

- Compileall: passed.
- Focused media tests: `18 passed`.
- Focused media coverage: combined targeted media report `85%`.
- Ruff: passed.
- Black: passed.
- Full pytest: `1776 passed`, `777 warnings`, `54 subtests passed`.
- Full branch-aware coverage: `78.5829%` displayed as `79%`.
- Statement coverage: `82.5509%` displayed as `83%`.
- Branch coverage: `65.3993%` displayed as `65%`.

Updated media module coverage from the full-suite JSON:

- `isrc_manager/media/audio_visualization.py`: `85.3041%` displayed as `85%`.
- `isrc_manager/media/waveform.py`: `86.0324%` displayed as `86%`.
- `isrc_manager/media/waveform_cache.py`: `90.5253%` displayed as `91%`.

Remaining largest missing-line contributors after this continuation:

1. `isrc_manager/main_window.py` - `1333` missing lines
2. `isrc_manager/contract_templates/dialogs.py` - `864` missing lines
3. `isrc_manager/media/preview_dialogs.py` - `524` missing lines
4. `isrc_manager/tracks/edit_dialog.py` - `415` missing lines
5. `isrc_manager/history/manager.py` - `301` missing lines
6. `isrc_manager/contract_templates/export_service.py` - `261` missing lines
7. `isrc_manager/code_registry/service.py` - `247` missing lines
8. `isrc_manager/application_settings_dialog.py` - `208` missing lines
9. `isrc_manager/media/equalizer.py` - `204` missing lines
10. `isrc_manager/contract_templates/service.py` - `194` missing lines

Recommended next batch:

- Prefer `contract_templates/export_service.py` and `contract_templates/service.py`, then
  `code_registry/service.py` and `history/manager.py`, before returning to large headless Qt dialog
  modules.

## Continuation checkpoint - 2026-05-25 21:26:50 UTC

Batch B/C service coverage was completed after the media continuation. This pass added focused
behavioural tests for contract-template export/service paths, code-registry legacy/generation
branches, and history backup/error recovery paths.

Tests expanded in this batch:

- `tests/contract_templates/test_export_service.py`
  - deterministic `QtWebEngineHtmlPdfAdapter` success, load-failure, print-failure, missing-source,
    and missing-output coverage using fake page/timer/event-loop objects.
- `tests/contract_templates/test_revision_service.py`
  - managed draft working-file lifecycle coverage, managed-path boundary validation, clear/load
    behaviour, and draft registry assignment reuse/conflict paths.
- `tests/test_code_registry_service.py`
  - manual-category generation rejection, SHA-vs-sequential generation validation, blank lookup,
    unused-entry filtering, legacy `ExternalCatalogIdentifiers` reads, and schema-not-ready no-op
    initialization.
- `tests/history/_support.py` and `tests/history/test_history_recovery.py`
  - backup registration/delete cleanup, companion/sidecar removal, missing-backup errors, and
    explicit file-restore recovery errors.

Validation run after this continuation:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/contract_templates/test_export_service.py tests/contract_templates/test_revision_service.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/test_code_registry_service.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/history/test_history_recovery.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/contract_templates/test_export_service.py tests/contract_templates/test_revision_service.py tests/test_code_registry_service.py
.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests
.venv/bin/python -m ruff check tests/contract_templates/test_export_service.py tests/contract_templates/test_revision_service.py tests/test_code_registry_service.py tests/history/_support.py tests/history/test_history_recovery.py
.venv/bin/python -m black --check tests/contract_templates/test_export_service.py tests/contract_templates/test_revision_service.py tests/test_code_registry_service.py tests/history/_support.py tests/history/test_history_recovery.py
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

Observed result:

- Focused contract-template tests: `37 passed`, `4 subtests passed`.
- Focused code-registry tests: `28 passed`.
- Focused history recovery tests: `5 passed`.
- Combined touched focused tests: `65 passed`, `4 subtests passed`.
- Compileall: passed.
- Ruff: passed.
- Black check: passed after formatting the touched tests.
- Full pytest: `1783 passed`, `785 warnings`, `54 subtests passed`.
- Full branch-aware coverage: `78.7701%` displayed as `79%`.
- Statement coverage: `82.7131%` displayed as `83%`.
- Branch coverage: `65.6689%` displayed as `66%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/contract_templates/export_service.py`: `74.2245%` displayed as `74%`
  (`261` to `209` missing lines, `158` to `140` missing branches).
- `isrc_manager/contract_templates/service.py`: `78.7681%` displayed as `79%`
  (`194` to `156` missing lines, `152` to `137` missing branches).
- `isrc_manager/code_registry/service.py`: `68.3740%` displayed as `68%`
  (`247` to `230` missing lines, `177` to `159` missing branches).
- `isrc_manager/history/manager.py`: `78.7603%` displayed as `79%`
  (`301` to `294` missing lines, `201` to `196` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target could not be reached in this batch because the remaining gap is still very large:
`12357` missing lines and `7386` missing branches across the measured `isrc_manager` package. The
largest remaining contributors are GUI composition/dialog surfaces and broad workflow modules that
need careful headless Qt tests, not superficial import or constructor coverage.

Remaining largest missing-line contributors after this continuation:

1. `isrc_manager/main_window.py` - `1333` missing lines
2. `isrc_manager/contract_templates/dialogs.py` - `864` missing lines
3. `isrc_manager/media/preview_dialogs.py` - `524` missing lines
4. `isrc_manager/tracks/edit_dialog.py` - `415` missing lines
5. `isrc_manager/history/manager.py` - `294` missing lines
6. `isrc_manager/code_registry/service.py` - `230` missing lines
7. `isrc_manager/contract_templates/export_service.py` - `209` missing lines
8. `isrc_manager/application_settings_dialog.py` - `208` missing lines
9. `isrc_manager/media/equalizer.py` - `204` missing lines
10. `isrc_manager/code_registry/workspace.py` - `180` missing lines

Recommended next batch:

- Batch D1: `contract_templates/dialogs.py`, `media/preview_dialogs.py`, and
  `tracks/edit_dialog.py` through focused headless Qt tests that patch dialogs, file pickers, and
  worker boundaries.
- Batch D2: continue `history/manager.py` and `code_registry/service.py` around recovery repair,
  reassignment targets, reclassification, and conflict/error branches.
- Batch D3: `code_registry/workspace.py`, `media/equalizer.py`, and `application_settings_dialog.py`
  with controller/service-driven assertions before attempting broader `main_window.py` routing.

## Continuation checkpoint - 2026-05-25 21:57:09 UTC

The pursuit continued with behavioural tests for high-value GUI helper/workflow modules while
keeping coverage measured only with `--cov=isrc_manager`.

Tests added or expanded:

- `tests/test_media_preview_preload.py`
  - managed custom audio media, `TrackService` source fallbacks, preload-state metadata, cancellation
    cleanup, decode errors, and waiting-preload fallback/ready branches.
- `tests/tracks/test_edit_dialog_behaviors.py`
  - bulk-field and bulk-media save decisions, album-art ownership hints/deduplication, party-backed
    artist fallback text, album-art replacement block messages, saved-media display text, and BUMA
    work resolution.
- `tests/test_application_settings_dialog_behaviors.py`
  - smart history budget math/source fallback, profile database discovery/deduplication, party-backed
    artist resolution, owner-party payload fallback, and retention mode detection.
- `tests/test_media_equalizer_coverage.py`
  - settings load/save fallback branches, ffmpeg/soundfile failure handling, response helper branches,
    and headless Qt equalizer curve/panning widget behaviour.
- `tests/test_main_window_helpers.py`
  - help-file refresh, log viewer rendering, selection-scope fallbacks, hidden-column settings
    parsing/writing/clearing, header ordering, and catalog track-choice fallback logic.
- `tests/contract_templates/test_workspace_layout_helpers.py`
  - dock group ordering, gap detection, rebuild split direction, floating feature flags, and dock
    order hint updates.

Validation run after this continuation:

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_media_preview_preload.py tests/tracks/test_edit_dialog_behaviors.py tests/test_application_settings_dialog_behaviors.py tests/test_media_equalizer_coverage.py tests/test_main_window_helpers.py tests/contract_templates/test_workspace_layout_helpers.py --no-cov
python3 -m black tests/test_media_preview_preload.py tests/tracks/test_edit_dialog_behaviors.py tests/test_application_settings_dialog_behaviors.py tests/test_media_equalizer_coverage.py tests/test_main_window_helpers.py tests/contract_templates/test_workspace_layout_helpers.py
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  --cov=isrc_manager \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=json \
  --cov-fail-under=0
```

Observed result:

- Focused touched tests: `47 passed`.
- Black formatting: passed after reformatting touched tests.
- Full pytest: `1813 passed`, `784 warnings`, `54 subtests passed`.
- Full branch-aware coverage: `79.5174%` displayed as `80%`.
- Statement coverage: `83.3790%` displayed as `83%`.
- Branch coverage: `66.6868%` displayed as `67%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/main_window.py`: `70.8914%` displayed as `71%`
  (`1333` to `1202` missing lines, `587` to `532` missing branches).
- `isrc_manager/contract_templates/dialogs.py`: `74.3142%` displayed as `74%`
  (`864` to `817` missing lines, `445` to `419` missing branches).
- `isrc_manager/media/preview_dialogs.py`: `80.4046%` displayed as `80%`
  (`524` to `412` missing lines, `280` to `237` missing branches).
- `isrc_manager/tracks/edit_dialog.py`: `69.0306%` displayed as `69%`
  (`415` to `319` missing lines, `219` to `157` missing branches).
- `isrc_manager/application_settings_dialog.py`: `79.2851%` displayed as `79%`
  (`208` to `150` missing lines, `107` to `76` missing branches).
- `isrc_manager/media/equalizer.py`: `74.3848%` displayed as `74%`
  (`204` to `171` missing lines, `61` to `58` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target could not be reached in this continuation because the remaining gap is still
`11881` missing lines and `7167` missing branches. The gap is concentrated in very large
GUI/workflow surfaces plus branch-heavy services where meaningful coverage requires additional
headless Qt, database, and fake-host workflow scenarios rather than import-only or constructor-only
tests.

Remaining largest combined line/branch gaps:

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

Recommended next batch:

- Batch E1: continue `main_window.py` helper/controller workflows for backup/restore, clipboard,
  GS1 routing, catalog choices, hidden column persistence, and storage conversion callbacks.
- Batch E2: continue `contract_templates/dialogs.py` workspace panel actions, fill-form refresh/save,
  revision/draft deletion/activation, registry selector generation, and manual widget construction.
- Batch E3: continue `media/preview_dialogs.py` and `tracks/edit_dialog.py` around active load
  result handling, source loading, cache eviction, file picker/message-box branches, and save flows.
- Batch E4: continue service branches in `history/manager.py`, `code_registry/service.py`,
  `contract_templates/export_service.py`, `contract_templates/service.py`, and `exchange/service.py`.

## Continuation checkpoint - 2026-05-25 22:27:37 UTC

The pursuit continued with real service-level tests in `quality`, `releases`, and `code_registry`,
while preserving the measured scope as `--cov=isrc_manager` only. One production bug was fixed:
quality export serialization now uses `dataclasses.asdict()` because `QualityIssue` is a slotted
dataclass and does not expose `__dict__`.

Tests added or expanded:

- `tests/test_quality_service.py`
  - CSV/JSON export of slotted issue models, scoped derived-value regeneration, scoped date
    normalization, media relinking unavailable/skipped/scoped repair paths, normalize-date parser
    edge cases, and unknown fix rejection.
- `tests/test_release_service.py`
  - release family inference/share logic, add-track duplicate/invalid filtering, missing delete
    errors, matching/upsert behaviour, artwork managed/database conversion, missing blob/release
    fetch failures, and artwork validation errors.
- `tests/test_code_registry_service.py`
  - assignment-target search for tracks/releases/contracts, missing/wrong owner assignment errors,
    busy contract destination protection, catalog ensure generation, stale internal realignment,
    external value preservation, and unsupported/missing owner errors.

Validation run after this continuation:

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
```

Observed result:

- Focused quality service tests: `20 passed`.
- Focused release service tests: `18 passed`.
- Focused code-registry service tests: `31 passed`.
- Full pytest: `1833 passed`, `775 warnings`, `54 subtests passed`.
- Full branch-aware coverage after the required 95% gate attempt: `79.8832%` displayed as `80%`.
- Statement coverage: `83.6898%` displayed as `84%`.
- Branch coverage: `67.2353%` displayed as `67%`.
- Required `--cov-fail-under=95` command: tests passed, then exited `1` because total coverage was
  below the 95% gate (`1833 passed`, `777 warnings`, `54 subtests passed`).
- Compileall, Ruff, Black check, and mypy: passed. Ruff initially reported one import-order issue in
  `tests/test_quality_service.py`; it was fixed and rerun successfully.

Updated module coverage from the full-suite JSON:

- `isrc_manager/quality/service.py`: `69.18%` to `87.52%`
  (`118` to `37` missing lines, `99` to `51` missing branches).
- `isrc_manager/releases/service.py`: `74.11%` to `87.75%`
  (`100` to `44` missing lines, `67` to `35` missing branches).
- `isrc_manager/code_registry/service.py`: `68.37%` to `78.37%`
  (`230` to `145` missing lines, `159` to `121` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target could not be reached in this continuation because the remaining measured gap is still
`11659` missing lines and `7049` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `14059` additional line/branch slots would need to be covered to
reach 95% without adding production code. The remaining gap is distributed across large workflow
surfaces and branch-heavy services; reaching the gate safely requires multiple additional behavioural
batches rather than shallow imports, constructor-only tests, skips, exclusions, or threshold changes.

Remaining largest combined line/branch gaps:

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

Recommended next batch:

- Batch F1: `history/manager.py` recovery and invariant workflows, including replay/apply failure
  paths, snapshot archive restore, and artifact reference scrubbing.
- Batch F2: `services/tracks.py` media metadata maps, storage conversion failures, album conflict
  snapshots, managed media cleanup, and album metadata propagation.
- Batch F3: `contract_templates/export_service.py` catalog value resolution, payload replacement,
  preview materialization/pruning, PDF renderer fallbacks, and DOCX placeholder errors.
- Batch F4: headless Qt fake-host batches for `main_window.py`, `contract_templates/dialogs.py`,
  `media/preview_dialogs.py`, and `tracks/edit_dialog.py`.

## Continuation checkpoint - 2026-05-26 05:20:15 UTC

The next workflow coverage batch started with `history/manager.py` and then used the refreshed gap
map to add behavioural tests in `tracks/edit_dialog.py`, `media/preview_dialogs.py`, and
`contract_templates/dialogs.py`. This batch stayed headless-safe by using fake services/parents,
patched message boxes/dialog factories, and direct workflow helper calls instead of brittle
full-window journeys.

Tests added or expanded:

- `tests/history/*`
  - recovery-state repair of moved backup sidecars, orphan sidecar conflicts, dangling snapshot
    references, missing snapshot archives, corrupted snapshot/redo boundaries, snapshot action
    rollback after history recording failure, database/file rollback after side-effect failure,
    directory target rejection, and explicit missing track/event-recording failures.
- `tests/tracks/test_edit_dialog_behaviors.py`
  - single and bulk edit validation, no-op, cancellation, success, propagated/non-propagated,
    rollback, payload/audit, media picker, clipboard, album-art ownership, GS1 launch, and routing
    paths.
- `tests/test_media_preview_preload.py`
  - custom-audio missing row/blob, temp-file cleanup, late cancellation, state failure, cancelled
    preload handoff, empty prepared preload, and owned prepared-media disposal during cancellation.
- `tests/contract_templates/test_workspace_layout_helpers.py`
  - dock-state serialization, area coercion, visibility normalization, saved-topology detection,
    logical visibility fallback, and floating-transition hook safety.

Validation run after this continuation's coverage implementation:

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
- Full pytest with coverage fail-under disabled: `1853 passed`, `785 warnings`,
  `54 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then exited `1` because total
  coverage was `80.5198%`, below the 95% gate (`1853 passed`, `785 warnings`,
  `54 subtests passed`).
- Ruff: passed after fixing one import-order issue in
  `tests/contract_templates/test_workspace_layout_helpers.py`.
- Black check: passed.
- Mypy: passed.
- Full branch-aware coverage after the required 95% gate attempt: `80.5198%` displayed as `81%`.
- Statement coverage: `84.2648%` displayed as `84%`.
- Branch coverage: `68.0766%` displayed as `68%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/history/manager.py`: `78.76%` to `86.69%`
  (`294` to `176` missing lines, `196` to `131` missing branches).
- `isrc_manager/tracks/edit_dialog.py`: `69.03%` to `92.19%`
  (`319` to `62` missing lines, `157` to `58` missing branches).
- `isrc_manager/media/preview_dialogs.py`: `80.40%` to `81.04%`
  (`412` to `398` missing lines, `237` to `230` missing branches).
- `isrc_manager/contract_templates/dialogs.py`: `74.31%` to `74.94%`
  (`817` to `796` missing lines, `419` to `410` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is
`11248` missing lines and `6868` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `13467` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Remaining largest combined line/branch gaps:

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

- Batch G1: fake-host workflow tests for `main_window.py` backup/restore, catalog choice, GS1,
  clipboard/media routing, and storage conversion callbacks.
- Batch G2: `contract_templates/dialogs.py` draft save/export/delete, revision activation/rescan,
  placeholder rebind, selector generation, and modal/failure branches.
- Batch G3: `media/preview_dialogs.py` active load result, source loading, preload cache eviction,
  artwork/bookmark/volume/equalizer branches.
- Batch G4: deeper `history/manager.py` cleanup, retention, compaction, and snapshot archive
  restore branches.

## Continuation checkpoint - 2026-05-26 05:45:51 UTC

The next workflow coverage batch used the 4.6 coverage evidence to target `main_window.py`, which
had become the largest remaining combined line/branch gap after the history-first work. The tests
stay at narrow helper and composition-shell boundaries with fake settings, profile stores,
controller modules, message boxes, and headless Qt widgets. They avoid launching a brittle
full-window flow.

Tests added or expanded:

- `tests/test_main_window_helpers.py`
  - help dialog modal and non-modal routing.
  - local path open success/failure handling and message-box warnings.
  - top-chrome boundary handling for absent and real toolbars.
  - artist-code migration from settings, invalid defaulting, direct setting, and settings-focus
    delegation.
  - background runtime setup, write-lock configuration, status-bar activity messages, database
    preparation error paths, background error presentation, and scaled progress callbacks.
  - composition-shell delegation to app sound, update, diagnostics, theme, settings,
    history-retention, profile-session, foreground-service initialization, and audio-conversion
    controllers.

Validation run after this continuation's coverage implementation:

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

Updated module coverage from the full-suite JSON:

- `isrc_manager/main_window.py`: `70.8914%` to `73.3591%`
  (`1202` to `1084` missing lines, `532` to `503` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is
`11131` missing lines and `6840` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `13322` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Remaining largest combined line/branch gaps:

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

- Batch H1: continue `main_window.py` backup/restore, catalog choice, GS1, clipboard/media routing,
  and storage-conversion callback workflows.
- Batch H2: `contract_templates/dialogs.py` draft save/export/delete, revision activation/rescan,
  placeholder rebind, selector generation, and modal/failure branches.
- Batch H3: `media/preview_dialogs.py` active load result, source loading, preload cache eviction,
  artwork/bookmark/volume/equalizer branches.
- Batch H4: deeper `history/manager.py` cleanup, retention, compaction, missing-file, and snapshot
  archive restore branches.

## Continuation checkpoint - 2026-05-26 06:11:06 UTC

The next workflow coverage batch targeted `contract_templates/dialogs.py`, the second-largest
remaining combined line/branch gap. It focused on the dockable workspace host and live HTML
fill-preview controller, using real headless Qt widgets for local state and fake panel/export
services only at external preview-materialization boundaries.

Tests added or expanded:

- `tests/contract_templates/test_workspace_layout_helpers.py`
  - `_DockableWorkspaceTab` layout normalization, lock/unlock, pending-state compatibility,
    capture fallback, reset, scroll-area repair, panels-menu synchronization, dock recovery, saved
    visibility restoration, move/float/hide commands, layout-event ignore reasons, compaction
    branching, and title-bar menu/drag/context-menu behaviour.
  - `_FillHtmlPreviewController` stale-state status handling, pending/active temp-tree cleanup,
    payload-key fallback, runtime preview source failure/signature handling, no-view/no-revision
    refresh skips, preview materialization success, load rejection cleanup, materialization failure,
    stale pending replacement, race cleanup, ignored load completion, and delete-tree exception
    swallowing.

Validation run after this continuation's coverage implementation:

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

Updated module coverage from the full-suite JSON:

- `isrc_manager/contract_templates/dialogs.py`: `74.9377%` to `77.8470%`
  (`796` to `697` missing lines, `410` to `369` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is
`11031` missing lines and `6798` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `13180` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Remaining largest combined line/branch gaps:

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
- Batch I2: continue `contract_templates/dialogs.py` draft save/export/delete, revision activation,
  rescan/rebind, selector generation, and modal/failure branches outside the workspace host.
- Batch I3: `media/preview_dialogs.py` active load result, source loading, preload cache eviction,
  artwork/bookmark/volume/equalizer branches.
- Batch I4: deeper `history/manager.py` cleanup, retention, compaction, missing-file, and snapshot
  archive restore branches.

## Continuation checkpoint - 2026-05-26 06:43:48 UTC

The next workflow coverage batch used the 4.8 coverage evidence to target
`media/preview_dialogs.py`. `history/manager.py` remains a valid follow-up target, but the refreshed
gap map showed the media preview workflow had the larger safer GUI gap after prior history coverage
work, so this continuation picked the headless-safe media preview surface.

Tests added or expanded:

- `tests/test_media_preview_preload.py`
  - `_ImagePreviewDialog` invalid/valid image data, zoom step/factor handling, Ctrl-wheel, native
    zoom, pinch gestures, double-click reset, export picker payloads, empty export no-op, and
    `_HiDpiArtworkLabel` target sizing, activation, and clear paths.
  - `_AudioPreviewDialog` loop/shuffle/auto-advance button state, album-scope title fallback and
    ordering, album menu rebuilds, equalizer propagation/dialog reuse, bookmark load/failure/menu
    add/remove/clear paths, and play-next placeholder/current/next-track routing.

Validation run after this continuation's coverage implementation:

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
- Ruff, Black check, and mypy: passed.
- Full branch-aware coverage after the required 95% gate attempt: `80.9908%` displayed as `81%`.
- Statement coverage: `84.7166%` displayed as `85%`.
- Branch coverage: `68.6111%` displayed as `69%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/media/preview_dialogs.py`: `81.0386%` to `85.5374%`
  (`398` to `293` missing lines, `230` to `186` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is
`10925` missing lines and `6753` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `13029` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Remaining largest combined line/branch gaps:

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

Remaining `media/preview_dialogs.py` gaps are concentrated around image-preview show/resize/paint
fallbacks (`199-399`), audio icon and transport button construction/fallbacks (`1533-1809`), active
audio load/preload/cache/waveform orchestration (`2701-3457`), and artwork context-menu/export,
volume/gain, navigation/end-of-media, visualization, and cleanup branches (`3522-3903`).

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

## Continuation checkpoint - 2026-05-26 07:06:35 UTC

This continuation returned to `history/manager.py` for a recovery-heavy behavioural batch. The
tests focus on corrupted-state, rollback, sidecar, quarantine, managed-file, and setting payload
boundaries without changing production code or adding coverage exclusions.

Tests added or expanded:

- `tests/history/test_history_recovery.py`
  - snapshot restore-as-action preserves the original recording failure when rollback restore and
    cleanup also fail.
  - repair normalizes stale heads, corrupted non-state reversible rows, re-linked event children,
    and dangling snapshot references.
  - corrupted/non-dict sidecars, inferred snapshot/backup metadata, orphan asset manifests, nested
    artifact quarantine scrubbing, managed-state clone/restore failures, external rollback error
    aggregation, and setting payload invalid/legacy fields.

Validation run after this continuation's coverage implementation:

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
- Ruff, Black check, and mypy: passed.
- Full branch-aware coverage after the required 95% gate attempt: `81.1123%` displayed as `81%`.
- Statement coverage: `84.8202%` displayed as `85%`.
- Branch coverage: `68.7924%` displayed as `69%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/history/manager.py`: `86.6927%` to `91.6775%`
  (`176` to `101` missing lines, `131` to `91` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is
`10851` missing lines and `6714` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `12916` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Remaining largest combined line/branch gaps:

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

Remaining `history/manager.py` gaps are concentrated around redo-plan boundary failures
(`738`, `794-802`), snapshot replay failure rollback and low-level inverse dispatch branches
(`1420-1532`, `1627-1669`), snapshot restore/insert failure boundaries (`1715-1867`), deeper
undo-tree normalization/bootstrap branches (`1962-2251`), sidecar write failure swallowing and
archive gaps (`2332-2595`), snapshot-protection/quarantine/path exception branches (`2651-2909`),
serialization/coalescing/update errors (`3133-3172`), and timestamp helpers (`3210`).

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

## Continuation checkpoint - 2026-05-26 07:21:51 UTC

This continuation targeted `main_window.py` after the 4.10 evidence showed it was the largest
remaining combined line/branch gap. The batch added direct behavioural tests for startup feedback,
runtime loading feedback, ready-gate orchestration, waveform-cache startup gating, and modal startup
message-box suspend/resume behaviour. It used fake feedback controllers and fake `QMessageBox`
instances, so no full-window GUI flow or timing sleeps were introduced.

Tests added or expanded:

- `tests/test_main_window_helpers.py`
  - startup progress tracker delegation, controller fallback reporting, completed-feedback no-ops,
    storage startup progress draining, and startup splash suspend/resume exception handling.
  - runtime loading feedback creation, phase/status/progress fallback paths, invalid progress input,
    finish exception swallowing, startup-ready gating, waveform cache startup pass submission, and
    modal startup message box parent/configuration branches.

Validation run after this continuation's coverage implementation:

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
- Ruff, Black check, and mypy: passed.
- Full branch-aware coverage after the required 95% gate attempt: `81.2166%` displayed as `81%`.
- Statement coverage: `84.9209%` displayed as `85%`.
- Branch coverage: `68.9086%` displayed as `69%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/main_window.py`: `73.3591%` to `75.0210%`
  (`1084` to `1011` missing lines, `503` to `477` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is
`10779` missing lines and `6689` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `12817` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Remaining largest combined line/branch gaps:

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

Remaining `main_window.py` gaps are concentrated around the Qt message filter/full bootstrap,
remaining startup feedback no-op/error boundaries, and larger backup/restore, catalog/media routing,
GS1/storage conversion, diagnostics, update, settings, menu, dock, and action-dispatch workflows.

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

## Continuation checkpoint - 2026-05-26 07:50:04 UTC

This continuation targeted `contract_templates/dialogs.py`, the second-largest remaining GUI/workflow
gap after the 4.11 main-window batch. The tests exercise real workspace panel behaviour with
headless-safe widgets and only mock external prompt/open boundaries.

Tests added or expanded:

- `tests/contract_templates/test_dialogs.py`
  - profileless symbol/fill/export/preview/admin states remain safe and empty when service providers
    return `None`.
  - draft save blocks registry validation failures, handles assignment failure after creation,
    attempts rollback deletion, swallows rollback deletion failure, and reports the original failure.
  - draft load/export/open failure paths cover no selection, missing revision, missing export service,
    PDF export exception prompts, export warning text, no retained PDF artifact, and external-open
    failure status.

Validation run after this continuation's coverage implementation:

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
- Ruff, Black check, and mypy: passed.
- Full branch-aware coverage after the required 95% gate attempt: `81.3080%` displayed as `81%`.
- Statement coverage: `85.0160%` displayed as `85%`.
- Branch coverage: `68.9876%` displayed as `69%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/contract_templates/dialogs.py`: `77.8470%` to `79.6135%`
  (`697` to `629` missing lines, `369` to `352` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is
`10711` missing lines and `6672` missing branches. At the current denominator (`71483` statements
plus `21514` branches), roughly `12734` additional line/branch slots would need to be covered to
reach 95% without adding production code.

Remaining largest combined line/branch gaps:

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
zoom/fit fallbacks, dock restore/repair geometry and scroll-content recovery, preview runtime
rebuild/disposal edge cases, import/admin action branches, form-definition error/warning variants,
and additional admin draft/archive/delete/artifact action prompts and failures.

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

## Continuation checkpoint - 2026-05-26 08:12:26 UTC

This continuation targeted `contract_templates/export_service.py`, selected from the largest
remaining gaps as a high-value non-GUI workflow target. The tests exercise real export, preview,
resolution, registry, DOCX, and artifact behaviours with fake collaborators only at external
boundaries.

Tests added or expanded:

- `tests/contract_templates/test_export_service.py`
  - Qt WebEngine file/HTML render success and failure paths, including load failure, print failure,
    missing output, view creation, and deterministic base URL behaviour.
  - export entry-point failures for missing drafts, missing revisions, missing templates, and
    unsupported HTML-working-draft normalization.
  - payload resolution paths for duplicate-number controls, removed catalog placeholders, missing
    selected records, duplicate-iterated placeholders, stale selections, and indexed duplicate
    warning/error branches.
  - catalog and registry service boundaries for unavailable services, missing records, unsupported
    namespaces, and missing code registry services.
  - HTML preview synchronization/materialization source failures and preview-session pruning with
    malformed keep paths.
  - DOCX split-placeholder/corrupted-part recovery, render helper formatting, managed artifact
    storage failures, unsupported source formats, Pages availability failures, and HTML fallback PDF
    rendering.

Validation run after this continuation's coverage implementation:

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
- Export-service focused coverage command: `31 passed`, `1 warning`, `24 subtests passed`.
- Full pytest with coverage fail-under disabled: `1879 passed`, `786 warnings`,
  `74 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.5714%`, below the 95% gate (`1879 passed`, `781 warnings`,
  `74 subtests passed`).
- Ruff, Black check, and mypy: passed.
- Full branch-aware coverage after this batch: `81.5714%` displayed as `82%`.
- Statement coverage: `85.2203%` displayed as `85%`.
- Branch coverage: `69.4478%` displayed as `69%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/contract_templates/export_service.py`: `74.2245%` to `91.8759%`
  (`209` to `65` missing lines, `140` to `45` missing branches).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `10565`
missing lines and `6573` missing branches. At the current denominator (`71483` statements plus
`21514` branches), roughly `12491` additional line/branch slots would need to be covered to reach
95% without adding production code.

Remaining largest combined line/branch gaps:

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

Remaining `contract_templates/export_service.py` gaps are now mostly specialized failure variants:
owner blank aggregation, a low-level base URL branch, registry generation/category failure branches,
work/right/asset direct record variants, HTML preview clone fallback branches, draft storage/export
HTML storage error branches, Pages conversion temporary-file branches, and DOCX paragraph layout
fallback branches.

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

## Continuation checkpoint - 2026-05-26 08:43:39 UTC

This continuation returned to `history/manager.py` as requested. It added behavioural recovery and
replay coverage for snapshot/file rollback failures, missing snapshot/action payloads, archive
metadata helpers, sidecar persistence boundaries, stale head repair, status bootstrap, coalescing
negative paths, and JSON/path/timestamp helper fallbacks.

Tests added or expanded:

- `tests/history/test_history_recovery.py`
  - direct `HistoryEntry` factory for replay-path assertions.
  - `_apply_entry_payload` and snapshot action redo/undo missing-payload boundaries.
  - `_replay_entry` restore failure with failed file-state and snapshot-state rollback attempts.
  - archive/missing-path/root-normalization/manifest inference helper behaviour.
  - explicit snapshot/backup insert IDs, reload failure propagation, and sidecar write failure
    tolerance.
  - stale `HistoryHead`, bootstrap readiness, setting coalescing, `_loads`, `_remove_path`, and
    `_now_stamp` boundary behaviours.

Validation run after this continuation's coverage implementation:

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
- Focused history-manager coverage command: `53 passed`, `1 warning`, `4 subtests passed`.
- Full pytest with coverage fail-under disabled: `1884 passed`, `767 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.6715%`, below the 95% gate (`1884 passed`, `767 warnings`,
  `78 subtests passed`).
- Ruff, Black check, and mypy: passed.
- Full branch-aware coverage after this batch: `81.6715%` displayed as `82%`.
- Statement coverage: `85.3042%` displayed as `85%`.
- Branch coverage: `69.6012%` displayed as `70%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/history/manager.py`: `91.6775%` to `95.8821%`
  (`101` to `40` missing lines, `91` to `55` missing branches).

Remaining `history/manager.py` gaps after this batch:

- missing lines: `738`, `794`, `800`, `802`, `1420`, `1493-1495`, `1715-1716`,
  `1730`, `1733`, `1765`, `2122`, `2165`, `2176`, `2194`, `2216`, `2332-2339`,
  `2472`, `2651`, `2818`, `2821`, `2893-2894`, `2900-2903`, `2907-2909`, `3025`.
- missing branches are concentrated around early transaction/backup guards, status/coalescing/
  bootstrap fallbacks, snapshot archive side-effect exits, cleanup/path loop boundaries,
  external-state manifest branches, and late invariant/repair bookkeeping branches.

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `10505`
missing lines and `6540` missing branches. At the current denominator (`71483` statements plus
`21514` branches), roughly `12396` additional line/branch slots would need to be covered to reach
95% without adding production code.

Remaining largest combined line/branch gaps:

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

## Continuation checkpoint - 2026-05-26 09:16:02 UTC

This continuation used the validated `history/manager.py` checkpoint as the baseline and moved into
the next largest workflow target, `isrc_manager/main_window.py`. The tests stayed headless-safe and
targeted history-adjacent workflow helpers directly with fake managers, fake dialogs, fake task
submitters, and fake prompts.

Tests added or expanded:

- `tests/test_main_window_helpers.py`
  - Qt message filter branches for filtered multimedia/font messages, stderr fallback, previous
    handler forwarding, and the already-installed early return.
  - setting-bundle and file-history action workflows for unchanged no-ops, capture/record success,
    mutation rollback, failed rollback logging, callable labels, and payload factories.
  - history candidate, undo, redo, session-profile open/reload/delete, invalid timestamp, no-candidate,
    and exception-reporting paths.
  - manual snapshot, snapshot delete, backup delete, restore snapshot, and history dialog paths for
    missing managers, prompt cancellation, denied task budget, success callbacks, and error callbacks.

Validation run after this continuation's coverage implementation:

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

- Focused helper test file: `14 passed`.
- Focused main-window helper coverage command: `14 passed`.
- Full pytest with coverage fail-under disabled: `1888 passed`, `775 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `81.8370%`, below the 95% gate (`1888 passed`, `775 warnings`,
  `78 subtests passed`).
- Full branch-aware coverage after this batch: `81.8370%` displayed as `82%`.
- Statement coverage: `85.4609%` displayed as `85%`.
- Branch coverage: `69.7964%` displayed as `70%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/main_window.py`: `75.0210%` to `77.6398%`
  (`1011` to `898` missing lines, `477` to `434` missing branches).

Remaining `main_window.py` gaps after this batch:

- early remaining missing lines begin at `1012`, `1013`, `1062`, `1194`, `1204`,
  `1205`, `1242`, `1248`, `1249`, `1256`, `1257`, `1262`, `1377-1382`,
  `1504`, `1601-1603`, `1609-1610`, `1639-1640`, `1668`, `1684`, `1696-1697`,
  `1720`, `1876`, `1879`, `1887`, `1900-1902`, `1921`, `1985`, `2035`,
  `2338`, `2341`, `2610`, `2692-2693`, `2796`, `2849-2850`, `2877`, `2880`,
  `2899`, `2988-2991`, `3024-3026`, `3042-3043`, and `3140-3141`.
- remaining branch gaps are concentrated around startup/settings guards, action routing, dialog
  fallbacks, backup/restore, storage conversion, catalog/media dispatch, diagnostics/report flows,
  and shutdown/history cleanup boundaries.

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The temporary focused coverage artifact `coverage-main-window-helper.json` was removed.

The 95% target still requires additional behavioural batches. The remaining measured gap is `10393`
missing lines and `6498` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `12242` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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
  fake controllers and prompt services.
- Batch P2: continue `contract_templates/dialogs.py` admin action/delete/archive/artifact prompts,
  import cancellation/failure, form-definition error variants, and remaining preview rebuild/fallback
  branches.
- Batch P3: continue `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch P4: target `code_registry/workspace.py`, `contract_templates/service.py`,
  `exchange/service.py`, or `authenticity/service.py` with transaction, missing-file,
  registry-conflict, cleanup, and rollback tests.

## Continuation checkpoint - 2026-05-26 09:54:11 UTC

This continuation used the validated history/main-window checkpoint as its baseline. Because
`isrc_manager/history/manager.py` was already above the gate at `95.8821%`, the next safer
high-value target was `isrc_manager/contract_templates/dialogs.py`. The tests stayed headless-safe
and covered admin workflows, prompt boundaries, fake export services, real template service state,
and narrow widget helper branches without full-window automation.

Tests added or expanded:

- `tests/contract_templates/test_dialogs.py`
  - admin import and revision flows for missing profile services, file/input cancellation,
    create/import failures, successful DOCX import, revision failure, revision success, and
    no-selection guards.
  - template duplicate/archive/delete flows for confirmation cancellation, service failures,
    archive/restore state transitions, delete-with-files success, and no-selection guards.
  - revision, draft, snapshot, and artifact lifecycle flows for rescan, rebind, activation,
    export, archive/restore, open failure, delete cancellation, delete failure, delete success,
    unmanaged-artifact safety warnings, and no-artifact/no-draft guards.
  - selector-registry and manual-field widget branches for unavailable registry reasons,
    contract/track code generation, unsupported selectors, auto-field warnings, manual choices,
    date formats, and text fallback widgets.

Validation run after this continuation's coverage implementation:

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

- Focused admin workflow tests: `4 passed`.
- Focused profileless/no-selection guardrail test: `1 passed`.
- Focused fill registry/manual widget test: `1 passed`.
- Full contract-template dialog test file: `75 passed`.
- Full pytest with coverage fail-under disabled: `1894 passed`, `775 warnings`,
  `78 subtests passed`.
- Compileall: passed.
- Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `82.3113%`, below the 95% gate (`1894 passed`, `775 warnings`,
  `78 subtests passed`).
- Full branch-aware coverage after this batch: `82.3113%` displayed as `82%`.
- Statement coverage: `85.9225%` displayed as `86%`.
- Branch coverage: `70.3124%` displayed as `70%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/contract_templates/dialogs.py`: `79.6135%` to `88.7157%`
  (`629` to `301` missing lines, `352` to `242` missing branches).
- Aggregate branch-aware coverage: `81.8370%` to `82.3113%`
  (`10393` to `10063` missing lines, `6498` to `6387` missing branches).

Remaining `contract_templates/dialogs.py` gaps after this batch:

- interactive HTML preview internals around `318`, `386`, `412`, `441-488`, and `537-589`.
- workspace/dock layout branches around `1031`, `1172-1376`, `1412`, `1428`, `1473`, and `1476`.
- advanced admin and table fallback paths around `1660-1706`, `1959`, `1966`, `2203-2308`,
  `2405`, `2423`, `2777-2825`, `3025-3070`, `4806`, `4812`, `4815-4816`, `4840`,
  `4849`, `4858`, `4867`, `4908`, and `4956`.
- fill-form read/write, selector, and clipboard edges around `5202-5990`, `6050-6052`,
  `6181`, `6241-6256`, `6413`, `6415`, `6439`, and `6442`.

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `10063`
missing lines and `6387` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `11801` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

Recommended next batch:

- Batch Q1: continue `main_window.py` backup/restore, catalog/media routing, GS1/storage
  conversion, diagnostics, update, settings/action dispatch, and shutdown cleanup workflows.
- Batch Q2: continue `contract_templates/dialogs.py` interactive HTML preview, workspace/dock
  layout, advanced admin/table fallbacks, fill-form read/write, selector, and clipboard branches.
- Batch Q3: target `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch Q4: target `contract_templates/service.py`, `exchange/service.py`,
  `code_registry/service.py`, or `authenticity/service.py` with transaction, missing-file,
  registry-conflict, cleanup, and rollback tests.

## Continuation checkpoint - 2026-05-26 10:21:08 UTC

This continuation stayed on `isrc_manager/contract_templates/dialogs.py` and targeted the remaining
fill-workflow helper cluster from the previous checkpoint. The new tests cover real panel state and
widgets, real draft/snapshot/artifact service records, and fake prompt/export/preview boundaries
only where a deterministic failure or cancellation branch is needed.

Tests added or expanded:

- `tests/contract_templates/test_dialogs.py`
  - expanded `test_fill_registry_generation_and_manual_widget_branches_cover_guardrails` for release
    registry availability, selector-click forwarding, registry/contract service absence, and
    available registry auto-field tooltip branches.
  - added `test_fill_draft_selection_export_and_preview_helper_edges` for invalid/missing fill combo
    selections, successful admin-draft open into the fill tab, draft name/storage fallbacks, export
    status, latest-PDF lookup, clean/dirty export readiness, and suspended/current HTML preview
    refresh state.
  - added `test_fill_widget_state_symbol_details_and_manual_helper_edges` for selector/manual widget
    clearing, indexed selector rebuild preservation, widget read/write semantics, date format
    synchronization, dirty-state preview refresh, symbol detail rendering, manual symbol preview
    failures, fill change guards, draft change guards, and clipboard no-op guards.

Validation run after this continuation's coverage implementation:

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
- Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `82.4489%`, below the 95% gate (`1896 passed`, `784 warnings`,
  `78 subtests passed`).
- Full branch-aware coverage after this batch: `82.4489%` displayed as `82%`.
- Statement coverage: `86.0233%` displayed as `86%`.
- Branch coverage: `70.5727%` displayed as `71%`.

Updated module coverage from the full-suite JSON:

- `isrc_manager/contract_templates/dialogs.py`: `88.7157%` to `91.3342%`
  (`301` to `230` missing lines, `242` to `187` missing branches).
- Aggregate branch-aware coverage: `82.3113%` to `82.4489%`
  (`10063` to `9991` missing lines, `6387` to `6331` missing branches).

Remaining `contract_templates/dialogs.py` gaps after this batch:

- interactive HTML preview/native input paths around `318`, `386`, `412`, `441-488`, `537-589`,
  and `817-828`.
- dock/workspace layout state and repair paths around `1031`, `1172-1376`, `1412`, `1428`,
  `1473`, `1476`, and `1524-1525`.
- advanced admin/import/revision/table fallback paths around `1660-1706`, `1959-1966`,
  `2203-2308`, `2405`, `2423`, `2777-2825`, `3025-3070`, `3365-3371`, `3451-4486`,
  and `4806-5095`.
- narrow remaining fill-form branches around draft delete-with-files, admin change handlers,
  table-selection absent-service guards, restore-selection item gaps, and fallback placeholders
  (`5311`, `5322-5324`, `5397`, `5402`, `5413-5425`, `5879`, `6413`, `6415`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `9991`
missing lines and `6331` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `11673` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

Recommended next batch:

- Batch R1: move back to `main_window.py` backup/restore, catalog/media routing, GS1/storage
  conversion, diagnostics, update, settings/action dispatch, and shutdown cleanup workflows.
- Batch R2: target `media/preview_dialogs.py` active load result, raw-preview source loading,
  preload cache eviction/budget, artwork context menu/export, volume/gain, and visualization release
  branches.
- Batch R3: continue `contract_templates/dialogs.py` layout/repair/interactive-preview/admin-table
  branches after the fill-form reduction.
- Batch R4: target `contract_templates/service.py`, `exchange/service.py`,
  `code_registry/service.py`, or `authenticity/service.py` with transaction, missing-file,
  registry-conflict, cleanup, and rollback tests.

## Continuation checkpoint - 2026-05-26 10:52:16 UTC

This continuation targeted `isrc_manager/main_window.py`, the largest remaining combined
line/branch gap after checkpoint 4.17. The batch added headless-safe workflow tests for database
maintenance, album track ordering, edit routing, and GS1 dialog routing by exercising real `App`
methods on an unconstructed instance with fake dialogs, message boxes, background task runners, and
services. No production-code changes were made.

Tests added in `tests/test_main_window_helpers.py`:

- `test_main_window_database_maintenance_workflows_record_history_and_recover`
  - Exercises backup missing-db guard, backup history/file-effect recording, integrity verification,
    restore cancel/no-confirm, successful restore snapshot/safety-copy recording, restore worker
    error recovery, and restore finalization rollback from a safety copy.
- `test_main_window_album_track_ordering_dialog_covers_noop_and_reorder_paths`
  - Exercises album-order guards, dialog rejection, unchanged-order no-op, successful background
    reorder mutation/progress/refresh/status handling, and missing-track mutation failure.
- `test_main_window_editor_and_gs1_routing_cover_selection_and_dialog_failures`
  - Exercises edit dialog success/failure, selected-editor invalid/no-selection branches, explicit
    batch routing, GS1 no-selection/invalid-selection/success/failure branches, and cell edit routing.

Final coverage after the required `--cov-fail-under=95` run:

- Full branch-aware coverage: `82.4489%` to `82.7263%`
- Statement coverage: `86.0233%` to `86.3142%`
- Branch coverage: `70.5727%` to `70.8051%`
- Missing lines: `9991` to `9783`
- Missing branches: `6331` to `6281`
- `isrc_manager/main_window.py`: `77.6398%` to `81.9708%`
  (`898` to `690` missing lines, `434` to `384` missing branches)

Validation commands run:

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
- Full main-window helper file after first addition: `16 passed`.
- First full pytest with coverage fail-under disabled: `1898 passed`, `758 warnings`,
  `78 subtests passed`.
- Focused editor/GS1 routing test: `1 passed`.
- Full main-window helper file after second addition: `17 passed`.
- Second full pytest with coverage fail-under disabled: `1899 passed`, `690 warnings`,
  `78 subtests passed`.
- Compileall, Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `82.7263%`, below the 95% gate (`1899 passed`, `783 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `9783`
missing lines and `6281` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `11415` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

## Continuation checkpoint - 2026-05-26 11:13:46 UTC

This continuation checked the original preferred target first. `isrc_manager/history/manager.py`
was already at `95.8821%` in the refreshed full-suite report, with `40` missing lines and `55`
missing branches, so the batch stayed on the safer and higher-value target from checkpoint 4.18:
`isrc_manager/main_window.py`. No production-code changes were made.

Tests added in `tests/test_main_window_helpers.py`:

- `test_main_window_media_attach_helpers_cover_validation_matching_and_artwork_payloads`
  - Exercises audio-duration widget updates, file-picker cancel/selection routing, duplicate
    track-number warning branches, media candidate matching, missing-file guards, album-art attach
    planning, add-track media-source routing, and artwork payload fallback/override handling.
- `test_main_window_clipboard_helper_covers_empty_select_all_headers_and_sparse_cells`
  - Exercises clipboard copy with no model, select-all fallback, headers, sparse selections, empty
    cells, and empty selected-index short-circuit handling.

Final coverage after the required `--cov-fail-under=95` run:

- Full branch-aware coverage: `82.7263%` to `82.9156%`
- Statement coverage: `86.3142%` to `86.4723%`
- Branch coverage: `70.8051%` to `71.0979%`
- Missing lines: `9783` to `9670`
- Missing branches: `6281` to `6218`
- `isrc_manager/main_window.py`: `81.9708%` to `84.9589%`
  (`690` to `576` missing lines, `384` to `320` missing branches)

Validation commands run:

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
- Full main-window helper file after media-attach addition: `18 passed`.
- Focused media-attach plus clipboard helper tests: `2 passed`.
- Full main-window helper file after clipboard addition: `19 passed`.
- Full pytest with coverage fail-under disabled: `1901 passed`, `785 warnings`,
  `78 subtests passed`.
- Compileall, Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `82.9156%`, below the 95% gate (`1901 passed`, `758 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `9670`
missing lines and `6218` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `11239` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

## Continuation checkpoint - 2026-05-26 11:53:29 UTC

This continuation again checked `isrc_manager/history/manager.py` before choosing the next target.
The current full-suite evidence still had history above the 95% gate at `95.8821%`, with `40`
missing lines and `55` missing branches, so the batch used the safer higher-yield seams in
`isrc_manager/main_window.py` and `isrc_manager/media/preview_dialogs.py`. No production-code
changes were made.

Tests added in `tests/test_main_window_helpers.py`:

- `test_main_window_key_and_drop_event_routing_cover_handled_paths`
  - Exercises key routing, zoom event filtering, drag/drop acceptance, and table space-preview
    paths.
- `test_main_window_storage_conversion_blob_export_and_badge_workflows`
  - Exercises custom blob export and attach workflows, cancellation/error/success branches,
    attach rollback, storage conversion classification, worker callback paths, badge/icon/tooltip
    helpers, and track-list helpers.
- `test_main_window_table_header_layout_visibility_and_state_workflows`
  - Exercises table settings prefixes, header manager binding, header spec fallback/default-hidden
    behaviour, state save/load, action sync, visibility menus, and invalid/successful column
    toggles.

Tests added in `tests/test_media_preview_preload.py`:

- `test_audio_preview_dialog_active_load_cache_raw_and_submission_paths`
  - Exercises cached preview application, waiting-preload fallback, inline active-load submission,
    cache-hit/inflight/fresh-load track preview routing, raw preview cancellation, eviction, and
    state application.
- `test_audio_preview_dialog_result_cache_cleanup_and_source_loading_paths`
  - Exercises ignored/cancelled/stale/error/success active-load results, apply-fail cleanup, media
    disposal, retained-key cancellation, cache/budget eviction, and prepared/raw source loading.

Final coverage after the required `--cov-fail-under=95` run:

- Full branch-aware coverage: `82.9156%` to `83.2328%`
- Statement coverage: `86.4723%` to `86.7801%`
- Branch coverage: `71.0979%` to `71.4465%`
- Missing lines: `9670` to `9450`
- Missing branches: `6218` to `6143`
- `isrc_manager/main_window.py`: `84.9589%` to `87.7119%`
  (`576` to `457` missing lines, `320` to `275` missing branches)
- `isrc_manager/media/preview_dialogs.py`: `85.5374%` to `89.4626%`
  (`293` to `193` missing lines, `186` to `156` missing branches)

Validation commands run:

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
- Compileall, Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `83.2328%`, below the 95% gate (`1906 passed`, `716 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `9450`
missing lines and `6143` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `10944` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

## Continuation checkpoint - 2026-05-26 12:10:56 UTC

This continuation targeted `isrc_manager/tracks/edit_dialog.py`, a named priority module that was
still below the gate at `92.1926%`. The batch added real headless `EditDialog` construction coverage
and focused helper/workflow branches around bulk edit state, missing records, shared album art,
focus routing, media hints, and commit-failure callbacks. No production-code changes were made.

Tests added in `tests/tracks/test_edit_dialog_behaviors.py`:

- `test_edit_dialog_constructor_covers_single_and_bulk_layout_branches`
  - Exercises actual single and bulk dialog construction, combo source deduplication, managed
    database media displays, BUMA work-managed state, mixed bulk notes, locked bulk controls, shared
    artwork hints, and same-value locked bulk length/date branches.
- `test_edit_dialog_remaining_helper_edges_cover_empty_missing_and_menu_paths`
  - Exercises empty batch normalization, missing bulk snapshots, missing services, combo empty
    selection, bulk artist fallbacks, authority refresh, broken/fallback focus widgets, disabled and
    missing-tab focus targets, artwork display, owner filtering, artwork master menu paths, album-art
    controls, bulk state no-ops, focus registration, and mixed media apply behaviour.
- `test_edit_dialog_remaining_constructor_focus_hint_and_commit_edges`
  - Exercises no-saved-audio construction, initial focus, preferred focus widgets, successful focus
    routing, blank linked-work fallback, duplicate shared-art hint deduplication, and swallowed
    commit failures in single and bulk success callbacks.

Final coverage after the required `--cov-fail-under=95` run:

- Full branch-aware coverage: `83.2328%` to `83.3446%`
- Statement coverage: `86.7801%` to `86.8668%`
- Branch coverage: `71.4465%` to `71.6417%`
- Missing lines: `9450` to `9388`
- Missing branches: `6143` to `6101`
- `isrc_manager/tracks/edit_dialog.py`: `92.1926%` to `98.0481%`
  (`62` to `8` missing lines, `58` to `22` missing branches)

Validation commands run:

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
- Compileall, Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `83.3446%`, below the 95% gate (`1909 passed`, `763 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `9388`
missing lines and `6101` missing branches. At the current denominator (`71483` statements plus
`21514` branches), `10840` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

## Continuation checkpoint - 2026-05-26 12:43:39 UTC

This continuation targeted `isrc_manager/contract_templates/service.py`, the largest remaining
service-level gap after the previous edit-dialog batch. It added focused behavioural tests for
template/revision guardrails, corrupt HTML imports, managed-file cleanup, storage conversions,
placeholder inventory replacement, draft recovery, snapshots, output artifacts, and delete cleanup.
It also fixed corrupt HTML ZIP package handling so path and byte inputs now raise
`ContractTemplateIngestionError` instead of leaking `zipfile.BadZipFile`.

Tests added in `tests/contract_templates/test_revision_service.py`:

- `test_template_revision_guardrails_assets_and_bad_imports_are_rolled_back`
  - Exercises missing template/revision/source guards, corrupt HTML ZIP scan/import rollback,
    archived template listing and duplicate propagation, and revision asset normalization.
- `test_revision_storage_html_resolution_and_inventory_edge_paths`
  - Exercises missing revision lookups, unsupported scan dispatch, Pages scan success/failure,
    corrupted source state, missing managed files, revision storage conversion, HTML storage
    rejection, HTML bundle normalization failure/success, support probes, and placeholder/binding
    inventory replacement.
- `test_draft_payload_working_file_snapshot_artifact_and_delete_edges`
  - Exercises draft update, archive/unarchive, list filters, storage conversion, missing/corrupted
    payload paths, missing working paths, unconfigured storage, resolved snapshots, artifacts,
    artifact deletion, and draft cleanup.
- `test_delete_template_removes_managed_sources_drafts_and_output_artifacts`
  - Exercises full template cleanup of managed HTML source bundles, draft payloads, working HTML
    trees, resolved snapshots, output artifacts, and repeated-delete guards.

Production change:

- `isrc_manager/contract_templates/html_support.py` catches `BadZipFile` for HTML ZIP path and byte
  ingestion and re-raises the workflow-level ingestion error.

Final coverage after the required `--cov-fail-under=95` run:

- Full branch-aware coverage: `83.3446%` to `83.5038%`
- Statement coverage: `86.8668%` to `86.9840%`
- Branch coverage: `71.6417%` to `71.9392%`
- Missing lines: `9388` to `9305`
- Missing branches: `6101` to `6037`
- `isrc_manager/contract_templates/service.py`: `78.9855%` to `89.4928%`
  (`154` to `74` missing lines, `136` to `71` missing branches)
- `isrc_manager/contract_templates/html_support.py`: `66.7832%` to `68.4932%`
  (`62` to `59` missing lines, `33` missing branches unchanged)

Validation commands run:

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
- Targeted service/html-support coverage check: `16 passed`.
- Compileall, Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage was `83.5038%`, below the 95% gate (`1913 passed`, `784 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The remaining measured gap is `9305`
missing lines and `6037` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `10692` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

## Continuation checkpoint - 2026-05-26 13:00:49 UTC

This continuation targeted `isrc_manager/contract_templates/dialogs.py`. The requested starting
point, `history/manager.py`, was checked against the latest evidence and remains above the module
gate at `95.8821%`, so the safer high-value workflow target was the contract-template workspace
dialog host.

Tests added in `tests/contract_templates/test_dialogs.py`:

- `test_workspace_host_layout_recovery_edges_cover_pending_and_normalizer_paths`
  - Covers layout normalization reentrancy, failing normalizers, not-ready restore deferral,
    pending-state reuse, transient restore churn, and incompatible saved layout states.
- `test_workspace_host_apply_pending_state_handles_missing_visibility_and_restore_errors`
  - Covers pending restore recovery when visibility metadata is absent and `restoreState` raises.
- `test_workspace_host_compaction_resize_and_panel_runtime_edge_paths`
  - Covers missing host layout reset no-ops, visible-dock resize filtering, floating-dock hooks,
    HTML preview runtime cleanup failures, unavailable web-engine fallback, missing preview layout,
    no-view zoom, rebuild coalescing, and missing preview-host guards.

Final coverage after the clean full-suite run with `--cov-fail-under=0`:

- Full branch-aware coverage: `83.5038%` to `83.5489%`
- Statement coverage: `86.9840%` to `87.0232%`
- Branch coverage: `71.9392%` to `72.0043%`
- Missing lines: `9305` to `9277`
- Missing branches: `6037` to `6023`
- `isrc_manager/contract_templates/dialogs.py`: `91.3342%` to `92.2070%`
  (`230` to `202` missing lines, `187` to `173` missing branches)
- `isrc_manager/history/manager.py`: remained `95.8821%`

Validation commands run:

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
- Targeted dialog coverage check: passed.
- Compileall, Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage remained below the 95% gate (`1916 passed`, `779 warnings`,
  `78 subtests passed`).
- Incremental full pytest with `--cov-fail-under=0`: passed (`1916 passed`, `768 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The latest measured gap is `9277`
missing lines and `6023` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `10650` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

Recommended next batch:

- Batch X1: target `main_window.py` delete workflow, shutdown cleanup, settings/update routing,
  diagnostics, bulk operations, and remaining storage conversion callbacks.
- Batch X2: continue `contract_templates/dialogs.py` interactive preview, workspace action state,
  and fill/admin selection/failure branches.
- Batch X3: target `media/preview_dialogs.py` artwork export/context menus, volume/gain,
  visualization release, raw-source failures, and cache boundary cases.

## Continuation checkpoint - 2026-05-26 13:35:02 UTC

This continuation targeted `isrc_manager/main_window.py`, the largest remaining combined gap.
The requested starting point, `history/manager.py`, was checked against the latest evidence and
remains above the module gate at `95.8821%`, so the safer high-value workflow target was the
main-window command-routing and host-helper surface.

Tests added/expanded in `tests/test_main_window_helpers.py`:

- `test_first_launch_close_workspace_and_add_track_guard_workflows`
  - Covers first-launch settings routing, close guards for active background tasks, profile-gated
    catalog/code-registry/global-search actions, workspace panel refresh/configuration, diagnostics
    cleanup panels, add-data row factories, add-track entry wiring, artist lookup, and media filter
    helpers.
- `test_startup_feedback_logging_and_trace_edge_paths`
  - Covers startup feedback reporting, loading progress/status fallbacks, startup completion
    fallbacks, bootstrap log flushing, logging handler cleanup failures, trace field normalization,
    reserved trace context handling, disabled trace logging, and buffered/configured event logging.
- `test_background_task_submission_wrappers_cover_profile_lock_bundle_and_audit_paths`
  - Covers profile-required background task rejection, write-lock task submission, cancellation
    checks, completion progress callbacks, bundle context handling, and schema audit callback
    success/failure paths.
- `test_table_layout_history_hint_and_resize_edge_paths`
  - Covers table layout history suspension, refresh-after-history-change recovery, saved hint
    application, header reorder/resize history routing, signal bind/unbind failures, and compact
    row/column mode toggles.
- The log-viewer helper test now covers a missing logs directory.

No production code changed in this continuation.

Final coverage after the clean full-suite run with `--cov-fail-under=0`:

- Full branch-aware coverage: `83.5489%` to `83.6844%`
- Statement coverage: `87.0232%` to `87.1477%`
- Branch coverage: `72.0043%` to `72.1763%`
- Missing lines: `9277` to `9188`
- Missing branches: `6023` to `5986`
- `isrc_manager/main_window.py`: `87.7119%` to `89.8103%`
  (`457` to `368` missing lines, `275` to `239` missing branches)
- `isrc_manager/history/manager.py`: remained `95.8821%`

Validation commands run:

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
- Compileall, Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage remained below the 95% gate (`1920 passed`, `768 warnings`,
  `78 subtests passed`).
- Incremental full pytest with `--cov-fail-under=0`: passed (`1920 passed`, `776 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The latest measured gap is `9188`
missing lines and `5986` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `10524` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

Recommended next batch:

- Batch Y1: continue `main_window.py` delete workflow, shutdown cleanup, settings/update routing,
  diagnostics, bulk operations, and storage conversion callbacks.
- Batch Y2: continue `contract_templates/dialogs.py` interactive preview, workspace action state,
  and fill/admin selection/failure branches.
- Batch Y3: target `media/preview_dialogs.py` artwork export/context menus, volume/gain,
  visualization release, raw-source failures, and cache boundary cases.

## Continuation checkpoint - 2026-05-26 13:59:51 UTC

This continuation stayed on `isrc_manager/main_window.py`, still the largest remaining combined
gap. The batch added more headless-safe workflow seam coverage for shortcut routing, catalog zoom
gestures, audit failure handling, add-track lookup refresh, save validation exits, generated-ISRC
failure paths, and rollback handling.

Tests added/expanded in `tests/test_main_window_helpers.py`:

- `test_shortcut_zoom_audit_and_refresh_helper_edge_paths`
  - Covers explicit shortcut duplicate/empty registration, disabled shortcut triggering,
    platform-aware shortcut ordering, help HTML rendering, AuditLog write/commit failures,
    background status no-op routing, scaled UI progress fallbacks, edit-identity routing, catalog
    cleanup target collection, and workspace dock identity refresh.
- `test_catalog_zoom_gestures_and_add_track_lookup_edge_paths`
  - Covers wheel/native/pinch zoom calculations and routing, smart zoom reset, gesture no-op paths,
    zoom font scaling, add-track lookup refresh with duplicate/blank values, current-text
    preservation, catalog number refresh, and lazy add-track panel initialization.
- `test_save_validation_media_generation_and_rollback_paths`
  - Covers save validation for missing title/artist, missing Work, invalid UPC/EAN, invalid ISWC,
    lossy audio cancellation, media-storage cancellation, generated-ISRC exhaustion, invalid
    generated-ISRC release, SQLite integrity rollback, and generic save rollback.

No production code changed in this continuation.

Final coverage after the clean full-suite run with `--cov-fail-under=0`:

- Full branch-aware coverage: `83.6844%` to `83.7919%`
- Statement coverage: `87.1477%` to `87.2386%`
- Branch coverage: `72.1763%` to `72.3389%`
- Missing lines: `9188` to `9123`
- Missing branches: `5986` to `5951`
- `isrc_manager/main_window.py`: `89.8103%` to `91.5058%`
  (`368` to `303` missing lines, `239` to `203` missing branches)
- `isrc_manager/history/manager.py`: remained `95.8821%`

Validation commands run:

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
- Compileall, Ruff, Black check, and mypy: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage remained below the 95% gate (`1923 passed`, `785 warnings`,
  `78 subtests passed`).
- Incremental full pytest with `--cov-fail-under=0`: passed (`1923 passed`, `784 warnings`,
  `78 subtests passed`).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The latest measured gap is `9123`
missing lines and `5951` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `10424` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

Recommended next batch:

- Batch Z1: continue `main_window.py` track editor/GS1 fallbacks, bulk media workflows, storage
  conversion callbacks, update/recovery shutdown tails, and remaining action-ribbon paths.
- Batch Z2: continue `contract_templates/dialogs.py` interactive preview, workspace action state,
  and fill/admin selection/failure branches.
- Batch Z3: target `media/preview_dialogs.py` artwork export/context menus, volume/gain,
  visualization release, raw-source failures, and cache boundary cases.

## Continuation checkpoint - 2026-05-26 14:23:46 UTC

This continuation checked `history/manager.py` first, but the current full report showed it already
above the local gate (`95.8821%`, `40` missing lines, `55` missing branches). The batch therefore
targeted `isrc_manager/contract_templates/dialogs.py`, the next safer high-value GUI/workflow
target with substantial branch gaps.

Tests added/expanded in `tests/contract_templates/test_dialogs.py`:

- `test_html_preview_fit_fallbacks_measurement_failures_and_scroll_helpers`
  - Exercises preview fit fallback scheduling, non-fit no-ops, measurement callback type failures,
    content-size fallback failures, retry/finalize behaviour, zoom-step boundary inputs,
    JavaScript scroll routing, and native zoom-state reset.
- `test_fill_title_bar_menu_and_drag_guard_edges`
  - Exercises locked/unlocked dock title-bar action state, disabled floating, safe-drag gating,
    position fallback handling, and release passthrough.
- `test_workspace_host_layout_integrity_repairs_scroll_boundary_states`
  - Exercises central-canvas exposure boundaries, visible scroll-area repair, swallowed repair
    exceptions, missing scroll content, and unrecoverable synthetic layout integrity.
- `test_fill_form_refresh_handles_empty_revision_and_corrupted_definition_states`
  - Exercises uninitialized fill refresh, empty template lists, templates with no revisions, and
    form-definition build failure.
- `test_fill_draft_create_and_html_sync_failures_keep_user_in_draft_context`
  - Exercises draft create failure and post-save HTML sync failure without leaving the fill
    workflow context.

No production code changed in this continuation.

Final coverage after the latest full-suite report:

- Full branch-aware coverage: `83.7919%` to `83.9102%`
- Statement coverage: `87.2386%` to `87.3519%`
- Branch coverage: `72.3389%` to `72.4737%`
- Missing lines: `9123` to `9042`
- Missing branches: `5951` to `5922`
- `isrc_manager/contract_templates/dialogs.py`: `92.2070%` to `94.4929%`
  (`202` to `121` missing lines, `173` to `144` missing branches)
- `isrc_manager/history/manager.py`: remained `95.8821%`

Validation commands run:

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
- Focused coverage probe: passed (`86 passed`); the temporary
  `coverage-contract-dialogs.json` artifact was removed because the full report is authoritative.
- Compileall, Ruff, Black check, and mypy: passed.
- Incremental full pytest with `--cov-fail-under=0`: passed (`1928 passed`, `726 warnings`,
  `78 subtests passed`).
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1`
  because coverage remained below the 95% gate (`1928 passed`, `768 warnings`,
  `78 subtests passed`; `83.91%` total coverage).

The refreshed full coverage report is preserved locally in:

- `coverage.json`
- `htmlcov/`

The 95% target still requires additional behavioural batches. The latest measured gap is `9042`
missing lines and `5922` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `10314` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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
- Batch AA3: continue `contract_templates/dialogs.py` once the larger remaining gaps shrink,
  focusing on admin action fallback/failure paths, WebEngine-unavailable setup, and remaining
  restore-layout branches.

## Continuation checkpoint - 2026-05-26 15:16:20 UTC

This continuation targeted `isrc_manager/media/preview_dialogs.py`, which was still the
second-largest combined GUI/workflow gap after checkpoint 4.26. `history/manager.py` remains above
the local module gate from the prior evidence. No production code changed.

Tests added/expanded in `tests/test_media_preview_preload.py`:

- `test_audio_preview_preload_workers_cover_late_cancel_and_cleanup_failures`
  - Exercises close-failure cleanup, late cancellation, duplicate cancellation checks,
    prepared-media disposal, and owned-source cleanup failure swallowing.
- `test_audio_preview_track_load_close_and_decode_cancel_edges`
  - Exercises track-load close failures and cancellation immediately after decode completion.
- `test_audio_preview_dialog_icon_menu_logging_and_selection_edge_guards`
  - Exercises Windows PATH setup, icon fallback paths, logging failures, empty control/menu guards,
    invalid album/bookmark/play-next inputs, and cached preview-state fallback.
- `test_audio_preview_dialog_preload_cache_waveform_navigation_and_cleanup_edges`
  - Exercises preload-result disposal, bridge shutdown disposal, temp-file hazards, cached waveform
    no-peak state, export filtering, artwork preview boundaries, shuffle/navigation boundaries,
    end-of-media restart, and reset-source exception swallowing.
- Existing image/equalizer tests now cover event-filter zoom routing and existing equalizer-dialog
  synchronization.

Final coverage after the latest strict full-suite report:

- Full branch-aware coverage: `83.9102%` to `84.1338%`
- Statement coverage: `87.3519%` to `87.5351%`
- Branch coverage: `72.4737%` to `72.8316%`
- Missing lines: `9042` to `8911`
- Missing branches: `5922` to `5845`
- `isrc_manager/media/preview_dialogs.py`: `89.4626%` to `95.7428%`
  (`193` to `62` missing lines, `156` to `79` missing branches)

Validation commands run so far in this continuation:

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
- Touched-file Ruff/Black checks: passed.
- mypy: passed.
- Incremental full pytest with `--cov-fail-under=0`: passed (`1932 passed`, `738 warnings`,
  `78 subtests passed`) and refreshed `coverage.json`/`htmlcov/`.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1` because
  coverage remained below the 95% gate (`1932 passed`, `784 warnings`, `78 subtests passed`;
  `84.13%` total coverage).

The 95% target still requires additional behavioural batches. The latest measured gap is `8911`
missing lines and `5845` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `10106` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

Remaining `media/preview_dialogs.py` gaps are now smaller and concentrated around image pinch/paint
fallbacks, remaining icon/init variants, equalizer/bookmark provider edges, cached-state queue
alternatives, visualization release/timer paths, artwork context-menu sender variants, and
close/change event tails.

Recommended next batch:

- Batch AB1: return to `main_window.py` for the largest remaining GUI host gaps, especially
  track editor/GS1 fallbacks, bulk media workflows, storage conversion callbacks,
  update/recovery shutdown tails, and action-ribbon routing.
- Batch AB2: target `exchange/service.py` transaction/import failure and rollback branches.
- Batch AB3: follow with `conversion/dialogs.py` or `works/dialogs.py` using headless-safe dialog
  fakes and prompt/file-picker seams.

## Continuation checkpoint - 2026-05-26 15:18:58 UTC

This continuation targeted `isrc_manager/exchange/service.py`, the largest non-main-window
service/workflow gap after checkpoint 4.27. No production code changed.

Tests added in `tests/exchange/_support.py` and exposed through existing exchange wrappers:

- `case_package_helper_edges_cover_missing_media_and_schema_boundaries`
  - Exercises package helper boundaries, missing schema fallbacks, ownership-interest publisher
    precedence, media path/package resolution, fallback packaged-media byte fetches, missing media
    cleanup warnings, release artwork fallback packaging, unsupported package schemas, missing
    manifests, unsafe ZIP paths, directory extraction, and direct media recovery without an index.
- `case_inspection_import_source_and_identifier_edges_are_recoverable`
  - Exercises CSV sniffer fallback, inspection/import cancellation hooks, package warnings,
    identifier review/staging, import source directory resolution, normalization boundaries,
    media source resolution, and identifier classification/counter edge paths.

Final coverage after the latest strict full-suite report:

- Full branch-aware coverage: `84.1338%` to `84.3027%`
- Statement coverage: `87.5351%` to `87.6680%`
- Branch coverage: `72.8316%` to `73.1198%`
- Missing lines: `8911` to `8816`
- Missing branches: `5845` to `5783`
- `isrc_manager/exchange/service.py`: `81.4839%` to `91.6129%`
  (`169` to `74` missing lines, `118` to `56` missing branches)

Validation commands run in this continuation:

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

- Initial focused exchange pytest completed the selected tests but exited `1` because the default
  coverage plugin applied the global 95% gate to a narrow subset.
- Focused exchange pytest with `--no-cov`: passed (`18 passed`).
- Focused touched-file Ruff/Black checks: passed.
- Required full pytest with `--cov-fail-under=95`: tests passed, then command exited `1` because
  coverage remained below the 95% gate (`1934 passed`, `775 warnings`, `78 subtests passed`;
  `84.30%` total coverage).
- Compileall, full Ruff, full Black check, and mypy: passed.

The 95% target still requires additional behavioural batches. The latest measured gap is `8816`
missing lines and `5783` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `9949` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

Remaining `exchange/service.py` gaps are concentrated around export CSV/XLSX writer branches,
JSON inspection cancellation, supported-target duplicate edges, repair-queue update paths, XML
custom-field conflict/missing-field branches, release upsert matching alternatives, and transaction
rollback/failure paths.

Recommended next batch:

- Batch AC1: target `main_window.py` only through narrow controller-like seams, not brittle
  full-window flows.
- Batch AC2: target `code_registry/service.py` or `authenticity/service.py` for service-level
  behavioural gains with fewer GUI constraints.
- Batch AC3: return to `exchange/service.py` for rollback, XML conflict, repair queue update, and
  export CSV/XLSX direct writer branches.

## Latest Continuation - Code Registry Workflow Edge Coverage

The requested starting point, `history/manager.py`, was checked against the latest coverage evidence
before selecting the target. It remained above the local module gate at `95.8821%` branch-aware
coverage, while `code_registry/service.py` was still a large service-level gap at `78.3740%` with
`145` missing lines and `121` missing branches. This continuation therefore used the safer
higher-value exception and added registry workflow tests.

Tests added in `tests/test_code_registry_service.py` cover:

- Assignment target discovery and guarded assignment across tracks, releases, and contracts.
- Catalog value assurance for generated, stale, imported external, external-identifier, missing,
  and unsupported-owner paths.
- Category/listing, manual/inactive generation, transaction rollback, blank lookup, filtered
  choices, missing delete, and trigger-backed delete failure paths.
- Identifier resolution and assignment for inferred modes, missing/wrong-category records,
  internal/external conflict guards, minimal schema fallback, empty clearing, and missing external
  table behavior.
- Capture/generation failures for invalid inputs, SHA capture/reuse, malformed internal values,
  missing prefixes, sequence exhaustion, SHA collision retry, and generated-entry reload failure.
- External identifier reclassification and legacy schema update/promotion/shadow-state workflows.

Final coverage after the latest passing full-suite report:

- Full branch-aware coverage: `84.3027%` to `84.4790%`
- Statement coverage: `87.6680%` to `87.8009%`
- Branch coverage: `73.1198%` to `73.4406%`
- Missing lines: `8816` to `8721`
- Missing branches: `5783` to `5714`
- `isrc_manager/code_registry/service.py`: `78.3740%` to `91.3821%`
  (`145` to `52` missing lines, `121` to `54` missing branches)

Validation commands run in this continuation:

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
- Focused Ruff and Black checks for the touched test file: passed.
- Full pytest with the strict 95% coverage gate produced an intermediate coverage report and exited
  `1` only because total coverage remains below 95%.
- Full pytest/coverage with `--cov-fail-under=0`: passed (`1938 passed`, `728 warnings`,
  `78 subtests passed`; `84.48%` total coverage).
- Compileall, full Ruff, full Black check, mypy, and `git diff --check`: passed.

The 95% target still requires additional behavioural batches. The latest measured gap is `8721`
missing lines and `5714` missing branches. At the current denominator (`71489` statements plus
`21514` branches), `9785` additional line/branch slots would need to be covered to reach 95%
without adding production code.

Remaining largest combined line/branch gaps:

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

Recommended next batch:

- Batch AD1: target `authenticity/service.py`, `storage_admin.py`, or `services/tracks.py` for
  another service-level workflow batch.
- Batch AD2: target `conversion/dialogs.py` or `works/dialogs.py` with headless-safe dialog tests
  and fake prompt/file services.
- Batch AD3: target `main_window.py` only through command-routing/controller seams.

## Latest Continuation - Contract Template Dialog Layout/Admin Edge Coverage

This stop-point continuation targeted `isrc_manager/contract_templates/dialogs.py`, which was still
a large user-prioritized GUI/workflow gap after the code-registry batch. No production code changed.

Tests added in `tests/contract_templates/test_dialogs.py` cover:

- Workspace host layout recovery and registration boundaries, including pending-state compatibility,
  exposed-canvas false paths, scroll-area content readiness, layout-integrity failures,
  unrecoverable restore reset fallback, floating transition no-ops, dock-layout guard paths, and
  multi-group area rebuild behavior.
- Workspace panel refresh/selection/preview helper edges, including unknown tab fallback, refresh
  routing, restore-suppressed tab changes, validator exception swallowing, deleted-window layout
  notification, inactive-tab refresh no-ops, profileless draft refresh, stale loaded-draft cleanup,
  editable-payload preview refresh, clear-preview fallback, export-without-draft status,
  WebEngine-unavailable preview status, symbol copy no-ops, invalid selected table IDs, file dialog
  path normalization, and suspended admin-change handlers.
- Admin ZIP import/revision dispatch and delete paths, including ZIP import routing to
  `import_html_package_from_path`, record-only template deletion success, delete-with-files failure
  status/warning behavior, and draft delete-with-files success without modal leakage.

Final coverage after the latest passing full-suite report:

- Full branch-aware coverage: `84.4790%` to `84.5768%`
- Statement coverage: `87.8009%` to `87.8807%`
- Branch coverage: `73.4406%` to `73.5986%`
- Missing lines: `8721` to `8664`
- Missing branches: `5714` to `5680`
- `isrc_manager/contract_templates/dialogs.py`: `94.4929%` to `96.4464%`
  (`121` to `62` missing lines, `144` to `109` missing branches)

Validation commands run in this continuation:

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
- Touched-file Ruff and Black checks: passed.
- Full pytest/coverage with `--cov-fail-under=0`: passed (`1941 passed`, `774 warnings`,
  `78 subtests passed`; `84.58%` total coverage).

The session was stopped at this natural handoff point before rerunning the strict
`--cov-fail-under=95` command or full compile/Ruff/Black/mypy validation after this last batch.
The gate remains incomplete, with `9694` additional line/branch slots needed at the current
denominator.

Remaining largest combined line/branch gaps:

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

Recommended next session:

- Batch AE1: target `conversion/dialogs.py` or `works/dialogs.py` with focused headless dialog
  tests and fake file/prompt services.
- Batch AE2: target `authenticity/service.py`, `storage_admin.py`, or `services/tracks.py` for
  service-level branch/error-path coverage.
- Batch AE3: target `main_window.py` only through command-routing/controller seams.
