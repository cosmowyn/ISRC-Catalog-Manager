# UI PQ Execution Summary

This is an internal engineering UI qualification artifact. It is not a regulatory certification or external compliance claim.

- Generated: 2026-06-14T19:42:31.281457+00:00
- Inventory items discovered: 413
- Traceability rows written: 413
- Automated traceability rows: 386
- Pending/manual/out-of-scope rows: 27
- Deviations recorded: 28
- Open actionable deviations: 1
- Pending/manual deviations: 27
- Object-name gap deviations: 0
- QA database: /private/var/folders/6n/jmt1mclx4db3_18pj0z9n8l40000gn/T/tmpfglcc9ty/qt-settings/AppLocalDataLocation/Database/default.db

## Executed Evidence Events

- `UI-PQ-INV-001` passed: Runtime UI inventory and traceability matrix were generated.
- `UI-PQ-SMOKE-001` passed: Main window, menu bar, and QA database are reachable.
- `UI-PQ-MENU-001` passed: Runtime menu/action inventory was generated.
- `UI-PQ-SET-001` passed: Visual screenshots, baseline comparison, dialog capture, and theme payload verification completed.
- `UI-PQ-HELP-001` passed: Help documentation coverage matched runtime inventory, workflow playbooks, chapter-depth checks, and real UI screenshot references.
- `UI-PQ-CAT-001` passed: Track was created through Add Track UI and edited through Edit Track UI.
- `UI-PQ-REL-001` passed: Party, Work, and Release relationships were created or verified through manager UI.
- `UI-PQ-CON-001` passed: Contract and Rights Matrix records were created through UI and verified in the database.
- `UI-PQ-ACC-001` failed: accounting workflow failed: AssertionError: Enabled button was not found: Issue
- `UI-PQ-SC-001` passed: SoundCloud publish dialog options, private preflight, watermarked source, artwork, mocked publish action, progress UI, completion UI, run state, and no-secret storage were verified without network.
- `UI-PQ-DIAG-001` passed: Diagnostics report, SQLite integrity, backup creation, and isolated restore verification completed against the QA profile.
- `UI-PQ-IMP-001` passed: Generated report, document, CSV, and PDF comparison checks completed with stable baselines.
- `UI-PQ-ASSET-001` passed: Deliverables and Asset Versions action, dock, asset table, search, and derivative ledger navigation were qualified.
- `UI-PQ-AUTH-001` passed: Authenticity key, direct watermark export, signed sidecar verification, forensic export, forensic inspection, and result dialogs were verified.
- `UI-PQ-MEDIA-001` passed: Media audio attachment, media player command routing, no-ffmpeg conversion boundary, managed derivative export, and derivative ledger drill-in were verified.
