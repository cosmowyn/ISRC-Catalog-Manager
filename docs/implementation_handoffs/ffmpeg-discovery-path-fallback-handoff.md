# FFmpeg Discovery Path Fallback Handoff

## 1. Problem

After the latest app update, managed audio derivative export could show:

- `Managed audio derivative export requires ffmpeg on PATH.`
- `Install ffmpeg to enable derivative export and the external conversion utility.`

This could happen even when ffmpeg was installed locally. On macOS, a Finder-launched packaged app does not necessarily inherit the same shell `PATH` as Terminal, so `shutil.which("ffmpeg")` can miss a Homebrew install at `/opt/homebrew/bin/ffmpeg`.

## 2. Root Cause

`AudioConversionService` was the gatekeeper for derivative export and external conversion availability, but its discovery logic only checked:

- `shutil.which("ffmpeg")`

There was a separate macOS PATH adjustment in the audio preview dialog, but that code only ran when the preview dialog was constructed. It did not help the conversion service during export availability checks.

## 3. Fix

`isrc_manager/media/conversion.py` now centralizes ffmpeg fallback discovery in `_ffmpeg_candidate_paths()`.

Discovery order is:

- normal `PATH` lookup through `shutil.which("ffmpeg")`
- explicit overrides from `ISRC_MANAGER_FFMPEG` and `FFMPEG_BINARY`
- PyInstaller bundle-adjacent locations
- executable-adjacent locations
- common macOS locations, including `/opt/homebrew/bin/ffmpeg`
- common Windows package-manager and manual install locations
- common Linux locations

The warning copy in `ISRC_manager.py` was also softened so it says ffmpeg is required and suggests installing it or adding it to PATH, instead of implying PATH is the only supported discovery route.

## 4. Files Changed

- `isrc_manager/media/conversion.py`
- `ISRC_manager.py`
- `tests/test_audio_conversion_pipeline.py`

## 5. Tests And Checks

Validated with:

- `.venv/bin/python -m pytest tests/test_audio_conversion_pipeline.py -q`
- `.venv/bin/python -m ruff check isrc_manager/media/conversion.py tests/test_audio_conversion_pipeline.py ISRC_manager.py`
- `.venv/bin/python -m black --check isrc_manager/media/conversion.py tests/test_audio_conversion_pipeline.py ISRC_manager.py`
- `PATH=/usr/bin:/bin .venv/bin/python - <<'PY' ...` smoke check confirming the service still finds `/opt/homebrew/bin/ffmpeg`

## 6. Outcome

Managed audio derivative export and external conversion should now stay available in the packaged macOS app when ffmpeg is installed through Homebrew, even if the app was launched without a shell PATH.
