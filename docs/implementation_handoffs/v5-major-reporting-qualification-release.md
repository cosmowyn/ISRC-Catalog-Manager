# v5.0.0 Major Reporting and Qualification Release Handoff

Date: 2026-06-01
Branch: `main`
Target release: `v5.0.0`

## Purpose

This release consolidates the local major feature work with the current online `main` branch and
publishes a v5.0.0 major release. The online repository had advanced through v4.0.5 with release
metadata and workflow fixes; those commits were fetched and fast-forwarded locally before the local
feature set was reapplied.

## Online Sync

Remote `main` was 14 commits ahead before release preparation. The local checkout was synced by:

1. fetching `origin/main` and tags;
2. stashing the full local tracked and untracked worktree;
3. fast-forwarding local `main` to `origin/main`;
4. popping the stash back onto the updated branch.

No merge conflicts remained after reapplying the local changes. The remote changes preserved in the
offline checkout include the v4.0.1 through v4.0.5 release metadata, release badge updates, and
protected-main version-bump workflow changes.

## Major Features

### Crash and Manual Bug Reporting

- Added `isrc_manager.reporting` as a dedicated reporting feature package.
- Added startup-based crash detection through a runtime session marker.
- Added clean-shutdown marking from the main window close path.
- Added last-known event/workflow capture through the app event logger.
- Added a crash consent prompt shown only after an unclean prior session is detected.
- Added `Help > Report a Bug...` for manual user-initiated reports.
- Added manual bug report fields for summary, description, reproduction steps, expected behaviour,
  actual behaviour, optional sanitised logs, and optional technical system details.
- Added a shared report preview dialog that shows the exact Markdown payload before submission.
- Added local pending report storage for offline or rejected submissions.
- Added local rate limiting, duplicate detection, and cooldown handling.

### Privacy and Security

- Added a central `ReportSanitizer` for report text and metadata.
- Redaction covers secrets, passwords, API keys, GitHub tokens, OAuth tokens, bearer tokens,
  connection strings, private keys, email addresses, phone numbers, local user names, home-folder
  paths, binary data, and obvious raw SQL/database row content.
- Reports are sanitised during construction, preview, and again at the submission boundary before
  proxy submission or pending local storage.
- The desktop app does not contain GitHub write credentials and does not directly create issues
  with a bundled token.

### GitHub Reporting Infrastructure

- Added structured issue forms:
  - `.github/ISSUE_TEMPLATE/bug_report.yml`
  - `.github/ISSUE_TEMPLATE/crash_report.yml`
  - `.github/ISSUE_TEMPLATE/config.yml`
- Added `scripts/configure_github_reporting.py` to create or update the required `bug`,
  `user-report`, and `crash-report` labels from an environment-provided token.
- Added `isrc_manager.reporting.proxy`, a reference WSGI report proxy that uses a server-side
  GitHub App installation token and enforces schema, repository, label, title prefix, app-version,
  payload-size, sanitisation, and rate-limit checks.
- Documented the GitHub App permission model: install only on the target repository with Metadata
  read-only and Issues read/write; do not grant Contents, Actions, Pull requests, Administration,
  Secrets, or Workflow permissions.

### UI PQ and Help Governance

- Added automated UI PQ assets for visual qualification, screenshot capture, baseline comparison,
  generated document/report comparison, PDF comparison, dialog verification, generated document
  verification, and theme verification.
- Added help documentation validation with current UI screenshots and traceability evidence.
- Updated `AGENTS.md` so all code changes must be governed by current QA/PQ tests and user-visible
  changes must update the in-app Help manual.
- Added the help screenshot refresh workflow.
- Updated help content to describe reporting, privacy, report previews, and pending report storage.

### SoundCloud, Authenticity, and Forensics

- Updated authenticity verification thresholds and user-facing reporting so degraded derivatives
  around 70 percent confidence can be reported as likely matches rather than false negatives.
- Added conversion support for non-WAV authenticity checks.
- Expanded forensic watermark exports beyond MP3 and added SoundCloud-specific export behavior with
  SoundCloud fixed as the recipient and safe public SoundCloud profile metadata included in the
  forensic trace.
- Added tests for authenticity, forensic export, SoundCloud persistence/token behavior, and dialog
  paths.

### Accounting and Business Workflow Qualification

- Added invoice workspace/package infrastructure.
- Expanded UI-led accounting qualification for invoice creation, line entry, posting, payment,
  credit notes, royalty statements, payouts, generated reports, and ledger checks.
- Added direct record-opening behavior from relevant tables where requested.
- Added generated invoice/report/validation artifacts under the PQ evidence outputs.

## Release Metadata

- `pyproject.toml` version: `5.0.0`
- `isrc_manager/version.py` fallback: `5.0.0`
- `README.md` current source release marker: `5.0.0`
- `docs/release-builds.md` canonical source version marker: `5.0.0`
- `RELEASE_NOTES.md`: extended v5.0.0 notes
- `docs/releases/v5.0.0.md`: extended v5.0.0 notes
- `docs/releases/latest.json`: v5.0.0 metadata

The final release commit should use `[skip version]` and the `v5.0.0` tag should be pushed
explicitly. This avoids the online version-bump workflow interpreting the already-bumped release
commit as a new post-5.0.0 change.

## Repository Configuration Status

The live GitHub repository labels could not be updated from the local environment because the local
`gh` authentication token for `cosmowyn` was invalid. Once a valid maintainer/admin token is
available, run:

```bash
GH_TOKEN=<token> python3 scripts/configure_github_reporting.py --repo cosmowyn/ISRC-Catalog-Manager
```

The script can be checked without network access using:

```bash
python3 scripts/configure_github_reporting.py --dry-run
```

## Validation Performed

During the reporting/proxy work and release preparation, the following validation commands were run:

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/reporting tests/test_main_window_shell_conversion.py --no-cov
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/ui_qa --no-cov
python3 -m compileall ISRC_manager.py isrc_manager tests
python3 -m ruff check build.py isrc_manager scripts tests
python3 -m black --check build.py isrc_manager scripts tests
python3 -m mypy
python3 scripts/configure_github_reporting.py --dry-run
```

These checks passed before release staging. CI still needs to be monitored after pushing `main` and
the `v5.0.0` tag because the remote workflow matrix includes dependency audit, grouped shards,
coverage combination, and release package builds across supported operating systems.

## Follow-Up

- Re-authenticate GitHub CLI or provide a valid maintainer token, then apply reporting labels to the
  live repository with `scripts/configure_github_reporting.py`.
- Deploy the report proxy behind HTTPS with GitHub App credentials stored only in the server secret
  store.
- Configure packaged builds or launch environment with `ISRC_REPORT_PROXY_URL` once the proxy is
  online.
- Monitor the `Version Bump`, `CI`, `Help Docs Refresh`, and `Release Builds` workflows after push.
