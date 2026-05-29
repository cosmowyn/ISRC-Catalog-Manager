# SoundCloud Publishing Integration

This integration now has a live execution layer behind explicit user connection and fakeable
transport boundaries. Tests remain no-network: OAuth, refresh, upload, update, persistence, and
error paths are exercised with fake transports and fake services.

The first GUI layer is available through the application settings dialog and catalog publish menu.
It delegates connection, planning, and execution work to the SoundCloud integration services rather
than implementing OAuth, token handling, or upload logic directly in widgets.

## Official SoundCloud API Mapping

Current official API assumptions:

- API base URL: `https://api.soundcloud.com`
- OAuth base URL: `https://secure.soundcloud.com`
- OAuth model: Authorization Code with PKCE
- token endpoint: `POST /oauth/token`
- refresh endpoint: `POST /oauth/token` with `grant_type=refresh_token`
- sign out endpoint: `POST /sign-out`
- authenticated account lookup: `GET /me`
- track upload: `POST /tracks` with `multipart/form-data`
- metadata update: `PUT /tracks/:id`
- request auth header: `Authorization: OAuth <redacted>`
- refresh tokens are single-use

Upload request fields used by this app:

- `track[title]`
- `track[asset_data]`
- `track[genre]`
- `track[isrc]`
- `track[release_date]`
- `track[artwork_data]`
- `track[label_name]`
- `track[release]`
- `track[license]`

Per-run fields:

- `track[sharing]`
- `track[tag_list]`
- `track[downloadable]`
- `track[streamable]`
- `track[commentable]`
- `track[reveal_stats]`
- `track[reveal_comments]`
- `track[purchase_url]`

The app does not send `track[purchase_title]`, `track[metadata_artist]`, or BPM. Those appear in
track resources or search/filter behavior, but they are not part of this implementation's current
documented upload/update request schema.

## App Metadata Availability And Gaps

Available mapping:

- track title
- genre
- valid ISRC
- conflict-free `YYYY-MM-DD` release date
- primary audio source
- unambiguous JPEG, PNG, or GIF artwork
- unambiguous release label
- unambiguous release title
- existing publication lookup by `remote_urn`

Intentionally omitted:

- internal comments
- contract notes
- rights notes
- QA notes
- private notes
- credentials
- hidden/custom purchase URLs unless explicitly provided as a per-run option

## Per-Run Defaults

The app keeps safer catalog defaults than SoundCloud defaults:

- `sharing=private`
- `downloadable=false`
- `streamable=true`

`purchase_url` is explicit per run only. It is never auto-mapped from hidden/custom catalog fields.

## OAuth And Keychain Storage

The live flow is:

1. Generate PKCE verifier and S256 challenge.
2. Generate CSRF `state`.
3. Build the SoundCloud authorization URL.
4. Parse the callback URL.
5. Validate `state`.
6. Exchange the authorization code for a token bundle.
7. Look up the authenticated account with `/me`.
8. Persist the token bundle outside SQLite.
9. Update non-secret SQLite account state.

Persistent token storage uses OS keychain/keyring through the `keyring` package when a safe backend
is available. If no safe keyring backend is available, the integration falls back to session-only
memory storage and the user must reconnect next session.

The keychain layer is conservative:

- safe Python `keyring` backends are accepted;
- macOS Keychain, Windows Credential Locker, Linux Secret Service, and KWallet are supported when
  exposed through a safe keyring backend;
- null, fail, plaintext, and `keyrings.alt` fallback backends are rejected;
- there is no plaintext file fallback;
- there is no environment-variable token fallback.

The storage code is isolated from Qt and exposed through a narrow `SoundCloudCredentialStore`
protocol. Runtime selection is handled by `SoundCloudCredentialManager`, which prefers
`KeyringSoundCloudCredentialStore` when a safe OS-backed keyring backend is available and otherwise
uses `SessionOnlySoundCloudCredentialStore`.

Token bundle keychain records include:

- access token;
- refresh token;
- token type;
- scope;
- expiry timestamp;
- SoundCloud account identifier;
- created timestamp;
- updated timestamp.

Client secrets, when required by SoundCloud OAuth requests, are handled as write-only credentials in
the settings tab. They are masked, handed directly to the SoundCloud secure credential store, and
cleared from the input field after save or error. The client secret is never reflected back into UI
state and is never written to SQLite.

If a secure keyring backend is present but token persistence fails, the app does not update SQLite
account state. The user must reconnect.

SQLite never stores:

- access tokens
- refresh tokens
- auth codes
- client secrets
- Authorization headers
- callback query strings

SQLite may store only non-secret account and publication state such as account id, username,
connection status, token storage kind, token-store key, remote publication URN, run status, and
redacted errors.

