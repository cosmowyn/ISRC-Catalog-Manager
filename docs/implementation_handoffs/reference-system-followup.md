# Reference System Follow-Up Handoff

Current product version: `2.0.0`

Date: 2026-03-18

## Status

This handoff uses the current repository state as the source of truth.

Important: the worktree was clean when this document was prepared. The planned "finishing pass" changes did not land as code in this snapshot. This means:

- the repository still contains the earlier partial reference-modernization work
- the low-risk cleanup planned for contract links, release metadata, layout density, dock tabs, and scroll reachability is still open
- this document should be treated as the starting brief for the next implementation phase, not as a post-merge summary of completed changes

## What Was Implemented In This Pass

No repository code changes landed in this pass.

What did happen:

- the target areas were inspected
- root causes were confirmed against the real code
- the low-risk implementation plan was defined

Existing already-landed work that is present in the repository today:

- `isrc_manager/rights/dialogs.py` already uses structured editable combos for party, contract, work, track, and release references
- `isrc_manager/assets/dialogs.py` already uses editable track and release reference combos
- `isrc_manager/releases/dialogs.py` already uses editable stored-value combos for `catalog_number_edit` and `upc_edit`
- `isrc_manager/works/dialogs.py` already manages linked tracks through a table-based editor rather than raw ID text

## What Was Intentionally Deferred

These items remain intentionally deferred for the next phase because they are higher risk than the original low-risk cleanup:

- replacing `ContractEditorDialog.parties_edit` with a structured party-role editor
- replacing `ContractEditorDialog.obligations_edit` with a structured obligation editor
- surfacing `supersedes_contract_id` and `superseded_by_contract_id` in the contract UI
- territory and date-field redesigns in release and rights editors
- a broad responsive rewrite of all action-row layouts
- dock-state versioning or destructive dock-state resets

Because the planned finishing pass did not land, these lower-risk items are also still open:

- structured selectors for contract work/track/release links
- structured selectors for contract document supersedence
- release artist/label suggestion combos
- contract editor density improvements
- release browser and global search scroll reachability fixes
- work manager top action-row spacing cleanup
- explicit dock tab-position and repaint-state fixes

## Confirmed Findings

### 1. Contract relationship fields are still raw text

In `isrc_manager/contracts/dialogs.py`:

- `work_ids_edit`, `track_ids_edit`, and `release_ids_edit` are still `QLineEdit` fields
- they are populated from `detail.work_ids`, `detail.track_ids`, and `detail.release_ids`
- they serialize back through `_parse_int_list()`

Current semantics:

- users must enter comma-separated numeric IDs manually
- the dialog emits plain `list[int]` values into `ContractPayload`

### 2. Contract document supersedence is still raw text

In `isrc_manager/contracts/dialogs.py`:

- `ContractDocumentEditor.supersedes_edit` and `superseded_by_edit` are `QLineEdit`
- they serialize through `_parse_optional_int()`

Current semantics:

- users must know document IDs
- there is no selector or in-editor reference resolution

### 3. The contract editor is still dense

In `isrc_manager/contracts/dialogs.py`:

- lifecycle dates are still laid out in a fixed `QGridLayout`
- `summary_edit`, `notes_edit`, `parties_edit`, and `obligations_edit` still use relatively tall fixed minimum heights
- `ContractDocumentEditor` still uses a horizontal `QSplitter` with a non-scrollable detail pane

### 4. Release metadata modernization is still partial

In `isrc_manager/releases/dialogs.py`:

- `catalog_number_edit` and `upc_edit` already use editable stored-value combos
- `primary_artist_edit`, `album_artist_edit`, `label_edit`, and `sublabel_edit` are still plain `QLineEdit`
- `territory_edit` is still a plain `QLineEdit`, which is currently appropriate for intentional free text

### 5. Button spacing is still using the older fixed-grid pattern

In `isrc_manager/ui_common.py`:

- `_create_action_button_grid()` is the shared action-row helper
- it already provides positive spacing, but it does not provide a higher-level clustered layout pattern

In `isrc_manager/works/dialogs.py`:

