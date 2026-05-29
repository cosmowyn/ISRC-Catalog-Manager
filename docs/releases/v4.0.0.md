# ISRC Catalog Manager 4.0.0

Version: 4.0.0
Date: 2026-05-29
Type of update: Major

## Release summary

ISRC Catalog Manager 4.0.0 is a major SoundCloud publishing, secure-credential, metadata-sync, and quality-gate release. It turns the earlier no-network SoundCloud preparation into a guarded live workflow with OAuth, OS keychain/keyring persistence, preflight planning, upload/update execution, publication history, remote-linking tools, and a broader metadata review path.

The release keeps the app local-first. Catalog data remains in the profile SQLite database, while SoundCloud secrets are isolated in OS-backed credential storage when available and otherwise held only in memory for the current session.

## Headline features

- Added a SoundCloud settings tab with client id, redirect URI, account status, storage-mode status, masked write-only client secret entry, connect, refresh, and disconnect actions.
- Added Authorization Code with PKCE support, local callback capture, CSRF state validation, token exchange, token refresh, and disconnect cleanup.
- Added secure SoundCloud credential persistence through OS keychain/keyring services with session-only fallback when a safe backend is unavailable.
- Added a SoundCloud publish dialog with dry-run preflight, private-by-default sharing, per-run tags, description, buy link, comments/stat/comment reveal controls, explicit-content control, and contains-music control.
- Added a separate catalog track picker window with visible checkboxes, filtering, and sortable browsing so track selection does not crowd the publish dialog.
- Added catalog-table handoff paths for SoundCloud publishing, including the Publish -> SoundCloud menu path and a track context action that opens the publish dialog for manual review.
- Added live publish execution through background-task-compatible workers with cancellation checks and per-item persistence.
- Added remote update and remote-linking workflows for tracks already uploaded to SoundCloud before this app managed them.
- Added a richer remote matching browser that lists existing SoundCloud uploads and a side-by-side remote-vs-catalog metadata comparison before updating.
- Added SoundCloud publish history browsing with run/item status, counts, timestamps, and redacted errors.
- Added official SoundCloud logo assets in the publish dialog, resolved theme-sensitively between the black and white transparent logos.

## SoundCloud publishing workflow

Publishing now follows this sequence:

1. The user connects an explicit SoundCloud account from settings.
2. The user opens Publish -> SoundCloud, the catalog context menu action, or a SoundCloud workflow shortcut.
3. The publish dialog receives selected tracks or lets the user open the separate track picker.
4. The planner builds a dry-run preflight table before any live API call.
5. Blocking problems prevent publishing; warnings remain reviewable.
6. The publish worker creates a publish run and commits each run item independently.
7. Each item performs create or update according to the planned publication state.
8. Remote URN, remote URL, status, redacted error, evidence hashes, and timestamps are persisted.
9. Catalog records are preserved on failure.

Publishing remains safe by default:

- `sharing` defaults to `private`.
- `downloadable` remains `false`.
- `streamable` remains `true`.
- Internal comments, contracts, rights notes, QA notes, private notes, credentials, auth codes, and callback query strings are never published.
- Existing uploads can be linked and updated only after a manual review step.

## Media preparation

SoundCloud upload preparation now handles both managed files and profile-database embedded media.

- Embedded audio stored in SQLite can be extracted for publish preparation.
- Embedded artwork stored in SQLite can be extracted when it is an allowed image type.
- Managed-file audio and artwork remain supported.
- Upload audio is prepared through the watermarking/export path so only watermarked derivatives are uploaded.
- Upload audio is converted to WAV for SoundCloud upload execution.
- Artwork validation remains limited to SoundCloud-supported JPEG, PNG, and GIF image data.

## Metadata mapping

The SoundCloud mapping now covers the catalog fields needed for real release operations where the SoundCloud API accepts them.

Mapped catalog values include:

- title
- genre
- tags
- description
- buy link
- artist
- publisher
- composer from linked work/party metadata
- release title
- album title
- record label
- release date
- ISRC
- UPC/EAN
- ISWC when available
- P line using the current year and owner/company metadata
- contains music
- explicit-content state
- artwork

The comparison dialog shows catalog value, current SoundCloud value, and changed/same state before update.

## Known SoundCloud API limitation

The public SoundCloud API accepts the core track update fields used by the primary update request. Some richer metadata fields visible in the SoundCloud web editor appear to be handled by SoundCloud's web/API-v2 surface and may reject third-party app calls with HTTP 403 even after the public API update succeeds.

In this release, those rich metadata failures are logged and redacted, and the publish item is not treated as a failed upload when the supported public API update completed. Remaining rich-metadata parity is intentionally tracked as follow-up work rather than hidden behind brittle browser automation.

## OAuth and credential security

SoundCloud credential handling is now isolated behind a dedicated credential/token store abstraction.

- `client_id` and `redirect_uri` may be stored in normal app settings.
- `client_secret`, access tokens, refresh tokens, token expiry, token bundle metadata, auth codes, Authorization headers, and OAuth callback query strings are not stored in SQLite or normal settings.
- Persistent secrets are stored only in an OS-backed keychain/keyring backend when a safe backend is detected.
- If a safe OS backend is unavailable, the app uses session-only in-memory storage and clearly reports that reconnect is required after restart.
- Stored client secrets are write-only in the settings UI and are never reflected back into widget text.
- Redaction covers Authorization headers, OAuth tokens, client secrets, auth codes, callback URLs/query strings, logs, exceptions, UI messages, publish-run records, and test snapshots.

