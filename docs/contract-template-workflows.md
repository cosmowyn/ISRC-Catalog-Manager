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

Registry-backed placeholders are also supported, but they are handled as authoritative draft-owned auto fields rather than vague hint-text values. That means template drafting can resolve and, where appropriate, generate:

- track and release catalog numbers
- contract numbers
- license numbers
- `Registry SHA-256 Key` values

When one of those symbols is present, the fill workflow validates the required registry category and prefix first. If configuration is valid, the app can generate the authoritative value on the first saved draft when needed, link it to that document workflow, and then reuse the same value across later saves, previews, and exports for that draft lifecycle. If a required prefix is missing, generation is blocked with a clear nudge to finish configuration in `Code Registry Workspace > Categories`.

The symbol catalog and generator are there so source templates can use the same canonical placeholder
syntax the fill form understands.

## Bundled example template

The repository includes a bundled print-safe starter package at
[`HTML license template/README.md`](../HTML license template/README.md).

That example is a seven-page remix license bundle with:

- one HTML entrypoint: `License Template.html`
- one repeated banner image: `banner.png`
- one repeated footer logo: `footer-logo.png`
- canonical placeholders for owner, counterparty, track title, `manual.date`, `manual.year`, `db.contract.license_number`, and `db.contract.registry_sha256_key`

Use the `.html` file directly when the PNG assets stay beside it, or zip the bundle when you want a portable HTML package. Because the app's preferred drafting path is print-safe HTML, this bundled example is the recommended starting point for new contract and license templates.

## Legal and customization note

The bundled example is a starting point only. It is not legal advice, carries no warranty, and must not be blindly copied into production use without review. Users are responsible for adapting the wording, rights positions, jurisdictional assumptions, and commercial terms to their own needs and for obtaining qualified legal advice where appropriate.

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
