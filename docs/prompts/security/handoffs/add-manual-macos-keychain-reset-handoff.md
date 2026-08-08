# Completion Handoff

## Original prompt

Design a safe, manual-button-only way to reset this ad-hoc-signed macOS app's stored
Keychain credentials after an update, allow a fresh start, and never remove unrelated
passwords.

## Result

Implemented a manual **Reset Stored Credentials…** action under Application Settings >
General > Security. The action requires an explicit warning confirmation with Cancel as
the default, runs immediately outside Settings Save/Cancel semantics, and is available
only on supported macOS systems.

The reset boundary deletes generic-password items only for the two fixed app-owned
services `isrc-catalog-manager.database` and `isrc-catalog-manager.soundcloud`. It uses
the fixed Apple `/usr/bin/security` executable with an argument list, `shell=False`, no
user-derived service or account values, no Keychain enumeration, and discarded command
output. It repeatedly removes exact-service matches so stale and orphaned app entries are
included. Partial deletion, authorization cancellation, timeouts, and command failures
are reported with sanitized counts and causes.

The workflow runs as a non-cancellable exclusive background task, refreshes the visible
SoundCloud state, and instructs the user to restart before re-entering existing database
encryption passwords and reconnecting SoundCloud. Help, security policy, UI
qualification, traceability, and regression coverage were updated. The Settings security
controls were also extracted from the oversized dialog into a focused module.

## Files changed

- `SECURITY.md`
- `artifacts/ui_pq/visual/baselines/settings_dialog.png`
- `docs/help/screenshots/chapter_gs1-metadata.png`
- `docs/help/screenshots/chapter_settings.png`
- `docs/help/screenshots/chapter_theme-settings.png`
- `docs/help/screenshots/settings_dialog.png`
- `docs/prompts/security/add-manual-macos-keychain-reset.md`
- `docs/prompts/security/handoffs/add-manual-macos-keychain-reset-handoff.md`
- `isrc_manager/application_settings_dialog.py`
- `isrc_manager/application_settings_security.py`
- `isrc_manager/credential_namespaces.py`
- `isrc_manager/credential_reset.py`
- `isrc_manager/credential_reset_controller.py`
- `isrc_manager/help_content.py`
- `isrc_manager/integrations/soundcloud/token_store.py`
- `isrc_manager/qa/scenarios.py`
- `isrc_manager/qa/traceability.py`
- `isrc_manager/services/database_security.py`
- `isrc_manager/settings_controller.py`
- `tests/ci_groups.py`
- `tests/test_application_settings_dialog_behaviors.py`
- `tests/test_credential_reset.py`
- `tests/test_credential_reset_controller.py`
- `tests/test_database_security.py`
- `tests/test_help_content.py`
- `tests/test_settings_controller.py`
- `tests/ui_qa/test_ui_pq_settings_theme_help.py`

## Verification

- Focused credential reset, controller, Settings UI, Settings wiring, and Help pytest
  suite passed.
- macOS integration coverage created an explicit temporary Keychain, removed all items in
  both app services, preserved an unrelated canary item, and then removed only that
  temporary Keychain. The default/login Keychain was not used.
- Existing database-security and SoundCloud keyring/OAuth/persistence pytest suites
  passed. Two object-based monkeypatch updates fixed their Python 3.14 importer-test
  setup without changing production behavior.
- `history-storage-migration` grouped run passed all 49 modules.
- Full UI-PQ suite passed all 27 tests after the intentional Settings baseline refresh;
  its reset control was verified without activation.
- The broader `ui-app-workflows` grouped run passed through 68 of 95 modules, then its
  120-second module limit stopped `tests.test_theme_builder`. The exact timed-out test
  passed independently in 1.4 seconds, and the dedicated UI-PQ suite passed.
- Full Ruff, Black check, configured mypy, compileall, and `git diff --check` passed.

## Prompt archive

- `docs/prompts/security/add-manual-macos-keychain-reset.md`
- `docs/prompts/security/handoffs/add-manual-macos-keychain-reset-handoff.md`

## Follow-up actions

- Before release, qualify the original failure mode with two independently built,
  ad-hoc-signed packaged macOS app bundles: store credentials with build A, replace it
  with build B, run the manual reset, verify an unrelated canary remains, restart, and
  re-enter/reconnect credentials. Do not dump the login Keychain during this test.
- Decompose the pre-existing oversized `application_settings_dialog.py` (now 1,959 lines)
  and `settings_controller.py` (1,034 lines) in a separate low-risk refactor.

## Notes

- Exact fixed-service matching is the central unrelated-password safety boundary. No
  wildcard, substring, account-derived, class-only, or whole-Keychain deletion exists.
- Local SoundCloud credential removal does not revoke remote SoundCloud access, and the
  confirmation tells the user this before deletion.
- Database encryption passwords, profile databases, catalogs, settings, certificates,
  keys, internet-password items, and other applications' credentials are not targeted.
- Unrelated pre-existing cleanup-workflow files in the dirty worktree were left untouched.
- `application_settings_dialog.py` was reduced by 80 lines through the focused Security
  panel extraction. The minimal controller wiring added to `settings_controller.py` did
  not justify a broader high-risk decomposition within this security fix.
