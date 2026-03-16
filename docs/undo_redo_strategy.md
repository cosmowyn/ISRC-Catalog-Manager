# Undo / Redo / History Strategy

## Goal

Add a complete, persistent undo/redo system for user actions in ISRC Manager, including:

- standard undo / redo for reversible actions
- grouped undo for batch operations
- full persistent history across launches
- snapshot support for high-risk or high-volume operations
- the ability to move backward and forward through history without losing prior branches

This document is based on the current codebase as of March 16, 2026.

## Executive Summary

The current application does not have a central mutation layer. State changes are performed directly from:

- `App`
- `EditDialog`
- `LicenseUploadDialog`
- `LicensesBrowserDialog`
- `LicenseeManagerDialog`
- `_ManageArtistsDialog`
- `_ManageAlbumsDialog`
- `DraggableLabel`

Those changes touch multiple storage layers:

1. profile SQLite database
2. `QSettings` / `settings.ini`
3. app-managed filesystem storage, especially `DATA_DIR()/licenses`, `DATA_DIR()/release_media`, `DATA_DIR()/contract_documents`, and `DATA_DIR()/asset_registry`
4. profile `.db` files themselves during profile removal and restore

Because of that, a complete undo/redo system here should **not** be implemented as a simple in-memory stack.

The recommended approach is a **hybrid history engine**:

- logical inverse commands for normal CRUD and settings changes
- grouped actions for multi-step user operations
- full snapshots for imports, schema-affecting actions, profile deletion, and database restore
- branch-aware persistent history, not a destructive linear redo stack

## Current Mutation Surface

### A. Track and catalog data

Primary user-facing data mutations:

- `App.save`
  - inserts into `Tracks`
  - may insert into `Artists`
  - may insert into `Albums`
  - rewrites `TrackArtists`
- `EditDialog.save_changes`
  - updates `Tracks`
  - may insert into `Artists`
  - may insert into `Albums`
  - rewrites `TrackArtists`
- `App.delete_entry`
  - deletes `Tracks`
  - cascades related rows through FK constraints
- `App.import_from_xml`
  - inserts many `Tracks`
  - may insert many `Artists`
  - may insert many `Albums`
  - inserts `TrackArtists`
  - inserts `CustomFieldValues`

### B. Custom fields

- `App.manage_custom_columns`
  - inserts / updates / deletes `CustomFieldDefs`
  - deletes definitions with cascading value deletion
  - can effectively change schema semantics for large parts of the app
- `App._on_item_double_clicked`
  - updates `CustomFieldValues`
  - may update `CustomFieldDefs.options` for dropdowns
- `App.cf_save_value`
  - inserts / updates `CustomFieldValues`
  - stores BLOB data in DB
- `App.cf_delete_blob`
  - deletes a `CustomFieldValues` row

### C. License management

- `LicenseUploadDialog._save`
  - may insert into `Licensees`
  - inserts into `Licenses`
  - copies PDF into `DATA_DIR()/licenses`
- `LicensesBrowserDialog._edit_selected`
  - may insert into `Licensees`
  - updates `Licenses`
  - may copy replacement PDF into `DATA_DIR()/licenses`
- `LicensesBrowserDialog._delete_selected`
  - deletes from `Licenses`
  - may delete stored PDF files from disk
- `LicenseeManagerDialog._add`
  - inserts into `Licensees`
- `LicenseeManagerDialog._rename`
  - updates `Licensees`
- `LicenseeManagerDialog._delete`
  - deletes from `Licensees`

### C2. Legacy license migration

- `App.migrate_legacy_licenses_to_contracts`
  - captures a pre-migration snapshot
  - creates or reuses `Parties` from legacy `Licensees`
  - creates `Contracts`
  - creates `ContractDocuments`
  - copies managed PDFs from `DATA_DIR()/licenses` into `DATA_DIR()/contract_documents`
  - verifies the copied file checksums before cleanup
  - deletes migrated rows from `Licenses`
  - deletes migrated rows from `Licensees`
  - deletes the old managed legacy PDF files only after verification succeeds
  - captures a post-migration snapshot and records the action as a snapshot-backed history entry

