# Release-Ready Export, Track Ordering, and Focused Editor Follow-up

## Summary

This handoff covers a connected workflow pass across export packaging, track ordering, editor UX, and save/attach responsiveness.

The implemented result is:

- release-ready audio exports now use album folders and stored track titles instead of hash-suffixed filenames
- tracks now have a stored `track_number` field with schema migration, editor support, duplicate warnings, and album-wide reorder tooling
- add/edit attach flows derive track length from audio automatically while still allowing manual correction
- long-running save and attach flows report truthful background progress instead of leaving the UI apparently frozen
- catalog-table double-click on standard fields now opens Edit Track focused on the relevant tab/control instead of using direct upload shortcuts for the built-in audio and artwork columns

This pass also cleaned up BUMA work-number ownership in Edit Track, updated help text, and aligned the affected tests with the new behavior.

## Main Behavior Changes

### Release-ready export packaging

- Managed and forensic export filenames no longer append the short file-hash suffix to the user-facing audio filename.
- Single-file exports now write into an album-named directory and use the stored track title as the final filename stem.
- Multi-file ZIP exports now package files under album directories and name the archive from the release/package name instead of batch/hash-style naming.
- The derivative ledger still records the output hash, but `filename_hash_suffix` is now intentionally blank for these release-ready outputs.

### Stored track numbers

- `Tracks.track_number` is now a first-class stored field and schema target moved to `41`.
- The migration backfills the new column only when legacy release placements provide one consistent track number for a given track.
- Add Track defaults stored track number to `1`.
- Add Album defaults each row’s stored track number from local adding order.
- Edit Track exposes the stored track number directly.
- Duplicate track numbers inside the same album warn but do not block save, so manual resequencing remains possible.
- Tag/export logic now prefers the stored track number and only falls back to release placement ordering when the stored value is missing.

### Album Track Ordering workspace

- A new `Album Track Ordering` workspace is available from both the catalog context menu and the Edit menu.
- It loads all tracks from the selected track’s album, shows them in current stored order, allows single-selection row moves, and supports drag reorder.
- Saving rewrites stored sequential track numbers for the album group and then re-synchronizes release ordering.

### Edit Track / Add Track / Add Album follow-ups

- Edit Track now resolves BUMA Wnr. from the linked Work when the track is work-governed and shows it as read-only there; legacy direct values remain editable when no Work governs the value.
- Audio attachment now derives track length from the chosen audio file in Add Track, Add Album, and Edit Track.
- Manual track-length edits are still allowed, but choosing a new audio file replaces the stored duration again with the fresh audio-derived value.

### Progress and responsiveness

- Single-track standard media attach now uses truthful background progress reporting.
- Album reorder saves now use the background-task progress dialog instead of appearing to hang.
- The previously landed truthful post-save orchestration remains the model for these newer save and attach flows.

### Catalog double-click focused editing

- Double-clicking standard catalog cells now opens Edit Track with a best-effort focus target:
  - track title and related metadata focus the Track tab
  - album title, track number, release date, and track length focus the Release tab
  - code columns focus the Codes tab
  - built-in audio/artwork columns focus the Media tab
- Standard audio and artwork columns no longer use the old direct-upload double-click shortcut.
- Custom blob columns keep their existing direct attachment workflow.

## Files / Layers Affected

### UI / controller

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `tests/app/_app_shell_support.py`

### Track / schema / help

- `isrc_manager/services/tracks.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/constants.py`
- `isrc_manager/help_content.py`

### Export / tags / derivative ledgers

- `isrc_manager/file_storage.py`
- `isrc_manager/media/derivatives.py`
- `isrc_manager/forensics/service.py`
- `isrc_manager/authenticity/service.py`
- `isrc_manager/tags/mapping.py`
- `isrc_manager/tags/models.py`
- `isrc_manager/tags/service.py`
- `isrc_manager/authenticity/models.py`
- `isrc_manager/exchange/service.py`

### Tests updated

- `tests/test_track_service.py`
- `tests/test_tag_service.py`
- `tests/test_help_content.py`
- `tests/test_audio_conversion_pipeline.py`
- `tests/test_forensic_watermark_service.py`
- `tests/app/_app_shell_support.py`

## Validation Performed

### Repo hygiene

- `PATH="$(pwd)/.venv/bin:$PATH" make fix`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m py_compile ISRC_manager.py $(find isrc_manager -name '*.py' | sort) $(find tests -name '*.py' | sort)`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m ruff check build.py isrc_manager tests`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m black --check build.py isrc_manager tests`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m mypy`
- `git diff --check`

### CI shard ownership verification

- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m tests.ci_groups catalog-services --verify`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m tests.ci_groups exchange-import --verify`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m tests.ci_groups history-storage-migration --verify`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m tests.ci_groups ui-app-workflows --verify`

### Grouped local test runs

- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m tests.run_group exchange-import --module-timeout-seconds 180 --group-timeout-seconds 900`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m tests.run_group history-storage-migration --module-timeout-seconds 180 --group-timeout-seconds 900`

### Focused UI reruns on Python 3.13 mirror env

- Temporary validation env:
  - `python3.13 -m venv /tmp/isrc-ci-313`
  - `/tmp/isrc-ci-313/bin/python -m pip install -e '.[dev]'`
- Passed:
  - `QT_QPA_PLATFORM=offscreen /tmp/isrc-ci-313/bin/python -m tests.run_module tests.app.test_app_shell_catalog_controller --verbosity 2 --timeout-seconds 300`
  - `QT_QPA_PLATFORM=offscreen /tmp/isrc-ci-313/bin/python -m tests.run_module tests.app.test_app_shell_catalog_model_view --verbosity 2 --timeout-seconds 300`
  - `QT_QPA_PLATFORM=offscreen /tmp/isrc-ci-313/bin/python -m tests.run_module tests.app.test_app_shell_editor_surfaces --verbosity 2 --timeout-seconds 300`
  - `QT_QPA_PLATFORM=offscreen QT_OPENGL=software QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu --disable-gpu-compositing --disable-software-rasterizer' /tmp/isrc-ci-313/bin/python -m tests.run_module tests.app.test_app_shell_layout_persistence --verbosity 2 --timeout-seconds 300`

### Local UI caveat

- The repo-local `.venv` uses Python `3.14`, and several `PySide6`/`QtWebEngine` offscreen UI runs segfaulted there inside Qt/PySide metaobject or GPU/Skia code before Python-level assertions could finish.
- A small runtime-safe follow-up changed a few `App.__init__` signal hookups to lambda callables, which avoids the early `PySide6` bound-method metaobject crash path seen on local `3.14`.
- The authoritative remaining full-matrix verification is expected to come from GitHub Actions on the repository’s supported CI interpreter set (`3.10` / `3.13`).

## Follow-up Notes

- If a future pass revisits UI-only local validation on macOS, prefer the Python `3.13` mirror env plus software-rendering flags for the WebEngine-heavy layout suites.
- If GitHub Actions reports UI-only failures beyond the modules already rerun here, start with the `ui-app-workflows` shard because that is where the focused-editor contract and the export naming assertions were updated.
