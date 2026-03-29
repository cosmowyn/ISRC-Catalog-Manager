# Master Catalog Transfer Export / Import

## 1. Existing export/import building blocks audited

The master transfer implementation reuses the app's real logical import/export surfaces instead of copying the SQLite database.

- Catalog:
  - Reused `isrc_manager.exchange.service.ExchangeService.export_package()`
  - Reused `ExchangeService.inspect_package()` for inspection preview
  - Reused `ExchangeService.import_package()` for governed catalog rehydration
- Contracts and Rights / repertoire:
  - Reused `isrc_manager.exchange.repertoire_service.RepertoireExchangeService.export_package()`
  - Reused `RepertoireExchangeService.inspect_package()` for non-mutating inspection preview
  - Reused `RepertoireExchangeService.import_package()` in staged `parties_only` then `remaining` phases
- Licenses:
  - Reused `isrc_manager.services.licenses.LicenseService.fetch_license_bytes()` for logical export
  - Reused `LicenseService.add_license()` for logical import
- Contract templates:
  - Reused `ContractTemplateService.load_revision_source_bytes()` for logical export
  - Reused `ContractTemplateService.create_template()` and `ContractTemplateService.import_revision_from_bytes()` for logical import
- UI/task lifecycle:
  - Reused background bundle tasks, `run_file_history_action`, `run_snapshot_history_action`, and `ImportReviewDialog`

## 2. Master package structure chosen

The package is a single ZIP with a root manifest and section payloads under `sections/`.

```text
master-transfer.zip
├── manifest.json
└── sections/
    ├── catalog/
    │   └── package.zip
    ├── repertoire/
    │   └── package.zip
    ├── licenses/
    │   ├── licenses.json
    │   └── files/...
    └── contract_templates/
        ├── templates.json
        └── files/...
```

Design choice:

- Catalog and repertoire stay in their existing section-level package formats and are nested unchanged.
- Licenses and contract templates now have dedicated logical section payloads inside the master package because they did not already have reusable exchange-package surfaces.
- The top-level manifest is summary/dispatch metadata, not a duplicate copy of all inner section rows.

## 3. Manifest/version strategy

The master package writes a root `manifest.json` with:

- `document_type = "master_transfer_package"`
- `package_format = "logical_catalog_transfer"`
- `package_format_version = 1`
- `app_name`
- `app_version`
- `exported_at` in UTC
- `compatibility` policies for future readers
- `import_guidance` with the staged logical rehydration order
- `sections` with per-section metadata
- `files` with relative path, size, and SHA-256
- `omitted_sections` for known non-covered areas

Compatibility rules:

- Older or same manifest versions are accepted.
- Newer manifest versions fail explicitly.
- Unknown optional sections warn and skip.
- Unknown required sections fail before import.

## 4. Master export behavior

User-facing entry point:

- `File -> Export -> Master Catalog Transfer -> Export Master Transfer ZIP…`

Runtime behavior:

1. Export catalog through `ExchangeService.export_package()`
2. Export repertoire through `RepertoireExchangeService.export_package()`
3. Export licenses into `licenses.json` plus packaged PDF files
4. Export contract templates into `templates.json` plus packaged revision source files
5. Write the top-level manifest with checksums and staged import guidance
6. Package everything into one ZIP

Progress behavior:

- Runs as a managed background read task
- Reports real staged progress
- Only reaches `100%` after the final ZIP is written

## 5. Master import behavior

User-facing entry point:

- `File -> Import & Exchange -> Master Catalog Transfer -> Import Master Transfer ZIP…`

Inspection / preview flow:

1. Open ZIP
2. Safe-extract into a temp workspace
3. Validate root manifest and file checksums
4. Inspect catalog section through the real catalog inspector
5. Run a real catalog dry-run through `ExchangeService.import_package(..., mode="dry_run")`
6. Inspect repertoire section through the real repertoire inspector
7. Read license/template section payloads for preview rows
8. Show `ImportReviewDialog` before any write occurs

