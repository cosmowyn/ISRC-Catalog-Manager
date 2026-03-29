# Truthful Diagnostics Startup Progress

## 1. Previous simplified progress model found

Before this pass, the diagnostics dialog startup strip was effectively a generic busy indicator:

- The dialog loading bar was indeterminate
- Startup only surfaced coarse status text like `Loading diagnostics...`
- The real diagnostics worker did substantial sequential work, but it did not report completed work units back into the dialog
- The dialog could only tell the user that startup was busy, not what had actually finished

## 2. Real diagnostics startup checks identified

The actual startup report builder already performs a fixed diagnostics pipeline:

- Environment details collection
- Storage layout inspection
- Schema version check
- Schema layout validation
  - required table inspection
  - required `Tracks` column inspection
- SQLite integrity check
- Foreign-key consistency check
- Custom-value integrity check
- Legacy promoted-field overlap inspection
- Managed-file validation
  - track audio references
  - album artwork references
  - license file references
- History diagnostics
  - recovery-state inspection
  - snapshot issue summary
  - backup issue summary
  - history invariant summary
  - history storage budget preview
- Application-wide storage audit
  - active profile discovery
  - per-profile managed reference collection
  - managed-root audit
  - history / backup / session audit
  - generated export / log audit
  - summary finalization

## 3. Long-running checks broken into which substeps

This pass broke the coarse grouped work into meaningful reportable units where that work was already real:

- Schema layout now reports table inspection and required-track-column inspection separately
- Managed-file diagnostics now advance per referenced managed file instead of as one opaque check
- History diagnostics now advance across five real substeps instead of one grouped history milestone
- Application-wide storage now reuses the storage-admin service’s real progress model instead of hiding it behind generic diagnostics loading

## 4. New truthful progress model

Diagnostics startup now uses `DiagnosticsProgressTracker` in [isrc_manager/diagnostics_progress.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/diagnostics_progress.py).

Key behavior:

- Progress is tracked in real completed work units, not arbitrary milestone percentages
- Managed-file validation reserves one unit per referenced managed file, with a minimum fallback unit when there are no references to scan
- Application-wide storage reserves the exact number of units reported by `ApplicationStorageAdminService.inspect_progress_total(...)`
- The dialog bar percentage is then derived by `QProgressBar` from those real completed units

## 5. How current-check reporting now works

The diagnostics async path now forwards both:

- status updates
- progress updates

The diagnostics dialog loading strip now shows:

- a determinate progress bar
- the current active diagnostic check message

Examples of visible active-check messages:

- `Checking managed audio references (12/97)...`
- `Evaluated history storage budget.`
- `Audited generated exports and log files.`

## 6. How `100%` correctness is enforced

`100%` is reserved for true completion of diagnostics startup, not just worker completion.

Implementation detail:

- the diagnostics worker reserves one final UI-completion unit in the total progress plan
- worker-side diagnostics only complete the real diagnostic work units
- `on_success_before_cleanup` applies the report to the dialog first
- only after that UI-side application step completes does the startup flow emit the final `Diagnostics ready.` update and reach the total unit count

This keeps `100%` aligned with diagnostics startup actually being ready to use.

## 7. Files changed

- [ISRC_manager.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [isrc_manager/app_dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_dialogs.py)
- [isrc_manager/diagnostics_progress.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/diagnostics_progress.py)
- [isrc_manager/storage_admin.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/storage_admin.py)
- [tests/test_app_dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_app_dialogs.py)

## 8. Tests added / updated

- `tests/test_app_dialogs.py`
  - diagnostics async loader now exercises determinate progress updates
  - loading bar state is validated against reported work units
  - completion is validated so the bar only reaches its terminal value after the final progress update
- `tests/test_storage_admin_service.py`
  - remained in the focused verification suite because diagnostics now depends on truthful application-storage progress totals

## 9. Remaining limitations or next bottlenecks

- SQLite integrity and foreign-key checks are still each one coarse unit because the underlying SQLite pragmas do not expose finer-grained progress boundaries through the current service layer
- History storage budget preview still hides the internal detail of the cleanup service’s own scan pipeline behind one real substep, because the current cleanup service does not yet emit finer progress callbacks
- `ISRC_manager.py` still has pre-existing repo-wide lint debt outside this feature area; this pass validated the touched diagnostics modules and tests directly
