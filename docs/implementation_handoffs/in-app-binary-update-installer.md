# In-App Binary Update Installer Handoff

Date: 2026-04-26

## Summary

The app now has a packaged-binary update path. When a newer GitHub Release is available, packaged
builds can download the correct platform archive, verify its SHA256 checksum, stage it safely, launch
a detached helper process, exit the main app, replace the installed binary or app bundle, and restart.

Source checkouts intentionally do not self-install binary updates. They can still check versions and
view release notes.

## Files Changed

- `ISRC_manager.py`
  - Adds `Download and Install` to the update-available prompt for packaged builds.
  - Downloads, verifies, extracts, and prepares updates through a background task.
  - Launches the detached helper and quits the main app before replacement.
  - Adds helper-mode CLI routing via `--run-updater-helper`.
- `isrc_manager/update_checker.py`
  - Moves the manifest URL to the GitHub Release `latest.json` asset.
  - Adds strict platform asset parsing for Windows, macOS, and Linux.
  - Validates HTTPS URLs, SHA256 digests, and release-version binding.
- `isrc_manager/update_installer.py`
  - Implements platform selection, download/cache handling, checksum verification, safe archive
    extraction, replacement-candidate discovery, target detection, restart command construction, and
    detached helper launch.
- `isrc_manager/updater_helper.py`
  - Waits for the main app process to exit, backs up the target, installs the staged replacement,
    restarts the app, logs the operation, and rolls back on replacement or restart setup failure.
- `.github/workflows/release-build.yml`
  - Generates and uploads release-scoped `latest.json` after package checksums are known.
- `tests/test_update_checker.py`
  - Covers strict asset manifest parsing and new manifest URL.
- `tests/test_update_installer.py`
  - Covers platform selection, download checksums, safe extraction, traversal rejection, app target
    detection, restart command construction, backup naming, and helper launch.
- `tests/test_updater_helper.py`
  - Covers helper argument parsing, replacement success, rollback, restart failure rollback, and wait
    behavior.
- `tests/test_update_ui_integration.py`
  - Covers the new install button routing and preserves release-notes routing.
- `tests/ci_groups.py`
  - Adds the new tests to the grouped CI set and raises the baseline count.
- `pyproject.toml`
  - Adds the new updater modules to mypy coverage.
- `README.md`, `docs/release-builds.md`, `docs/README.md`, `isrc_manager/help_content.py`
  - Document the in-app updater, manifest, checksums, release assets, cache, and helper flow.

## Manifest Expectations

The app now reads:

```text
https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/latest/download/latest.json
```

The manifest must include `version`, `released_at`, `summary`, `release_notes_url`, optional
`minimum_supported_version`, and an `assets` object with exactly `windows`, `macos`, and `linux`.
Each asset must include a filename, HTTPS GitHub Release URL, and lowercase 64-character SHA256.
Asset names and URLs must reference the same `vX.Y.Z` release as the manifest version.

## Platform Selection

- Windows selects `assets.windows`.
- macOS/Darwin selects `assets.macos`.
- Linux selects `assets.linux`.

Unsupported platforms get a clear message and no install button.

## Download And Cache Behavior

Downloads are written under the app-managed update workspace below the preferred app data root:

```text
<app data>/updates/vX.Y.Z-<platform>/
```

Downloads use HTTPS, timeouts, size limits, and a non-empty file check. The package is hashed after
download and deleted if the checksum does not match.

## Archive Safety

The updater supports `.zip`, `.tar.gz`, and `.tgz`. Archive members are validated before extraction.
Absolute paths, drive-qualified paths, `..` escapes, symbolic links, hard links, and special tar
entries are rejected.

## Installer Helper Flow

The main app prepares a copied helper runtime and launches it with `--run-updater-helper`. This keeps
replacement out of the running main process. The helper receives current PID, target path, staged
replacement path, expected version, backup path, restart command, and log path.

The helper then:

1. waits for the main PID to exit,
2. validates target and replacement paths,
3. moves the current install to a backup path,
4. moves the staged replacement into place,
5. restarts the app,
6. writes an install log.

## Platform Replacement Rules

- Windows replaces the detected `.exe` target.
- macOS replaces the whole `.app` bundle when running from a bundle.
- Linux replaces the detected PyInstaller app folder when `_internal` is present, otherwise the
  executable target.

## Backup And Rollback

The old installation is moved to a sibling `*.backup-before-vX.Y.Z-YYYYMMDD-HHMMSS` path before the
replacement is moved into place. If replacement fails, the helper restores the backup. If restart
setup fails, the helper also restores the backup and logs the failure.

## Known Limitations

- The updater does not perform code-signature or notarization verification yet.
- The helper treats successful process launch as a successful restart; it does not yet confirm that
  the new app reached a healthy post-start state.
- Admin rights are not escalated. Installs in protected locations may fail unless the current user can
  write to the app location.
- The current release workflow produces ZIP/TAR packages, not DMG/MSIX/AppImage installers.

## QA

Passed locally on the Python 3.14.4 virtual environment:

```bash
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
.venv/bin/python -m py_compile ISRC_manager.py build.py isrc_manager/update_checker.py isrc_manager/update_installer.py isrc_manager/updater_helper.py isrc_manager/help_content.py tests/test_update_checker.py tests/test_update_installer.py tests/test_updater_helper.py tests/test_update_ui_integration.py
.venv/bin/python -m compileall -q ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_update_checker tests.test_update_installer tests.test_updater_helper tests.test_update_ui_integration -v
QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600
.venv/bin/python tests/ci_groups.py catalog-services --verify
git diff --check
```

`QT_QPA_PLATFORM=offscreen PYTHON=.venv/bin/python make check` passed compile, Ruff, Black, and
mypy, then segfaulted during the monolithic full unittest discovery path. The CI workflow uses
`tests.run_group` sharding instead of that monolithic local discovery path; the affected
`catalog-services` shard passed.

## Future Improvements

- Add code-signing and notarization checks before accepting macOS packages.
- Add a post-restart success marker so old backups can be cleaned only after the new version confirms
  startup.
- Add installer formats for users who prefer system-managed updates.
- Add delta packages when release sizes become large enough to justify the extra complexity.