## Settings Tab And Connection UX

The application settings dialog includes a SoundCloud tab. The tab exposes only safe connection
settings:

- client id
- redirect URI
- account display/status
- token storage mode
- keychain availability
- session-only fallback status

It does not show client secrets, access tokens, refresh tokens, authorization codes, callback query
strings, callback URLs with secrets, or Authorization headers.

Connection actions are:

- Connect to SoundCloud
- Refresh connection
- Disconnect
- Store client secret securely

The tab calls the SoundCloud connection service adapter. It does not perform token exchange or
SQLite updates itself. Redacted errors are shown in the tab when connection work fails.

If OS keychain/keyring persistence is unavailable, the tab clearly reports that session-only token
storage is active and reconnect will be required after the session ends.

Client secret handling remains behind the secure credential-store seam. The settings tab does not
provide a readable plaintext client-secret field. The masked write-only field is used only to hand a
secret into the secure credential flow.

The Connect action builds a PKCE authorization URL, opens the user's browser, and captures the
callback without persisting it. Loopback redirect URIs are captured through a temporary local
callback listener. Non-loopback redirect flows use a hidden callback paste field. Full callback URLs
are never logged, persisted, or displayed after entry.

The Refresh action loads the current token bundle from the keychain/session store and applies
single-use refresh semantics. The Disconnect action best-effort signs out remotely when an access
token is available, deletes local keychain and session credentials, marks the non-secret account row
disconnected, and leaves catalog tracks plus publication history intact.

## Settings Shortcut

SoundCloud publishing controls can open the application settings dialog directly on the SoundCloud
tab. The shortcut reuses the same settings dialog and tab implementation; it does not duplicate
settings UI or connection behavior.

## Single-Use Refresh Semantics

SoundCloud refresh tokens are treated as single-use:

- The refresh request is attempted once with the currently stored refresh token.
- A successful refresh response must be written to the token store before SQLite account state is
  updated.
- If writing the new token bundle fails, SQLite state is left unchanged and reconnect is required.
- The old refresh token is never retried after a successful refresh response.

## Publish-Run Schema

Migration `42 -> 43` adds dedicated tables:

- `SoundCloudAccounts`
- `SoundCloudTrackPublications`
- `SoundCloudPublishRuns`
- `SoundCloudPublishRunItems`

SQLite stores only non-secret state:

- account identity and connection status
- token storage kind and token-store key
- publication identity by canonical `remote_urn`
- optional numeric remote id when safely parseable
- remote URL
- publish run status and timestamps
- per-item status, operation, redacted error, timestamps
- metadata hash and audio hash evidence

`remote_urn` is canonical. Numeric ids are a convenience for API update calls and are derived only
when safely parseable.

## Upload Execution Workflow

The execution path is:

1. Build a dry-run preflight plan.
2. Create a publish run.
3. Create run items for selected tracks.
4. Resolve a valid access token, refreshing when needed.
5. Execute each item.
6. Commit after each item.
7. Upsert publication records on success.
8. Mark failed or cancelled items with redacted errors.
9. Finalize run counts and status.

Create operations upload audio. Update operations send metadata/artwork only; audio replacement is
not planned or executed.

One failed item does not roll back successful items. Catalog tracks are not modified by publish
failures.

## Catalog Publish Workflow

The catalog menu includes:

- `Catalog -> Publish -> SoundCloud`

The action opens the SoundCloud publishing dialog with the currently selected catalog track ids when
available. The dialog can also expand a selected track to its album group when the catalog track
service can safely infer that group.

The dialog includes a `Choose tracks...` button that opens a separate catalog track picker window,
so the main publish window stays focused on preflight and execution status. The picker lists safe
catalog fields only:

- checkbox;
- title;
- album;
- artist;
- ISRC;
- duration.

The picker supports filtering across title, album, artist, ISRC, and track id. Table headers can be
used for quick sorting, including album/title browsing. Checked rows become the selected publish set
when the user applies the selection.

The publish dialog shows a preflight table before live publishing:

- track title
- create/update operation
- metadata readiness
- audio and artwork readiness
- warnings
- blocking errors
- planned sharing state
- known remote publication status

Default publishing remains safer than SoundCloud defaults:

- private sharing
- not downloadable
- streamable

Blocking preflight issues disable live publishing. Warnings remain visible but allow the user to
continue after review. Live publishing delegates to the background-task-compatible SoundCloud
publish executor, and run/item persistence remains in the SoundCloud persistence layer.

Cancellation requests are surfaced in the dialog. Already committed per-item results remain intact;
the integration does not mutate catalog track records on SoundCloud publish failures.

The dialog includes a publish-run history browser. It displays non-secret run summaries only:

- run id;
- status;
- created timestamp;
- item counts.

