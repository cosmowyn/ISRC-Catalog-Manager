# GS1 Workflow Notes

## Where the feature lives

- UI dialog: `isrc_manager/gs1_dialog.py`
- Canonical models: `isrc_manager/services/gs1_models.py`
- Profile/app settings: `isrc_manager/services/gs1_settings.py`
- SQLite persistence: `isrc_manager/services/gs1_repository.py`
- Validation rules: `isrc_manager/services/gs1_validation.py`
- Workbook alias mapping and locale helpers: `isrc_manager/services/gs1_mapping.py`
- Workbook verification: `isrc_manager/services/gs1_template.py`
- Excel export transport: `isrc_manager/services/gs1_excel.py`
- Facade used by the UI: `isrc_manager/services/gs1_integration.py`

The main window only wires these pieces together and opens the dialog from the catalog context.

## Workbook verification

The app does not generate a GS1 workbook from scratch. It requires the user to choose the official workbook from their GS1 portal or regional GS1 environment.

Verification works by:

1. opening the workbook as Excel, not by trusting the filename
2. scanning sheets and candidate header rows
3. matching workbook headers to canonical GS1 field names through alias scoring
4. selecting the best target sheet by score plus sheet-name heuristics
5. requiring the core GS1 columns needed for export before a workbook is accepted

This makes the flow tolerant to header wording/order differences while still rejecting arbitrary spreadsheets.

## International header mapping

The internal schema is canonical and language-neutral. Workbook handling uses an alias layer that maps canonical fields such as:

- `gtin_request_number`
- `product_classification`
- `consumer_unit_flag`
- `target_market`
- `product_description`
- `brand`
- `quantity`
- `unit`

to workbook headers in regional variants. Dutch GS1 headers are supported as aliases, but the code is not tied to Dutch sheet names or sheet indexes.

## Batch numbering

Batch export never stores temporary request numbers in the database. The Excel exporter computes them at write time and fills the detected GTIN/code column with:

- first exported row: `1`
- second exported row: `2`
- third exported row: `3`

and so on in export order. This is the value GS1 uses to assign the next available GTINs during workbook upload.

## Template configuration

- The default template path is stored in app-level `QSettings` under `gs1/template_path`.
- Profile-specific GS1 defaults are stored in `app_kv`.
- The GS1 dialog checks the configured template on open and prompts for a replacement if the file is missing or invalid.
- The Application Settings dialog now includes a GS1 tab for the default template path plus default market/language/brand/subbrand/packaging/classification values.
