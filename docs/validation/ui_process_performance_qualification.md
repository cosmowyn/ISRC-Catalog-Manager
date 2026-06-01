# UI Process / Performance Qualification Framework

This document defines an internal engineering-grade UI qualification package for ISRC Catalog
Manager. It borrows the discipline of process/performance qualification, but it is not a claim of
regulatory certification, GMP validation, legal compliance, or external certification.

## 1. Purpose

The purpose of the UI PQ framework is to demonstrate that the complete user-exposed application is
discoverable, traceable, testable, evidence-backed, and regression-controlled. It supports internal
quality control, release readiness, workflow reliability, and follow-up engineering planning.

The framework is intentionally two-stage:

1. Document the intended full-application UI qualification plan.
2. Execute the plan through automated tests that produce inventory, evidence, traceability, and
   deviations.

## 2. Scope

The scope is the complete user-exposed UI of ISRC Catalog Manager, including every visible command,
workflow, dialog, setting, manager, generated output, and integration surface discovered in the
repository or runtime Qt object tree.

Covered UI families include:

- Startup, profile, database selection, storage migration, and first-run paths.
- Main window menus, toolbar/ribbon actions, layout controls, docks, tabs, and saved layouts.
- Catalog table operation, track and album creation/editing, media columns, custom fields, and
  catalog relationship controls.
- Work, release, party/counterparty, rights, contracts, license templates, assets, deliverables,
  code registry, GS1, SENA/BUMA/STEMRA, and repertoire workflows.
- Media player, audio attachment, waveform/cache, conversion, derivatives, authenticity,
  forensic watermarking, watermark verification, and provenance/manifest tools.
- Import/export flows, generated metadata, PDFs, packages, manifests, ledgers, logs, and reports.
- SoundCloud publishing and account/token/keyring surfaces in mocked/no-network mode only.
- Diagnostics, repair, snapshots, restore, undo/redo/history, recovery, and support/log surfaces.
- Application settings, theme builder, advanced QSS editor, help, about, and documentation browser.
- Accounting, invoicing, royalties, ledger, statements, payouts, VAT, reports, and related settings.

Any discovered UI surface must be mapped to one of these statuses:

- `automated`: executed by the UI PQ suite with evidence.
- `mocked`: executed through first-class UI controls with external network/credential boundaries
  replaced by explicit no-network mocks.
- `pending`: inventoried and traceable, but full automation remains a follow-up.
- `out_of_scope`: excluded only with documented rationale.
- `uncovered`: discovered without matrix coverage; always a deviation.

## 3. Exclusions

Exclusions are allowed only when a UI item is genuinely not user-exposed or not executable in
headless test mode. Convenience is not an acceptable exclusion.

Current exclusion policy:

- Live SoundCloud/API calls are excluded from automated execution and replaced with mocks.
- Real keyring writes, real credentials, and token persistence are excluded and replaced with mocks.
- Real user profiles and user databases are excluded; UI PQ uses temporary QA storage only.
- Destructive restore/repair operations against real data are excluded; deterministic temporary
  fixtures must be used.
- External certification, legal compliance, and regulatory validation claims are excluded.

Every other missing or incomplete item must appear in `artifacts/ui_pq/deviations.csv`.

## 4. Validation Strategy