The history browser does not display token, callback, Authorization header, or client-secret data.

The dialog also supports linking catalog tracks to uploads that already exist on SoundCloud. Users
can still paste a known SoundCloud URL/id/URN, but the preferred flow is `Browse existing
uploads...`, which fetches the connected account's upload list through the authenticated
SoundCloud client and shows a filterable matcher window. Selecting a remote upload only links the
catalog track to the remote `remote_urn`; it does not update SoundCloud until the user reviews the
preflight and starts an explicit metadata update.

For linked update plans, `Compare remote vs catalog...` fetches the current SoundCloud metadata and
shows a side-by-side comparison before any update is executed. The comparison is read-only, redacts
errors, and includes catalog-derived fields such as title, description, tags, artist, composer,
publisher, release data, ISRC, UPC/EAN, ISWC, P-line, and explicit/contains-music flags when those
fields are present in the update plan.

Quota display remains intentionally limited. The planner displays quota/rate-limit state when a
snapshot can be resolved safely; otherwise it reports that quota data is unavailable rather than
guessing.

## Error And Rate-Limit Handling

The client normalizes SoundCloud HTTP failures into redacted `SoundCloudAPIError` values.

Handled response categories:

- `400` malformed request
- `401` expired or invalid auth
- `403` forbidden
- `404` missing resource
- `409` or `422` validation/conflict-style failures
- `413` size failures
- `429` rate limits
- `500`, `503`, and `504` service failures
- malformed token or track responses

Rate-limit responses are parsed for retry and remaining-limit metadata when headers are present.
Publish planning warns when known remaining rate limit is low and blocks explicit quota exhaustion.

## Redaction Rules

The redaction layer removes:

- `Authorization: OAuth ...`
- `Authorization: Bearer ...`
- `Authorization: Basic ...`
- `access_token=...`
- `refresh_token=...`
- `client_secret=...`
- `code=...`
- JSON token fields
- callback URL query strings

Redacted strings are used for exceptions, UI messages, and run records.

## Testing Rules

SoundCloud tests use:

- fake transports
- fake API clients
- fake token stores
- in-memory SQLite
- no real credentials
- no browser launch
- no upload to SoundCloud
- no network calls

## Remaining Follow-Up Work

Remaining UI and live-connection follow-ups:

- reconnect prompts for session-only token fallback
- richer quota display if SoundCloud exposes additional account quota fields
- streamed multipart transport for very large files if the default stdlib transport proves too
  memory-heavy for production upload sizes

## Rich metadata update note

The public SoundCloud API schema documents the core track fields used by uploads and updates, while the SoundCloud web editor exposes additional publisher metadata such as publisher, composer, album title, UPC/EAN, ISWC, P-line, contains-music, and explicit-content values. The integration keeps the documented core fields as the baseline and sends the richer catalog-derived values as best-effort nested `publisher_metadata` during metadata updates.

Owner/company metadata may be used as a safe fallback for publisher and record-label style fields when the catalog track or linked work does not provide a more specific value. Secret values, OAuth callback query strings, and Authorization headers are never included in metadata update payloads, publish-run records, logs, or documentation examples.

When a new upload includes rich publisher metadata, the app performs the audio/artwork upload first and then sends a metadata-only follow-up update after SoundCloud returns the remote track id. This avoids audio replacement during metadata updates while matching the SoundCloud web editor's top-level `publisher_metadata` JSON shape for fields that are not represented cleanly in the public OpenAPI upload schema.

Rich publisher metadata is additionally synced through SoundCloud's API-v2 track metadata endpoint using the top-level JSON shape observed from the SoundCloud web editor. This API-v2 call is treated as best-effort: if SoundCloud rejects it or changes the endpoint, the app keeps the primary upload/update result and writes a redacted warning to the application log so the failed metadata boundary can be diagnosed without exposing OAuth tokens or credentials.

The API-v2 rich metadata sync targets the SoundCloud track URN route (`tracks/soundcloud:tracks:<id>`) with owner representation, matching the route shape used by SoundCloud's current web client more closely than a bare numeric track id. A rejected call remains non-fatal because the public upload/update can succeed while SoundCloud declines web-editor-only metadata writes for the OAuth app.

Current SoundCloud web bundles show metadata saves using `PUT api-v2/tracks/:urn` with top-level JSON attributes. Owner representation is used for owner reads, not for the save route, so the integration mirrors the save route directly and avoids adding an owner query parameter to rich metadata updates.

When SoundCloud returns 403 for rich web-editor metadata, the app treats the public track update as successful but records a non-secret warning on the publish item. The compare dialog labels affected rich metadata rows as `Web-only/API not confirmed` when the catalog value exists but SoundCloud does not return the value through the API.
