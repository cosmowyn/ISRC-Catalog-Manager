# ISRC Catalog Manager 6.0.0

[![Release](https://img.shields.io/github/v/tag/cosmowyn/ISRC-Catalog-Manager?label=release)](https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/tag/v6.0.0)

Version: 6.0.0
Date: 2026-06-03
Type of update: Major

## Highlights
- Moved profile databases to a SQLCipher-backed encrypted architecture for new profiles and encrypted profile opens.
- Added password prompting, session-only password handling, optional safe OS keychain/keyring remember support, and an in-app change-password workflow.
- Added plaintext-profile migration handling with verified encryption and recovery backups retained in the app backup directory.
- Added SQLCipher migration regression coverage from legacy schema versions 1 through 44 to schema target 45.
- Updated Storage Admin and Help so manual database backups and profile-maintenance recovery backups are warning-protected recovery points.

## Fixes
- Prevented profile-maintenance encryption backups from being written beside the source profile; they now go to the configured app backup directory.
- Prevented backup-sidecar write failures from being reported as failed encryption after the encrypted profile has already been created successfully.
- Protected manual database backups from recommended automatic cleanup while preserving cleanup eligibility for restore safety copies.

## Internal/technical changes
- Added `sqlcipher3==0.6.2` and `keyring==25.7.0` runtime dependencies.
- Added SQLCipher connection/session password services and encrypted schema migration tests.
- Updated build, package smoke, Help, UI QA evidence, settings, storage-admin, and schema tests for the encrypted profile architecture.