- the Work Manager top "Find and Manage" actions still use a 3-column fixed grid

In `isrc_manager/releases/dialogs.py`:

- Release Browser actions still use a local `QGridLayout` instead of a reusable cluster pattern

### 6. Release Browser and Global Search still have scroll-reachability gaps

In `isrc_manager/releases/dialogs.py`:

- the right detail column is not wrapped in its own scroll area
- only the Overview tab body is scrollable
- the bottom `Release Actions` section is outside that scroll surface

In `isrc_manager/search/dialogs.py`:

- the left saved-search pane is a plain `QWidget`
- `Delete Saved Search` sits below the list in a non-scroll-safe column

### 7. Main-window dock tabs are still relying on default tab positioning and eager state saves

In `isrc_manager/main_window_shell.py`:

- there is no explicit `setTabPosition(...)` call for the workspace docks

In `isrc_manager/catalog_workspace.py`:

- `CatalogWorkspaceDock.show_panel()` calls `setVisible(True)` before tabification completes
- `visibilityChanged` triggers `_on_visibility_changed()`
- `_on_visibility_changed()` calls `app._save_main_dock_state()`

In `ISRC_manager.py`:

- `_save_main_dock_state()` is already guarded by `_suspend_dock_state_sync`
- that guard is not used by `CatalogWorkspaceDock.show_panel()` today

Net effect:

- dock state can be saved while the dock is visible but not yet fully tabified
- the underlying repaint/layout issue is still unpatched in this snapshot

## Hidden Dependencies

### Contract link persistence is full-replacement, not patch-based

`ContractService.create_contract()` and `ContractService.update_contract()` both replace:

- parties
- obligations
- work links
- track links
- release links
- documents

Relevant code:

- `isrc_manager/contracts/service.py`
- `_replace_parties()`
- `_replace_obligations()`
- `_replace_links()`
- `_replace_documents()`

Implication:

- any future structured UI must round-trip the complete current set
- if the UI drops an item during load/edit/save, the service will delete it

### Contract relationships are stored in dedicated link tables

Schema definitions in `isrc_manager/services/schema.py`:

- `ContractWorkLinks`
- `ContractTrackLinks`
- `ContractReleaseLinks`

Implication:

- the next pass should preserve `ContractPayload.work_ids`, `track_ids`, and `release_ids`
- avoid schema churn unless there is a very strong reason

### Contract document supersedence uses real foreign keys

Schema in `isrc_manager/services/schema.py`:

- `ContractDocuments.supersedes_document_id`
- `ContractDocuments.superseded_by_document_id`
- both reference `ContractDocuments(id)` with `ON DELETE SET NULL`

Implication:

- arbitrary IDs are risky
- any selector-based UI should prefer valid known documents

### New documents do not have stable IDs during a single unsaved edit session

This is the most important hidden dependency for the next risky pass.

In `ContractService._replace_documents()`:

- existing documents can be updated by `document_id`
- new documents are inserted and only receive IDs after insert
- there is no temporary-key resolution layer
- there is no post-insert remapping pass for document-to-document references

Implication:

- a structured document supersedence UI cannot safely support references between two brand-new unsaved documents without extra infrastructure
- options for the next phase:
  - support selectors only for already-persisted document records
  - add temporary client-side document keys plus a post-save remap step
  - add a two-pass save strategy for new documents

### Party text currently supports name-based creation

In `ContractService._resolve_party_id()`:

- if `party_id` is present, it is used directly
- if only `name` is present and `party_service` exists, `ensure_party_by_name()` is called

Implication:

- replacing the current `parties_edit` text DSL with strict selectors would remove a real workflow unless new-party creation remains supported

### Contract validation depends on document semantics

In `ContractService.validate_contract()`:

- active contracts should have linked parties
- active contracts should have an active `signed_agreement` marked `signed_by_all_parties`
- amendment documents are expected to declare `supersedes_document_id`

Implication:

- any next-phase document editor redesign must preserve these semantics and make them more obvious, not less

### Relationship explorer reads the same underlying contract link tables

In `isrc_manager/search/service.py`, `RelationshipExplorerService` builds relationship views from:

