# v6.0.0 Database Encryption Architecture Handoff

Date: 2026-06-03
Branch: `main`
Target release: `v6.0.0`

## Purpose

This handoff records the v6.0.0 major architectural change from plaintext SQLite-first profile
storage to SQLCipher-backed encrypted profile handling. The change is classified as major because
new profiles now require a database password, encrypted profiles require a password before opening,
and legacy plaintext profiles enter an explicit migration/decision flow.

## What Changed

- Added `isrc_manager.services.database_security` for SQLCipher connection opening, password policy,
  session password storage, keyring-backed remembered passwords, plaintext detection, profile
  encryption, rekeying, and SQLCipher availability errors.
- Wired `App` startup to use `DatabaseSessionPasswordManager`,
  `KeyringDatabaseCredentialStore`, `SQLCipherDatabaseService`, and a password-aware
  `SQLiteConnectionFactory`.
- Updated profile creation to require a valid database password before activating the new profile.
- Updated profile browsing and profile switching to detect plaintext/encrypted database files before
  activation.
- Added plaintext-profile migration prompts: encrypt now, open unencrypted for the session, or
  cancel.
- Added an optional suppress-warning setting for users who intentionally continue opening plaintext
  profiles.
- Added a change-password command routed through Application Settings and profile-session logic.
- Added backup handling for profile-maintenance encryption: the previous plaintext database is
  written to the configured app backup directory with `.db.backup.json` metadata.
- Updated Storage Admin so manual database backups and sidecar-backed database backups are retained
  as warning-protected recovery points rather than recommended cleanup.
- Updated Help content and UI QA evidence for the encrypted profile and backup safety workflows.

## Boundary Rationale

Encryption operations live in the services layer because they are persistence/security operations,
not widget behavior. Profile prompts and user decisions remain in `profile_session.py` because that
module already owns profile-opening workflow orchestration and narrow application-host routing.
Storage cleanup classification remains in `storage_admin.py` because that surface owns app-storage
inspection and cleanup policy.

## Migration and Recovery Behavior

- New SQLCipher profiles are created by opening the database through the password-aware connection
  factory.
- Existing encrypted databases are detected as non-empty files without the plaintext SQLite header
  and require a valid password before activation.
- Existing plaintext SQLite profiles warn before opening. If the user chooses encryption, the app
  creates a SQLCipher copy, verifies integrity, and replaces the active database only after the
  encrypted result is valid.
- The previous plaintext profile is retained under the app backup directory as a `.db` recovery
  backup with `.db.backup.json` sidecar metadata.
- If sidecar metadata write fails after encryption succeeds, the app warns but does not report a
  false encryption failure.

## Tests Added or Updated

- `tests/test_database_security.py`
  - SQLCipher connection creation and wrong-password rejection.
  - Password-aware session service opening.
  - SQLCipher schema initialization.
  - SQLCipher migration from every legacy `user_version` 1 through 44 to schema target 45.
  - SQLCipher password changes and plaintext migration.
  - Explicit backup-path creation for profile encryption.
  - Keyring persistence safety and expiry behavior.
- `tests/test_profile_session_controller.py`
  - New-profile password prompting.
  - Encrypted-profile password change.
  - Plaintext warning suppression.
  - Profile encryption backup routing to `backups_dir` with sidecar metadata.
  - Sidecar-write failure tolerance after successful encryption.
- `tests/test_storage_admin_service.py`
  - Manual and sidecar-backed database backup protection.
  - Warning-required deletion behavior.
- `tests/test_help_content.py`
  - Help coverage for SQLCipher profiles, database password controls, migration backups, and backup
    cleanup protection.

## Validation Run

The following validation commands passed locally:

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_database_security.py --no-cov
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/database --no-cov
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_profile_session_controller.py tests/test_help_content.py --no-cov
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_database_admin_service.py tests/test_storage_admin_service.py tests/test_help_content.py tests/test_main_window_helpers.py::test_main_window_database_maintenance_workflows_record_history_and_recover --no-cov
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/ui_qa --no-cov
python3 -m compileall ISRC_manager.py isrc_manager tests
python3 -m ruff check build.py isrc_manager scripts tests
python3 -m black --check build.py isrc_manager scripts tests
python3 -m mypy
```

## Remaining Risks

- Users who forget an encrypted profile password cannot recover that profile through the app. The
  Help and release notes should keep making this explicit.
- Packaged release smoke must continue verifying `sqlcipher3` and `keyring` availability on every
  target platform.
- Migration backups are intentionally plaintext recovery artifacts. Users should keep them only as
  long as needed and protect their backup storage.
