# Contract Template Workflows

The `Contract Template Workspace` is the app's drafting surface for placeholder-driven contract and
license templates.

It is designed for users who want to keep original source files intact while filling reusable
template symbols from authoritative catalog and repertoire data.

## What the workspace does

The workspace combines three related surfaces:

- `Import`: manage templates and revisions
- `Symbol Generator`: browse available placeholder symbols and copy them into source templates
- `Fill Form`: draft against the selected revision, preview the resolved result, and export PDF

The drafting model is intentionally stable:

- the original imported source file stays unchanged
- the editable working draft is normalized to HTML
- live preview renders from that HTML working draft
- PDF export uses the same HTML working draft rather than a separate rendering path

## Supported source formats

The workspace accepts:

- Apple Pages
- DOCX
- HTML
- packaged HTML bundles such as ZIP files that contain HTML plus companion assets

### Best-practice guidance

Print-safe HTML templates provide the best fidelity and the cleanest drafting/export path.

Pages and DOCX imports are still supported, but they are normalized behind the scenes into HTML
working drafts so preview and PDF export stay consistent.

## Import behavior

### Pages

- the original `.pages` file is preserved unchanged
- the source is normalized through `Pages -> DOCX -> HTML`
- the resulting HTML becomes the working draft used for preview and export

### DOCX

- the original `.docx` file is preserved unchanged
- the source is normalized through `DOCX -> HTML`
- the resulting HTML becomes the working draft used for preview and export

### HTML

- HTML stays HTML
- HTML package assets are preserved with the working bundle

## Filling template values

The `Fill Form` workspace resolves placeholders from:

- catalog records such as tracks, releases, works, contracts, rights, and assets
- parties and owner settings
- manual fields when a value should be typed directly instead of selected from the catalog

Registry-backed entity fields stay available in the fill form. That means template drafting can resolve and, where appropriate, generate:

- track and release catalog numbers through their linked registry-aware fields
- contract numbers
- license numbers
- `Registry SHA-256 Key` values

Generation in the fill form creates the authoritative registry value immediately and links it back to the selected entity instead of inserting ad hoc text into the draft only.

The symbol catalog and generator are there so source templates can use the same canonical placeholder
syntax the fill form understands.

## Preview and export

The live preview is an HTML preview of the current editable draft state.

That means:

- the preview reflects the same working content that drives export
- placeholder replacement does not mutate the stored source template
- PDF export uses the normalized HTML working draft

For DOCX- and Pages-derived drafts, the system can still retain a compatibility DOCX artifact where
appropriate, but the actual preview/export engine is HTML-based.

## Why this matters

This workflow keeps the user-facing process familiar while solving a real backend problem:

- one working draft format
- one preview engine
- one PDF export path
- original source files preserved for traceability and re-import safety

`Registry SHA-256 Key` remains distinct from the audio authenticity subsystem. It is a code-registry value for contracts and related workflows, not a watermark key and not an authenticity signing key.

## Related docs

- [Repository README](../README.md)
- [Code Registry Workflows](code-registry-workflows.md)
- [Catalog Workspace Workflows](catalog-workspace-workflows.md)
- [Attachment Storage Modes](file_storage_modes.md)
- [Diagnostics and Recovery](diagnostics-and-recovery.md)
