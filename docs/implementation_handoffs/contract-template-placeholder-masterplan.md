# Contract Template Placeholder Masterplan

Current product version: `2.0.0`

Date: 2026-03-24

## Status

Phase 0 is complete.

This master plan records the product pivot away from the earlier in-app builder direction and into a placeholder-driven document template workflow grounded in the live repository.

Important scope notes:

- external documents remain the layout source of truth
- this is not a free-form HTML authoring tool
- this is not a visual contract builder
- compiled remnants under `isrc_manager/document_studio/__pycache__` are not source of truth and must not drive design decisions
- no major runtime feature code landed in Phase 0; this pass is architecture, phasing, and continuity only

## Source Of Truth

This master plan was built from:

- the user prompt dated 2026-03-24
- the live repository state
- focused planning-worker findings reconciled by central oversight
- the current docked-workspace, storage, history, and contract surfaces

Primary repo surfaces:

- `ISRC_manager.py`
- `isrc_manager/catalog_workspace.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/contracts/models.py`
- `isrc_manager/contracts/service.py`
- `isrc_manager/contracts/dialogs.py`
- `isrc_manager/file_storage.py`
- `isrc_manager/history/manager.py`
- `isrc_manager/history/cleanup.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/services/gs1_settings.py`
- `isrc_manager/services/gs1_template.py`
- `isrc_manager/domain/standard_fields.py`
- `docs/catalog-workspace-workflows.md`
- `docs/file_storage_modes.md`

Relevant prior handoffs and guides:

- `docs/implementation_handoffs/backlog-unified-implementation-strategy.md`
- `docs/implementation_handoffs/storage-migration-reliability-fix.md`
- `docs/implementation_handoffs/derivative-ledger-workspace-cleanup.md`
- `docs/implementation_handoffs/catalog-workspace-ui-followup.md`

## Product Framing

### What this workspace is

This workspace is the app-owned operational layer for:

- importing contract template source documents
- scanning reserved placeholders
- generating valid placeholder symbols from known app data
- mapping placeholders to authoritative database fields or typed manual inputs
- saving editable drafts
- restoring editable drafts later
- resolving source documents into final output artifacts
- exporting finished documents to PDF
- administering template, draft, snapshot, and artifact lifecycle safely

### What this workspace is not

This workspace is not:

- a visual page builder
- an HTML-first contract authoring studio
- a free-form layout designer
- a place to invent values from filenames, surrounding text, or ambiguous related records

### How it fits the current app

The existing app is a docked catalog operations workspace. The new feature should fit that model as a sibling operational workspace beside the catalog table and existing managers, not as a standalone mini-application. The contract domain, dual storage model, history/snapshot protections, and workspace-dock shell already exist and should be extended rather than bypassed.

## Repo-Grounded Baseline

The current repository already provides the following reusable foundations:

- first-class contract records, linked parties, obligations, documents, and work/track/release links
- dual `database` versus `managed_file` storage conventions
- safe managed-file deletion and storage-mode conversion patterns
- docked workspace shells with persistent layout restore
- structured reference selectors and safe picker widgets
- history snapshots and cleanup semantics for managed roots
- template-like storage and ZIP/XML parsing precedents through the GS1 workflow

The current repository does not yet provide:

- a reusable contract-template library model
- a placeholder registry or placeholder parser
- a generic document-template ingestion service for Word or Pages
- a draft lifecycle model for editable template fills
- a resolved snapshot or output artifact ledger for this workflow

## Shared Invariants And Non-Goals

These rules should stay true through every phase:

- external document layout stays authoritative
- the app owns data injection, draft lifecycle, and export
- known database placeholders resolve through explicit registries and selectors, never string guessing
- repeated identical placeholders dedupe to one logical input field
- ambiguous multi-record relationships fail validation until the user chooses a scope or record
- raw file bytes are never expanded into placeholder values
- destructive cleanup never silently deletes managed files still referenced by the database
- template source assets, drafts, snapshots, and exported artifacts must have honest storage semantics
- no phase may drift back toward the old builder-first direction

