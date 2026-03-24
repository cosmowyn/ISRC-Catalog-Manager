# Automatic Audio Export Metadata Embedding

## 1. Product Decision And Scope

This pass implements one consistent product rule:

- catalog-backed audio exports automatically attempt metadata embedding
- the catalog is the only metadata source of truth for export-time embedding
- external-only conversion remains a plain conversion workflow and does not invent metadata
- metadata embedding is no longer framed as a separate required user step

This work covered the user-facing audio export families plus the raw track-audio export helpers used from the catalog table.

## 2. Audited Export / Conversion Workflow Matrix

| Workflow | Catalog-backed | Output behavior | Metadata behavior after this pass |
| --- | --- | --- | --- |
| `Export Audio Derivatives…` | Yes | Managed derivative transcode plus ledger registration | Automatically attempts catalog metadata embedding on the final output |
| `Export Authentic Masters…` | Yes | Direct watermark master export plus signed sidecar | Automatically attempts catalog metadata embedding on the exported master |
| `Export Provenance Copies…` | Yes | Lossy copy export plus signed lineage sidecar | Automatically attempts catalog metadata embedding on the exported copy |
| `Export Forensic Watermarked Audio…` | Yes | Recipient-specific lossy export plus forensic/derivative ledger registration | Automatically attempts catalog metadata embedding on the final delivery file |
| `Export Catalog Audio Copies…` | Yes | Plain original-format catalog copy export | Automatically attempts catalog metadata embedding on the exported copy |
| Raw `Audio File` export from the track table | Yes | Byte-for-byte export of the attached primary track audio | Automatically attempts catalog metadata embedding on the saved export |
| `Convert External Audio Files…` | No | Plain utility conversion only | Strips inherited source metadata and does not invent catalog metadata |
| Raw custom `blob_audio` export | Not treated as trustworthy catalog-audio export | Byte-for-byte export of an arbitrary custom attachment | Left unchanged; no automatic metadata embedding |

## 3. Final Metadata Embedding Rule

- If the export is based on catalog-backed primary track audio, the app automatically attempts to embed catalog metadata into the exported file.
- Managed-file and database/blob-backed primary audio now follow the same export metadata policy.
- Release-level export metadata only uses release context when that context is unambiguous enough to be trustworthy.
- If export metadata cannot be resolved or cannot be written safely, the export copy still succeeds and the metadata step is skipped with a warning.

## 4. Catalog Source-Of-Truth Policy

The authoritative export metadata builder is now:

- `isrc_manager/tags/catalog.py`
  - `build_catalog_export_tag_data(...)`

That helper delegates to the broader catalog tag mapper, but fixes the export-time policy around release selection:

- export workflows use `CATALOG_EXPORT_RELEASE_POLICY = "unambiguous"`
- managed-file and blob-backed sources share the same catalog metadata builder
- existing file tags and filenames are not treated as canonical export truth

The low-level best-effort export helper is:

- `isrc_manager/tags/catalog.py`
  - `write_catalog_export_tags(...)`

That helper centralizes:

- catalog metadata lookup
- empty-metadata detection
- safe tag writing
- fail-safe warning return instead of hard export failure

## 5. Managed-File And Blob-Backed Parity

Parity is now explicit across:

- managed derivative export
- authenticity master export
- provenance export
- forensic export
- plain catalog-audio copy export
- raw track-audio export helper

The metadata source is always the catalog. Storage mode only affects how source audio bytes are materialized.

## 6. External Conversion Fail-Safe Behavior

`Convert External Audio Files…` remains intentionally catalog-free.

After this pass:

- the external coordinator still runs without track IDs, release lookups, authenticity, or derivative registration
- the conversion layer now accepts an explicit metadata behavior
- the external path uses `metadata_behavior="strip"`
- ffmpeg output is told to drop inherited metadata and non-audio attached streams for this workflow

This keeps the external path safe and honest:

- conversion still succeeds without catalog metadata
- no catalog metadata is invented
- unmanaged source metadata is not silently carried forward as if it were catalog truth

## 7. Unsupported / Missing-Metadata Behavior

Catalog-backed exports now treat metadata embedding as best effort:

- if metadata is empty, ambiguous, or unavailable, the export still succeeds
- if the output container rejects metadata writing, the export still succeeds
- warnings explain that metadata embedding was skipped

This behavior now applies to:

- managed derivatives
- authenticity masters
- provenance copies
- forensic exports
- catalog audio copies
- raw track-audio exports

## 8. Manual Metadata Action Cleanup

The old manual framing was:

- `Export Tagged Audio Copies…`

That action was not removed outright because it still represents a real capability:

- exporting original-format catalog audio copies without transcoding, watermarking, or derivative registration

The cleanup decision was:

- keep the capability
- remove the “manual tag writing” framing
- rename it to `Export Catalog Audio Copies…`
- describe metadata embedding as automatic, not as a separate required step

Related UI wording was updated in:

- menus
- action ribbon descriptions
- context menu labels
- in-app help
- workflow docs

## 9. Docs / Help Surfaces Updated

Updated public-facing wording in:

- `README.md`
- `docs/README.md`
- `docs/catalog-workspace-workflows.md`
- `docs/import-and-merge-workflows.md`
- `docs/file_storage_modes.md`
- `docs/audio-authenticity-workflow.md`
- `isrc_manager/help_content.py`

The updated wording now reflects:

- automatic metadata embedding on catalog-backed exports
- the renamed `Export Catalog Audio Copies…` workflow
- the explicit metadata-free external conversion rule

## 10. Tests Added / Updated

Updated or added coverage in:

- `tests/test_audio_conversion_pipeline.py`
  - blob-backed managed authenticity export tags
  - blob-backed managed lossy export tags
  - mixed-source lossy ZIP tag coverage on both outputs
  - external conversion uses metadata stripping
  - ffmpeg strip-mode command flags
- `tests/test_authenticity_verification_service.py`
  - blob-backed authenticity master export tag coverage
  - provenance export tag coverage
- `tests/test_forensic_watermark_service.py`
  - blob-backed forensic export tag coverage
- `tests/test_tag_service.py`
  - plain catalog copy export remains successful when metadata embedding is skipped
- `tests/app/_app_shell_support.py`
  - renamed plain export workflow coverage
  - raw track-audio export now embeds metadata
  - updated menu/context-menu wording assertions
- `tests/app/test_app_shell_editor_surfaces.py`
  - updated aliases for the renamed workflow coverage

Verification run used:

```bash
python3 -m unittest tests.test_audio_conversion_pipeline tests.test_authenticity_verification_service tests.test_forensic_watermark_service tests.test_tag_service tests.app.test_app_shell_editor_surfaces
```

Result:

- `Ran 67 tests`
- `OK`

## 11. Remaining Edge Cases And Follow-Up Recommendations

- Raw custom `blob_audio` export was intentionally left as a byte-for-byte export. The app does not have a trustworthy semantic guarantee that an arbitrary custom audio blob should inherit the parent track’s catalog metadata.
- If custom audio fields later become first-class deliverables, they should get an explicit metadata policy instead of inheriting track metadata by assumption.
- If the app later adds more audio export surfaces, they should use `write_catalog_export_tags(...)` for catalog-backed outputs or `metadata_behavior="strip"` for plain external conversion.
