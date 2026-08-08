# Optimize GitHub Actions usage and artifact retention

## Category

devops

## Original prompt, cleaned

You are working in the ISRC Manager repository.

The repository and its GitHub Actions workflows need to be audited and optimised. GitHub is
reporting that approximately 90% of the Actions budget has been consumed.

Your task is to determine exactly why usage is so high, implement meaningful optimisations, and clean
up obsolete build artifacts and downloads without removing functionality, weakening validation
coverage, or making the workflows unreliable.

Work autonomously. Inspect the repository and its workflow history before making changes. Do not stop
after producing recommendations: implement the safe improvements, test them, and document the result.

### Primary objectives

1. Determine what is consuming the GitHub Actions budget:
   - Hosted-runner minutes.
   - Excessive workflow frequency.
   - Duplicate workflow runs.
   - Long-running jobs.
   - Oversized or unnecessarily retained artifacts.
   - Cache usage.
   - Repeated dependency installation.
   - Repeated builds.
   - Unnecessary matrix combinations.
   - Dashboard screenshot and report generation.
   - Scheduled workflows.
   - Workflows triggered by generated files or bot commits.
   - Any other material source of Actions usage.
2. Optimise all GitHub Actions workflows without losing functionality.
3. Refactor the QA/PQ dashboard workflow so that it runs incrementally whenever this is safe.
4. Implement automatic cleanup of obsolete GitHub Actions artifacts, build downloads, and release
   assets according to the semantic-version retention policy defined below.
5. Preserve a reliable way to perform a complete, clean validation run.

### Operating principles

- Do not remove tests, validation steps, supported platforms, release outputs, or required status
  checks merely to reduce Actions usage.
- Do not weaken QA or PQ acceptance criteria.
- Do not hide failures by marking important jobs as optional.
- Preserve existing workflow outputs unless there is a documented reason to change them.
- Prefer deterministic and maintainable solutions over complicated optimisations with marginal
  savings.
- When change impact cannot be determined safely, run the complete relevant validation set.
- Shared configuration, test infrastructure, dependency, build-system, or dashboard-rendering changes
  must trigger all affected validations.
- Required status checks must continue to appear, even when individual test groups do not need to run.
- Use least-privilege workflow permissions.
- Avoid irreversible deletion when a version or artifact cannot be identified reliably.
- Do not delete source-code tags, release notes, or Git history.
- Do not push, merge, or publish a release unless explicitly instructed. Make and validate the
  repository changes in the current working branch.

### Phase 1 — Audit current usage

Inspect at least:

- `.github/workflows/`
- Local or composite actions.
- Reusable workflows.
- Workflow trigger definitions.
- Cron schedules.
- Matrix strategies.
- Concurrency settings.
- Artifact upload and download steps.
- Artifact retention settings.
- Dependency caching.
- Build caching.
- GitHub Pages or dashboard deployment workflows.
- Release workflows.
- Automated commits made by workflows.
- Recent workflow-run frequency and duration.
- Recent artifact sizes and retention periods.
- Duplicate runs caused by both `push` and `pull_request`.
- Runs triggered by generated screenshots, reports, dashboards, version files, or bot commits.

Use GitHub CLI/API data when available to identify:

- Number of runs per workflow.
- Average and maximum duration.
- Failed or cancelled run frequency.
- Artifact count and total size.
- Workflows responsible for the greatest runner usage.
- Workflows responsible for the greatest artifact storage.
- Repeated runs for the same commit.
- Jobs that routinely perform identical work.

Distinguish clearly between runner-minute consumption and artifact/cache storage. If billing
information is not accessible, estimate relative usage from workflow-run history and artifact
metadata and state that limitation.

Create `docs/github-actions-audit.md`.

Include a table containing:

- Workflow name.
- Trigger.
- Approximate frequency.
- Average duration.
- Main cost drivers.
- Artifacts produced.
- Current retention.
- Proposed optimisation.
- Risk of the proposed change.
- Expected relative saving.

### Phase 2 — General workflow optimisation

Implement all safe and relevant optimisations discovered during the audit. Consider the following,
but only apply them where they fit the repository.

#### Trigger optimisation

- Prevent duplicate `push` and `pull_request` runs for the same commit.
- Add accurate `paths` or `paths-ignore` filters where entire workflows are irrelevant to certain
  changes.
- Prevent generated dashboard files, screenshots, reports, or bot commits from triggering recursive
  workflow runs.