Apply flow:

1. Repertoire `parties_only` phase to seed Party ids
2. Catalog package import through the real governed catalog import logic
3. License section import through `LicenseService.add_license()`
4. Repertoire `remaining` phase with remapped Party/Track/Release ids
5. Contract template import through `create_template()` plus `import_revision_from_bytes()`

Failure behavior:

- Manifest/file validation failures stop before writes
- Catalog failures stop the master import explicitly
- Missing packaged files, unsafe paths, unresolved remaps, and checksum mismatches raise visible errors
- No raw database replacement occurs

## 6. How current import logic is reused

This implementation intentionally replays logical data through current services:

- Catalog rows go through governed track/work import and release upserts
- Repertoire entities go through repertoire import phases and domain services
- Licenses are reattached through the license service, not by copying stored blobs directly into tables
- Contract templates are recreated through the template service's current revision-import path, so current scanning and revision rules apply

This is explicitly a logical migration path, not a raw database clone.

## 7. Relationship / integrity considerations handled

Relationship-safe rehydration is handled in two places.

Cross-section remapping:

- Catalog import now returns source-to-target Track and Release ids
- Repertoire import now accepts seeded Party/Track/Release maps
- Master import stages use those maps so works/contracts/rights/assets rebind to the newly imported entities

Section-level lineage preservation:

- Repertoire import now preserves contract supersession links
- Repertoire import now preserves asset `derived_from_asset_id` lineage
- Repertoire export now avoids packaged-file name collisions by using deterministic id-prefixed archive members
- Repertoire export now fails loudly if a contract document or asset cannot actually be packaged
- Repertoire `remaining` phase reuses an existing governed work linked to the imported track when it matches the exported work identity, preventing duplicate work creation during master import

Known intentional omissions in format v1:

- History snapshots
- Authenticity / forensic / derivative runtime ledgers
- Contract template drafts, resolved snapshots, and output artifacts
- Work / recording ownership interests

These omissions are called out in the manifest and surfaced as warnings where applicable.

## 8. Tests added / updated

Added:

- `tests/exchange/test_master_transfer.py`
  - master export writes one ZIP with manifest and section payloads
  - inspection previews contents without writing
  - round-trip import rehydrates catalog/repertoire/licenses/templates through real logic
  - contract supersession and asset derivation survive remapping
  - checksum mismatch fails visibly
  - export/import progress reaches truthful completion

Updated:

- `tests/app/_app_shell_support.py`
  - menu snapshots now include Master Catalog Transfer import/export menus
  - master export uses a background task
  - master import requires review before apply
- `tests/app/test_app_shell_editor_surfaces.py`
  - exposed the new app-shell master transfer tests
- `tests/ci_groups.py`
  - grouped the new master transfer suite into the exchange-import shard

Focused verification run:

- `python3 -m unittest tests.exchange.test_master_transfer tests.exchange.test_exchange_package tests.exchange.test_repertoire_exchange_service`
- `python3 -m unittest tests.test_background_app_services tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_master_transfer_export_uses_background_task tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_master_transfer_import_requires_review_before_apply tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_file_menu_groups_xml_import_under_import_exchange_and_preserves_wiring tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_file_menu_groups_exchange_exports_and_saved_import_reset`

## 9. Risks / caveats

- Repertoire preview is still inspection-based, not a true dry-run apply simulation like catalog.
- Ownership interests are not yet represented by a dedicated logical transfer section.
- Contract template runtime artifacts are intentionally omitted because the authoritative library is the template + revision source set, not derived workspace state.
- Importing into a non-empty profile is supported technically but intentionally warned against because the feature is designed as a logical migration path into a clean or migration profile.

## 10. Explicit non-DB-clone statement

This feature is a logical transfer path, not a raw database clone.

- It does not export the SQLite database as the primary artifact.
- It does not restore by replacing the database file.
- It re-imports logical data through the app's current service logic and current version rules.
