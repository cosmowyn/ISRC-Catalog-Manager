# Audio Authenticity Workflow

This guide mirrors the in-app help chapter `Audio Authenticity`.

Use `Help > Help Contents` for the integrated manual. This page is the repository-side summary of the authenticity and provenance workflow.

## What The Workflow Does

The authenticity workflow combines two linked layers:

- a compact keyed watermark embedded into supported master exports
- an Ed25519-signed manifest that carries the authenticity claim

The watermark links the file back to the catalog record. The signed manifest provides the cryptographic proof.

## Core Commands

- `Settings > Audio Authenticity Keys…`
- `Catalog > Audio > Authenticity & Provenance > Export Authentic Masters…`
- `Catalog > Audio > Authenticity & Provenance > Export Provenance Copies…`
- `Catalog > Audio > Authenticity & Provenance > Verify Audio Authenticity…`

## Direct Authentic Masters

Authentic master export is intended for WAV, FLAC, and AIFF.

The workflow:

- starts from selected catalog-backed audio
- writes a new export copy instead of modifying the stored source
- embeds the keyed watermark token
- writes standard metadata tags where trustworthy catalog values exist
- writes a sibling `.authenticity.json` sidecar

## Provenance Copies

Provenance export is intended for supported lossy delivery copies.

The workflow:

- starts from attached derivative audio
- requires a valid parent direct-authenticity record
- copies the derivative without claiming direct watermark extraction from that codec
- writes catalog metadata where appropriate
- writes a signed provenance sidecar that points back to the parent authenticity record

## Verification

Verification can inspect:

- selected catalog audio
- an external file chosen from disk

Direct verification is limited to the supported master formats. Lossy derivatives are verified by signed lineage.

## Scope

This feature is not DRM and does not present watermarking alone as proof. It is a provenance workflow built around signed manifests, supported direct-master formats, and honest verification results.
