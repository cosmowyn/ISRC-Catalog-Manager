# Attachment Storage Modes

This guide mirrors the in-app help chapter `File Storage Modes`.

Use `Help > Help Contents` for the integrated manual. This page summarizes how file-backed records are stored across the catalog.

## Storage Modes

The app supports two storage modes for file-backed records:

- `Database`: raw file bytes are stored directly in the profile database
- `Managed file`: the app copies the file into an app-controlled local storage folder and stores the managed path

## Covered Record Types

The storage model applies across:

- track audio
- track and release artwork
- custom binary fields
- contract and license documents
- asset versions
- GS1 workbook templates

## Operational Rules

- managed-file mode never depends on the original chosen file remaining in place
- supported records can be converted between modes without changing the surrounding preview, export, replace, or delete workflow
- stale managed files are removed only when they are no longer referenced
- legacy records remain readable even when their explicit storage metadata predates the current model

## Media Attachment

For reviewed media attachment workflows, the storage mode is chosen during the confirmation step before the write is applied. That keeps the intended target record and the intended storage behavior visible in the same decision surface.

## Related In-App Help Topics

- `File Storage Modes`
- `Bulk Audio Attach`
- `GS1 Metadata`
- `Works, Rights, and Contracts`
