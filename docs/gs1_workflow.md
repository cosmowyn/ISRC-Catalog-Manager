# GS1 Workflow Guide

This guide mirrors the in-app help chapter `GS1 Metadata`.

Use `Help > Help Contents` for the integrated manual. This page summarizes the repository-side GS1 workflow.

## What The GS1 Workflow Covers

The GS1 workflow connects catalog data to a validated workbook export process.

- launch GS1 editing from a single track or a selected batch
- group release-related selections into product rows where appropriate
- validate the workbook structure before export
- keep the configured workbook template in database or managed-file storage
- save profile-specific GS1 defaults for recurring exports

## Why Workbook Validation Matters

The export depends on a structured spreadsheet format, so the app verifies workbook structure rather than trusting the filename alone. That keeps workbook drift and template mistakes from silently producing bad output.

## Related In-App Help Topics

- `GS1 Metadata`
- `File Storage Modes`
- `Application Settings`