## Proposed Domain Model

### 1. `ContractTemplate`

Purpose:

- library-facing record representing one reusable business template

Key fields:

- `id`
- `name`
- `description`
- `template_family` such as `contract`, `license`, `memo`, `other`
- `source_format` such as `docx`, `pages`, `docx_derived_from_pages`
- `active_revision_id`
- `archived`
- `created_at`
- `updated_at`

### 2. `ContractTemplateRevision`

Purpose:

- immutable template-source revision plus scan results and ingestion metadata

Key fields:

- `id`
- `template_id`
- `revision_label`
- `source_filename`
- `source_mime_type`
- `storage_mode`
- `source_blob` or `managed_file_path`
- `source_checksum_sha256`
- `scan_status`
- `scan_error`
- `derived_scan_format`
- `derived_scan_path` or `derived_scan_blob`
- `placeholder_inventory_json`
- `placeholder_count`
- `created_at`

Notes:

- this keeps the uploaded source document authoritative while still allowing derived scanable forms for Pages bridges

### 3. `TemplatePlaceholderDefinition`

Purpose:

- canonical placeholder inventory for one template revision

Key fields:

- `id`
- `template_revision_id`
- `canonical_symbol`
- `binding_kind` such as `db` or `manual`
- `namespace`
- `key`
- `display_label`
- `inferred_field_type`
- `cardinality`
- `required`
- `source_occurrence_count`
- `metadata_json`

### 4. `TemplatePlaceholderBinding`

Purpose:

- registry-backed meaning for a placeholder, separate from one specific draft value

Key fields:

- `id`
- `template_revision_id`
- `canonical_symbol`
- `resolver_kind`
- `resolver_target`
- `scope_entity_type`
- `scope_policy`
- `widget_hint`
- `validation_json`

Notes:

- for `db` symbols this points into authoritative services and field definitions
- for `manual` symbols this stores type metadata, defaults, and validation hints

### 5. `TemplateDraft`

Purpose:

- mutable editable fill session that can be reopened later

Key fields:

- `id`
- `template_revision_id`
- `name`
- `status` such as `draft`, `ready`, `archived`
- `scope_entity_type`
- `scope_entity_id`
- `storage_mode`
- `draft_payload_json` or `managed_file_path`
- `manual_values_json`
- `binding_selections_json`
- `inference_overrides_json`
- `last_resolved_snapshot_id`
- `created_at`
- `updated_at`

Notes:

- the draft index row stays in the database in all cases
- the editable payload supports `database` or `managed_file` mode to satisfy the requested managed-versus-embedded draft workflow
- managed drafts must still be app-owned files, never pointers to arbitrary external locations

### 6. `ResolvedDocumentSnapshot`

Purpose:

- immutable record of a resolved draft state used for preview/export reproducibility

Key fields:

- `id`
- `draft_id`
- `template_revision_id`
- `scope_entity_type`
- `scope_entity_id`
- `resolved_values_json`
- `resolution_warnings_json`
- `preview_payload_json`
- `resolved_source_path` or `resolved_source_blob`
- `resolved_checksum_sha256`
- `created_at`

### 7. `OutputArtifact`

Purpose:

- metadata ledger for exported deliverables

Key fields:

- `id`
- `snapshot_id`
- `artifact_type` such as `pdf`, `resolved_docx`
- `output_path`
- `output_filename`
- `mime_type`
- `size_bytes`
- `checksum_sha256`
- `retained`
- `created_at`

Notes:

- exported files stay file-backed
- the database stores metadata, references, and hashes, not PDF blobs

### 8. `StorageMode`

Use existing repo vocabulary:

- `database`
- `managed_file`

Recommended per object:

