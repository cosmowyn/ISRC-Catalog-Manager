# Completion Handoff

## Original prompt

> Investigate the undo/redo stack. When deleting records from the database and trying to undo it, I get an error message saying that it is not allowed. The purpose of the undo is to be able to reverse destructive actions by the user.
>
> Patch the findings and restore full undo/redo capability.

## Result

The destructive-action Undo/Redo stack is restored for history-backed catalog and profile operations. The original failure was caused by snapshot replay deleting every domain table, which activated the append-only accounting triggers even when the user action had not changed accounting data.

Replay now applies primary-key row deltas only to records changed by the original action. It preserves protected accounting, issued-document, royalty, audit, and registry state; validates the expected live state before mutation; enforces foreign-key order and integrity; and leaves the history entry retryable if replay cannot complete safely.

The implementation also restores and replays action-owned settings and managed files, with conflict checks, per-artifact inventories and digests, fixed-root containment, symlink rejection, case-only rename support, and fail-closed behavior for missing or altered recovery artifacts. SQLCipher profile snapshots and session-level profile create/remove history remain usable across password changes with rollback-safe rekeying.

Track, release, work, contract, party, rights, asset, cleanup, and profile destructive workflows are covered. Party merges and managed asset files are reversible; external asset references and later unrelated records remain untouched. Append-only financial records continue to use their dedicated correction/reversal workflows instead of weakening their database protections.

## Files changed

- Core history replay and integrity: `isrc_manager/history/manager.py`, `snapshot_replay.py`, `snapshot_scope.py`, and `snapshot_security.py`.
- Session profile history: `isrc_manager/history/session_manager.py`, `session_bundle.py`, `isrc_manager/profile_session.py`, and `isrc_manager/main_window.py`.
- Encrypted database wiring: `isrc_manager/services/database_security.py`, `isrc_manager/app_services.py`, and `isrc_manager/tasks/app_services.py`.
- Destructive workflow integration: `isrc_manager/assets/`, `isrc_manager/parties/`, and `isrc_manager/rights/`.
- Help and qualification coverage: `isrc_manager/help_content.py`, `isrc_manager/qa/`, relevant `tests/history/`, asset/party/rights/session/app-shell/UI-PQ tests, and refreshed tracked UI-PQ/help evidence artifacts.
- Prompt archive: `docs/prompts/bugfix/restore-destructive-undo-redo.md` and this handoff.

The shared worktree also contains separate credential-reset and GitHub-cleanup changes; those were preserved and are not part of this result.

## Verification

Passed in the active environment:

- Critical original regression plus recovery and app-shell workflow: 22 tests passed. The app test posts accounting canaries before and after Track deletion, then verifies Delete -> Undo -> Redo without an error or immutable-row change.
- Core history, party/rights, and asset integration suite: 99 tests and 4 subtests passed.
- `python3 -m tests.run_group history-storage-migration`: all 53 owned modules passed.
- `python3 -m tests.run_group catalog-services`: all 104 owned modules passed.
- `python3 -m tests.run_group ui-app-workflows --module-timeout-seconds 180 --group-timeout-seconds 900`: all 96 owned modules passed.
- `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/ui_qa --no-cov`: 28 tests passed. The refreshed full qualification evidence contains 15 passed workflow events and zero actionable deviations.
- Group ownership verification passed for all four CI groups.
- `python3 -m compileall -q ISRC_manager.py isrc_manager tests` passed.
- `python3 -m ruff check build.py isrc_manager scripts tests` passed.
- `python3 -m black --check build.py isrc_manager scripts tests` passed for 635 files.
- `python3 -m mypy` passed for 50 configured source files.
- `git diff --check` passed.

## Prompt archive

- Prompt: `docs/prompts/bugfix/restore-destructive-undo-redo.md`
- Handoff: `docs/prompts/bugfix/handoffs/restore-destructive-undo-redo-handoff.md`

## Follow-up actions

- Decompose the pre-existing oversized `history/manager.py`, `profile_session.py`, and `main_window.py` modules in a dedicated maintenance change. Cohesive replay, scope, security, and session-bundle responsibilities were extracted here, but a complete split would be too risky to combine with this data-integrity fix.

## Notes

- Threat model: protected assets are catalog/profile state, immutable ledgers, encrypted snapshots, settings, and managed files. Untrusted boundaries include snapshot manifests, artifact paths, stale live state, and concurrent filesystem/database changes. Replay now authenticates recorded state, constrains paths to owned roots, checks conflicts before mutation, and compensates or rolls back on failure.
- Explicit administrative cleanup/history purge operations and replaceable convenience data such as saved searches or preview bookmarks remain intentional non-history actions. Posted financial data remains append-only and is corrected through domain-specific reversal workflows.
- The UI workflow group needed a 180-second per-module limit locally because the complete theme-builder module takes about 139 seconds in this environment; it passed with the CI-compatible higher limit.
- No production database or user-managed external asset was modified during verification; tests used disposable profiles and temporary managed roots.
