# Forensic Watermarking Lossy Follow-Up

## 1. How Forensic Watermarking Differs From Authenticity Watermarking

Authenticity watermarking remains the canonical/master workflow:
- lossless/authenticity-safe formats only
- tied to Ed25519-signed authenticity manifests
- verified through the authenticity verification path

Forensic watermarking remains separate:
- recipient-/export-specific leak tracing
- layered on top of managed derivative export and the forensic export ledger
- not a signed-master authenticity claim
- not DRM
- not a claim of perfect adversarial resistance

This pass keeps those semantics separate and only expands the forensic branch.

## 2. Why This Pass Targets Lossy Delivery Formats

The earlier forensic pass only exposed lossless targets because the first implementation reused the PCM-oriented watermark path directly.

That was not sufficient for the product goal of leak-traceable shared delivery copies.

This follow-up moves forensic export onto a lossy delivery scope:
- MP3 is now a real managed forensic export target
- authenticity masters stay on WAV / FLAC / AIFF
- provenance-only authenticity exports remain separate from forensic exports

## 3. How MP3 Forensic Export Was Implemented

The central managed forensic coordinator remains `ForensicExportCoordinator`.

The export flow for MP3 is now:
1. resolve managed catalog source
2. transcode to MP3 delivery format
3. write catalog metadata to the MP3
4. apply forensic watermark through a lossy-finalization branch
5. hash the final completed MP3
6. write/update derivative ledger
7. write/update forensic export ledger
8. finalize filename with hash suffix
9. ZIP if bulk

The lossy-finalization branch is handled by `ForensicWatermarkService.embed_export_path(...)`.

For MP3 it currently:
- decodes the tagged intermediate MP3 to a temporary WAV analysis source
- embeds the forensic watermark in PCM
- re-encodes the result back to MP3
- lets the coordinator rewrite the catalog tags onto the final MP3 before hashing

That keeps MP3 export real without changing the authenticity master path.

## 4. Additional Lossy Formats Supported

This pass intentionally enables:
- `MP3`

Other lossy forensic targets are still withheld for now.

Reason:
- the runtime conversion/tagging stack can write additional lossy formats
- but this pass only validates MP3 end-to-end for honest managed forensic export and inspection semantics

The architecture leaves room for adding OGG/OGA, Opus, or M4A later once their forensic export and inspection behavior is validated honestly.

## 5. Export-Ledger Model

No schema change was required in this pass.

The existing `ForensicWatermarkExports` table already records:
- `forensic_export_id`
- `batch_id`
- `derivative_export_id`
- `track_id`
- `key_id`
- `token_version`
- `forensic_watermark_version`
- `token_id`
- `binding_crc32`
- `recipient_label`
- `share_label`
- `output_format`
- `output_filename`
- `output_sha256`
- `output_size_bytes`
- `source_lineage_ref`
- `created_at`
- `last_verified_at`
- `last_verification_status`
- `last_verification_confidence`

That means MP3 forensic exports are still:
- tied to derivative lineage
- tied to a forensic export id
- traceable back to batch, source track, labels, and final hash
- stored as references only, never as DB audio blobs

## 6. Payload / Token Design

The existing compact forensic token was retained.

Current payload shape:
- version: 1 byte
- token id: 48-bit integer
- binding CRC32: 4 bytes
- payload CRC32: 4 bytes

`binding_crc32` still binds the exported copy to:
- batch id
- track id
- output format
- recipient label
- share label

The richer mapping remains in the ledger.

## 7. Detection / Resolution Workflow

Inspection stays in `ForensicExportCoordinator.inspect_file(...)`.

For lossy forensic inspection the workflow is:
1. choose suspicious file
2. normalize it to an analysis WAV when the file is not on the direct PCM/lossless path
3. attempt blind forensic token extraction
4. if unresolved, check exact output SHA-256 against the forensic ledger
5. if still unresolved, rebuild an unwatermarked reference from the current catalog source and the stored output format, normalize that reference to the same analysis format, and run reference-guided comparison

Result states remain:
- `forensic_match_found`
- `forensic_match_low_confidence`
- `forensic_watermark_not_detected`
- `unsupported_format_or_insufficient_confidence`
- `token_found_but_unresolved`

Important honesty boundary:
- exact-file matches are currently the strongest MP3 forensic resolution path
- blind extraction remains conservative
- reference-guided comparison is available, but this pass does not claim strong resistance to severe re-encoding or hostile edits

## 8. UI / Workflow Changes

The forensic workflow remains distinct in:
- Catalog menu
- catalog context menu
- ribbon/action registry
- forensic export dialog
- forensic inspection dialog

Updated product messaging now explicitly frames forensic export as:
- recipient-specific
- lossy delivery oriented
- leak tracing
- separate from signed authenticity masters

Managed derivative export copy also now clarifies that its lossy branch does **not** apply recipient-specific forensic watermarking.

## 9. Runtime Capability Gating

Managed forensic targets are no longer just a static format list.

`AudioConversionService` now probes forensic targets through the same kind of transcode-and-tag usability check already used for managed lossy derivatives.

A forensic target is only offered when the runtime can:
- encode it
- reopen it
- write/read metadata successfully

In this pass, that exposed target set is intentionally narrowed to:
- `MP3`

If MP3 cannot be produced honestly in the local runtime, it stays unavailable.

## 10. Tests Added / Updated

Updated coverage now includes:
- single managed MP3 forensic export
- bulk managed MP3 forensic export
- MP3 derivative/export ledger linkage
- final hash taken from the completed watermarked MP3
- exact-hash resolution of a known exported MP3
- low-confidence reference-guided MP3 inspection path
- clean MP3 no-match path
- unsupported decode-failure path
- capability-gating failure when MP3 forensic export is unavailable
- tighter forensic schema assertions for the existing ledger table

Files updated for tests:
- `tests/test_forensic_watermark_service.py`
- `tests/app/_app_shell_support.py`
- `tests/database/_schema_support.py`

## 11. Current Robustness Limits

These limits remain explicit:
- this is not DRM
- this is not perfect leak attribution
- this does not claim immunity to deliberate stripping or severe recompression
- MP3 forensic inspection is currently strongest for exact-file matches and conservative reference-guided comparison
- this pass does not yet expose additional lossy forensic targets beyond MP3
- authenticity verification semantics remain separate and stronger for signed lossless masters

## 12. Future Roadmap For Stronger Lossy Forensic Support

Recommended next steps:
- add a forensic-versioned lossy-specific DSP profile instead of relying on the current PCM-oriented core alone
- add explicit encoder provenance such as bitrate/quality mode to the forensic ledger if reproducibility becomes important
- validate OGG/OGA, Opus, and M4A end-to-end before exposing them
- strengthen blind extraction for lossy exports
- add forensic verification event history beyond the current `last_verified_*` fields
- add recipient-specific delivery presets once the current lightweight label-based flow proves stable