- template source revision: `database` or `managed_file`
- draft payload: `database` or `managed_file`
- resolved snapshot metadata: database
- output artifact: file-only ledger reference

### 9. Lifecycle States

Recommended initial lifecycle set:

- template: `active`, `archived`
- revision: `scan_pending`, `scan_ready`, `scan_blocked`, `archived`
- draft: `draft`, `ready`, `archived`
- snapshot: immutable
- artifact: `generated`, `failed`, `deleted_record_only`, `deleted_file_only`

### 10. Future Signing Seam

Do not implement signing in Phase 0, but keep a seam on `OutputArtifact` or a sibling table for:

- `signature_state`
- `signature_provider`
- `signature_reference`
- `signed_at`

That preserves future signing/export without coupling the current phases to unfinished signature infrastructure.

## Placeholder Grammar

### Canonical Syntax

Canonical persisted symbols should use:

- `{{db.track.track_title}}`
- `{{db.track.artist_name}}`
- `{{db.release.title}}`
- `{{db.contract.signature_date}}`
- `{{db.custom.cf_12}}`
- `{{manual.license_date}}`
- `{{manual.batch_label}}`

Structure:

- `{{ <binding_kind> "." <namespace> "." <key> }}`

### Why this grammar

- it is explicit about database-backed versus manual fields
- it avoids collision with the GS1 workflow, which already uses single-brace placeholders like `{ContractNr}`
- it is safe to parse without introducing expressions, filters, or executable logic
- it gives the symbol generator a stable canonical output format

### Parsing Rules

- only `{{...}}` tokens are reserved
- single braces remain literal text
- trim outer whitespace
- normalize `binding_kind`, `namespace`, and `key` to lowercase snake_case
- reject malformed tokens, nested placeholders, and inline formatting syntax
- dedupe by canonical tuple, not raw token text
- keep original occurrence locations separately for scan results and diagnostics

### Validation Rules

Validation happens in three seams:

- parse time: malformed syntax or unsupported token shape
- template validation time: unknown namespace/key, unsupported field type, unsupported cardinality
- draft/export time: missing manual values, unresolved selectors, ambiguous related-record scope

### Cardinality Rule

No placeholder may silently choose one record from many.

Examples:

- `db.track.*` is direct in track scope
- `db.release.*` is valid only when a release is explicitly chosen or a single unambiguous release is bound
- `db.work.*`, `db.contract.*`, `db.right.*`, `db.asset.*`, and `db.party.*` require explicit scope or selector resolution when multiple related rows exist

### Custom Field Rule

Custom fields should persist as stable IDs:

- canonical: `{{db.custom.cf_12}}`

Human labels may be shown in the generator, but storage and deduplication should use the stable custom-field ID.

## Template Ingestion Strategy

### Authoritative Source

The uploaded external document is the source-of-truth layout asset. The app may derive scanable or previewable intermediates, but those are secondary artifacts.

### Supported Source Families

#### DOCX

DOCX is the first-class ingestion target.

Why:

- the repo already has ZIP/XML parsing precedent through the GS1 template workflow
- no Word-specific Python dependency exists today
- direct OOXML scanning is realistic inside the current dependency set

DOCX strategy:

- store the original upload using the existing dual-storage pattern
- scan placeholders directly from OOXML text runs, tables, and headers/footers
- preserve occurrence inventory and scan diagnostics
- Phase 2 should start with block-safe scanning, not full document editing

#### Pages

Native `.pages` parsing is not currently a trustworthy baseline in this repo.

Phase 0 recommendation:

- accept `.pages` as a source asset only through a macOS adapter seam
- retain the original `.pages` file as a stored source revision
- derive a scanable form through a local conversion bridge when available
- preferred bridge target is DOCX so the rest of the pipeline remains format-consistent

Practical macOS facts observed during Phase 0:

- `Pages.app` is present on this machine
- `textutil` is available at `/usr/bin/textutil`
- no LibreOffice/soffice binary is present

