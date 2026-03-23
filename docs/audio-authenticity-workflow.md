# Audio Authenticity Workflow

This guide explains the user-facing audio authenticity workflow in ISRC Catalog Manager.

The feature combines two separate layers:

- a compact keyed watermark embedded into exported WAV or FLAC copies
- an Ed25519-signed manifest that carries the real authenticity claim

That distinction matters. The watermark links exported audio back to a catalog record, but the signed manifest is what provides the cryptographic authenticity check.

## What The Feature Is For

Use this workflow when you want to:

- export catalog audio with a practical authenticity marker
- keep a signed manifest alongside the export
- verify whether a WAV or FLAC file matches a signed catalog record
- inspect either selected catalog audio or an outside file without importing it first

This feature is not DRM and not a copy-protection system.

## Keys

Open `Settings > Audio Authenticity Keys…` to manage signing keys.

- Public keys are stored in the profile database.
- Private keys are stored locally in the app settings folder.
- Local private-key storage is practical, but it is not tamper-proof.

The default key is used for new authenticity exports.

## Export Watermarked Audio

Use `Catalog > Export Authenticity Watermarked Audio…`.

The export workflow:

1. Uses the selected tracks from the catalog.
2. Chooses a supported WAV or FLAC reference source for each track.
3. Writes a new export copy instead of modifying the original stored audio.
4. Embeds a compact keyed watermark token into the export copy.
5. Writes standard embedded metadata tags when those catalog values are already available.
6. Writes a sibling `*.authenticity.json` sidecar containing the signed manifest data needed for portable verification.

The export copy can therefore contain both:

- normal user-visible metadata tags such as title, artist, ISRC, and release fields where available
- the separate authenticity watermark/signature workflow

## Verify Audio Authenticity

Use `Catalog > Verify Audio Authenticity…`.

If one supported catalog track audio source is selected, the app lets you choose between:

- `Selected Track Audio`
- `Choose External File…`

If no supported track audio is selected, the app opens the external-file picker directly.

That means verification is not limited to attached catalog media. You can verify:

- a file already stored in the current profile
- an exported file from elsewhere on disk
- an external delivery or received audio file, as long as it is WAV or FLAC

## What Verification Checks

The verifier attempts to:

1. detect the keyed watermark
2. resolve the embedded token to a manifest from the open profile or an adjacent sidecar
3. verify the Ed25519 signature
4. compare the inspected audio against the signed reference expectations

The result states are intentionally narrow and honest:

- `verified_authentic`
- `watermark_found_signature_invalid`
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

- WAV and FLAC are the supported formats for this workflow in v1.
- A watermark always changes the waveform slightly, so the goal is perceptual transparency, not mathematical identity.
- Watermarking alone is not treated as strong proof.
- Public-key-only checks can validate a manifest signature, but they do not automatically prove the keyed watermark path if local extraction material is unavailable.
- Robustness against every lossy transcode or hostile edit is out of scope for this version.

## Where To Read More

- Use the in-app `Help` chapter for `Audio Authenticity` for the quickest overview.
- See [Catalog Workspace Workflows](catalog-workspace-workflows.md) for how the feature fits into daily catalog use.
- See [Implementation Handoffs](implementation_handoffs/) for deeper internal technical notes.