### D. Artist / album maintenance

- `_ManageArtistsDialog._delete_selected`
  - deletes unused `Artists`
- `_ManageArtistsDialog._purge_unused`
  - bulk deletes unused `Artists`
- `_ManageAlbumsDialog._delete_selected`
  - deletes unused `Albums`
- `_ManageAlbumsDialog._purge_unused`
  - bulk deletes unused `Albums`

### E. Settings and profile data

- `App.edit_identity`
  - writes `identity/window_title` and `identity/icon_path` in `QSettings`
- `App.set_artist_code`
  - writes profile-scoped key in `app_kv`
- `App.set_isrc_prefix`
  - writes `ISRC_Prefix`
- `App.set_sena_number`
  - writes `SENA`
- `App.set_btw_number`
  - writes `BTW`
- `App.set_buma_info`
  - writes `BUMA_STEMRA.relatie_nummer`
- `App.set_ipi_info`
  - writes `BUMA_STEMRA.ipi`

### F. Profile lifecycle

- `App.create_new_profile`
  - creates a new `.db` file
  - initializes schema
  - changes active profile
- `App.remove_selected_profile`
  - deletes a `.db` file from disk
  - may close and reopen connections
- `App.restore_database`
  - replaces the current database file from backup
  - is effectively a full-state replacement

### G. Persistent UI preferences

These are persistent, but lower-value from a history standpoint:

- `DraggableLabel.mouseReleaseEvent`
  - writes hint bubble positions to `QSettings`
- `App._toggle_columns_movable`
  - writes table preference to `QSettings`
- `App._save_header_state`
  - writes column order / header state to `QSettings`

### H. Non-mutating side effects that should not be part of undo

These should be logged in history, but not placed on the reversible stack by default:

- `App.export_full_to_xml`
- `App.export_selected_to_xml`
- `LicensesBrowserDialog._download_pdf`
- `App.backup_database`
- `App.verify_integrity`

These operations create artifacts or reports, but they do not change core app state in a way users normally expect `Undo` to reverse.

## Key Architectural Constraints

### 1. Mutations are not centralized

The biggest implementation blocker is not storage; it is the fact that DB writes, settings writes, and file writes are spread across many UI methods.

Undo/redo should not be added directly to those methods one by one as ad hoc patches.

Before implementation, mutations need to be routed through a central action layer.

### 2. Not all actions can be reversed logically

Some operations are natural command actions:

- create track
- update track
- delete track
- change prefix
- rename licensee
- attach blob

Some operations are much safer as snapshot actions:

- import XML
- manage custom columns
- migrate legacy licenses into contracts
- remove profile
- restore database
- bulk purge artists / albums

### 3. History must be persistent

If history disappears on app close, it will not satisfy the “full undo history” goal.

History should be stored per profile and survive restarts.

### 4. Redo should be branch-aware

A conventional two-stack model destroys redo history when the user undoes three steps and then performs a new action.

That does not satisfy “full history”.

The recommended design is:

- persistent history as a graph
- one current head pointer per profile
- undo moves the head backward
- redo moves to a chosen child branch
- new actions from an older state create a new branch instead of erasing the old future

## Recommended Architecture

### Core components

Introduce a dedicated undo subsystem:

```text
isrc_manager/
  history/
    __init__.py
    manager.py
    actions.py
    snapshots.py
    storage.py
    files.py
    models.py
```

Recommended responsibilities:

- `HistoryManager`
  - execute actions
  - record history
  - undo current action
  - redo selected branch
  - jump to snapshot or entry
- `ActionContext`
  - provides DB connection
  - provides settings adapter
  - provides managed file store
  - provides active profile path
- `UndoableAction`
  - encapsulates one logical user action
- `SnapshotManager`
  - creates and restores snapshots
- `HistoryStorage`
  - persists entries, head pointers, and branch structure
- `ManagedFileStore`
  - stores captured files for reversible filesystem actions

## Current Implementation Notes

The current implementation now includes two important pieces that were only proposed earlier:

