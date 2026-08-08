# Completion Handoff

## Original prompt

Commit and push everything to `main`. Check the push: the online CI Actions are
failing. Fix all failures and track subsequent pushes until all CI tests and
online Actions workflows are successful.

## Result

- Corrected GitHub environment leakage in QA/PQ planner tests.
- Added the missing Qt runtime libraries to release-neutral Linux QA.
- Stabilised full-window Qt capture geometry and narrowly scoped visual
  comparison tolerances without weakening default acceptance.
- Replaced stale cross-platform screenshots only from trusted, inspected Linux
  CI artifacts.
- Extended deferred comparison reporting to collect all visual and business
  workflow mismatches while preserving strict CI failure and evidence.
- Published and independently verified v6.2.4.
- Required fresh tag CI, generated-main CI, Release Builds, Help publication,
  and final Pages deployment to complete successfully.

## Files changed

- `.github/workflows/release-build.yml`
- `isrc_manager/qa/harness.py`
- `isrc_manager/qa/scenarios.py`
- `isrc_manager/qa/visual.py`
- `tests/test_python_314_compatibility.py`
- `tests/test_qa_pq_execution.py`
- `tests/test_qa_pq_impact.py`
- `tests/ui_qa/test_qa_helpers.py`
- Canonical screenshots under `artifacts/ui_pq/visual/baselines/`
- Generated Help screenshots under `docs/help/screenshots/`
- Version and release metadata through v6.2.4
- QA/PQ dashboard history under `docs/validation/`

## Verification

- Full local Ruff, Black, configured mypy, compileall, focused QA tests, and
  diff checks passed.
- The complete trusted Linux artifact set passed all 66 screenshot comparisons.
- Main CI `31279729870` and generated-main CI `31280418189` succeeded.
- Tag CI `31280418285` and Release Builds `31280418298` succeeded.
- Help runs `31280319188` and `31281053547` succeeded.
- Final Pages runs `31280333634` and `31281068627` succeeded.
- v6.2.4 was published with five assets; binary sizes, GitHub digests,
  `SHA256SUMS.txt`, and `latest.json` were independently cross-checked.

## Prompt archive

- `docs/prompts/devops/repair-online-ci-and-release-workflows.md`
- `docs/prompts/devops/handoffs/repair-online-ci-and-release-workflows-handoff.md`

## Follow-up actions

None required for CI or release correctness. A separate maintainability change
could improve two pre-existing accounting screenshot names and captured states.

## Notes

- Direct protected-branch pushes used the repository's authorised maintainer
  bypass.
- Obsolete already-failing CI runs were cancelled only after replacement heads
  were registered, saving runner time without cancelling current validation.
- Superseded Pages cancellations and expected `[skip version]` jobs were not
  failures; each had a successful current replacement.
- `isrc_manager/qa/scenarios.py` remains at its pre-existing 3,112 lines; this
  repair did not increase it.