Implication:

- the design should keep a macOS document-adapter seam for Pages conversion and PDF rendering
- the core service model must not depend on native Pages parsing logic being universally available

#### Other Formats

Only add other formats when they are operationally honest:

- `rtf`, `txt`, or `html` can later be admitted through explicit adapters
- PDF should not be treated as a placeholder-template source format

### Ingestion Output

Every imported template revision should produce:

- stored source document metadata
- scan status
- canonical placeholder inventory
- occurrence diagnostics
- optional derived scanable asset metadata

### Current Limitations To Record

Initial scanning should be explicit about what is covered:

- body text
- tables
- headers and footers

Deferred or adapter-specific areas:

- text boxes
- comments
- tracked changes
- embedded objects
- Pages-native internal structure parsing

## Dynamic Form Generation Strategy

### Form-Build Inputs

The dynamic form is generated from:

- template revision placeholder inventory
- placeholder binding registry
- current draft scope
- stored binding selections and manual values

### Database-Backed Placeholders

Known database placeholders should resolve through registry entries, not ad hoc field-name matching.

Widget strategy should reuse current repo patterns:

- reference selectors for `party`, `work`, `track`, `release`, `contract`, `document`
- editable stored-value combos where the app already uses them safely
- selection-scope banner when the workspace follows the active catalog selection

Database-backed placeholders should always use picker-driven controls or explicit scope selectors, never free text.

### Manual Placeholders

Manual placeholders should infer or declare one of:

- text
- date
- number
- boolean
- option

Recommended inference rules:

- `*_date` => date
- `is_*`, `has_*`, `*_flag`, `*_verified`, `*_signed`, `*_approved` => boolean
- `*_count`, `*_number`, `*_sequence`, `*_length_sec`, `*_percent`, `*_share` => number
- everything else => text unless manually overridden

### Dedupe Rule

One canonical placeholder becomes one logical input field.

If `{{db.track.track_title}}` appears twelve times, the form shows one control and every occurrence resolves from that one value source.

### Ambiguity Rule

If a detected placeholder name could map to multiple incompatible interpretations, the workspace must stop and require an explicit binding decision. No silent best guess.

## Draft Persistence Strategy

### Draft Storage

Drafts are editable state and must reopen exactly as last saved.

Recommended design:

- DB row always exists as the draft index and search surface
- payload storage mode can be `database` or `managed_file`
- managed draft payloads live under an app-owned managed root such as `contract_template_drafts/`
- no external absolute-path draft pointers

### Draft Payload Must Preserve

- template revision reference
- current scope entity selection
- DB binding selections
- manual input values
- manual type overrides
- validation state
- last resolved snapshot reference
- last opened/exported timestamps

### Resume Behavior

Opening a draft restores:

- the selected template revision
- the selected scope
- the generated form
- every resolved picker/manual value
- the latest saved preview state

### Snapshot Relationship

Resolve/export creates immutable snapshots; it does not overwrite the mutable draft in place.

## PDF Generation Strategy

### Authoritative Output Model

The workflow should keep the external document family authoritative through resolution:

- DOCX templates resolve to a resolved DOCX artifact
- Pages-origin templates resolve through a macOS adapter that yields a resolved document artifact compatible with later PDF export

The preview layer may use an extracted or simplified representation, but the preview is not the canonical authoring format.

### PDF Export Path

Phase 0 recommendation:

- build a document-renderer adapter seam, not a monolithic PDF service
- primary Phase 6 target is macOS-local rendering because the current environment provides Pages and text utilities but not LibreOffice

Recommended adapter chain:

1. resolve placeholders into a source-family artifact
2. hand that artifact to a local renderer adapter
3. export PDF
4. register the PDF in the artifact ledger

Expected first renderer priorities:

- DOCX via a macOS local document renderer adapter
- Pages-origin templates via a Pages-backed adapter

### Preview Strategy