- snapshot-backed migration for the legacy license archive into the newer party/contract/document model
- managed-directory snapshot coverage beyond the original license and track-media folders

Current managed directory snapshot coverage includes:

- `licenses`
- `track_media`
- `release_media`
- `contract_documents`
- `asset_registry`

Current snapshot restore behavior now restores the full application domain state instead of only the older legacy tables, while still excluding the history tables themselves.

### Mutation flow

Every mutating operation should follow this shape:

1. UI creates an action object
2. `HistoryManager.execute(action)` opens a managed transaction
3. action captures “before” state
4. action applies the mutation
5. action captures “after” state or inverse payload
6. history entry is persisted
7. UI refresh occurs

Undo:

1. `HistoryManager.undo()` resolves current head
2. if logical inverse exists, apply inverse transaction
3. if snapshot action, restore snapshot
4. update head pointer
5. refresh affected UI

Redo:

1. choose next child from current history node
2. replay logical redo or restore snapshot-after
3. move head pointer forward

## Recommended Persistence Model

### A. History tables

Add tables to the profile database for history metadata:

```sql
CREATE TABLE IF NOT EXISTS HistoryEntries (
    id INTEGER PRIMARY KEY,
    profile_path TEXT NOT NULL,
    parent_id INTEGER,
    branch_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    label TEXT NOT NULL,
    action_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    reversible INTEGER NOT NULL DEFAULT 1,
    strategy TEXT NOT NULL,              -- inverse | snapshot | event
    payload_json TEXT,                   -- user-facing metadata
    inverse_json TEXT,                   -- logical undo payload
    redo_json TEXT,                      -- logical redo payload
    snapshot_before_id INTEGER,
    snapshot_after_id INTEGER,
    file_bundle_id INTEGER,
    status TEXT NOT NULL DEFAULT 'applied'
);

CREATE TABLE IF NOT EXISTS HistoryHead (
    profile_path TEXT PRIMARY KEY,
    current_entry_id INTEGER,
    current_branch_id TEXT
);

CREATE TABLE IF NOT EXISTS HistorySnapshots (
    id INTEGER PRIMARY KEY,
    profile_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL,                  -- auto | pre_import | pre_restore | manual
    db_snapshot_path TEXT NOT NULL,
    settings_json TEXT,
    manifest_json TEXT
);
```

### B. File capture store

Do not store captured PDFs and large snapshot binaries inside SQLite blobs for routine history.

Store them on disk under an app-managed object store, for example:

```text
DATA_DIR()/history/
  objects/<sha256>
  snapshots/<profile-id>/<timestamp>.db
  manifests/<entry-id>.json
```

Then reference those paths from `HistoryEntries` and `HistorySnapshots`.

### C. Settings capture

For complete reversibility, capture the persistent settings touched by actions:

- `identity/window_title`
- `identity/icon_path`
- table header state if included in scope
- draggable label positions if included in scope

This can be stored as JSON per entry or per snapshot.

## Action Strategy Matrix

### Use logical inverse actions

These should be implemented as explicit undoable commands:

- track create
- track update
- track delete
- custom field value update
- blob attach / replace / delete
- ISRC prefix and registration-number updates
- identity changes
- artist code changes
- license add
- license edit
- license delete
- licensee add / rename / delete
- delete unused artists
- delete unused albums

### Use grouped logical actions

These should be one history entry with nested sub-effects:

- track create with auto-created artist / album rows
- track update with replaced additional artists
- license edit that also adds a new licensee and replaces a file

### Use snapshot actions

These should restore from a captured snapshot instead of relying on row-level inverse logic:

- XML import
- manage custom columns
- bulk purge unused artists
- bulk purge unused albums
- remove selected profile
- restore database

### Use history-only events

These should appear in the history timeline, but not on the default undo stack:

- export XML
- download PDF
- create backup
- integrity check

## Snapshot Policy

### Snapshot triggers

Create snapshots:

- before XML import
- before manage custom columns
- before restore database
- before remove selected profile
- before bulk purge operations
- every N reversible actions, such as every 25 actions
- on explicit “Create Snapshot” from the history UI

### Snapshot contents