- `ContractWorkLinks`
- `ContractTrackLinks`
- `ContractReleaseLinks`
- `ContractDocuments`

Implication:

- next-phase reference changes must keep those tables and fields populated consistently or search/relationship surfaces will silently degrade

### Quality and other consumers already depend on the existing payload fields

Examples:

- `ContractPayload.supersedes_contract_id` and `superseded_by_contract_id` already exist in the models and schema
- `isrc_manager/quality/service.py` already carries those contract fields through quality summaries

Implication:

- if contract-to-contract supersedence is surfaced later, it should reuse the existing payload and schema fields rather than inventing a parallel representation

## Required Semantics For The Next Risky Reference-Unification Pass

The next phase should preserve these semantics unless a deliberate migration plan is approved:

1. `ContractPayload`, `ContractDocumentPayload`, and `ReleasePayload` must remain wire-compatible.
2. Work, track, and release contract links must continue to serialize as plain integer ID lists.
3. Document supersedence must continue to serialize as integer document IDs or `None`.
4. Any UI replacement for raw contract link fields must preserve the full existing set on load/save.
5. The contract party workflow must still allow linking an existing party and creating a party from a typed name.
6. Amendment documents must still be able to express "this document supersedes that document."
7. Free-text release fields that are intentionally open-ended must stay free text.
8. Suggestion-backed controls must stay editable and non-forcing.
9. Object names, dialog roles, and QSS hooks should be preserved unless an alias is added first.
10. Undo/redo and existing action payload shapes must not be broken by UI-only reference work.

Recommended practical rule:

- use structured selectors where the stored semantic is an actual foreign-key or link-table reference
- keep editable free text where the stored semantic is descriptive metadata, not a canonical entity link

## Candidate Target Fields And Surfaces For The Next Pass

### Highest-value reference targets

1. `ContractEditorDialog.work_ids_edit`
2. `ContractEditorDialog.track_ids_edit`
3. `ContractEditorDialog.release_ids_edit`
4. `ContractDocumentEditor.supersedes_edit`
5. `ContractDocumentEditor.superseded_by_edit`

These are the clearest reference surfaces still using raw IDs.

### High-risk structured-editor targets

1. `ContractEditorDialog.parties_edit`
2. `ContractEditorDialog.obligations_edit`

These should likely move to table-based or row-based structured editors, but only after the next phase explicitly preserves:

- party-name creation semantics
- party role and `is_primary`
- obligation type, dates, completion, and notes

### Supported-but-unsurfaced contract references

1. `ContractPayload.supersedes_contract_id`
2. `ContractPayload.superseded_by_contract_id`

These are already in:

- `isrc_manager/contracts/models.py`
- `isrc_manager/contracts/service.py`
- `isrc_manager/services/schema.py`

No contract UI currently exposes them.

### Secondary release-metadata follow-up targets

These are not risky reference-unification work, but they are reasonable follow-on metadata candidates:

1. `ReleaseEditorDialog.primary_artist_edit`
2. `ReleaseEditorDialog.album_artist_edit`
3. `ReleaseEditorDialog.label_edit`
4. `ReleaseEditorDialog.sublabel_edit`

They should stay editable suggestion controls, not forced references.

### Shared-widget extraction candidates

If the next phase wants one reusable reference-control system, existing patterns worth aligning:

- rights editor structured combos in `isrc_manager/rights/dialogs.py`
- asset editor structured combos in `isrc_manager/assets/dialogs.py`
- release stored-value combos in `isrc_manager/releases/dialogs.py`
- work editor track-link table in `isrc_manager/works/dialogs.py`

## Files Likely Involved

Primary files:

- `isrc_manager/contracts/dialogs.py`
- `isrc_manager/contracts/models.py`
- `isrc_manager/contracts/service.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/search/service.py`
- `isrc_manager/releases/dialogs.py`
- `isrc_manager/ui_common.py`

Likely secondary files:

- `isrc_manager/rights/dialogs.py`
- `isrc_manager/assets/dialogs.py`
- `isrc_manager/quality/service.py`
- `isrc_manager/catalog_workspace.py`
- `isrc_manager/main_window_shell.py`
- `ISRC_manager.py`

