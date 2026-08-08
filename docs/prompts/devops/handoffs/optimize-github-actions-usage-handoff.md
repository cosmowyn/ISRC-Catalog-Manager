# Completion Handoff

## Original prompt

> Analyse and optimise GitHub Actions usage for the ISRC Manager repository without weakening
> required CI, supported-platform release builds, or QA/PQ acceptance strength. Implement
> evidence-based workflow, incremental qualification, provenance, retention, and safe semantic
> cleanup changes; document the audit, tests, estimates, limitations, and operator commands. Do not
> push, merge, publish a release, or perform unreviewed destructive cleanup.

The complete cleaned prompt is archived at
`docs/prompts/devops/optimize-github-actions-usage.md`.

## Result

The audit identified three primary contributors:

- GitHub Release downloads held 65.91 GiB across 420 assets, while active Actions artifacts held
  42.09 GiB; 37.01 GiB of the Actions total was short-lived release intermediates without an
  appropriate retention limit.
- CI and Release Builds were the largest measured workflow consumers at 23.6 and 13.7 aggregate
  run-wall hours respectively. Only two CI SHAs had duplicate push/PR events, so branch-trigger
  deduplication was not the dominant opportunity.
- UI QA/PQ modules were pytest functions passed through a unittest-only grouped runner, so they
  collected zero tests while stale checked-in evidence could still be uploaded. This was a
  correctness defect as well as an efficiency problem.

Implemented changes:

- CI now runs on `main`, `v*` tags, pull requests, a weekly schedule, and explicit manual full
  validation. It uses PR-only cancellation, keeps stable required job names, applies explicit job
  timeouts and 1/7/14/30-day purpose-based artifact retention, and reports an aggregate gate even
  when component work is skipped.
- A standard-library-only impact planner maps changed paths to stable QA/PQ components, closes
  dependencies conservatively, and forces complete validation for tags, schedules, manual full
  requests, shared infrastructure, unknown paths, and uncertain change input.
- UI QA/PQ runs once under pytest. Compatible unaffected component outputs can be reused and merged;
  source/runtime/provenance drift fails closed to a complete regeneration. Schema-v2 provenance
  binds the source commit, trusted producer run, repository input hashes, runner image, Python/Qt
  stack, and exact Linux Qt/XCB/OpenGL package versions.
- The grouped runner now executes unittest-only, pytest-only, and mixed modules without silently
  omitting top-level pytest tests. The previously mixed layout-helper module now runs all ten tests.
- Help validation runs inside CI. The privileged publisher accepts only a successful base-repository
  default-branch push and an exact attested artifact/run/SHA, validates bounded flat PNG input and
  passing evidence, rejects symlink/rename/path attacks, and safely handles the immediate
  dashboard-only automation child before a freshness-guarded push.
- Release validation is performed once for platform-neutral checks while all three supported package
  builds and packaged-binary smoke tests remain. Transfer artifacts use one-day retention and zero
  recompression. Tags must exactly match `[project].version`, peel to the triggering immutable
  commit, and remain bound to that commit immediately before release create/edit and upload.
- Version Bump enforces its repository-specific `[skip version]` marker before runner allocation,
  uses read-only workflow permissions plus a temporary deploy key, and atomically pushes the
  generated main commit and release tag.
- The new weekly cleanup uses exact package/producer allowlists and retains the latest four releases
  in the current minor line, the latest release in each of the previous two minor lines, and the
  latest release in the preceding major line. It protects current/latest, draft, prerelease,
  deployment, and public-link versions; applies 500-item/120 GiB ceilings; revalidates inventory and
  candidate hashes; and writes durable JSONL audits before each deletion request.
- Destructive cleanup is fail-closed both in Actions and locally: `--apply` requires an expected
  default-branch SHA, a real non-sparse clean worktree root, complete public-link index state, API
  agreement with the current default tip, and an immediate repeat of that guard before deletion.

Evidence-based saving estimates:

