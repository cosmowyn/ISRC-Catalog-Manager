# Diagnostics and Recovery

This guide groups the app's operational safety tools in one place: quality review, diagnostics, snapshots, backups, cleanup, trim, storage migration, and logs.

## What This Enables

The product is designed to be recoverable. That matters because catalog work often involves imports, bulk edits, storage changes, and file-backed records that should not be treated as disposable.

The app separates two related but different jobs:

- `Quality Dashboard` helps you find catalog problems in the data itself.
- `Diagnostics` helps you verify the health of the application environment, storage layout, and managed files around the catalog.

## Quality Dashboard Versus Diagnostics

These surfaces solve different problems.

### Quality Dashboard

Use the quality dashboard when you want to review catalog content for operational issues such as:

- missing or duplicate identifiers
- invalid or incomplete release data
- missing artwork or media references
- rights, contract, work, or asset problems
- items that could block export readiness or downstream use

The dashboard is built for action. It does not just report issues; it also offers direct entry points back into the affected record and can surface suggested fixes where the app can safely help.

### Diagnostics

Use diagnostics when you want to verify the environment around the catalog:

- application and profile version information
- storage layout
- schema validity
- SQLite integrity
- foreign-key integrity
- custom-value integrity
- managed-file integrity for path-backed records
- history storage health

Diagnostics is the right surface when the question is, "Is the app and profile still healthy?"

## Suggested Fixes

The quality and diagnostics surfaces can offer guided repairs when the issue is safe to correct automatically.

Examples include:

- regenerating derived values
- normalizing date formats
- relinking missing media by filename
- filling blank track values from linked release metadata where appropriate
- reconciling history artifacts
- migrating a legacy storage layout into the preferred app-managed structure

These are deliberate, scoped fixes rather than broad auto-repair. The app stays conservative about what it changes.

## Snapshots And Backups

The history system is part of the recovery story.

- Undo and redo cover the immediate reversible chain.
- Manual snapshots create named restore points for larger operations.
- Backups preserve additional recovery options beyond the live undo stack.
- Restore paths exist so imports, license migration, and other heavier tasks are not one-way changes.

This is important because the app is meant for real catalog operations, not disposable scratch data.

## Cleanup

Cleanup is not a blind delete operation.

- The cleanup flow previews what is eligible.
- It protects items that are still required by undo, redo, snapshot restore, backup restore, or session restore.
- It distinguishes between eligible and protected artifacts.
- It helps keep history and storage from growing without context.

Use cleanup when you want to remove old restore artifacts without breaking the current recovery chain.

## Trim Behavior

Trim history is the more aggressive history-reduction tool.

- It keeps the most recent reversible actions on the active branch.
- It preserves the current redo chain where applicable.
- It removes older history rows.
- It then removes newly unreferenced snapshot, archive, and file-state artifacts.

That makes trim useful when you want to reduce history volume while keeping the current working branch recoverable.

## Restore Safety

Recoverability is built into the app's higher-risk flows.

- Imports run with history support.
- Snapshots capture the profile database and related managed state where supported.
- Cleanup avoids deleting anything still referenced by the live history chain.
- Migration does not replace the active layout until the staged copy has been verified.

The central idea is simple: the app prefers staged, verified transitions over destructive replacements.

## Storage Migration

Diagnostics can guide a staged migration from a legacy app-data layout into the preferred app-managed root.

- The migration is blocked while background tasks are running.
- The active profile is closed before migration begins.
- Data is staged into a temporary sibling root first.
- SQLite databases are copied with SQLite's backup API rather than raw file copies.
- Embedded paths in history and backup metadata are rewritten.
- Verification happens before the staged root is promoted.
- The legacy root is left intact.

That approach is conservative by design and gives diagnostics a real repair workflow instead of a simple folder move.

## Logs

When you need to investigate something that the UI alone cannot explain, the app provides logs.

- The application log is intended for readable troubleshooting.
- The trace log gives a structured record for deeper diagnosis.
- Both can be opened from the app so you do not have to hunt through folders manually.

Use logs together with diagnostics when a problem is not obvious from the quality dashboard alone.

## Practical Order Of Operations

For most troubleshooting, the safest order is:

1. Review the quality dashboard.
2. Open the affected record and inspect related managers if needed.
3. Run diagnostics to verify storage and environment health.
4. Use a suggested fix if one is available and clearly appropriate.
5. Review history, snapshots, or backups before trimming or migrating.
6. Check logs if the problem still needs investigation.

That sequence keeps you in a recoverable path and avoids jumping straight to destructive cleanup.