Likely tests:

- `tests/test_repertoire_dialogs.py`
- `tests/test_contract_rights_asset_services.py`
- `tests/test_app_shell_integration.py`
- `tests/test_ui_common.py`

## Blockers And Risks

### 1. New-document reference resolution

Without temporary IDs or a post-save remap layer, document-to-document selectors cannot safely support references between two newly added unsaved documents in one edit session.

### 2. Silent data loss through full replacement

Any selector UI that fails to preserve all loaded references will delete rows from the link tables on save.

### 3. Party workflow regression

If `parties_edit` becomes selector-only, the current name-based party creation workflow will break unless there is an explicit "create or resolve party" path.

### 4. Over-constraining free-text metadata

Release artist, label, sublabel, and territory should not be turned into hard foreign-key references without a product decision and a migration story.

### 5. Mixed patterns across editors

The repo already contains several reference-input patterns. A next pass that introduces a fourth or fifth pattern will increase maintenance cost instead of reducing it.

### 6. Dock/layout work can distract from the reference pass

The dock tab-visibility and scroll-reachability fixes are real, but they are orthogonal to risky reference unification. Keep them in a separate patch unless they are required to make the new selectors usable.

## Recommended Implementation Order

1. Introduce one reusable internal reference-selector primitive in `isrc_manager/ui_common.py` or a small new helper module.
2. Apply it first to the lowest-risk contract link fields:
   - works
   - tracks
   - releases
3. Add tests that prove those fields still round-trip exact ID lists through `ContractPayload`.
4. Decide how document supersedence will handle unsaved new documents before touching `ContractDocumentEditor`.
5. Only after that decision, replace the raw document ID fields with selectors.
6. Treat `parties_edit` as a separate design problem:
   - existing party lookup
   - create-by-name
   - role label
   - primary flag
7. Treat `obligations_edit` as another separate design problem:
   - row editing
   - dates
   - completion
   - notes
8. Once contract surfaces are stable, optionally align release artist/label suggestion controls to the same editable-combo conventions.

Recommended split:

- Patch 1: reusable selector helper plus contract work/track/release links
- Patch 2: document supersedence after unsaved-document strategy is chosen
- Patch 3: party and obligation structured editors
- Patch 4: optional release metadata suggestion cleanup

## Recommended Tests For The Next Phase

### Dialog tests

Extend `tests/test_repertoire_dialogs.py` to verify:

- contract link widgets are no longer raw `QLineEdit`
- document supersedence controls are selector-based if that phase lands
- free-text fields that should stay free text still do
- release artist/label controls remain editable if suggestion combos are added

### Service and round-trip tests

Extend `tests/test_contract_rights_asset_services.py` to verify:

- exact preservation of `work_ids`, `track_ids`, and `release_ids`
- duplicate and invalid IDs are normalized exactly once
- document supersedence still persists correctly
- unresolved or not-yet-resolved selector states are either safely blocked or safely preserved according to the chosen strategy
- party creation by typed name still works if the party editor is replaced

### Integration tests

Extend `tests/test_app_shell_integration.py` to verify:

- contract edits still save and reopen with the same linked references
- relationship explorer still shows linked works, tracks, releases, documents, and parties after edits
- no regressions in workspace panel activation when new selector controls are present

### Shared-widget tests

Extend `tests/test_ui_common.py` if a shared selector helper is introduced:

- editable behavior
- completer behavior
- unresolved-item display behavior
- add/remove behavior
- serialization back to integer IDs

### Regression tests that should stay green

Keep these areas green while doing next-phase work:

- schema service tests
- search and relationship explorer tests
- rights editor tests
- asset editor tests
- release service tests

## Suggested Non-Goals For The Next Reference Pass

To keep the next phase focused, avoid bundling:

- dock tab repaint fixes
- broad layout-density cleanup
- global action-row spacing refactors
- theme or QSS restyling
- persistence-format changes

Those are still worthwhile, but they should not be coupled to the risky reference-unification work unless a specific control cannot be made usable without them.
