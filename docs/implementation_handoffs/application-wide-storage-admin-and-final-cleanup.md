# Application-Wide Storage Admin And Final Cleanup

## 1. Current storage / retention problem areas found

The repository already retained large amounts of application data outside the active profile database:

- Active profile databases under `Database/`
- Backup database copies under `backups/` and `backups/pre_restore/`
- Profile-scoped history snapshots, snapshot archives, and file-state bundles under `history/`
- Session-level profile lifecycle snapshots under `history/session_profile_snapshots/`
- Managed files under roots such as `track_media/`, `release_media/`, `licenses/`, `contract_documents/`, `asset_registry/`, `custom_field_media/`, `gs1_templates/`, and contract-template storage roots
- Generated exports and logs under `exports/` and `logs/`

Before this pass, diagnostics and cleanup were mostly profile/history scoped. There was no single app-wide admin tool that let a user inspect deleted-profile residue, orphaned managed files, old database copies, and retained recoverability artifacts from one place inside the app.

## 2. Application-wide storage categories implemented

The new app-wide audit classifies storage items using repo-backed rules instead of guessing:

- `In Use by Active Profile`
  - Files still referenced by active profile databases
  - History/session artifacts still referenced by retained undo/redo state
- `Deleted / Missing Profile Residue`
  - History trees tied to a missing profile stem
  - Backup/session artifacts tied to removed profile paths
- `Orphaned / Unreferenced`
  - Managed files or history artifacts inside app-owned roots with no active references
- `Recoverability / History Artifact`
  - Retained snapshots/backups/file-state bundles that are still app-managed history artifacts but are not currently required by active live objects
- `Other App-Managed File`
  - Generated exports and log files that are app-managed but do not have a strong live-reference model

Type/category reporting is separate from safety status, so the UI can distinguish both what a file is and why it is currently protected or reclaimable.

## 3. Diagnostics expansion performed

Diagnostics now includes an `Application Storage` summary block on the Health tab.

It reports:

- Total app usage
- Current active profile attributed usage
- Reclaimable now
- Deleted-profile residue
- Orphaned / unreferenced
- Warning / protected bytes

This expands diagnostics from active-profile-only history reporting into application-wide visibility.

## 4. New admin panel behavior

A new `Application Storage Admin…` entry was added under `Help`, and Diagnostics now links to the same surface through `Open Application Storage Admin…`.

The new admin dialog provides:

- Application-wide summary metrics
- A `Cleanup Candidates` tab
- A `Warnings & In Use` tab
- Per-item details including:
  - status
  - category
  - path
  - size
  - associated profile when known
  - live reference explanation when available
- Final cleanup actions from one place inside the app

This is an application-wide storage administration surface, not a profile-only history cleanup dialog.

## 5. Final deletion semantics

Cleanup runs through `ApplicationStorageAdminService` and deliberately avoids the normal history/snapshot helper wrappers.

Important semantics:

- Cleanup does **not** create new undo records
- Cleanup does **not** create new redo records
- Cleanup does **not** create new snapshots
- Cleanup does **not** create secondary “cleanup safety copies”

For protected history/session artifacts, final cleanup removes the dependent retained history/session references first, then deletes the storage artifact directly. This keeps cleanup final without leaving dangling retained-history metadata behind.

## 6. Active-use warning logic

Items that are still referenced by active profiles or live retained recovery state are flagged with stronger warnings.

Examples:

- Managed media still referenced by active tracks
- History snapshots still referenced by retained history
- Session profile snapshots still referenced by session undo/redo

The admin dialog requires a stronger typed confirmation (`DELETE`) before removing these warning/protected items.

## 7. Tests added / updated

New or updated coverage:

- `tests/test_storage_admin_service.py`
  - application-wide accounting exists
  - current-profile vs app-wide usage is distinguished
  - deleted-profile residue is detected
  - orphaned managed files are detected
  - in-use artifacts are flagged
  - final cleanup removes items without creating new history/session records
  - protected snapshot cleanup purges dependent history references
  - deleted-profile session snapshot cleanup purges dependent session-history references
- `tests/test_app_dialogs.py`
  - Diagnostics shows application-wide storage summary and routes to the admin surface
  - `ApplicationStorageAdminDialog` loads through the async host path
  - warning-backed cleanup uses the stronger confirmation path
- `tests/app/_app_shell_support.py`
  - Help menu expectations updated for the new admin entry
  - dialog-routing coverage updated for the new action

## 8. Risks / caveats

- The app-wide audit is intentionally conservative. Files are only labeled orphaned when a real reference model proves that no active profile still points to them.
- `exports/` and `logs/` are surfaced as other app-managed files rather than falsely labeled orphaned, because they do not have strong live DB-reference semantics.
- Final cleanup of in-use managed files is intentionally destructive and will leave active rows pointing to missing files if the user confirms the stronger warning. This is by design for a true admin cleanup tool.
- `ISRC_manager.py` still contains pre-existing repo lint exclusions / long-standing style debt outside this feature area; the new storage-admin modules and tests were linted directly and pass.

## 9. Explicit product statement

Application-wide cleanup now gives the user central control over unwanted retained data from inside the app without requiring manual OS-shell cleanup.

This feature is a true application-wide storage administration and final cleanup path. It is **not** a normal edit workflow, and it is **not** routed through ordinary snapshot/undo history creation.