- The final GET-only cleanup plan found 282 eligible objects totalling 73.541 GiB: 234 GitHub
  Release assets (61.277 GiB) and 48 active Actions artifacts (12.264 GiB). No DELETE request was
  issued.
- One-day release transfer retention prevents the previously observed 37.01 GiB class from
  recurring at the old lifetime. Purpose-based retention is expected to remove another 3.4–5.0 GiB
  of ordinary non-release Actions artifacts at steady cadence.
- The observed upper bound for CI push/PR deduplication is only 2/159 runs (1.3%). No unsupported
  runner-minute percentage is claimed: correct pytest PQ adds validation that the old workflow did
  not actually execute, and incrementality limits that new cost rather than pretending it is a pure
  reduction.

Operator commands:

```bash
gh workflow run ci.yml --ref main -f full_validation=true
gh workflow run cleanup-build-artifacts.yml --ref main -f mode=dry-run
gh workflow run cleanup-build-artifacts.yml --ref main -f mode=apply
```

Direct local apply remains deliberately stricter than dry-run:

```bash
GITHUB_TOKEN=... python scripts/cleanup_github_builds.py \
  --repository cosmowyn/ISRC-Catalog-Manager \
  --repository-root . \
  --expected-default-sha "$(git rev-parse HEAD)" \
  --audit-log github-build-cleanup-audit.jsonl \
  --apply
```

## Files changed

- Workflows:
  - `.github/workflows/ci.yml`
  - `.github/workflows/help-docs-refresh.yml`
  - `.github/workflows/release-build.yml`
  - `.github/workflows/version-bump.yml`
  - `.github/workflows/cleanup-build-artifacts.yml` (new)
- Audit and traceability:
  - `docs/github-actions-audit.md` (new)
  - `docs/prompts/devops/optimize-github-actions-usage.md` (new)
  - `docs/prompts/devops/handoffs/optimize-github-actions-usage-handoff.md` (new)
- QA/PQ planning, execution, and provenance:
  - `isrc_manager/qa/harness.py`
  - `isrc_manager/qa/impact.py` (new)
  - `isrc_manager/qa/impact_rules.py` (new)
  - `scripts/qa_pq_impact.py` (new)
  - `scripts/qa_pq_artifacts.py` (new)
  - `scripts/qa_pq_fingerprints.py` (new)
  - `scripts/qa_pq_provenance.py` (new)
  - `scripts/qa_pq_runtime.py` (new)
  - `scripts/trusted_ci_artifacts.py` (new)
  - `scripts/apply_help_screenshots.py` (new)
  - `scripts/update_qa_pq_history.py`
  - `artifacts/ui_pq/visual/baselines/ui_pq_report_summary.json`
- Cleanup implementation:
  - `scripts/cleanup_github_builds.py` (new)
  - `scripts/github_cleanup_api.py` (new)
  - `scripts/github_build_cleanup_audit.py` (new)
- Tests and grouped-runner ownership:
  - `tests/ci_groups.py`
  - `tests/run_module.py`
  - `tests/test_apply_help_screenshots.py` (new)
  - `tests/test_cleanup_github_builds.py` (new)
  - `tests/test_python_314_compatibility.py`
  - `tests/test_qa_pq_artifacts.py` (new)
  - `tests/test_qa_pq_execution.py` (new)
  - `tests/test_qa_pq_history.py`
  - `tests/test_qa_pq_impact.py` (new)
  - `tests/test_trusted_ci_artifacts.py` (new)
  - `tests/ui_qa/conftest.py`
  - `tests/ui_qa/test_ui_pq_help_documentation.py`
  - `tests/ui_qa/test_ui_pq_inventory.py`
  - `tests/ui_qa/test_ui_pq_smoke.py`
  - `tests/ui_qa/test_ui_pq_traceability.py`

Unrelated pre-existing and concurrently edited worktree files were preserved and are not included in
this task-owned list.

## Verification