The automated suite runs in headless Qt mode:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/ui_qa
```

The Makefile shortcut is:

```bash
make ui-pq
```

The narrower Help documentation and screenshot refresh gate is:

```bash
make help-docs
```

The `Help documentation refresh` GitHub Actions workflow runs this gate on pull requests and on
pushes to `main`. On `main`, if the current UI produces updated Help screenshots, the workflow
commits the refreshed `docs/help/screenshots` files back to the branch with a CI-skip commit.

The UI PQ suite has a suite-local pytest configuration because UI PQ coverage is measured through
runtime UI inventory and traceability, while the repository-wide pytest configuration applies a
package coverage gate that is not meaningful for this long-running qualification view.

The strategy includes:

- UI smoke validation.
- Full runtime UI inventory validation.
- Menu/action reachability and classification validation.
- Dialog and workflow inventory, with open/close automation added incrementally.
- Workflow validation through real Qt objects for major business-object creation paths.
- Data integrity validation through a temporary SQLite QA profile.
- Cross-workspace relationship validation between tracks, works, releases, parties, contracts, and
  rights created or selected through their first-class UI surfaces.
- Import/export and generated-output traceability, including deterministic generated JSON, HTML,
  CSV, and PDF comparison artifacts.
- Error/recovery traceability for diagnostics, repair, backup, snapshot, and restore paths.
- Progress/cancel traceability where background work exists.
- Authentication/token/keyring coverage through mocks only.
- SoundCloud/API coverage through the first-class publish dialog, with only the live network/API
  execution boundary replaced by a no-network mock.
- Accounting/royalty coverage through Invoice Workspace UI controls for invoice creation, line
  entry, invoice posting, payment entry, credit notes, royalty posting, statement generation,
  payout creation, report refresh, and ledger/database verification.
- Visual qualification through headless screenshot capture, nonblank-image checks, and baseline
  comparison artifacts.
- Generated-output qualification through deterministic JSON report, HTML document, CSV report, and
  PDF structural comparison artifacts.
- Help documentation qualification through runtime inventory-to-manual coverage, required
  workflow playbooks, chapter-depth checks, real UI screenshot references, and one current
  screenshot embedded in every Help chapter.
- Deviation recording for failures, missing coverage, incomplete automation, and unsupported test
  conditions.

## 5. Qualification Levels

- UI Inventory Qualification: every user-visible surface is discovered and catalogued.
- UI Reachability Qualification: every surface can be opened or triggered safely, or is recorded as
  pending.
- Functional Workflow Qualification: core workflows produce expected user-visible behaviour.
- Data Integrity Qualification: created/modified data persists correctly in the QA database.
- Relationship Qualification: links between tracks, works, releases, parties, contracts, rights,
  assets, invoices, royalty accounts, and payouts are correct.
- Output Qualification: exports, PDFs, manifests, packages, reports, and generated files are created
  and parseable.
- Error/Recovery Qualification: expected invalid states produce controlled errors and recovery
  paths.
- Performance/Responsiveness Qualification: major workflows avoid UI freezes and background tasks
  report progress truthfully.

## 6. Qualification Matrix Fields

The generated matrix in `artifacts/ui_pq/traceability_matrix.csv` records every discovered runtime
UI inventory row with:

- Inventory ID.
- UI area.
- Kind.
- UI object text/objectName.
- Test ID.
- Qualification level.
- Coverage status.
- Automation status.
- Manual follow-up status.
- Rationale.
- Evidence reference.

The source matrix in `isrc_manager/qa/traceability.py` defines, for each workflow family:

- Test ID.
- UI area.
- UI object/action/dialog identifiers.
- Preconditions.
- Test data.
- Steps.
- Expected result.
- Data objects created/modified.
- Critical dependencies.
- Evidence captured.
- Deviation criteria.
- Automation status.
- Manual follow-up status.

## 7. Required Critical End-To-End Scenario

The automated implementation covers the UI-driven backbone of the required scenario:

1. Launch application in QA mode.
2. Create/use temporary profile and SQLite database.
3. Validate startup/profile shell.
4. Create a QA track through Add Track, update it through Edit Track, and refresh the catalog UI.
5. Create/link a party.
6. Create/link a work.
7. Create/link a release and placement.
8. Create/link a contract/license-style agreement.
9. Create/link a rights record.
10. Verify track/work/release/party/contract/right relationships in the QA database.
11. Open the Royalties & Accounting workspace, create draft invoices through the invoice controls,
    add invoice lines, issue invoices, record payments, create a credit note, create and post a
    royalty calculation, generate a royalty statement, record payouts, refresh reports, capture
    screenshots at each stage, and verify database plus balanced ledger state.
12. Open the SoundCloud publish dialog, configure track/release selection, metadata, artwork, and
    private publishing options, validate the watermarked upload source, execute the no-network mock
    through the dialog Publish button, and verify progress/completion UI plus persisted run state.
13. Build the diagnostics report, run SQLite integrity, create a backup, restore that backup to an
    isolated throwaway target, and verify restored integrity.
14. Capture visual screenshots, compare baselines, verify help/about dialogs, and validate theme
    payload generation.
15. Validate the Help manual against runtime UI inventory, workflow playbooks, chapter depth, and
    screenshot-backed visual references. Refresh the checked-in Help screenshot set from the
    current UI, including one chapter screenshot per Help chapter.
16. Generate and compare deterministic report, HTML, CSV, and PDF artifacts.
17. Inventory remaining authenticity, media, and secondary surfaces.
18. Record all incomplete dialog-level automation as deviations.

The following remain pending and are intentionally recorded as deviations:

- Full media/audio fixture attachment and playback verification.
- Feature-specific contract template rendering and exported document comparison.
- Destructive diagnostics repair simulation; backup and isolated restore are automated.
- Full settings-tab edit/apply/revert coverage.

## 8. Mandatory Broad Workflow Coverage Plan

| Area | Current status | Follow-up |
| --- | --- | --- |
| Startup/profile management | Automated smoke | Add profile chooser open/close and migration prompt branches |
| Catalog table operation | Automated Add Track creation, Edit Track update, screenshot baseline, UI/database verification | Add delete/duplicate branches |
| Track and album creation | Automated single-track Add/Edit path | Automate album batch workflow |
| Work management | Automated Work Manager create/link path with screenshot baseline and database verification | Add edit/duplicate/delete branches |
| Release management | Automated Release Browser verification of UI-created release and placement | Add explicit Release Browser create/edit branches |
| Party/counterparty management | Automated Party Manager create path with screenshot baseline and database verification | Add edit/merge/delete paths |
| Contract management | Automated Contract Manager create/link path with screenshot baseline and database verification | Add edit/document tab/template rendering paths |
| License template generation | Pending | Render template output and parse generated document |
| Rights matrix/workflows | Automated Rights Matrix create/link path with screenshot baseline and database verification | Add conflict, edit, and delete paths |
| Assets/deliverables | Pending | Add asset/version/deliverable UI scenarios |
| Derivative/export ledger | Pending | Add generated derivative and ledger parse checks |
| Media player/playback UI | Pending | Add deterministic synthetic audio fixtures |
| Audio attachment | Pending | Add temp WAV/MP3 attachment through UI |
| Authenticity/watermark | Pending | Add synthetic manifests/watermarks and verification outputs |
| SoundCloud publishing | Automated first-class publish dialog execution with no-network API mock, screenshot evidence, watermarked source validation, artwork validation, progress UI, completion UI, and persisted run verification | Add broader update/link-existing-upload branches |
| Import flows | Pending | Add temp CSV/XML/XLSX import UI workflows |
| Export flows | Automated generated-output comparison harness | Add feature-specific export UI workflows |
| GS1 workflows | Pending | Add GS1 settings/dialog UI coverage |
| SENA/BUMA/STEMRA templates | Pending | Add template-specific generated-output checks where present |
| Diagnostics | Automated report, integrity, backup, isolated restore | Add destructive repair queue simulation with disposable fixtures |
| Repair flows | Pending | Add safe temporary repair branches |
| Snapshots/restore | Partial via isolated database backup restore | Add temp snapshot restore simulation |
| Undo/redo/history | Pending | Add history action reachability and state assertions |
| Theme builder/QSS editor | Automated theme payload verification | Add edit/apply/revert UI scenarios |
| Application settings | Automated visual/dialog smoke for settings/help/about area | Add each settings tab open/close and persistence checks |
| Keyring/token settings | Mocked pending | Add mock token store assertions |
| PDF/document output | Automated PDF profile and generated document comparison | Add feature-specific exported file comparisons |
| Update/release metadata | Pending | Add no-network update-surface checks |
| Help/documentation browser | Automated dialog capture plus 100% inventory/manual coverage gate and per-chapter screenshot validation | Add feature-specific screenshot mappings when new UI surfaces need more specific images |
| Logging/support surfaces | Pending | Add log/support surface reachability |
| Accounting/invoicing/royalty/ledger/payout/reporting | Automated UI-led ledger lifecycle through Invoice Workspace controls with screenshot evidence and database/ledger verification | Add branch coverage for voids, disputes, imports, and alternate VAT scenarios |

## 9. Acceptance Criteria

- No unhandled exceptions during the UI PQ harness setup.
- All expected UI controls are reachable or deviations are recorded.
- All discovered UI surfaces are inventoried.
- Every discovered UI surface has traceability status.
- All required QA data objects are created where applicable.
- Cross-links are correct for the UI-created catalog, party, work, release, contract, and rights
  records.
- Feature-specific generated-output gaps are deviations until parseability checks exist.
- Mocked integrations remain offline.
- Failed checks are written to `artifacts/ui_pq/deviations.csv`.
- Uncovered UI surfaces are written as deviations.
- Incomplete automation gaps are written as deviations.
- Help documentation must report 100% coverage in `artifacts/ui_pq/help/help_coverage.json`;
  any missing or shallow help coverage is a failing `UI-PQ-HELP-001` deviation until the help file
  is updated.
- Every Help chapter must embed a screenshot from `docs/help/screenshots/chapter_<chapter_id>.png`.
  The UI PQ suite refreshes these files from the current qualified UI screenshots before validating
  the generated Help manual.
- Evidence is generated for each executed test family.

## 10. Deviation Sheet Specification

The machine-readable deviation sheet is:

```text
artifacts/ui_pq/deviations.csv
```

Required columns:

- deviation_id
- timestamp
- test_id
- severity
- ui_area
- workflow
- ui_object
- step
- expected
- actual
- exception_type
- exception_message
- screenshot_path
- log_path
- database_path
- evidence_path
- coverage_status
- recommended_followup
- owner
- status

## 11. Evidence Specification

The UI PQ suite writes:

- `artifacts/ui_pq/summary.md`
- `artifacts/ui_pq/deviations.csv`
- `artifacts/ui_pq/evidence.json`
- `artifacts/ui_pq/ui_inventory.json`
- `artifacts/ui_pq/traceability_matrix.csv`
- `artifacts/ui_pq/visual/visual_manifest.json`
- `artifacts/ui_pq/visual/generated_output_manifest.json`

The visual manifests record screenshot capture metadata, baseline comparison results, generated
report/document comparisons, and PDF structural validation profiles.

## 12. Current Implementation Notes

The current implementation is an incremental qualification framework. It does not claim 100% UI
automation. It creates an evidence-backed backlog by producing deviations for pending, manual, or
partial areas while keeping actionable runtime failures separate from manual coverage gaps. This is
intentional: the framework should make coverage gaps visible rather than silently passing them.

The latest generated `artifacts/ui_pq/summary.md` reports zero open actionable deviations, 361
automated traceability rows, and 51 pending/manual rows out of 412 discovered rows. Catalog,
party/work/release, contract, and rights qualification now runs through first-class UI actions and
records screenshot-baseline evidence before database assertions. Remaining deviations are
pending/manual coverage items for workflow areas that still need deeper UI automation.

Primary implementation modules:

- `isrc_manager/qa/harness.py`
- `isrc_manager/qa/inventory.py`
- `isrc_manager/qa/traceability.py`
- `isrc_manager/qa/deviations.py`
- `isrc_manager/qa/evidence.py`
- `isrc_manager/qa/scenarios.py`
- `isrc_manager/qa/visual.py`
- `tests/ui_qa/`
