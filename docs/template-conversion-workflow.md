# Template Conversion Workflow

The `File > Conversion…` workflow is the app's template-driven export system for rigid third-party registration and exchange templates.

It is designed for situations where an external organization provides a required target structure and expects the filled output to stay faithful to that structure:

- CSV column templates
- XLSX workbook templates
- repeat-node XML templates

This is especially useful for preparing upload sheets used by PRO and collection-society workflows, such as SENA-style work-registration spreadsheets, where the target layout is fixed and the exported file must match that upload sheet closely.

## What Conversion Does

Conversion is export-oriented.

It does not import rows into the catalog database. Instead it:

1. inspects a target template file
2. inspects a source file or current-profile track rows
3. suggests mappings between source fields and template targets
4. lets you correct those mappings manually
5. previews the exact rendered output plan
6. writes a new output file in the template's format

## Supported Inputs

### Target template formats

- `CSV`
- `XLSX`
- `XLSM` / `XLTX` / `XLTM` through the workbook adapter family
- `XML` with a repeat-node record model

### Source modes

- source file:
  - `CSV`
  - `XLSX`
  - `XLSM` / `XLTX` / `XLTM`
  - `XML`
  - `JSON`
- current-profile tracks:
  - flattened track-centric export rows from the current catalog profile
  - seeded from the current selection first, then filtered visible rows when a filter is active

## Preview And Mapping

The dialog is organized around four tabs:

- `Template`: detected target fields, locations, scope, and warnings
- `Source`: parsed source rows with per-row include toggles
- `Mapping`: source-field, constant-value, or unmapped choices plus explicit transforms
- `Output Preview`: the real compiled output plan that export uses

## Reusing Templates And Mappings

When a profile is open, the conversion dialog can save a reviewed template into the profile database.

That saved record can include:

- the original template file bytes
- template metadata such as filename, format, and chosen scope
- the selected source mode
- the current mapping created by the user

This is meant for recurring third-party upload sheets. For example, if you regularly prepare a SENA work-registration workbook, you can save that workbook and its reviewed mapping once, then reload both together later for a faster repeat workflow.

The dialog still supports lighter-weight mapping presets as well:

- mapping presets remain available through `QSettings`
- saved profile templates store the real template file plus an optional mapping payload

Supported transforms are intentionally small and explicit:

- `identity`
- `duration_seconds_to_hms`
- `date_to_year`
- `bool_to_yes_no`
- `comma_join`

Required unmapped targets block export. Optional and XML-unknown empty targets warn instead.

## Format Behavior

### CSV

- preserves detected delimiter and quoting dialect
- preserves header order
- replaces the contiguous sample data region below the header
- keeps trailing rows after the first blank separator break

### XLSX

- preserves the workbook and other sheets
- chooses a writable data sheet, or lets you choose when more than one sheet looks valid
- overwrites the sample rows under the header
- blanks leftover sample rows
- clones row style when more rendered rows are needed than the template already contains

### XML

- supports repeat-node templates only in this version
- preserves the surrounding tree outside the repeated record set
- clones the chosen sample node for each selected output row
- preserves the XML declaration when the template includes one

## Export Safety

- Conversion always writes a new output file.
- It does not overwrite the original template in place.
- Export runs through the same background-task and file-history pattern used by the other reviewed export workflows when a profile is open.

## Current Limits

- database-backed conversion is intentionally track-centric in this version
- XML support is intentionally limited to repeat-node templates
- JSON is source-only in this version, not a target template format
- mapping presets are stored in `QSettings`, while saved templates plus optional mappings live in the open profile database