- Live audit and cleanup verification used GitHub GET requests only. The final dry-run made 55 GET
  requests and zero non-GET requests; it retained the intended versions and reported 282 eligible
  objects/73.541 GiB with zero deletions.
- Focused workflow, cleanup, provenance, impact, runner, history, and Python-compatibility suite:
  136 passed plus 8 subtests.
- Canonical full UI QA/PQ suite: 30 passed.
- Real mixed grouped module: pytest selected 10 definitions and 10 passed. Group ownership
  verification passed with 3,274 discovered definitions.
- A coverage-enabled history group completed all 54 modules successfully. Earlier complete catalog,
  exchange, and UI application shard runs also passed; the mixed module was subsequently rerun
  through the corrected pytest route.
- Full Ruff passed; full Black check passed for 655 files; configured mypy passed for 50 source
  files; full compileall passed.
- Checksum-verified actionlint 1.7.12 and an independent Ruby YAML parse passed all five workflows.
- The isolated `python -I` impact CLI passed without importing the PySide6 package initializer.
- `pip-audit -r requirements.txt` reported no known vulnerabilities.
- A clean temporary PyInstaller build completed, and the packaged macOS arm64 binary smoke test
  passed for version 6.1.3.
- A clean-workspace full repository run reached 92.78% branch coverage: 3,360 passed, 23 skipped,
  196 subtests passed, and 846 warnings were reported. Its sole failure was a new guard test that
  incorrectly assumed the validation copy retained `.git`; the production guard correctly failed
  closed. The test was made self-contained with a temporary Git worktree, after which the complete
  33-test cleanup suite passed both in the source checkout and the Git-metadata-free validation
  copy. The 14-minute full application run was not repeated after that test-only correction.

## Prompt archive

- Prompt: `docs/prompts/devops/optimize-github-actions-usage.md`
- Completion handoff: `docs/prompts/devops/handoffs/optimize-github-actions-usage-handoff.md`

## Follow-up actions

- After review/merge, manually run one full CI validation, observe the Help publisher, validate the
  next real release tag, and inspect the first weekly cleanup plan/apply audit before relying on the
  recurring steady state.
- Obtain an account billing export or a token with the account scope needed to reconcile the 90%
  usage notification across repositories, Actions artifacts, caches, Packages, and runner SKUs.
- Re-measure job aggregate time and artifact bytes after at least four weeks and replace retention
  modelling with observed steady-state data.
- Review the 74 legacy `workflow_dispatch` release artifacts separately; they are intentionally
  skipped because they do not satisfy the strict tag-push producer policy.
- Consider pinning third-party/official actions to reviewed immutable commit SHAs. Current major
  tags are a documented non-blocking supply-chain opportunity, not a supported usage saving.

## Notes

- No commit, push, merge, tag, release publication, API deletion, or other live destructive action
  was performed.
- The account billing endpoint was unavailable to the current GitHub token, so the audit separates
  measured repository storage/run evidence from explicit estimates and makes no unsupported billing
  claim.
- Unchanged component evidence is not regenerated, but the complete canonical bundle is uploaded on
  each producing run because it is newly provenance-bound and serves as the trusted future baseline.
- Stable required check contexts were prioritised over a dynamic job matrix or top-level path
  filters; skipped components still report a terminal result through the aggregate gate.
- The cleanup API is necessarily non-atomic. Arbitrary external links cannot be discovered, and
  state can still change in the narrow interval after a guard or between individual deletion calls;
  exact allowlists, ceilings, immediate revalidation, durable audit, and idempotent 404 handling
  bound this residual risk.
- No production dependency was added. The Governor used the highest available inherited model and
  reasoning configuration; worker-model availability was not exposed for independent usage-window
  inspection.
- No task-owned production module exceeds 1,000 lines. Cleanup policy/orchestration is 779 lines and
  the artifact orchestrator is 764 lines after their REST, audit, fingerprint, and provenance
  responsibilities were extracted; both should remain capped rather than absorb new concerns.
