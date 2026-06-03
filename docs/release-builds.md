# Release Build Automation

GitHub Actions builds public release packages from immutable version tags.

## Trigger

The normal release path is:

```text
push to main
version-bump workflow fingerprints application-code changes
version-bump workflow updates release metadata only when the gate opens
version-bump workflow creates vX.Y.Z only for gated or explicitly requested releases
release-build workflow builds and publishes packages for that tag
```

The release workflow is `.github/workflows/release-build.yml` and runs only for tags matching
`v*`. The version-bump workflow pushes release tags through the protected-main automation deploy key,
so tag pushes start release builds directly. In that path, the resolved tag is validated as
SemVer-style before packaging.

Documentation-only pushes, reruns, Help screenshot refresh commits, generated release metadata,
tests, UI QA/PQ evidence, workflow-only edits, and release-automation maintenance do not create a new
version automatically. Any real production-code change in the configured runtime/build fingerprint
paths opens the automatic bump gate, even when the patch is small. The fingerprint includes shipped
runtime resources because bundled resources change application behaviour for users. Maintainers can
still request an explicit bump with commit markers such as `[bump version]`, `[version bump]`,
`version-bump: true`, `release: true`, or `semver: patch|minor|major`.

## Canonical Version Sync

`pyproject.toml` under `[project].version` is the single canonical source for the production app
version. When the fingerprint gate or explicit marker requests a release, the version-bump workflow
updates that value first, then runs `scripts/sync_version_docs.py` to align the current public
markers, `RELEASE_NOTES.md`, and `docs/releases/latest.json`.

<!-- version:sync:start -->
Current canonical source version: `6.0.0` (`v6.0.0`).
Repository latest metadata: [`docs/releases/latest.json`](releases/latest.json).
Latest release notes: [`RELEASE_NOTES.md`](../RELEASE_NOTES.md).
<!-- version:sync:end -->

The sync script is intentionally conservative. Historical release files such as
`docs/releases/vX.Y.Z.md`, old implementation handoffs, changelog history, and example package names
remain historical records and are not rewritten unless a maintainer edits them directly.
`python scripts/sync_version_docs.py --check` fails the workflow when any synced current-version
surface drifts away from `pyproject.toml`.

## Platforms

Each tag build runs natively on:

- `windows-latest`
- `macos-latest`
- `ubuntu-latest`

Release builds use exact Python `3.14.4` through `actions/setup-python`. Each platform job also
asserts `sys.version_info[:3] == (3, 14, 4)` before dependency installation so public release
packages cannot silently fall back to a different interpreter. Linux installs the same Qt runtime
libraries used by CI before running tests or PyInstaller.

## QA Before Packaging

Each platform job installs the project with build and developer extras:

```bash
python -m pip install -e ".[dev,build]"
```

The PyInstaller pin is kept aligned between `pyproject.toml` and `requirements.txt`, which keeps
the packaging lane on the same release-build dependency set used by local bootstrap.

Before `build.py` runs, the workflow executes:

```bash
python -m compileall -q ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests
python -m ruff check build.py isrc_manager scripts tests
python -m black --check build.py isrc_manager scripts tests
python -m mypy
python -m pytest -q --no-cov tests/test_build_requirements.py tests/test_release_automation.py tests/test_sync_version_docs.py tests/test_python_314_compatibility.py
```

The broader CI workflow still runs its full grouped test matrix on repository pushes.

## Build And Assets

The platform jobs run:

```bash
python build.py
```

`build.py` cleans stale local `build/` and `dist/`, runs PyInstaller, stages the platform output
under `dist/release/`, creates an upload-ready archive under `dist/release/packages/`, and writes
`dist/release_manifest.json`.

SoundCloud credential storage imports Python `keyring` dynamically at runtime, and encrypted
profile support imports `sqlcipher3` dynamically for SQLCipher connections. The build command
therefore explicitly includes `keyring` and `sqlcipher3`, collects `keyring.backends`, and copies
package metadata so the frozen app can discover safe OS keychain/keyring backends and initialize
SQLCipher profile databases.

Package names include:

- app name
- version tag
- operating system
- runner architecture
- archive type

Examples:

```text
ISRCManager-v3.3.3-windows-x64.zip
ISRCManager-v3.3.3-macos-arm64.zip
ISRCManager-v3.3.3-linux-x64.tar.gz
```

The macOS architecture follows the selected `macos-latest` runner. This workflow does not yet
produce a universal binary, DMG, code-signed app, or notarized app.

## Publishing

Matrix jobs upload their platform package as workflow artifacts. A single final `publish` job then:

1. downloads all platform artifacts,
2. chooses release notes from `docs/releases/vX.Y.Z.md`, then `RELEASE_NOTES.md`, then a minimal fallback,
3. creates `SHA256SUMS.txt`,
4. creates a release-scoped `latest.json` manifest with platform asset URLs and SHA256 digests,
5. creates or updates the matching GitHub Release,
6. uploads all platform archives, `latest.json`, and checksums with `gh release upload --clobber`.

The workflow uses the repository `GITHUB_TOKEN` with `contents: write`; it is not triggered from
pull requests.

## Update Check Integration

The version-bump workflow still updates `docs/releases/latest.json` as repository release metadata.
The desktop app now checks the GitHub Release asset
`https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/latest/download/latest.json` so the
manifest is generated after package checksums exist.

The release-scoped manifest includes:

- `version`, `released_at`, `summary`, and `release_notes_url`
- `assets.windows`, `assets.macos`, and `assets.linux`
- each asset's filename, HTTPS GitHub Release download URL, and SHA256 digest

Packaged app updates use that manifest to select the current platform package, verify the download,
stage it safely, and launch the detached updater helper. Source checkouts can still check release
metadata and view release notes, but automatic binary installation is intentionally limited to
packaged builds.

## Local Verification

A maintainer can smoke-test the same package collection path locally:

```bash
python -m pip install -e ".[dev,build]"
python -m pytest -q --no-cov tests/test_build_requirements.py tests/test_release_automation.py tests/test_sync_version_docs.py
python build.py
```

The packaged smoke entrypoint checks that the frozen binary includes the dynamic `keyring` and
`sqlcipher3` modules plus their metadata before reporting success. Local builds produce packages
only for the current operating system.