A full snapshot for a profile should include:

- SQLite DB backup of current profile
- relevant persistent settings JSON
- manifest of app-managed files referenced by reversible actions

For profile deletion, snapshot should also include the profile file path itself.

## Recommended UI Behavior

### Keyboard shortcuts

Recommended defaults:

- `Ctrl+Z` / `Cmd+Z`: undo last reversible action
- `Ctrl+Shift+Z` or `Ctrl+Y`: redo

### History panel

Add a dock or dialog that shows:

- action label
- timestamp
- profile
- entity
- grouped children, where relevant
- snapshot markers
- branch markers

Recommended actions in the UI:

- undo
- redo
- jump to selected entry
- create snapshot
- prune old snapshots

### User-visible labels

History labels should be specific:

- `Create Track: My Song`
- `Update Track: My Song`
- `Delete Track: My Song`
- `Import XML: 17 tracks`
- `Manage Custom Columns`
- `Add License: My Song / ACME Publishing`
- `Delete Profile: demo.db`

## Implementation Risks Specific To This Repo

### 1. Direct SQL in dialogs

Multiple dialogs write directly to the shared connection. Those writes must be rerouted through a history-aware service layer before undo becomes reliable.

### 2. Mixed DB and filesystem mutations

Licenses are split across DB rows plus external PDF files. A reversible action must capture both.

### 3. Cascade deletes

Deleting tracks, custom field definitions, or profile DBs can remove large related state. Row-level inverse logic must either capture the entire deleted subtree or use snapshots.

### 4. Existing migration discipline needs tightening

The current migration system already needs careful handling before new history tables are added. Undo/history should be introduced only after the migration path for the new tables is explicit and tested.

### 5. Audit log is not enough

The current `AuditLog` is append-only and good for traceability, but it is not suitable as an undo engine:

- it does not capture before-state
- it does not store inverse payloads
- it does not represent filesystem changes
- it does not track history head or redo branches

Audit logging should remain, but it should not be reused as the undo mechanism.

## Recommended Staging Plan

### Stage 0: Centralize mutations

Before building history:

- move mutating operations into service objects
- keep UI code responsible only for dialogs and refreshes
- make every service method the sole owner of one transaction

Target services:

- `TrackService`
- `CustomFieldService`
- `LicenseService`
- `SettingsService`
- `ProfileService`
- `HistoryManager`

### Stage 1: Add linear persistent undo for core actions

Start with the highest-value actions:

- track create / update / delete
- custom field value edits
- blob attach / delete
- settings changes
- license add / edit / delete
- licensee add / rename / delete

At this stage, redo can still be linear if that speeds delivery.

### Stage 2: Add snapshot actions

Next support:

- XML import
- manage custom columns
- bulk purges
- restore database
- remove profile

### Stage 3: Upgrade to branch-aware history

Replace destructive redo semantics with branch-aware navigation:

- store parent-child relationships
- keep all futures after branching
- expose branch choice in history UI

### Stage 4: Add snapshot browsing and jump-to-point restore

Allow users to:

- inspect prior points in time
- restore to a chosen history entry
- create named manual snapshots

### Stage 5: Optional preference history

Only if desired, expand the system to include:

- table layout preferences
- hint bubble positions
- other persistent UI settings

This should be opt-in or filtered, because it can generate noisy history.

## Recommended Initial Scope

If you want a production-usable first release quickly, implement this first:

1. persistent undo/redo for track CRUD
2. persistent undo/redo for custom field edits and blob changes
3. persistent undo/redo for license add/edit/delete
4. persistent undo/redo for settings changes
5. snapshot undo for XML import and custom column management

That gives users real value quickly while avoiding the hardest branch-history work until the mutation layer is centralized.

## Definition Of Done

The undo/redo system should only be considered complete when:

- every reversible user mutation is routed through `HistoryManager`
- history persists across app restarts
- batch actions are grouped
- imports, schema-affecting actions, and restore flows use snapshots
- redo does not silently discard prior history branches
- licenses and other filesystem-backed actions restore both DB rows and files
- tests cover core actions, grouped actions, and snapshot restore paths
