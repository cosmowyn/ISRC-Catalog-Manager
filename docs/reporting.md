# Crash and Bug Reporting

ISRC Catalog Manager supports privacy-safe crash reports and manual bug reports.

## Security Model

The desktop application does not ship a GitHub personal access token and does not store
repository-write credentials in plaintext configuration. Issue creation is designed to use a
server-side HTTPS report proxy configured with `ISRC_REPORT_PROXY_URL`. The proxy owns any GitHub
credentials and must enforce:

- request schema validation;
- payload size limits;
- server-side rate limits and spam protection;
- accepted application versions/origins;
- a fixed repository target;
- a fixed allow-list of labels;
- a second sanitisation pass before creating the GitHub issue.

If `ISRC_REPORT_PROXY_URL` is not configured, reports are not submitted directly. The application
saves the sanitised pending report under the local app data `reports/pending` folder.

`ISRC_REPORT_REPOSITORY` can override the repository slug sent to a proxy. It defaults to
`cosmowyn/ISRC-Catalog-Manager`.

Do not create a shared `bug_report` GitHub account, ship a personal access token, embed a GitHub
App private key, or package any other write credential in the desktop app. Even a fine-grained token
limited to Issues read/write would be extractable from the app bundle and could be abused to create
issues as that account. GitHub secret scanning may also revoke such leaked credentials.

## GitHub Repository Configuration

The repository is configured with structured issue forms under `.github/ISSUE_TEMPLATE`:

- `bug_report.yml` creates `[Bug Report]` issues with `bug` and `user-report` labels;
- `crash_report.yml` creates `[Crash Report]` issues with `bug`, `user-report`, and
  `crash-report` labels;
- `config.yml` disables blank issues so public manual reports follow a structured template.

Create or update the labels with:

```bash
GH_TOKEN=<admin-or-maintainer-token> python3 scripts/configure_github_reporting.py \
  --repo cosmowyn/ISRC-Catalog-Manager
```

The script only reads `GH_TOKEN` or `GITHUB_TOKEN` from the environment. It does not persist the
token. For a dry run:

```bash
python3 scripts/configure_github_reporting.py --dry-run
```

## Proxy GitHub App Setup

Use a GitHub App for production report submission.

1. Create a GitHub App dedicated to ISRC Catalog Manager report submission.
2. Grant repository permissions:
   - Metadata: read-only;
   - Issues: read and write.
3. Do not grant Contents, Pull requests, Actions, Administration, Secrets, or Workflow access.
4. Install the app only on `cosmowyn/ISRC-Catalog-Manager`.
5. Generate a private key for the app and store it only in the proxy runtime secret store.
6. Deploy a proxy that exposes a single HTTPS POST endpoint and uses the GitHub App installation
   token server-side.

The reference WSGI proxy contract lives in `isrc_manager.reporting.proxy`. It validates schema,
repository, title prefix, accepted app versions when configured, fixed label allow-lists, payload
size, sanitisation, and process-local rate limits before creating a GitHub issue. Production
deployments should also enforce rate limits at the ingress/API gateway because client-side and
process-local controls can be bypassed.

Proxy deployment variables:

```text
GITHUB_APP_ID
GITHUB_APP_INSTALLATION_ID
GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_FILE
ISRC_REPORT_PROXY_REPOSITORY=cosmowyn/ISRC-Catalog-Manager
ISRC_REPORT_PROXY_ALLOWED_VERSIONS=5.0.0
ISRC_REPORT_PROXY_MAX_BYTES=180000
ISRC_REPORT_PROXY_GITHUB_BODY_MAX_BYTES=60000
ISRC_REPORT_PROXY_PER_IP_HOUR_LIMIT=20
```

The desktop client should then be launched or packaged with only the public endpoint and repository:

```text
ISRC_REPORT_PROXY_URL=https://reports.example.com/isrc-catalog-manager
ISRC_REPORT_REPOSITORY=cosmowyn/ISRC-Catalog-Manager
```

Release builds read those two environment variables when `python build.py` runs. When
`ISRC_REPORT_PROXY_URL` is present, the build writes a bundled `resources/reporting.json` file that
contains the public HTTPS proxy URL, the repository slug, and an explicit
`contains_credentials: false` marker. The packaged app loads `ISRC_REPORT_PROXY_URL` first, then
falls back to that bundled public config. Users do not need a GitHub login, token, or local setup.

For GitHub Actions release builds, set the repository or organization secret
`ISRC_REPORT_PROXY_URL` to the deployed HTTPS endpoint. The release workflow passes that value only
to the packaging step. It is not a credential, and the proxy must still enforce server-side schema,
size, rate-limit, sanitisation, and label policy before creating a GitHub issue.

## Automatic Crash Detection

On startup the app writes a runtime session marker under the app data `reports/runtime` folder. On
clean shutdown that marker is closed cleanly. If the next startup finds a previous marker without a
clean shutdown, the user is prompted before a crash report is generated for review.

Crash reports may include:

- application version and available build metadata;
- operating system, Python, Qt, and PySide6 versions;
- timestamp and last recorded app workflow event;
- recent sanitised application logs;
- recent sanitised traceback, exception, or faulthandler files when present.

No crash report is sent without explicit user consent and a preview step.

## Manual Bug Reports

Users can open `Help > Report a Bug…`. The dialog collects:

- summary;
- description;
- steps to reproduce;
- expected behaviour;
- actual behaviour;
- optional sanitised recent logs;
- optional technical system details.

The user then sees the exact Markdown payload that will be submitted or saved. The report can be
copied locally, cancelled, or submitted.

## Privacy Behaviour

All reports pass through `isrc_manager.reporting.sanitizer.ReportSanitizer` before preview and
again before submission. The sanitiser redacts common high-risk patterns, including:

- passwords, secrets, API keys, OAuth tokens, bearer tokens, and GitHub tokens;
- connection strings;
- private keys;
- email addresses and phone numbers;
- local usernames and absolute home-folder paths;
- obvious SQL row content;
- binary data.

Reports must not include raw catalog databases, contract data, royalty data, private documents, or
audio files. Users should describe private workflow symptoms rather than pasting private source
records.

## Abuse Protection

The desktop app applies local rate limits before submission:

- maximum reports per hour;
- maximum reports per day;
- duplicate report detection;
- cooldown after repeated failed proxy submissions or proxy rate-limit responses;
- payload size limits;
- online issue-body shortening before GitHub submission, so large crash diagnostics do not exceed
  GitHub issue body limits.

Missing local proxy configuration and local validation failures are saved as pending reports without
consuming the submission-failure cooldown. This keeps the app abuse-resistant without locking out a
user after the report proxy has just been configured.

Server-side controls remain mandatory for production GitHub issue creation because client-side rate
limits can be bypassed.

## Limitations

The app cannot capture a report at the instant of a process crash. It detects an unclean prior
session on the next startup. System event-log collection is intentionally conservative and currently
limited to app-owned logs and app-owned traceback/exception files to avoid collecting private system
data.
