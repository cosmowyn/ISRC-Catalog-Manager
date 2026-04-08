# Bundled HTML License Template Example Handoff

## Purpose

This pass adds the new repository-bundled HTML license template example, documents how to use it correctly inside the application, and updates the public-facing repo/wiki docs so users can discover it as the preferred starting point for print-safe contract and license generation.

## Source Of Truth Used

The source of truth for the documentation in this pass is:

- [`HTML license template/License Template.html`](../../HTML license template/License Template.html)

The HTML itself establishes the real bundle requirements:

- seven A4 pages
- one HTML entrypoint
- repeated `banner.png` header artwork on every page
- repeated `footer-logo.png` artwork in every footer
- canonical owner, party, track, manual, and registry-backed placeholders
- a native HTML preview/export path that matches the app's preferred print-safe workflow

## Files Added In The Main Repo

- [`HTML license template/README.md`](../../HTML license template/README.md)
- [`docs/implementation_handoffs/bundled-html-license-template-example.md`](./bundled-html-license-template-example.md)

The bundle assets themselves were also added to the tracked repository contents:

- `HTML license template/License Template.html`
- `HTML license template/banner.png`
- `HTML license template/footer-logo.png`

## Public-Facing Repo Docs Updated

- [`README.md`](../../README.md)
- [`docs/README.md`](../README.md)
- [`docs/contract-template-workflows.md`](../contract-template-workflows.md)
- [`docs/code-registry-workflows.md`](../code-registry-workflows.md)

## What The New Bundle README Explains

The bundle README now tells users:

- what files belong to the example bundle
- which placeholder families the example actually uses
- how to keep the HTML and companion assets together
- that the `.html` file can be imported directly when the sidecar assets stay beside it
- that zipping the folder is the right portable-package option
- that content edits belong in the HTML source
- that asset renames require updating `BANNER_SRC` and `FOOTER_LOGO_SRC`
- that `License Number` and `Registry SHA-256 Key` generation depend on configured registry prefixes
- that the first saved draft is where draft-owned registry values are generated and persisted

## Wiki Updates

The GitHub wiki was also updated so the public wiki points to the bundled example template and explains its intended use as a print-safe starter package.

## Legal Positioning Added

The public docs now state clearly that:

- the example is provided as-is
- it is not legal advice
- there is no warranty about enforceability or suitability
- users must not blindly copy it
- users are responsible for customizing it to their own facts, jurisdiction, and commercial terms
- use of the example is entirely at the user's own discretion and risk

## Notes

- This pass is documentation- and asset-focused. No application code paths changed.
- The included example currently demonstrates `db.contract.license_number` and `db.contract.registry_sha256_key` directly in the source HTML. Users who want contract numbers or catalog numbers in their own derived templates should insert those canonical symbols through the in-app `Symbol Generator`.