- Review scheduled workflows and reduce unnecessary frequency without compromising required periodic
  validation.
- Ensure release-only work is not performed for ordinary commits.

#### Incremental execution

- Detect changed files once in an initial job.
- Map changed files to affected components, tests, dashboard sections, screenshots, and build targets.
- Pass these results to later jobs as outputs.
- Dynamically construct test matrices from the affected components.
- Skip unaffected jobs while retaining an always-running summary/status job.
- Trigger a full run when shared or cross-cutting files change.
- Trigger a full run when change detection is uncertain.

#### Reuse and caching

- Build shared outputs once per workflow and reuse them between jobs.
- Avoid rebuilding the same application separately for every test group.
- Cache dependencies using lockfile-based keys.
- Cache build outputs only where correctness can be guaranteed.
- Avoid broad cache keys that can restore incompatible outputs.
- Do not cache secrets or sensitive generated data.
- Avoid reinstalling unchanged browser binaries, test tools, or package managers unnecessarily.

#### Run cancellation and limits

- Add appropriate `concurrency` groups.
- Use `cancel-in-progress: true` for superseded pull-request and branch-validation runs.
- Do not cancel release or deployment runs where interruption could create an inconsistent state.
- Add reasonable job timeouts to prevent hung jobs from consuming excessive minutes.
- Use shallow checkouts unless full Git history is genuinely needed.

#### Matrix optimisation

- Remove duplicate or redundant matrix combinations only after confirming they provide no distinct
  coverage.
- Do not remove supported environments merely to reduce cost.
- Where appropriate, run the broad compatibility matrix on releases or scheduled full runs and use a
  representative matrix for ordinary pull requests.
- Document any distinction between pull-request, default-branch, scheduled, and release validation.

#### Artifact optimisation

- Do not upload artifacts that are empty, unchanged, or never consumed.
- Compare hashes before uploading generated screenshots, reports, or dashboard data.
- Upload debugging artifacts only on failure when they are not needed after successful runs.
- Set explicit `retention-days` values based on artifact purpose.
- Compress large artifacts where useful.
- Do not upload the same build repeatedly under different job names.
- Preserve release artifacts according to the version-retention policy below.

### Phase 3 — QA/PQ dashboard refactor

The QA/PQ dashboard currently appears to rerun all validation tests and regenerate all screenshots
and artifacts during every execution.

Refactor this workflow so that ordinary changes only rerun and regenerate the affected portions.

#### Required behaviour

1. Create a clear mapping between:
   - Source-code paths.
   - Test suites.
   - QA/PQ dashboard sections.
   - Screenshots.
   - Generated reports.
   - Shared dependencies and configuration.
2. Run only the affected test suites when a change is isolated to a known component.
3. Regenerate only the affected screenshots, reports, and dashboard sections.
4. Preserve valid unchanged dashboard outputs rather than unnecessarily recreating them.
5. Include provenance for reused outputs:
   - Source commit.
   - Test version.
   - Dashboard or renderer version.
   - Relevant dependency or configuration hash.
   - Generation timestamp.
6. Never silently combine incompatible old and new outputs. If compatibility cannot be established,
   regenerate the affected dashboard or perform a complete rebuild.
7. Shared changes must force broader validation. Examples include:
   - Test-runner configuration.
   - Dashboard rendering code.
   - Shared UI components.
   - Shared schemas.
   - Package lockfiles.
   - Build configuration.
   - Screenshot tooling.
   - Browser versions.
   - Common fixtures.
   - Global CSS or layout changes.
   - Validation rule changes.
8. Provide a complete-run mechanism:
   - `workflow_dispatch` input such as `full_validation: true`.
   - Full validation for release tags.
   - Full validation after changes to shared infrastructure.
   - A sensible periodic complete run on the default branch, preferably weekly unless the repository
     already requires another cadence.
9. Ensure the required QA/PQ status check still reports a clear result even when no component-specific
   test job needs to run.
10. Do not commit generated files when their contents have not changed.
11. Prevent automated dashboard updates from creating workflow loops.
12. Add tests for the change-detection and component-mapping logic.

Prefer a repository-native dependency map or a small maintainable script over a long collection of
fragile YAML expressions.

### Phase 4 — Version-based cleanup policy

Implement a cleanup script and GitHub Actions workflow for obsolete build artifacts and downloadable
release assets.

Use semantic versions.

Assume the latest stable release is the current release.

Retain:

