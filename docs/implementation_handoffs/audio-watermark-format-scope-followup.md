# Audio Watermark Format Scope Follow-Up

## 1. Direct-Watermark Format Support After This Pass

Direct embedded watermarking now supports:

- WAV
- FLAC
- AIFF (`.aif`, `.aiff`)

These are the formats for which the current keyed STFT watermark path is used for export and in-app verification.

## 2. Why These Formats Were Added

AIFF was added because the existing stack already supports it end to end:

- `soundfile` can decode and write it in the current runtime
- the tag layer already reads and writes AIFF metadata
- the existing desktop workflow already recognizes AIFF as normal audio media

No other new direct-watermark containers were added in this pass.

## 3. Provenance / Lineage-Only Formats

The following formats remain provenance-only in this implementation:

- MP3
- OGG / OGA
- Opus
- M4A / MP4 / AAC

These formats are not reported as directly watermark-verified. Instead, the app:

- copies the derivative as-is
- writes ordinary catalog metadata tags
- writes a signed provenance sidecar
- links that sidecar back to a previously verified watermarked master

The claim is therefore:

- “signed derivative of a verified master”

not:

- “direct watermark extracted from this lossy file”

## 4. Code Changes

The scope split is implemented in:

- [`isrc_manager/authenticity/models.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity/models.py)
- [`isrc_manager/authenticity/watermark.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity/watermark.py)
- [`isrc_manager/authenticity/service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity/service.py)

Key changes:

- split suffix handling into direct-watermark, provenance-only, and verification-intake groups
- added explicit sidecar `document_type` and `workflow_kind`
- added provenance-sidecar export for derivative files
- added verification basis reporting:
  - `direct_watermark`
  - `reference_guided_direct`
  - `sidecar_guided_direct`
  - `provenance_lineage`

## 5. UI / Help / Docs Changes

The desktop workflow now distinguishes:

- direct master authenticity export
- provenance-only derivative export
- unified verification intake across both paths

User-facing changes include:

- `Catalog > Export Authenticity Watermarked Audio…`
- `Catalog > Export Authenticity Provenance Audio…`
- `Catalog > Verify Audio Authenticity…`
- both export actions in the catalog-table context menu when a track has attached audio

Docs and help were updated to keep the direct-vs-lineage boundary explicit and to state that forensic watermarking is still a future, separate workflow.

## 6. Tests Added / Updated

Coverage added or expanded for:

- AIFF direct watermark embedding and verification
- provenance-only export sidecars for lossy derivatives
- lineage verification success and signature-failure cases
- provenance export failure when no parent direct authenticity manifest exists
- catalog menu and catalog-table context-menu exposure
- broader verification picker scope
- help-content wording assertions

## 7. Remaining Limitations

- No new codec-robust watermarking was added.
- Lossy formats still do not get direct watermark extraction claims.
- Provenance records are sidecar-only in this pass; there is no new database table for derivative exports yet.
- No transcoding pipeline was added. Provenance export copies the currently attached derivative file in its existing format.

## 8. Future Path For Lossy-Robust And Forensic Watermarking

Future forensic watermarking should remain separate from the current authenticity/provenance workflow.

Recommended direction:

- add a dedicated export ledger keyed by `export_id`
- attach optional recipient identity and delivery metadata there
- use recipient-specific watermark payloads and verification/reporting separate from current authenticity manifests
- keep current `workflow_kind` values as the boundary between:
  - canonical-master authenticity
  - derivative provenance lineage
  - future forensic recipient tracing

That approach preserves the meaning of the current authenticity documents while leaving a clean integration point for future leak-tracing workflows.
