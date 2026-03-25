# Contract Template Placeholder Workflow - Phase 6 Handoff

## Phase Goal

Land the final planned phase of the placeholder-template pivot:

- resolve editable draft payloads into immutable snapshots
- export resolved templates to PDF
- retain resolved DOCX and PDF artifacts safely
- add practical admin/archive tooling for templates, revisions, drafts, snapshots, and artifacts
- keep record deletion and file deletion explicitly separate

This phase stays placeholder-template-first. It does not reintroduce any builder-first or HTML-authoring workflow.

## What Was Implemented

### Export / Resolution

- Added `isrc_manager/contract_templates/export_service.py`
  - `ContractTemplateExportService`
  - `ContractTemplateExportError`
  - `TextutilDocxRenderAdapter`
- Export flow now:
  - loads a saved draft payload
  - resolves `db.*` placeholders against authoritative services
  - resolves `manual.*` placeholders from saved manual values
  - replaces placeholders in DOCX body/header/footer OOXML
  - creates an immutable resolved snapshot row
  - writes a managed `resolved_docx` artifact
  - renders a managed PDF artifact
  - updates `ContractTemplateDrafts.last_resolved_snapshot_id`

### Managed Artifact Storage

- Added `contract_template_artifacts` to managed storage layout in:
  - `isrc_manager/paths.py`
  - `isrc_manager/history/manager.py`
- Phase 6 artifact files are now retained under the contract-template managed roots and are covered by history snapshot/restore plumbing.

### Service / Cleanup Surface

- Extended `isrc_manager/contract_templates/service.py` with Phase 6 lifecycle helpers:
  - `duplicate_template(...)`
  - `list_template_drafts(...)`
  - `archive_draft(...)`
  - `set_draft_last_resolved_snapshot(...)`
  - `list_template_resolved_snapshots(...)`
  - `list_template_output_artifacts(...)`
  - `delete_output_artifact(...)`
  - `delete_draft(...)`
  - `delete_template(...)`
- Cleanup now explicitly removes descendant snapshot/artifact rows instead of depending on FK cascade behavior from the active SQLite connection settings.

### Workspace UI

- Extended `isrc_manager/contract_templates/dialogs.py`:
  - `TAB_ORDER` now includes `admin`
  - Fill tab now has:
    - `Export PDF`
    - `Open Latest PDF`
    - export status tracking tied to the currently loaded/selected draft
  - Added `Admin / Archive` tab with:
    - template library table
    - revision table
    - placeholder inventory table
    - draft table
    - snapshot table
    - artifact table
    - import/add-revision/duplicate/archive/delete actions
    - rescan and rebind actions
    - draft export/open/archive/delete actions
    - artifact open/delete actions
- Cleanup labels are explicit about:
  - record-only deletion
  - record + file deletion
  - managed-root-only file deletion

### App Wiring

- `ISRC_manager.py` now instantiates and injects `ContractTemplateExportService`.
- `ContractTemplateWorkspacePanel` now receives `export_service_provider`.
- Package exports were updated in:
  - `isrc_manager/contract_templates/__init__.py`
  - `isrc_manager/services/__init__.py`

## Source-of-Truth Files / Surfaces

### Runtime

- `isrc_manager/contract_templates/export_service.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/contract_templates/dialogs.py`
- `isrc_manager/contract_templates/models.py`
- `ISRC_manager.py`
- `isrc_manager/paths.py`
- `isrc_manager/history/manager.py`
- `isrc_manager/contract_templates/__init__.py`
- `isrc_manager/services/__init__.py`

### Tests

- `tests/contract_templates/test_export_service.py`
- `tests/test_contract_template_service.py`
- `tests/contract_templates/test_dialogs.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_paths.py`
- `tests/history/_support.py`
- `tests/history/test_history_snapshots.py`

## Tests Added / Updated

### Added

- `tests/contract_templates/test_export_service.py`

