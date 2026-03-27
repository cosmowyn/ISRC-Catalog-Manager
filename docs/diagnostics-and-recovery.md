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
- history storage budget pressure and safe reclaimable space
- legacy promoted-field collisions that now belong in default columns

Diagnostics is the right surface when the question is, "Is the app and profile still healthy?"

The diagnostics window now loads heavier reports and supported repair actions through the background task layer, so opening, refreshing, and repairing large profiles no longer has to feel like a frozen dialog.

## Suggested Fixes

The quality and diagnostics surfaces can offer guided repairs when the issue is safe to correct automatically.

Examples include:

- regenerating derived values
- normalizing date formats
- relinking missing media by filename
- filling blank track values from linked release metadata where appropriate
- reconciling history artifacts
- safely merging legacy promoted-field values into the matching default columns when blank cells can be filled conservatively
- migrating a legacy storage layout into the preferred app-managed structure

These are deliberate, scoped fixes rather than broad auto-repair. The app stays conservative about what it changes.

## Snapshots And Backups

The history system is part of the recovery story.

- Undo and redo cover the immediate reversible chain.
- Manual snapshots create named restore points for larger operations.
- Backups preserve additional recovery options beyond the live undo stack.
- Restore paths exist so imports, license migration, and other heavier tasks are not one-way changes.

This is important because the app is meant for real catalog operations, not disposable scratch data.

## Retention, Budget, And Automatic Cleanup

Recovery is no longer just about creating artifacts. It also includes conservative storage policy controls.

- `Settings > Application Settings > General` now includes snapshot retention and safety controls for the active profile.
- The named levels `Maximum Safety`, `Balanced`, and `Lean` provide preset cleanup behavior, while `Custom` lets you keep your own combination.
- The profile can store a soft history storage budget, an automatic-snapshot retention count, and an optional age limit for pre-restore safety copies.
- Automatic cleanup removes only eligible auto-generated artifacts. Manual snapshots and protected restore points stay protected by default, while ordinary backup records remain cleanup-eligible and older pre-restore safety backups can be pruned by age when that policy is enabled.

This keeps history growth practical without turning cleanup into a blind delete tool.

## Cleanup

Cleanup is not a blind delete operation.

- The cleanup flow previews what is eligible.
- It protects items that are still required by undo, redo, snapshot restore, or session restore. Ordinary backup records can still be cleanup candidates, and aged pre-restore safety backups can also become eligible under the active policy.
- It distinguishes between eligible and protected artifacts.
- It now shows the current budget posture and whether the active policy can still reclaim safe space.
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
- Snapshot creation, restore, and settings changes can warn before the profile would cross its configured history budget.
- Migration does not replace the active layout until the staged copy has been verified.

The central idea is simple: the app prefers staged, verified transitions over destructive replacements.

## Storage Migration

Diagnostics can guide a staged migration from a legacy app-data layout into the preferred app-managed root, and startup now uses the same migration service before managed writes begin.

- The migration is blocked while background tasks are running.
- The active profile is closed before migration begins.
- Data is staged into a temporary sibling root first.
- SQLite databases are copied with SQLite's backup API rather than raw file copies.
- Embedded paths in history and backup metadata are rewritten.
- Verification happens before the staged root is promoted.
- The legacy root is left intact.
- If the preferred root is already valid, the app can adopt it automatically instead of copying again.
- If a preserved staged migration exists and still validates, the app can resume from that stage instead of starting over.

That approach is conservative by design and gives diagnostics a real repair workflow instead of a simple folder move.

## Logs

When you need to investigate something that the UI alone cannot explain, the app provides logs.

- The application log is intended for readable troubleshooting.
- The trace log gives a structured record for deeper diagnosis.
- Both can be opened from the app so you do not have to hunt through folders manually.
- Startup and storage-migration decisions are buffered and written into the final log location once the launch root is settled.

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