1. The current stable release.
2. The previous three patch releases within the current major/minor line.
3. The latest stable release from each of the previous two minor lines within the current major
   version.
4. The latest stable release from the immediately preceding major version.

For example, when the current release is `3.4.7`, retain:

- `3.4.7`
- `3.4.6`
- `3.4.5`
- `3.4.4`
- The latest `3.3.x` release.
- The latest `3.2.x` release.
- The latest `2.x.x` release.

Older downloadable builds and release assets may be deleted.

Therefore, given:

- `3.4.7`
- `3.4.6`
- `3.4.5`
- `3.4.4`
- `3.4.3`
- `3.3.9`
- `3.3.8`
- `3.2.2`
- `3.1.7`
- `2.9.4`
- `1.8.1`

retain:

- `3.4.7`
- `3.4.6`
- `3.4.5`
- `3.4.4`
- `3.3.9`
- `3.2.2`
- `2.9.4`

The remaining obsolete downloadable builds may be removed.

#### Cleanup safeguards

- Parse semantic versions strictly.
- Ignore or report unparseable versions instead of deleting them.
- Do not automatically delete prereleases unless their retention behaviour is already clearly defined
  in the repository.
- Never delete the current release.
- Never delete Git tags, source history, release notes, or automatically generated source archives.
- Do not delete assets currently used by an active deployment or public download link.
- Keep an audit log of every retained and deleted item.
- Support a dry-run mode that performs no deletion.
- Make dry-run the default when the script is run locally.
- Require an explicit `--apply` or equivalent option for deletion.
- Add unit tests for version selection and deletion logic.
- Limit destructive workflow permissions to the cleanup job only.
- Use a scheduled cleanup workflow, preferably weekly.
- Also provide `workflow_dispatch` with dry-run/apply selection.
- Include the cleanup summary in the GitHub Actions job summary.

For ordinary, unversioned GitHub Actions artifacts, assign retention based on purpose. Use the shortest
practical period while preserving troubleshooting and audit needs. For example:

- Temporary PR artifacts: approximately 7 days.
- Failure diagnostics: approximately 14 days.
- Dashboard previews: approximately 14–30 days.
- Release artifacts: controlled by the semantic-version policy.

Adjust these values when repository requirements demonstrate that a longer period is necessary.

### Phase 5 — Validation

After making changes:

1. Validate all workflow YAML files.
2. Run `actionlint` or an equivalent workflow validator.
3. Run the repository's normal linting, unit tests, integration tests, and build.
4. Test change detection with representative scenarios:
   - Documentation-only change.
   - One isolated component change.
   - Shared dependency change.
   - Dashboard-renderer change.
   - Screenshot-test change.
   - Lockfile change.
   - Release tag.
   - Manual full-validation request.
5. Verify that required status checks still appear.
6. Verify that a skipped component does not result in a missing or permanently pending required check.
7. Verify that full validation still runs successfully.
8. Verify that unchanged screenshots and reports are not regenerated or uploaded.
9. Test cleanup logic against fixture version lists.
10. Run the cleanup process in dry-run mode and record what it would retain and delete.
11. Do not execute destructive cleanup against real repository assets unless the repository already
    has a safe, reviewed mechanism for doing so.

### Required deliverables

Produce:

1. The implemented workflow and supporting-script changes.
2. `docs/github-actions-audit.md`.
3. Automated tests for:
   - Changed-file/component mapping.
   - Semantic-version retention.
   - Cleanup dry-run behaviour.
4. A final summary containing:
   - Primary cause or causes of high Actions usage.
   - Workflows that consumed the most resources.
   - Exact files changed.
   - Optimisations implemented.
   - Functionality-preservation measures.
   - Estimated reduction in workflow runs, runner minutes, and artifact storage.
   - Remaining opportunities not implemented and why.
   - Any assumptions or limitations.
   - Instructions for manually forcing a complete QA/PQ validation.
   - Instructions for running cleanup in dry-run and apply modes.

Do not claim savings that cannot be supported by repository history or a clearly stated estimate.

## Context preserved

- Repository: ISRC Manager / `cosmowyn/ISRC-Catalog-Manager`.
- Changes must remain local: no push, merge, or release publication. Do not execute destructive
  cleanup unless the repository already has a safe, reviewed mechanism for doing so.
- Full validation, supported operating-system packages, status checks, and QA/PQ acceptance strength
  are mandatory.
- Cleanup retention and safety criteria are acceptance requirements, not suggestions.

## Redactions

None.
