# GS1 Workflow Guide

The GS1 workflow in ISRC Catalog Manager is designed for teams who need to prepare structured product data without losing the convenience of a local catalog workflow.

It helps you move from catalog metadata to official workbook export with fewer manual steps, fewer broken templates, and less dependency on external spreadsheets.

## What The GS1 Workflow Is Meant To Solve

GS1 data often lives in a fragile in-between state:

- product information exists in the catalog
- regional GS1 workbook templates change over time
- teams duplicate spreadsheet work manually
- workbook paths break when files are moved or renamed

The GS1 tools in this application solve that by treating GS1 preparation as part of catalog maintenance, not as a disconnected export chore.

## How It Works

### 1. Maintain GS1 metadata in the catalog

You can open GS1 metadata for:

- a single track
- a selected group of tracks
- grouped release selections that should become one product-level export row

The editor stores GS1 values in the profile database so the information stays with the catalog rather than living only in ad hoc spreadsheets.

### 2. Keep an official workbook on file

The app does not invent a GS1 workbook format. Instead, it works with the official workbook supplied by your GS1 environment or regional portal.

That workbook is:

- uploaded once into the app settings workflow
- stored either in the profile database or as a managed local file
- available for export later even if the original source file is moved or removed
- convertible later if your profile should switch storage mode

This removes a common failure point in spreadsheet-based GS1 workflows.

### 3. Verify workbook structure before export

Before a workbook is accepted, the app validates it by:

- opening it as a real Excel workbook
- scanning candidate sheets and header rows
- matching workbook headers against canonical GS1 fields
- applying alias and language-aware mapping
- selecting the best-fit export target sheet
- rejecting incomplete or unrelated spreadsheets

This means the workflow is tolerant to reasonable workbook variation, while still protecting the user from exporting into the wrong file.

### 4. Export from the catalog into the workbook

When you export, the app writes the current product data into the validated template and assigns batch request numbers in export order. Temporary request numbering is generated during export time rather than stored permanently in the database.

## What The Editor Covers

The GS1 editor is designed to keep the workflow clear and grouped. It covers areas such as:

- product identity
- brand and subbrand
- target market and packaging context
- language and commercial details
- consumer-unit state
- export readiness
- grouped product rows for release-based selections

The interface is tabbed so large GS1 datasets stay readable instead of becoming one long vertical form.

## Why The Workbook Is Verified Instead Of Trusted By Name

Simply choosing a file path is not enough for an export workflow that depends on a structured official spreadsheet.

The app validates the workbook by structure rather than filename so it can safely handle:

- renamed templates
- region-specific header wording
- workbook layouts that move fields around
- multiple likely tabs within one workbook

This makes the flow more reliable for real-world GS1 use.

## International Header Mapping

Internally, the GS1 layer uses canonical field names. Workbook export then maps those canonical fields onto the real workbook headers using an alias system.

This helps the app stay:

- language-aware
- template-tolerant
- easier to maintain across different GS1 workbook variants

The result is a workflow that is grounded in your catalog data rather than hard-coded to one spreadsheet shape.

## Profile-Based Defaults

The GS1 workflow also supports profile-specific defaults for values such as:

- target market
- language
- brand
- subbrand
- packaging type
- classification

That means repeated product exports can start from sensible defaults instead of requiring the same values to be typed over and over again.

## Why This Matters Operationally

For many small labels and independent catalog owners, GS1 preparation becomes a recurring administrative burden. By keeping the data inside the application:

- product metadata stays connected to the catalog
- workbook integrity is checked before export
- templates stay available inside the profile in either database or managed-file storage
- batch exports become more repeatable
- errors caused by spreadsheet drift become much less likely

In short, the GS1 workflow turns a fragile external spreadsheet step into a controlled part of catalog management.
