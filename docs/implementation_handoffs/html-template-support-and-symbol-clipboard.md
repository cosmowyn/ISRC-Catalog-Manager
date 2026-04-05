# HTML Template Support And Symbol Clipboard

Date: 2026-04-05

## Scope

This pass expanded the contract/license template workflow so HTML is now a first-class source format alongside the existing DOCX/Pages flow.

It also added native HTML draft-copy handling, true web-view preview, ZIP-packaged HTML+asset import, HTML-to-PDF export through Qt WebEngine, and double-click clipboard copy in the symbol generator.

## 1. Current Contract/License Template Workflow Audited

Before this pass:

- template import only admitted `.docx` and `.pages`
- scan/import/export dispatch was DOCX/Pages-oriented
- Pages support was conversion-based
- drafts persisted editable JSON payloads, not native rendered working files
- export always resolved through DOCX artifacts and DOCX-oriented PDF generation
- the workspace had no true HTML preview surface

Primary audited seams:

- `isrc_manager/contract_templates/ingestion.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/contract_templates/export_service.py`
- `isrc_manager/contract_templates/dialogs.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/storage_admin.py`

## 2. HTML Template Support Added

HTML is now a supported template source type.

Implemented in:

- `isrc_manager/contract_templates/ingestion.py`
- `isrc_manager/contract_templates/html_support.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/contract_templates/dialogs.py`

What changed:

- `.html` and `.htm` are accepted as template formats
- HTML source bytes are scanned directly for placeholders
- admin import/add-revision dialogs now admit `.html`, `.htm`, and `.zip`
- ZIP packages containing HTML plus assets can be imported through the same template workflow

## 3. Immutable Source Template + Draft Copy Behavior Implemented

The uploaded HTML source template now remains immutable.

Implemented behavior:

- HTML revisions are stored as managed source bundles under `contract_template_sources`
- the primary HTML file remains the authoritative source revision
- placeholder replacement does not mutate that stored source template
- drafting materializes a separate managed working-copy tree under `contract_template_drafts`
- HTML export operates from the filled draft/output path, not by rewriting the source revision

Relevant runtime surfaces:

- `isrc_manager/contract_templates/service.py`
- `isrc_manager/contract_templates/export_service.py`

## 4. Native HTML Draft Behavior Implemented

HTML templates now stay HTML during the draft stage.

Implemented behavior:

- no DOCX/Pages conversion is used for HTML drafting
- placeholder replacement happens directly in HTML text
- replacement occurs inside the draft copy, preserving the source revision
- the working copy keeps the source bundle structure so relative asset paths stay valid

Key implementation files:

- `isrc_manager/contract_templates/html_support.py`
- `isrc_manager/contract_templates/export_service.py`

## 5. HTML Preview / Web-View Path Used

HTML draft preview now uses a real web view.

Implemented behavior:

- fill-tab HTML preview uses `QWebEngineView`
- preview loads the managed draft-copy HTML file by local file URL
- CSS, images, and relative asset paths render through the real browser engine instead of a simplified text widget

Implemented in:

- `isrc_manager/contract_templates/dialogs.py`
- `isrc_manager/contract_templates/export_service.py`

## 6. ZIP Asset Package Behavior

ZIP-packaged HTML templates are now supported as an additional import path.

Implemented behavior:

- ZIP import accepts HTML plus supporting assets
- the package is normalized and persisted inside the existing template source storage model
- the primary HTML entrypoint is tracked as the revision source
- supporting files are tracked in `ContractTemplateRevisionAssets`
- storage-admin accounting now recognizes those managed asset files as live references

Implemented in:

- `isrc_manager/contract_templates/html_support.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/storage_admin.py`

## 7. HTML -> PDF Export Strategy Chosen

HTML-based export now uses Qt WebEngine PDF rendering for the highest-fidelity path available in this repo/runtime.

Chosen strategy:

- build/update a package-backed HTML draft working copy
- clone that working package into the resolved output tree
- render PDF from the resolved HTML file with `QWebEnginePage.printToPdf(...)`

Why this path was chosen:

- it preserves CSS/layout/image fidelity far better than `QTextDocument`
- it keeps preview and export on the same browser-engine rendering path
- it does not force HTML through the DOCX/Pages conversion path

Implemented in:

- `isrc_manager/contract_templates/export_service.py`

## 8. Symbol-Generator Clipboard Improvement

Double-clicking a symbol in the symbol table now copies that symbol directly to the clipboard.

Implemented in:

- `isrc_manager/contract_templates/dialogs.py`

Behavior:

- double click copies immediately
- existing selection behavior remains intact
- single-click detail/selection flow is preserved

## 9. Tests Added / Updated

Updated:

- `tests/contract_templates/_support.py`
- `tests/contract_templates/test_scanner.py`
- `tests/contract_templates/test_revision_service.py`
- `tests/contract_templates/test_export_service.py`
- `tests/contract_templates/test_dialogs.py`
- `tests/test_contract_template_service.py`

Coverage added/strengthened for:

- HTML format detection and native HTML scanning
- HTML file import
- ZIP-packaged HTML import with assets
- duplicate/rescan handling for HTML revisions
- immutable source-template plus working-copy behavior
- direct placeholder replacement in HTML draft content
- HTML export through the intended HTML PDF adapter path
- HTML preview loading through the workspace web view
- symbol-table double-click clipboard copy
- HTML draft/source cleanup lifecycle
- regression coverage for existing contract-template parser/catalog/form/export flows

Verification run:

```bash
python3 -m py_compile \
  isrc_manager/contract_templates/html_support.py \
  isrc_manager/contract_templates/export_service.py \
  tests/contract_templates/_support.py \
  tests/contract_templates/test_scanner.py \
  tests/contract_templates/test_revision_service.py \
  tests/contract_templates/test_export_service.py \
  tests/contract_templates/test_dialogs.py \
  tests/test_contract_template_service.py

python3 -m unittest \
  tests.test_contract_template_parser \
  tests.contract_templates.test_scanner \
  tests.contract_templates.test_revision_service \
  tests.contract_templates.test_catalog \
  tests.contract_templates.test_form_generation \
  tests.contract_templates.test_export_service \
  tests.contract_templates.test_dialogs \
  tests.test_contract_template_service
```

## 10. Risks / Caveats

- HTML export fidelity now depends on Qt WebEngine availability at runtime.
- PyInstaller/bundle packaging for WebEngine should be verified in the packaged app, even though the local runtime supports it.
- Plain standalone HTML import works best for self-contained HTML or local sibling assets that are intentionally bundled beside the source file. ZIP remains the safest path for portable HTML+asset templates.
- Automated tests assert structural/path behavior for HTML PDF export; they do not pixel-compare final PDF rendering.

## 11. Explicit Outcome Statement

HTML is now supported as a first-class contract/license template path without draft-stage conversion through DOCX/Pages and without mutating the stored source template.
