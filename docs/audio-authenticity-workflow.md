# Audio Authenticity Workflow

This guide explains the user-facing audio authenticity workflow in ISRC Catalog Manager.

The feature combines two separate layers:

- a compact keyed watermark embedded into exported WAV, FLAC, or AIFF master copies
- an Ed25519-signed manifest that carries the real authenticity claim

That distinction matters. The watermark links exported audio back to a catalog record, but the signed manifest is what provides the cryptographic authenticity check.

## What The Feature Is For

Use this workflow when you want to:

- export canonical master audio with a practical authenticity marker
- export lossy derivatives with signed lineage back to a verified master
- keep a signed authenticity or provenance document alongside the export
- verify whether a direct master file or supported derivative matches signed catalog expectations
- inspect either selected catalog audio or an outside file without importing it first

This feature is not DRM and not a copy-protection system.

## Keys

Open `Settings > Audio Authenticity Keys…` to manage signing keys.

- Public keys are stored in the profile database.
- Private keys are stored locally in the app settings folder.
- Local private-key storage is practical, but it is not tamper-proof.

The default key is used for new authenticity exports.

## Export Watermarked Master Audio

Use `Catalog > Export Authenticity Watermarked Audio…`.

The export workflow:

1. Uses the selected tracks from the catalog.
2. Chooses a supported WAV, FLAC, or AIFF reference source for each track.
3. Writes a new export copy instead of modifying the original stored audio.
4. Embeds a compact keyed watermark token into the export copy.
5. Writes standard embedded metadata tags when those catalog values are already available.
6. Writes a sibling `*.authenticity.json` sidecar containing the signed manifest data needed for portable verification.

The export copy can therefore contain both:

- normal user-visible metadata tags such as title, artist, ISRC, and release fields where available
- the separate authenticity watermark/signature workflow

## Export Provenance Audio

Use `Catalog > Export Authenticity Provenance Audio…`.

This workflow is for supported lossy derivatives that should inherit authenticity by lineage rather than by direct watermark extraction.

The export workflow:

1. Uses the selected tracks from the catalog.
2. Requires an existing direct authenticity manifest for the same track and a canonical reference that still matches that manifest.
3. Copies the attached derivative audio in its current format without transcoding it.
4. Writes standard embedded metadata tags when those catalog values are already available.
5. Writes a sibling `*.authenticity.json` sidecar containing:
   - the signed parent direct-authenticity document
   - a signed derivative provenance document with an `export_id`

That means lossy derivatives are verified through signed lineage back to a previously watermarked master, not by pretending the same embedded watermark check works equally on every codec.

## Verify Audio Authenticity

Use `Catalog > Verify Audio Authenticity…`.

If one supported catalog track audio source is selected, the app lets you choose between:

- `Selected Track Audio`
- `Choose External File…`

If no supported track audio is selected, the app opens the external-file picker directly.

That means verification is not limited to attached catalog media. You can verify:

- a file already stored in the current profile
- an exported file from elsewhere on disk
- an external delivery or received audio file, as long as it is in a supported direct or provenance format

## What Verification Checks

For direct master formats, the verifier attempts to:

1. detect the keyed watermark
2. resolve the embedded token to a manifest from the open profile or an adjacent sidecar
3. verify the Ed25519 signature
4. compare the inspected audio against the signed reference expectations

For provenance-only derivatives, the verifier attempts to:

1. load an adjacent provenance sidecar
2. verify the derivative document signature
3. verify the embedded parent direct-authenticity document signature
4. confirm the derivative file hash matches the signed lineage record
5. confirm the parent linkage against the open profile when the parent manifest exists locally

The result states are intentionally narrow and honest:

- `verified_authentic`
- `verified_by_lineage`
- `signature_invalid`
- `manifest_found_reference_mismatch`
- `no_watermark_detected`
- `unsupported_format_or_insufficient_confidence`

## What To Expect From Metadata Tags

During authenticity export, the app also writes ordinary file metadata tags into the exported copy.

- Track-level fields come from the catalog snapshot.
- Release-level fields are only embedded when the release context is clear enough to avoid tagging the file with the wrong release data.

This keeps the export useful in normal audio workflows without pretending that visible tags are the same thing as the authenticity claim.

## Practical Limits

Keep these limits in mind:

- Direct embedded watermark verification is limited to WAV, FLAC, and AIFF.
- MP3, OGG/OGA, Opus, and M4A/MP4/AAC are handled through signed provenance lineage only in this pass.
- A watermark always changes the waveform slightly, so the goal is perceptual transparency, not mathematical identity.
- Watermarking alone is not treated as strong proof.
- Public-key-only checks can validate a manifest signature, but they do not automatically prove the keyed watermark path if local extraction material is unavailable.
- Robustness against every lossy transcode or hostile edit is out of scope for this version.
- Future forensic watermarking for recipient-specific leak tracing is a separate direction and is intentionally not merged into the current authenticity/provenance workflow.

## Where To Read More

- Use the in-app `Help` chapter for `Audio Authenticity` for the quickest overview.
- See [Catalog Workspace Workflows](catalog-workspace-workflows.md) for how the feature fits into daily catalog use.
- See [Implementation Handoffs](implementation_handoffs/) for deeper internal technical notes.
