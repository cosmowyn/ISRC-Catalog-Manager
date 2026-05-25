# Targeted Duplication Follow-Up Report

## Scope

- Reviewed findings from the targeted duplication review:
  - `isrc_manager/authenticity/watermark.py`
  - `isrc_manager/forensics/watermark.py`
  - `isrc_manager/media/waveform_cache.py`
  - `isrc_manager/services/tracks.py`

## Summary

Both reviewed findings were confirmed as intentional design seams and do not require source remediation:

1. **Watermark helper functions** in authenticity and forensics are separate by design.
2. **Track service/protocol class names** in waveform cache and tracks are intentional protocol-vs-implementation boundaries.

## Files inspected

- `isrc_manager/authenticity/watermark.py`
  - `pack_token`
  - `unpack_token`
  - `sync_and_payload_bits`
- `isrc_manager/forensics/watermark.py`
  - `pack_token`
  - `unpack_token`
  - `sync_and_payload_bits`
- `isrc_manager/media/waveform_cache.py`
  - `TrackMediaSourceHandle`
- `isrc_manager/services/tracks.py`
  - `TrackService`

## Evidence summary

### Finding 1 — Watermark helper functions
- **Authenticity module**: `pack_token` builds a 25-byte token, `unpack_token` expects 25 bytes and returns the authenticity token model, and `sync_and_payload_bits` uses the authenticity sync word.
- **Forensic module**: `pack_token` builds a 15-byte token, `unpack_token` expects 15 bytes and returns the forensic token model, and `sync_and_payload_bits` uses the forensic sync word.
- The modules therefore differ in payload layout, byte sizes, sync framing, return model shape, and domain semantics.

### Finding 2 — Duplicate class names
- `isrc_manager/media/waveform_cache.py` contributes protocol/interface-style contracts.
- `isrc_manager/services/tracks.py` contributes concrete runtime implementations.
- Shared names represent different abstraction layers rather than duplicate logic.

## Final decisions

1. **Watermark helper functions**: keep separate intentionally.
2. **`TrackService` / `TrackMediaSourceHandle` naming**: keep separate intentionally.

## Validation commands and results

### Commands attempted

- `python3 -m compileall ISRC_manager.py isrc_manager`
- `QT_QPA_PLATFORM=offscreen python3 -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600`

### Results

- `compileall` result: **passed**.
- Test run result: **failed during collection/import** before test execution due missing runtime dependency.
- First representative error: `ModuleNotFoundError: No module named 'PySide6'`.
- This is an environment-readiness blocker, not a regression from this documentation pass.

## Source-code changes

No source-code remediation was required by this review.
No source files were modified in this closure pass.

## Conclusion

The duplication review is closed as an intentional design decision set. Remaining failures are due to missing test/runtime dependencies in the current environment.
