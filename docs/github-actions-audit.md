# GitHub Actions usage audit

Audit snapshot: 07-Aug-2026 to 08-Aug-2026. Repository: `cosmowyn/ISRC-Catalog-Manager`
(public).

## Conclusion

The repository's most plausible contribution to an Actions budget warning is **artifact storage,
not charged standard-runner minutes**:

- The Actions Artifacts API reports 809 active artifacts using 42.09 GiB. Versioned release-build
  intermediates account for 146 artifacts and 37.01 GiB of that total. Those intermediates
  duplicate the platform packages that are copied to GitHub Releases.
- GitHub Releases contain another 420 uploaded assets across 84 stable releases, using 65.91 GiB.
  Release assets are a separate download store: they are not returned by the Actions Artifacts API,
  so this audit does not count them as Actions artifact storage or claim that they caused the Actions
  alert.
- The repository uses only standard GitHub-hosted runners and is public. GitHub documents standard
  runner use in public repositories as free, and the latest sampled successful CI timing response
  reports 11 Ubuntu jobs but `billable.total_ms: 0`. Runner history is still analysed below because
  it represents avoidable load and would matter if repository visibility or runner selection changed.
- The account-level Actions billing endpoint was unavailable to the current token because it lacks
  the required `user` scope. Consequently, the reported “approximately 90%” account warning cannot
  be attributed exactly to this repository, nor split into minutes and storage from the available
  credentials. Other repositories and GitHub Packages may share the account's allowance.

