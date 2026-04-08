# HTML License Template Example

This folder contains a print-safe HTML starter bundle for the app's `Contract Template Workspace`.

It is a seven-page remix license example built as a native HTML working draft, with a shared banner image, a shared footer logo, and canonical placeholder symbols that the application can resolve during fill-form drafting and PDF export.

## Included Files

- `License Template.html`: the primary UTF-8 HTML template entrypoint
- `banner.png`: the repeated top banner used on every page
- `footer-logo.png`: the repeated footer logo used on every page

## What This Example Demonstrates

- a print-safe A4 HTML contract/license layout
- repeated page header and footer assets loaded from local companion files
- owner, party, track, and manual placeholders in canonical `{{...}}` syntax
- registry-backed draft generation for:
  - `{{db.contract.license_number}}`
  - `{{db.contract.registry_sha256_key}}`

## Placeholder Families Used By This Example

- `Owner`: `db.owner.artist_name`, `db.owner.bank_account_number`, `db.owner.chamber_of_commerce_number`, `db.owner.city`, `db.owner.company_name`, `db.owner.country`, `db.owner.display_name`, `db.owner.email`, `db.owner.legal_name`, `db.owner.phone`, `db.owner.postal_code`, `db.owner.street_name`, `db.owner.street_number`, `db.owner.vat_number`
- `Counterparty / Licensee`: `db.party.artist_name`, `db.party.bank_account_number`, `db.party.chamber_of_commerce_number`, `db.party.city`, `db.party.country`, `db.party.display_name`, `db.party.email`, `db.party.legal_name`, `db.party.phone`, `db.party.postal_code`, `db.party.street_name`, `db.party.street_number`, `db.party.vat_number`
- `Track`: `db.track.track_title`
- `Manual`: `manual.date`, `manual.year`
- `Registry-backed`: `db.contract.license_number`, `db.contract.registry_sha256_key`

## How To Create A Valid HTML Template For This App

1. Start by duplicating this folder so you keep the bundled example untouched.
2. Keep the HTML file and its companion assets together. The app can import the `.html` directly when `banner.png` and `footer-logo.png` sit beside it, or you can zip the folder and import it as an HTML package when you want a portable bundle.
3. Edit the contract text directly inside `License Template.html`. If you rename the asset files, update `BANNER_SRC` and `FOOTER_LOGO_SRC` near the bottom of the HTML so the page header and footer still resolve correctly.
4. Keep placeholders in canonical `{{...}}` form. If you want to extend the example with contract numbers or catalog numbers, copy the canonical symbols from the in-app `Symbol Generator` instead of inventing custom token names.
5. Import the template through `Contract Template Workspace > Import`.
6. In `Fill Form`, supply the normal record selections required by the placeholders in the template, enter `Date` and `Year`, and make sure the `License Number` and `Registry SHA-256 Key` categories have valid prefixes configured in `Code Registry Workspace > Categories`.
7. Save the first draft. That first saved draft is where the app can authoritatively generate and link the license number and registry SHA-256 key for this document lifecycle.
8. Use live preview and PDF export from the same working draft. Later saves, previews, and exports reuse the same generated registry-backed values for that draft instead of minting duplicates.

## Preferred Starting Point

This bundle is a preferred starting point for print-safe contract and license generation in the application because it stays on the app's native HTML workflow from import through preview and PDF export.

## Legal Notice

This example is provided as-is, without any warranty, and is not legal advice. The repository owner is not responsible for the content, enforceability, fitness, or consequences of using this template. Do not blindly copy it. Review every clause, adapt it to your own facts and jurisdiction, and seek qualified legal advice where appropriate. Any use of this example is entirely at your own discretion and risk.