Workspace preview is still useful before PDF export and can use:

- placeholder inventory preview
- resolved field preview
- simplified rendered preview snapshot

Preview exists to support editing and QA. It is not the primary authoring model.

### Export Honesty Rule

If an exact PDF renderer backend is unavailable, the UI must say so plainly and never imply that deleting or exporting did more than it actually did.

## Workspace Structure

### Top-Level Placement

Create a new docked workspace panel, not a modal utility and not an extension of the theme builder.

Recommended panel title:

- `Contract Template Workspace`

Recommended opening path:

- new workspace action wired through the existing dock shell and `_show_workspace_panel(...)`

### Internal Information Architecture

Use one coherent workspace with four top-level tabs:

- `Templates`
- `Symbol Generator`
- `Drafts`
- `Admin / Archive`

#### `Templates`

Recommended layout:

- left: template library table
- right: selected template workspace with tabs:
  - `Overview`
  - `Placeholders`
  - `Preview`
  - `Admin`

#### `Symbol Generator`

Purpose:

- generate valid database-backed symbols from known app fields
- show label, canonical symbol, entity scope, and notes
- provide copy actions and category browsing

#### `Drafts`

Purpose:

- browse saved drafts
- show storage mode, template revision, scope, updated time, ready/export status
- resume editing
- duplicate, archive, or delete drafts safely

#### `Admin / Archive`

Purpose:

- archive and restore templates
- inspect stale snapshots/artifacts
- convert storage mode
- rebuild previews
- clean up retained files with explicit semantics

## Admin Tools

At minimum, the workspace must provide:

- import template
- replace template source
- inspect detected placeholders
- re-scan template
- duplicate template
- archive template
- delete template safely
- browse drafts
- resume draft
- duplicate draft
- archive draft
- delete draft safely
- rebuild preview or resolved snapshot
- export stored source
- convert storage mode
- clean up retained generated files separately from deleting database rows

### Safe Deletion Rules

- deleting a DB row does not imply deleting stored files
- deleting retained/generated files is a separate action
- managed files are only unlinked after reference checks pass
- in-use templates default to archive, not hard delete
- draft and artifact cleanup must disclose whether the action removes:
  - database metadata only
  - retained files only
  - both, after explicit confirmation

## Phase Map

### Phase 0 - Master Strategy / Pivot Architecture

Goal:

- define the placeholder-template architecture and protect the pivot from builder drift

Dependencies:

- none

Acceptance boundary:

- master plan written
- Phase 0 handoff written
- future phase handoff paths defined
- planning-worker findings reconciled

Deferred items:

- all runtime feature code

Handoff path:

- `docs/implementation_handoffs/contract-template-placeholder-phase-0.md`

### Phase 1 - Placeholder Grammar + Core Domain Model + Storage Scaffold

Goal:

- add parser, registry, schema, services, and storage scaffolding

Dependencies:

- Phase 0

Acceptance boundary:

- parser exists
- canonical placeholder inventory model exists
- template, revision, draft, snapshot, and artifact schema exists
- storage-mode behavior is defined in code and tests

Deferred items:

- real document ingestion
- real UI
- PDF export

Handoff path:

- `docs/implementation_handoffs/contract-template-placeholder-phase-1.md`

### Phase 2 - Template Ingestion + Placeholder Scan Pipeline

Goal:

- import template source documents, scan placeholders, and persist placeholder inventory

Dependencies:

- Phase 1

Acceptance boundary:

- DOCX direct ingestion works
- placeholder scan pipeline persists canonical inventory
- Pages adapter seam exists and is explicitly classified as supported, bridged, or blocked
- template revisions can be re-scanned

Deferred items:

- symbol generator UI
- fill form UI
- draft editing workflow

Handoff path:

- `docs/implementation_handoffs/contract-template-placeholder-phase-2.md`

### Phase 3 - Symbol Generator Workspace + Mapping Dictionary