[GitHub's billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
distinguishes runner minutes, artifact/Packages storage, and cache storage. It also explains that
storage accrues hourly: deleting an artifact reduces current and future usage, but does not erase
usage already accrued in the current billing cycle.

## Method and limitations

The audit combined the tracked workflow configuration with paginated GitHub REST/CLI data:

- all workflow runs and events, plus per-run and per-job timestamps;
- Actions run-timing data for a recent successful CI run;
- Actions artifact metadata, including active/expired state and byte size;
- Actions cache inventory and byte size;
- stable GitHub Releases and uploaded release assets;
- the active repository ruleset's required check names; and
- static searches for schedules, matrices, concurrency, uploads/downloads, caching, workflow calls,
  local actions, generated commits, and skip markers.

The retained run-history window contains 729 records from 27-Apr-2026 through 07-Aug-2026. Counts in
the workflow table are for that window, not an extrapolated monthly billing period.

Durations in this document are elapsed run wall time (`run_started_at` to `updated_at`), rounded to
minutes. A run with parallel jobs can consume much more aggregate runner time than its wall time, so
the summed 43.9 hours below is **not a billable-minutes total**. Artifact sizes are API metadata
totals. The 240 expired records (24.01 GiB of historical size metadata) are not counted as active
storage. The account billing export is the only authoritative source for the 90% warning.

The recent window from 01-Jul-2026 contained 54 runs: CI 11, Help 9, Release Builds 1, Version Bump 5,
Pages 10, Dependabot 14, and Dependency Graph 4. CI's recent 23.2-minute mean is distorted by one
154.6-minute run-wall outlier (7 success, 1 failure, 3 cancelled); the one recent Release Builds run
took 20.7 minutes. The full-history means in the workflow table are more stable, while the recent
successful job breakdown is more useful for identifying current CI cost drivers.

## Baseline by resource type

| Resource | Observed inventory | Interpretation |
| --- | ---: | --- |
| Workflow runs | 729 runs; 43.9 h summed run wall time | Relative compute/activity only; parallel jobs make this an undercount of aggregate runner time. |
| Active Actions artifacts | 809; 42.09 GiB | Primary repository-level Actions storage concern. |
| Active versioned release intermediates | 146; 37.01 GiB | About 88% of active Actions artifact bytes; duplicates packages published to Releases. |
| Active CI/PQ/coverage/Help/dashboard artifacts | 656; 5.03 GiB | Historically inherited the 90-day repository default because uploads had no `retention-days`. |
| Expired artifact metadata | 240; 24.01 GiB historical size | Excluded from active-storage totals; retained API metadata is not evidence of live downloadable bytes. |
| Actions dependency caches | 4; 1,455,067,292 bytes (1.36 GiB) | Separate cache allowance; below the documented default 10 GiB per-repository cache allowance. Keep because it reduces downloads. |
| GitHub Release uploads | 420 assets; 65.91 GiB | Separate persistent release-download inventory, not Actions artifact API storage. Cleanup is still warranted. |

[GitHub documents](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
a 90-day default for new workflow artifacts and logs. A shorter workflow-level retention applies only
to newly uploaded artifacts; it does not retroactively shorten existing objects.

## Workflow inventory and optimization assessment

“Current retention” describes the audited configuration before this optimization unless explicitly
marked as an implemented working-tree value. Managed workflows have no YAML in this repository.

| Workflow name | Trigger | Approximate frequency | Average duration | Main cost drivers | Artifacts produced | Current retention | Proposed optimisation | Risk of the proposed change | Expected relative saving |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| CI | **Audited:** every non-Dependabot branch `push` plus every PR; no schedule/manual trigger. **Working tree:** `main` and `v*` pushes, PRs, Monday 02:23 UTC, and manual `full_validation` | 159 runs: 103 success, 24 failure, 32 cancelled; 127 push and 31 PR in the available event breakdown; 11 since 01-Jul-2026 | 8.9 min (max 154.6 min; 23.6 h total wall) | 11 historical parallel jobs; four test shards; Qt/APT setup; repeated pip setup; UI shard about 12 min and catalog shard about 6.5 min in a recent success. Correct pytest PQ adds work but runs by impact | Coverage intermediates, impact plan, canonical/reused PQ bundle, failure/Help subsets, XML/JSON coverage, dashboard data | **Audited:** 90 days. **Working tree:** 1 day transfer, 7 days coverage, 14 days PQ/Help/failure, 30 days plan/dashboard | **Implemented in the working tree:** main/tag/PR/full triggers; PR-only cancellation; dependency-free compile; conservative impact plan; producer-attested, schema-v2 provenance reuse; verified renderer runtime; always-reporting dedicated pytest job; explicit timeouts and 1/7/14/30-day retention; read-only contents permission, including Coverage | Medium: change detection, producer identity, runtime compatibility, and provenance must fail closed; every required check must still appear; weekly/tag/full routes add deliberate compute | Direct push/PR duplication was only 2 SHAs historically (at most 1.3% of CI runs), so trigger savings are small in the observed sample. Compile dependency installation took about 25 s. Incremental PQ avoids the much larger *new* cost of full pytest PQ on every isolated change, but no honest before/after percentage exists because those tests previously collected as zero. |
| Version Bump | **Audited and working tree:** push to `main`. **Working tree:** generated `[skip version]` commits still create a workflow record, but the job is skipped before runner allocation | 141 historical runs; 5 since 01-Jul-2026 | 0.3 min (max 0.7 min; 0.8 h total) | Full-history checkout and lightweight release metadata calculation; generated commits can cause downstream workflows | None | Not applicable | **Implemented in the working tree:** enforce the existing `[skip version]` marker in the job condition; keep freshness protection; default to read-only contents and push only with the deploy key; do not add an unsafe generic GitHub skip token that could suppress tag validation/publication | Low: the repository-specific marker affects only Version Bump; tag-triggered CI and Release Builds remain active | Avoids allocating a second Version Bump runner for each generated release commit. The historical count of those jobs was not derived, so no percentage is claimed; other generated-commit fan-out remains an architectural opportunity. |
| Dependency Graph (GitHub-managed) | Dynamic platform event, normally repository/dependency changes | 107 runs; 4 since 01-Jul-2026 | 0.9 min (max 15.1 min; 1.7 h total) | GitHub-managed dependency graph update | No repository-controlled artifacts | Managed | No repository YAML to tune; reduce only avoidable generated commits | Low | Small; about 4% of observed run wall time. |
| Release Builds | **Current:** SemVer-like `v*` tag push only. **Historical 26-Apr-2026 to 01-Jun-2026:** also `workflow_run` after Version Bump | 106 runs: 95 success, 11 failure; 26 tag pushes and 80 historical `workflow_run` events; 1 since 01-Jul-2026 | 7.8 min (max 60.4 min; 13.7 h total) | Required Windows/macOS/Linux package builds and smoke tests; release-neutral QA was repeated on all three OS jobs; transfer of roughly 0.8 GiB per release through temporary artifacts | Three platform package intermediates, then five uploaded release assets including packages/checksums/metadata | **Audited:** 90-day Actions default and persistent Releases. **Working tree:** 1-day intermediates; semantic cleanup for persistent packages | **Implemented in the working tree:** keep all platform builds/smokes; run neutral QA once on Ubuntu; install only build extras in platform jobs; zero recompression; 1-day intermediates; guarded semantic cleanup; default contents read and grant write only to publish | Medium for cleanup, mitigated by strict parsing, active-use protection, protected unknowns/prereleases/current version, whole-inventory revalidation, and no deletion of releases/tags/notes/source archives | The already-removed historical trigger eliminated 80/106 (75%) invocations, but not 75% of compute. Neutral QA removes two duplicates and three platform jobs install fewer extras; exact net minutes are unclaimed. One-day intermediates eliminate nearly all steady-state 37.01 GiB after old objects expire/are cleaned. |
| Help documentation refresh | **Audited:** `main` push plus every PR. **Working tree:** successful base-repository CI `push` runs on the default branch | 86 runs; 9 since 01-Jul-2026 | 1.2 min (max 1.9 min; 1.7 h total) | Audited workflow installed Qt/dependencies and regenerated Help. Working tree API-attests and validates CI output, then conditionally publishes changed screenshots | Audited Help evidence/screenshots; working-tree publisher creates no new artifact and consumes CI's Help subset | **Audited:** 90 days. **Working tree CI producer:** 14 days | **Implemented in the working tree:** PR/main Help pytest runs through impact-planned CI; publisher attests the exact run/artifact/SHA, verifies the download digest plus schema-v2 passing Help evidence, accepts only bounded flat PNG input, atomically replaces each validated PNG, rechecks main freshness, and keeps workflow permissions read-only | Low: CI must continue selecting `visual-help`; producer/artifact/provenance validation must fail closed; publication still depends on the deploy key and a fresh default-branch SHA | Removes the separate full Help test runner while preserving validation in CI. No-output CI runs incur only a short artifact check. The Help artifact lifetime falls from 90 to 14 days (about 84% under stable cadence/size). |
| Pages build and deployment (GitHub-managed) | Dynamic Pages source changes | 85 runs; 10 since 01-Jul-2026 | 1.0 min (max 15.8 min; 1.4 h total) | GitHub-managed Pages build/deploy | Managed Pages deployment | Managed | Continue “commit only on content change”; review Pages source settings separately if generated history commits do not need deployment | Medium because changing Pages source/settings can break the published dashboard | Small; about 3% of observed wall time. `[skip ci]` did not prevent sampled dynamic Pages runs. |
| Dependabot Updates (GitHub-managed) | Two weekly update streams: grouped pip and GitHub Actions updates | 45 runs; 14 since 01-Jul-2026 | 1.3 min (max 3.0 min; 1.0 h total) | Dependency resolution plus the PR validations that update PRs subsequently trigger | No repository-controlled artifacts | Managed | Existing grouping and open-PR limits are appropriate; keep weekly cadence | Low | No supported material saving without reducing update coverage. |
| Cleanup obsolete build downloads | Weekly Monday 03:17 UTC read-only plan followed by guarded apply; manual `workflow_dispatch` dry-run/apply choice | New; no historical runs | Not yet measured; 20 min per-job timeout | Paginated release/artifact/deployment inventory and conservative API deletion | Per-item JSONL plans/apply logs and job summaries | **Working tree:** 30 days for the small audit artifacts | **Implemented in the working tree:** separate read-only plan and write-capable apply jobs; scheduled apply after a successful plan; manual apply only from the default branch; immutable checkout; an immediate default-tip equality gate before public-link analysis; exact package/producer allowlists; active-use protection; fresh whole-inventory/candidate-fingerprint revalidation before the first deletion; 500-item/120 GiB ceilings; durable audit; least privilege | Medium because deletion is irreversible and the operation is not atomic: arbitrary external links cannot be discovered, and protected state could change after the default-tip check or pre-delete revalidation, or between individual deletions. Current repository, release-note, deployment, and Pages surfaces are scanned | The hardened live plan found 73.541 GiB eligible across Actions artifacts and Release downloads. Weekly guarded apply prevents that eligible inventory from accumulating again; explicit upload retention limits Actions recurrence. |

### Working-tree implementation status

- `ci.yml` implements main/tag/PR/manual/weekly triggers, PR-only cancellation, bounded jobs, a
  dependency-free compile check, exact-purpose retention, and component-aware pytest QA/PQ with
  producer-attested canonical output reuse. A reusable baseline must come from a successful
  completed default-branch `push` of the exact CI workflow in the same base/head repository.
  Artifact metadata must match that run's repository, branch, ID, and SHA. Schema-v2 provenance
  binds the bundle commit to the attested SHA and verifies runtime plus relevant-input hashes; any
  mismatch forces full regeneration. CI, including the Coverage job, has read-only contents
  permission.
- `help-docs-refresh.yml` no longer runs another Qt/pytest validation. After a successful main CI,
  it publishes changed screenshots only for an attested base-repository default-branch `push`
  producer. It verifies the exact run/artifact/SHA, download digest, schema-v2 source provenance,
  and passing Help evidence; rejects symlinks, nested/non-PNG files, and size/count violations;
  atomically replaces each validated PNG; and checks main freshness before download and commit.
  The freshness gate also accepts the exact one-commit dashboard-only child produced by the same CI
  run, checks its parent, subject, and complete path allowlist, and publishes screenshots on top of
  that commit. This avoids starving Help publication after CI's `[skip ci]` dashboard update without
  accepting stale screenshots across code or unrelated-data changes.
  Actions/contents stay read-only, checkout does not persist the token, and publishing uses the
  deploy key with GitHub SSH host keys fetched through the authenticated TLS API.
- `release-build.yml` keeps all three package/smoke platforms, moves platform-neutral checks to one
  Ubuntu job, installs only build extras in platform jobs, and gives already-compressed intermediates
  one-day zero-recompression transfer storage. Its prepare gate requires the tag version to match
  `[project].version`, requires the peeled tag commit to equal the triggering checkout, and passes
  that immutable commit SHA to every downstream checkout. Publication re-attests the remote tag
  immediately before both release mutations. Contents are read-only by default and write access is
  scoped to the publication job.
- `cleanup-build-artifacts.yml` and `scripts/cleanup_github_builds.py` implement a weekly read-only
  inventory followed by a guarded scheduled apply. Manual dispatch remains dry-run by default, with
  apply restricted to the default branch. Apply first requires its checkout to remain the current
  default-branch tip, then rebuilds and revalidates the complete inventory and candidate fingerprint
  immediately before its first deletion and aborts with zero deletions on drift.
- `version-bump.yml` now gives the workflow read-only contents permission and enforces its existing
  `[skip version]` marker in the job condition. The generated release commit therefore does not
  allocate another Version Bump runner; its deploy key performs the intentional main/tag update as
  one atomic remote transaction, so neither ref advances when the other is rejected.
- Focused security unit/static tests cover producer and artifact attestation,
  runtime/provenance drift, Help evidence and file-boundary validation, and the privileged workflow
  gates described above.

### Ranked causes

1. **Release-build intermediates dominate Actions artifact storage.** They occupy 37.01 of 42.09
   active GiB. Keeping cross-job artifacts for publication is correct; keeping each duplicate for the
   90-day default is not.
2. **Old GitHub Release downloads dominate persistent repository downloads.** Eighty-four releases at
   roughly 0.8 GiB each produced 65.91 GiB. This is separate from the Actions artifact quota, but is
   material obsolete storage requested for cleanup.
3. **CI dominates relative runner work.** CI contributes 23.6 of 43.9 hours (54%) of summed run wall
   time. CI plus Release Builds contribute 37.3 hours (85%). A recent successful CI run had about 31
   aggregate job-minutes despite 13.9 minutes of run wall time: UI 12.0, catalog 6.5, history 3.0,
   exchange 2.2, coverage 1.5, and roughly 0.8–1.3 minutes for each remaining check.
4. **The obsolete release trigger inflated historical workflow count.** The former `workflow_run`
   trigger caused 80 of 106 Release Builds invocations. It was removed on 01-Jun-2026; the current workflow
   is tag-only. It must not be described as a current defect.
5. **Artifact uploads used the blanket 90-day default.** Even same-run coverage transfer files and
   release intermediates had no explicit lifetime. The 656 active non-release artifacts use another
   5.03 GiB.
6. **The previous QA/PQ path was both wasteful and incorrect.** `tests.run_group` delegates to
   `unittest.defaultTestLoader`, while the `tests/ui_qa/test_ui_pq_*.py` suite is made of pytest-style
   top-level functions. Those modules therefore report zero tests. The UI shard uploaded the already
   checked-in `artifacts/ui_pq` tree, and the coverage job consumed it as if fresh. Dedicated pytest
   execution is mandatory; incremental selection is how to add it without running the entire PQ suite
   for every isolated change. The grouped module runner now routes zero-unittest and mixed
   unittest/pytest modules through in-process pytest, so ordinary shard modules cannot silently omit
   top-level pytest functions; the UI QA/PQ suite remains separately managed and runs once.
7. **Repeated setup is secondary.** `setup-python`'s pip cache avoids many downloads but does not
   create a reusable installed environment; clean runners still install the package in most jobs.
   The four active Linux/Python 3.14.4 pip caches are about 363 MB each and are keyed by dependency
   inputs; together they use 1.36 GiB, well below the separate default cache allowance. Keep them.
   There is no broad build-output cache. The compile job is the clear exception because `py_compile`
   does not import third-party dependencies.
8. **Push/PR duplication was possible, but not a major historical cause.** Only two distinct SHAs had
   both CI push and PR event runs. Restricting push validation to `main` removes the future duplicate
   path without suppressing PR checks, but the evidence does not support a large historical saving.

There are no repository-local/composite actions, reusable workflows, browser installations, or
ordinary test compatibility matrices to remove. The single CI Python value is the supported target,
3.14.4. The three release OS values produce distinct supported downloads and are retained. Before the
optimization, no tracked workflow used a cron schedule. The working tree adds only the requested
weekly clean CI validation and weekly guarded cleanup plan/apply sequence.

## Trigger, concurrency, and generated-commit behaviour

- CI's historical concurrency key used `github.ref`; a feature-branch push and that branch's PR used
  different refs, so they neither deduplicated nor cancelled one another. The working tree removes
  feature-branch push validation (the PR remains) and cancels only superseded PR runs, using the PR
  number in the concurrency key. Main, tag, scheduled, and manual runs are not cancelled mid-flight.
- The working tree deliberately retains a separate `v*` CI trigger. A commit pushed to `main` and then
  tagged can therefore receive both main-push and tag-push CI runs for the same SHA; the tag route
  forces the complete QA/PQ validation required for a release. The historical two-SHA push/PR count
  does not estimate this new, release-only validation overlap.
- The Help and QA/PQ history commit steps already compare the tracked paths before committing. Their
  generated commit messages include GitHub's recognized `[skip ci]` marker. GitHub documents that
  marker for `push` and `pull_request` workflows only; it does not guarantee suppression of dynamic
  platform workflows. A sampled QA/PQ history commit with `[skip ci]` still caused a Pages deployment.
- A skipped required workflow can leave its check pending on a PR. Generated commits are made only on
  `main`; incremental PR validation must keep always-reporting required jobs rather than using commit
  skip markers or top-level path filters. See
  [GitHub's skip-workflow warning](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
- Version Bump uses `[skip version]`, a repository-specific marker rather than a GitHub Actions skip
  token. Historically, the deploy-key push on 07-Aug-2026 was attributed to `cosmowyn`, not
  `github-actions[bot]`, so the actor guard did not prevent the generated v6.1.3 commit from starting
  CI, Help, Version Bump, Pages, Dependency Graph, and the tag release. The working-tree job condition
  now checks `[skip version]` directly, preventing runner allocation for the Version Bump follow-up
  even when deploy-key attribution bypasses the actor guard. Tag-triggered CI and Release Builds stay
  active. Replacing the marker with `[skip ci]` would be unsafe because the same commit is tagged and
  requires those tag validations/publication.

## Required checks and validation strength

The active ruleset requires the current job contexts. Optimizations must preserve these names and
must not omit a check when a component is unaffected:

- `Python dependency audit (3.14.4)`
- `Compile (3.14.4)`
- `Ruff lint (3.14.4)`
- `Black format check (3.14.4)`
- `mypy (3.14.4)`
- `Tests (catalog-services / py3.14.4)`
- `Tests (exchange-import / py3.14.4)`
- `Tests (history-storage-migration / py3.14.4)`
- `Tests (ui-app-workflows / py3.14.4)`
- `Coverage report`
- `Packaging smoke`

The optimization does not remove a test group, supported platform, audit, coverage gate, or package
smoke test. An incremental QA/PQ job must itself always report success/failure: in `none` mode it
records that no component work was required; it must not disappear through workflow-level filtering.

## QA/PQ incremental impact map

`isrc_manager/qa/impact.py` is the repository-native source of truth, with
`scripts/qa_pq_impact.py` as its standard-library-only CLI. It maps a changed path to a direct
component, adds dependency closure, and emits test targets plus dashboard, screenshot, report, and
artifact scopes. This summary is intentionally less detailed than the executable map:

| Component | Representative source scope | Pytest QA/PQ targets | Dependent/reused output scope |
| --- | --- | --- | --- |
| `core-inventory` | quality/code registries and ISRC registry | inventory, menus/actions, smoke, traceability | core inventory, main window, menus, evidence, traceability |
| `visual-help` | Help content, validation, `docs/help` | Help documentation; settings/theme/Help | Help chapters, screenshots, coverage, rendered manual |
| `catalog` | catalog table/workspace, tracks, tags | catalog workflow | catalog workflow evidence and visuals |
| `relationships-releases-parties` | works, releases, parties, promo codes | work/release/party workflow | relationships, releases, parties, repertoire |
| `contracts-rights` | contracts, templates, rights, licensing | contract workflow | contract/rights evidence and visuals |
| `accounting` | invoicing, ledgers, royalties | accounting workflow | accounting reports, royalty statements, visuals |
| `media-audio` | media, audio, sounds | media/audio workflow | audio/media evidence and visuals |
| `soundcloud` | SoundCloud integration | mocked SoundCloud workflow | publishing evidence and visuals |
| `diagnostics-history-storage` | diagnostics, history, database/profile/storage services | diagnostics/recovery; history replay | diagnostics, history, recovery, storage evidence |
| `imports-exports-reports` | conversion, exchange, reporting, import/export services | import/export workflow | generated reports, manifests, import/export evidence |
| `assets` | asset and deliverable workflows | assets/deliverables workflow | asset/deliverable evidence and visuals |
| `authenticity-forensics` | authenticity, forensics, watermarking | authenticity workflow | authenticity manifests, forensic ledger, visuals |

Dependencies are conservative: most feature components include `core-inventory` transitively;
relationship work includes `catalog`; contracts include relationships; accounting includes contracts;
and SoundCloud includes both contracts and media, while authenticity includes media. Media itself
includes catalog. Full mode also includes the QA-helper and visual-framework targets that are not safe
to assign to a single component.

Full QA/PQ validation is required when any of these applies:

- manual `full_validation: true`, a weekly schedule, or a release/tag ref;
- build/dependency/workflow/test-runner/QA-harness/dashboard-renderer changes;
- common fixtures, shared schemas, global UI/QSS/layout, screenshot baselines, or unknown production
  and test paths;
- missing, ambiguous, renamed, or otherwise uncertain change input.

Ordinary documentation and generated dashboard-output changes select no PQ component. Help content or
Help screenshot changes select `visual-help`. Known isolated source/test changes select their direct
component plus dependencies. The plan includes source commit, test and renderer versions, a mapping
hash, a changed-path hash, relevant input patterns/hashes, and the required generation timestamp
field.

Reuse first requires external producer attestation. A candidate canonical bundle must come from a
successful completed `push` run on the default branch, produced by the exact
`.github/workflows/ci.yml` path, with the repository and head-repository ID/name matching the base
repository. Its artifact metadata must agree with the attested run ID, repository IDs, branch, and
SHA; the bundle's `source_commit` must then equal that attested SHA. Missing or inconsistent
metadata selects no baseline and therefore forces a complete regeneration.

Canonical provenance schema v2 embeds a runtime fingerprint covering GitHub
`ImageOS`/`ImageVersion`, runner OS/architecture/environment, exact Python version and ABI identity,
Qt rendering environment, and exact pinned PySide/Qt, Pillow, NumPy, pytest, and pytest-cov
distributions. CI installs its canonical Linux Qt/XCB/OpenGL package set before baseline selection,
records every installed Debian package version, and verifies that system and Python package identity
again after dependency installation. Compatibility validation rejects runtime or shared-input drift,
an incompatible component set, or changes in any unselected component. It also checks the
bundle-wide and each reused component's relevant-input hash, plus test and renderer versions, before
mixing new and retained output. Any failure falls back to full regeneration rather than silently
combining incompatible evidence.

This design does not claim that incrementality makes validation stronger by itself. The correctness
gain comes from executing the pytest suite that the grouped unittest runner missed. Incrementality
contains that additional cost while a weekly/manual/release/shared-change route preserves a clean full
run.

## Artifact retention and storage estimates

Use purpose-specific retention on **new** uploads:

| Artifact purpose | Retention | Reason |
| --- | ---: | --- |
| Same-run coverage transfer and release publish intermediates | 1 day | Consumers complete in the producing run; permanent packages live in Releases. |
| Coverage XML/JSON and ordinary PR validation evidence | 7 days | Sufficient for near-term diagnosis without a 90-day tail. |
| UI/PQ and Help failure/qualification evidence | 14 days | Longer troubleshooting window for visual/GUI failures. |
| Dashboard history/preview, provenance plan, and cleanup audits | 30 days | Audit/review value, still one-third of the previous default. |
| Retained stable downloadable release packages | Semantic policy below | Public downloads, not temporary Actions artifacts. |

The exact byte saving from retention cannot be known without artifact-class byte totals. Holding
cadence and artifact size constant, changing a 90-day lifetime to 30/14/7/1 days reduces that class's
steady-state storage by approximately 67%/84%/92%/99%. Applied to the 5.03 GiB mixed non-release
inventory only as a window model, the plausible eventual reduction is roughly 3.4–5.0 GiB; it is not
an invoice forecast.

The original snapshot had 146 active release intermediates using 37.01 GiB. After hardening, a
GET-only live plan found 48 active eligible tag-push artifacts using 12.264 GiB. It conservatively
skipped 74 legacy artifacts whose producer event was `workflow_dispatch`, because current release
packages must come from a completed matching `release-build.yml` tag push. Expired records are
historical metadata rather than currently reclaimable bytes and are also skipped. Future release
intermediates expire after one day, so their steady state is normally zero between releases and at
most roughly one release's 0.8 GiB during publication. Existing objects keep their old expiry unless
reviewed cleanup removes them.

### Semantic-version cleanup policy

The 84 stable releases span 27-Apr-2026 through v6.1.3 on 07-Aug-2026. With v6.1.3 as the latest
stable release, retain:

- v6.1.3, v6.1.2, v6.1.1, and v6.1.0 (current plus three patches);
- v6.0.11 (latest available previous minor line; there is no second earlier 6.x minor line); and
- v5.1.0 (latest stable release from the immediately preceding major).

That selects 6 of 84 stable releases and leaves 78 older stable releases whose unambiguously
versioned downloadable build assets are eligible. The hardened GET-only live plan identified 234 such
Release assets using 61.277 GiB. Together with the 48 active Actions artifacts above, the current
eligible estimate was 282 objects and 73.541 GiB across the two separate stores. It issued no
`DELETE` requests. Old `SHA256SUMS.txt` and `latest.json` assets remain for audit because they do not
match an established platform-package name. Actual apply results may be lower as inventory changes or
when an asset is ambiguous, prerelease, not clearly an approved package, actively used, part of a
retained version, or otherwise protected. Releases, tags, release notes, draft/prerelease entries,
unparseable versions, and GitHub-generated source archives are never deleted. All decisions are
written durably to the JSONL log and summarized by count and byte size.

Run locally in dry-run mode (the default):

```bash
GITHUB_TOKEN=... python scripts/cleanup_github_builds.py \
  --repository cosmowyn/ISRC-Catalog-Manager \
  --audit-log github-build-cleanup-audit.jsonl
```

For a local or manually dispatched apply, proceed only after reviewing that audit:

```bash
GITHUB_TOKEN=... python scripts/cleanup_github_builds.py \
  --repository cosmowyn/ISRC-Catalog-Manager \
  --repository-root . \
  --expected-default-sha "$(git rev-parse HEAD)" \
  --audit-log github-build-cleanup-audit.jsonl \
  --apply
```

The workflow can be invoked manually with `mode=dry-run` (the default) or `mode=apply`; manual apply
is default-branch-only. Its weekly schedule runs a read-only plan and, after that succeeds, a separate
guarded apply. Both jobs check out the same immutable `github.sha`; only the apply job receives write
permissions. The destructive CLI requires the expected default-branch SHA, verifies it against both
the API and the real Git worktree root, rejects modified public-link surfaces, and repeats that guard
immediately before deletion. Apply also fetches the whole inventory again, recomputes the candidate
fingerprint, and aborts with zero deletions if it differs. Audit artifacts are kept for 30 days. No
destructive cleanup was executed during this audit.

```bash
gh workflow run cleanup-build-artifacts.yml --ref main -f mode=dry-run
gh workflow run cleanup-build-artifacts.yml --ref main -f mode=apply
```

### Supported saving estimates

| Measure | Evidence-based estimate |
| --- | --- |
| Workflow invocations | The historical release-trigger fix removed 80 extra invocations. Only 2 SHAs had duplicate CI push/PR events, so the observed upper bound from the new branch-trigger rule is 2/159 CI runs (1.3%), not a large percentage. Moving PR Help work into CI also removes a separate runner, but the event split needed for a defensible count was not available. |
| Runner time | Compile can avoid the sampled 25-second dependency installation on each CI run. Release-neutral QA avoids two duplicate executions but adds a standalone setup, so its net is intentionally not quantified. Correct pytest QA/PQ execution may increase absolute compute; incremental selection limits that new cost relative to running the complete PQ suite on every event. |
| Actions artifact storage | The hardened GET-only plan found 12.264 GiB eligible, about 29% of the earlier 42.09 GiB active inventory. Another 74 legacy producer-event artifacts were intentionally skipped. Mixed non-release retention should eventually save another 3.4–5.0 GiB under the stated steady-cadence model. |
| GitHub Release downloads | The GET-only dry-run found 61.277 GiB eligible, about 93% of the earlier 65.91 GiB inventory. This is not counted as Actions artifact storage. |
| Cache storage | No reduction proposed. The 1.36 GiB pip cache is below the separate allowance and trades storage for shorter dependency downloads. |

## Forcing a complete clean validation

After the optimized CI workflow is active, use the Actions UI's **Run workflow** control for `CI` and
set `full_validation` to `true`, or run:

```bash
gh workflow run ci.yml --ref main -f full_validation=true
```

The weekly CI run, tag/release route, shared-infrastructure changes, uncertain change detection, and
manual full request all select every QA/PQ component. A local clean QA/PQ run remains:

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/ui_qa --no-cov
```

## Remaining opportunities and decisions

- Obtain an account usage report or reauthenticate `gh` with the billing/`user` scope needed by the
  account endpoint. Only that report can reconcile the 90% notification across repositories,
  Packages, Actions artifacts, caches, and runner SKUs.
- Monitor the automatic weekly cleanup audit for false positives and inventory drift. It scans the
  repository documentation, release notes, current deployment metadata, and current Pages content,
  then performs a whole-inventory/fingerprint check immediately before the first deletion. The API
  operation is still non-atomic: arbitrary external download links cannot be discovered, and state
  can change after that check or between individual deletions. These residual limitations cannot be
  eliminated by the repository workflow, so retain the conservative allowlist, ceilings, and audits.
- Version Bump now pushes its generated main commit and release tag atomically, and the implemented
  `[skip version]` condition removes its self-triggered follow-up runner. The deliberate branch/tag
  CI overlap still validates the release tag independently; removing it would require a broader
  required-check redesign. Do not use `[skip ci]` while CI and Release Builds validate the tag.
- Review the Pages source configuration. Dynamic Pages runs were observed for generated commits even
  with `[skip ci]`, but changing Pages settings is outside repository-only workflow optimization and
  can affect the public dashboard.
- Do not merge the required CI checks merely to share one installed environment. Separate check names
  and clean runners provide isolation; the current cache plus removal of the compile-only install is
  the safer trade-off.
- Repository workflows still reference mutable major-version action tags such as
  `actions/checkout@v7` and `actions/download-artifact@v8`. Pinning reviewed actions to full commit
  SHAs, with Dependabot handling controlled updates, is a non-blocking supply-chain hardening
  option; it has no supported usage saving and is excluded from the estimates above.
- Re-measure artifact class bytes and job aggregate time after at least four weeks. Replace the
  retention-window estimates with actual steady-state data, and confirm the weekly full run catches no
  dependency-map omissions.
