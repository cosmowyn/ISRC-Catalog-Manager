# Master Export Selective Preview and Compatible Import

## 1. Current master export/import behavior audited

- The master transfer flow lived in `ISRC_manager.py` and `isrc_manager/exchange/master_transfer.py`.
- The export entry point now routes through a dedicated preview step before `MasterTransferService.export_package(...)`.
- Import already used a review-first flow: inspect package, show `ImportReviewDialog`, then apply through the real import logic.
- The actual logical export/import surfaces in the current app model are:
  - `catalog`
  - `repertoire`
  - `licenses`
  - `contract_templates`

## 2. Selective export preview design implemented

- Added a dedicated `MasterTransferExportDialog` in `isrc_manager/app_dialogs.py`.
- The dialog presents the exportable sections in a checkbox table with:
  - all sections checked by default
  - section labels
  - current entity counts
  - dependency notes / requirements
- Dependency-sensitive behavior is enforced in the preview:
  - `repertoire` requires `catalog`
  - `licenses` requires `catalog`
- If `catalog` is unchecked, dependent sections are automatically disabled and excluded until the dependency is selected again.
- Export does not start if the preview is cancelled.

## 3. Manifest changes made

- Master transfer package format version was bumped to `2`.
- Added explicit `export_selection` metadata to the manifest:
  - `available_sections`
  - `included_section_ids`
  - `omitted_sections`
- `omitted_sections` in the existing top-level manifest remains for non-format/runtime artifacts that are not part of the logical transfer surface.
- Intentionally user-excluded logical sections are now tracked separately in `export_selection`, so import can distinguish omission-by-choice from corruption.

## 4. Selective package import behavior

- `inspect_package(...)` now reads `export_selection`, understands intentionally omitted sections, and previews only included/importable sections.
- `import_package(...)` now imports only sections that are actually present and declared included.
- Partial packages are treated as valid when the manifest explicitly declares omissions.
- Existing legacy packages without `export_selection` still load safely through compatibility fallbacks, and version-1 manifests are not forced to declare newer sections that did not exist when they were written.

## 5. Dependency/integrity handling

- Export-side selection validation prevents invalid combinations from being produced through the normal UI.
- Import-side manifest validation now checks that exportable sections are explicitly described as included or intentionally omitted.
- For dependency breaks in edited or unusual packages:
  - import does not misclassify the package as generic corruption
  - inspection and import both warn clearly
  - it partially imports what can still be rehydrated
  - current behavior:
    - `repertoire` without `catalog`: seed Parties, skip Works/Contracts/Rights/Assets
    - `licenses` without `catalog`: keep license files previewable, skip attachment on import

## 6. Tests added/updated

- `tests/exchange/test_master_transfer.py`
  - exportable section preview coverage
  - selective export manifest coverage
  - selective inspection coverage
  - selective import coverage
  - legacy manifest compatibility coverage
  - dependency-warning partial import coverage
  - full export/import regression coverage retained
- `tests/test_app_dialogs.py`
  - all sections checked by default
  - dependency-driven checkbox disabling in the export preview dialog
- `tests/app/_app_shell_support.py`
  - export task starts only after preview acceptance
  - export task does not start when preview is cancelled
- `tests/app/test_app_shell_editor_surfaces.py`
  - app-shell wiring for the new preview gating

## 7. Risks/caveats

- `catalog`-only selective import still creates governed Work records where that already happens through the catalog import logic. That is intentional reuse of the real importer, not a special-case behavior in master transfer.
- The manifest compatibility path for older packages is preserved, but only v2 packages explicitly declare selective omissions.
- Dependency handling is conservative and tied to the current logical import model; if new sections are added later, their dependencies need to be declared in the same selection/manifest layer.

## 8. Explicit statement

Master export now supports selective section inclusion through a user-facing preview, and master import understands partial packages correctly through manifest-driven included/omitted section metadata. This remains a logical transfer workflow using the app’s real import/export logic, not a raw database backup or restore path.