Goal:

- create the symbol generator and curated mapping dictionary for known app data

Dependencies:

- Phase 1
- Phase 2 scan model

Acceptance boundary:

- user can browse canonical symbols from known DB fields
- copy-ready generator UI exists
- custom-field canonical behavior is defined

Deferred items:

- dynamic fill form
- draft persistence UI
- PDF export

Handoff path:

- `docs/implementation_handoffs/contract-template-placeholder-phase-3.md`

### Phase 4 - Dynamic Fill Form Generation + Smart Type Logic

Goal:

- build generated fill forms from detected placeholders

Dependencies:

- Phase 1
- Phase 2
- Phase 3 registry

Acceptance boundary:

- DB-backed placeholders use safe selectors
- manual placeholders infer typed controls
- repeated placeholders dedupe correctly
- ambiguous bindings are blocked and surfaced clearly

Deferred items:

- draft reopen lifecycle
- final artifact export

Handoff path:

- `docs/implementation_handoffs/contract-template-placeholder-phase-4.md`

### Phase 5 - Draft Editing / Resume / Managed-vs-Embedded Storage

Goal:

- save drafts, reopen drafts, and preserve editable state across storage modes

Dependencies:

- Phase 4

Acceptance boundary:

- draft can be stored in `database` or `managed_file` mode
- reopening restores the editable state
- immutable resolved snapshots are separated from mutable drafts

Deferred items:

- final PDF artifact tooling
- full admin cleanup tooling

Handoff path:

- `docs/implementation_handoffs/contract-template-placeholder-phase-5.md`

### Phase 6 - PDF Export + Admin Workspace Tools

Goal:

- generate PDF exports and land operational admin tooling

Dependencies:

- Phase 5

Acceptance boundary:

- resolved source artifact generation works
- at least one supported PDF renderer path is operational for the supported template family
- template/draft/archive/admin cleanup tooling exists
- cleanup semantics are explicit and tested

Deferred items:

- future signing integration
- package/export exchange integration

Handoff path:

- `docs/implementation_handoffs/contract-template-placeholder-phase-6.md`

## Dependencies And Ordering Constraints

- Phase 1 must land before any ingestion or UI work so the parser and schema do not drift
- Phase 2 must land before Phase 4 so the form generator consumes real scan results, not synthetic placeholder lists
- Phase 3 should precede or overlap Phase 4 because the generator and the resolver registry define the canonical symbol catalog
- Phase 5 depends on Phase 4 because drafts must restore a real generated form, not just raw JSON
- Phase 6 depends on Phase 5 because PDF exports must come from stable resolved snapshots and honest artifact ledgers

## QA/QC Baseline

Must remain true throughout implementation:

- no builder-first UI surfaces are introduced
- `ContractDocuments` is not repurposed as the template library
- dual storage semantics remain aligned with `database` and `managed_file`
- managed directories introduced by this workflow are registered for migration/history coverage
- workspace layout persistence remains intact
- deletion semantics remain explicit

Recommended test shape by feature area:

- parser and schema unit tests
- service tests modeled after contract, GS1, and storage tests
- dialog/workspace tests modeled after existing catalog workspace and contract dialog tests
- history/storage tests for managed roots and cleanup semantics

## Important Continuation Notes

- do not rely on `isrc_manager/document_studio/__pycache__`; it is compiled residue, not live source
- do not use the theme builder or generic HTML authoring as the primary template model
- keep DOCX as the first-class scan target unless a Pages adapter is proven reliable in code and tests
- if a new managed directory is added, include it in storage layout and history-managed-directory handling
- keep destructive file cleanup separate from row deletion
- treat the GS1 workflow as a storage/parsing precedent only, not as the template architecture itself

## Related Handoffs

- `docs/implementation_handoffs/contract-template-placeholder-phase-0.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-1.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-2.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-3.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-4.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-5.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-6.md`