### Updated

- `tests/test_contract_template_service.py`
- `tests/contract_templates/_support.py`
- `tests/contract_templates/test_dialogs.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_paths.py`
- `tests/history/_support.py`

### Verification Run

Passed:

```bash
python3 -m py_compile \
  isrc_manager/contract_templates/__init__.py \
  isrc_manager/contract_templates/export_service.py \
  isrc_manager/contract_templates/dialogs.py \
  isrc_manager/services/__init__.py \
  ISRC_manager.py \
  tests/contract_templates/_support.py \
  tests/contract_templates/test_export_service.py \
  tests/contract_templates/test_dialogs.py \
  tests/test_contract_template_service.py \
  tests/app/_app_shell_support.py \
  tests/app/test_app_shell_workspace_docks.py

python3 -m unittest tests.test_paths tests.history.test_history_snapshots

python3 -m unittest tests.contract_templates.test_export_service tests.test_contract_template_service

python3 -m unittest tests.contract_templates.test_dialogs

python3 -m unittest \
  tests.test_contract_template_parser \
  tests.test_contract_template_service \
  tests.contract_templates.test_scanner \
  tests.contract_templates.test_revision_service \
  tests.contract_templates.test_catalog \
  tests.contract_templates.test_form_generation \
  tests.contract_templates.test_export_service \
  tests.contract_templates.test_dialogs

python3 -m unittest tests.app.test_app_shell_startup_core tests.app.test_app_shell_workspace_docks
```

## Deferred Items

Phase 6 completes the planned masterplan, so remaining items are post-plan refinements rather than a new required phase:

- richer DOCX run-level replacement for more styling-preserving split-token cases
- broader OOXML coverage beyond document/header/footer parts
- stronger Pages export parity beyond the current local bridge seam
- optional artifact preview/open-history affordances beyond open-file actions
- optional rename/edit metadata tooling for imported templates

## Risks / Caveats

- PDF generation currently depends on a macOS-local bridge path:
  - resolved DOCX -> `textutil` HTML conversion -> Qt PDF writer
- DOCX placeholder replacement is still conservative:
  - body/header/footer only
  - split-run placeholders with layout nodes may still fail and surface as export errors
- Admin import currently prompts for a template name at import time, but broader metadata editing is still minimal.
- Artifact cleanup is intentionally limited to files inside managed contract-template artifact roots.

## Workers Used

- `Nietzsche` - PDF/export seam inspection
- `Euler` - admin/archive cleanup inspection
- `Einstein` - landing/test strategy inspection

## Worker Closures

- `Nietzsche` closed after reconciliation
- `Euler` closed after reconciliation
- `Einstein` closed after reconciliation

## QA / QC Summary

- Central Oversight kept the pivot external-template-first and placeholder-driven.
- Export stays anchored to stored template sources, mutable drafts, immutable snapshots, and file-backed artifacts.
- The workspace remains one coherent docked surface rather than a utility pile.
- Admin actions are explicit about record-vs-file consequences and do not repurpose `ContractDocuments`.
- Managed artifact storage was added honestly to the app storage/history surfaces and verified with restore coverage.
- Cleanup behavior no longer relies on SQLite FK cascade settings at runtime.

## Exact Safe Pickup Instructions

If work resumes after this handoff:

1. Start from the current `phase1-contract-template-scaffold` branch state.
2. Read this file plus:
   - `docs/implementation_handoffs/contract-template-placeholder-masterplan.md`
   - `docs/implementation_handoffs/contract-template-placeholder-phase-5.md`
3. Treat Phase 6 as the completed end of the planned pivot sequence.
4. If doing follow-up work, keep these guardrails:
   - no builder-first regression
   - no HTML authoring surface
   - no reuse of `ContractDocuments` as the template library
   - keep record deletion and file deletion separate
5. Re-run the Phase 6 verification commands above before extending export or admin behavior.