Refresh-token safety is single-use aware:

1. The current refresh token is used once.
2. The newly returned token bundle is written to secure storage first.
3. Only after secure storage succeeds is non-secret account state updated in SQLite.
4. If secure persistence fails, the account requires reconnect.
5. The app does not retry with a stale refresh token after an ambiguous successful refresh response.

Disconnect is local-safe:

- best-effort SoundCloud sign-out is attempted when an access token is available;
- local keychain/session credential entries are deleted;
- non-secret account state is marked disconnected;
- catalog tracks and publication history are not deleted.

## Database changes

This release adds dedicated SoundCloud integration storage instead of broadening the track table with secret or workflow state.

Dedicated non-secret state includes:

- `SoundCloudAccounts`
- `SoundCloudTrackPublications`
- `SoundCloudPublishRuns`
- `SoundCloudPublishRunItems`

The canonical remote identifier is `remote_urn`. Numeric remote ids are derived only when safely parseable. Public remote URLs are stored with the publication record and linked to the catalog track for future update flows.

SQLite stores only non-secret state such as connection status, account URN, username, permalink URL, last verified time, storage mode, publish-run status, redacted errors, remote URN, remote URL, timestamps, and media/hash evidence.

SQLite must never contain SoundCloud client secrets, access tokens, refresh tokens, auth codes, Authorization headers, or full OAuth callback query strings.

## Error handling and logs

SoundCloud API and publish workflow logging was expanded for troubleshooting without exposing secrets.

- API request start/completion/failure events are logged with method, endpoint, status, request id, payload category, and rate-limit details where available.
- Sensitive headers, tokens, callback URLs, auth codes, client secrets, and query strings are redacted.
- Upload execution errors are written to the application trace log.
- The publish dialog avoids dumping full tracebacks into the visible workflow area and instead exposes a route to the recent trace entry.
- Per-item failures are isolated so one failed upload does not corrupt or roll back unrelated item records.

## Quality and security gates

The repository quality target is now branch-aware coverage at 90% for the real `isrc_manager` package.

This release was validated with:

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=isrc_manager --cov-branch --cov-report=term-missing --cov-report=html --cov-report=json --cov-fail-under=90`
- result: `2382 passed, 87 subtests passed`
- coverage: `90.18%`
- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager tests`
- `.venv/bin/python -m ruff check build.py isrc_manager scripts tests`
- `.venv/bin/python -m black --check build.py isrc_manager scripts tests`
- `.venv/bin/python -m mypy`
- `.venv/bin/python -m pip_audit`
- `git diff --check`

Security dependency hardening included:

- Black updated to `26.3.1`.
- Security constraints added for `idna>=3.15` and `urllib3>=2.7.0`.
- Dependency audit completed with no known vulnerabilities reported.
- A targeted secret scan found no production/docs credentials or API keys; remaining token-like strings are fake redaction fixtures in tests.

## Dependabot policy

Dependabot remains enabled for weekly Python dependency and GitHub Actions checks. Runtime and development dependencies are grouped separately.

The previous Black semver-major ignore has been removed so future security-relevant major updates for development tooling are not silently suppressed by Dependabot.

## User-facing upgrade notes

- Users who previously connected SoundCloud in session-only mode may need to reconnect after restart.
- Users should verify the settings tab storage mode before assuming persistent SoundCloud connection is available.
- If OS keychain/keyring storage is unavailable, the app will continue safely in session-only mode and will not create plaintext token files.
- Existing SoundCloud uploads can be linked to catalog tracks through the matching/link workflow before update.
- SoundCloud updates should be reviewed through the comparison dialog before being applied.

## Known limitations and follow-up work

- Full parity with SoundCloud's web-only rich metadata editor remains limited by SoundCloud API permissions and observed API-v2 403 responses.
- Browser automation for SoundCloud web-editor fields is intentionally not included.
- Quota display remains limited to the rate/status information the supported API exposes.
- Publish-run history exists, but deeper filtering/report export can still be improved.
- Future UI work can add richer account diagnostics, batch metadata templates, and more detailed remote conflict handling.
- Remaining test warnings include pre-existing unclosed-database ResourceWarnings in broader GUI/app-shell coverage runs; they do not block the 4.0.0 gate but should be cleaned up in a follow-up maintenance pass.

## Maintainer handover

Focus areas for the next maintainer:

- Keep SoundCloud secrets behind the credential store boundary.
- Do not store tokens, auth codes, Authorization headers, callback query strings, or client secrets in SQLite, settings files, docs examples, screenshots, logs, or run records.
- Keep publish/update execution behind planner and service contracts rather than adding direct API calls in Qt dialogs.
- Preserve `remote_urn` as the canonical remote identifier.
- Continue using fake transports/stores in tests; do not add real SoundCloud network calls to tests.
- Treat SoundCloud API-v2 rich metadata failures as an external API limitation unless SoundCloud publishes a supported third-party schema for those fields.
- Keep release validation on Python 3.14.4 with headless Qt.
