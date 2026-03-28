# Media Attach Match/Resolve/Drag-Drop

## 1. What Already Existed Before Implementation

- Audio attachment already existed in two partial forms:
  - direct per-track media replacement from known track editors
  - `Catalog > Audio > Import & Attach > Bulk Attach Audio Files…` using `BulkAudioAttachService` and `BulkAudioAttachDialog`
- Album art attachment already existed as a direct per-track replacement workflow through known-track editors.
- Storage modes already existed and were enforced through `TrackService.set_media_path(...)`.
- `Add Track` already supported prefilling incoming audio and album-art source paths.

## 2. What Was Missing Or Incomplete

- No shared reviewed attach workflow existed for album art.
- Audio attach still depended on older assumptions in places and did not expose enough state for ambiguous matches.
- Unique matches were not fully documented as an explicit confirmation-first workflow.
- No app-shell drag-and-drop path existed for media attachment.
- There was no single attach model spanning:
  - match attempt
  - ambiguity handling
  - explicit confirmation
  - storage-mode choice
  - safe cancel behavior

## 3. Final Audio Attachment Workflow

- Audio files route through `bulk_attach_audio_files(...)`.
- The workflow first builds a candidate scope from selected tracks, current selection, visible rows, or the entire catalog.
- `BulkAudioAttachService` inspects filenames and embedded tags, then attempts to match incoming files to existing tracks.
- If one safe match is found, the user still sees the review dialog before any write.
- If no match is found, the review dialog opens with the file unresolved so the user can:
  - choose an existing track manually
  - skip the file
  - open `Add Track` with the audio file prefilled when a single file is being handled
- If duplicate or ambiguous matches are found, the review dialog opens with explicit ambiguity and candidate hints.
- No attach write occurs until the dialog is accepted.
- Cancelling the dialog leaves the database and stored media unchanged.

## 4. Final Album-Art Attachment Workflow

- Album art now routes through `attach_album_art_file_to_catalog(...)`.
- The workflow reuses the same reviewed attach pattern as audio:
  - automatic match attempt
  - explicit review even on one safe match
  - manual resolution when unmatched or ambiguous
  - explicit storage-mode choice before writes
- Album-art targets are filtered through the existing shared-art edit rules so only direct owners are offered for direct attachment.
- A single-file unresolved artwork flow can open `Add Track` with the image path prefilled.
- Cancelling the dialog leaves the database and stored media unchanged.

## 5. Selector / Match-Resolution / Confirmation Behavior

- `BulkAudioAttachDialog` was expanded into the shared review/confirmation surface for catalog media attach.
- It now supports:
  - generic media labels
  - searchable existing-track reassignment
  - candidate-hint display for ambiguous matches
  - built-in storage-mode selection
  - optional shared artist update for audio
  - optional `Open Add Track Instead…` flow for single-file unresolved work
- Duplicate track assignments inside one review session are blocked before acceptance.

## 6. Drag-And-Drop Behavior

- App-shell-level drop targets are configured on the main window, central widget, table surfaces, and the table viewport.
- Drag-and-drop reuses the same media-attach workflows instead of using a second simplified path.
- Single dropped audio file:
  - routes to `bulk_attach_audio_files(...)`
- Multi-file drop:
  - accepted only when at least one supported audio file is present
  - non-audio files in the same multi-drop are ignored later by the shared audio path
- Single dropped image file:
  - routes to `attach_album_art_file_to_catalog(...)`
- Multi-image drop:
  - rejected with a clear message because bulk album-art attach is not supported
- Unsupported dropped files:
  - rejected safely with an informational message

## 7. Multi-File Audio Handling And Single-File Image Handling

- Multi-file drops remain audio-only.
- Album art remains single-image only.
- This keeps the UX honest and avoids implying a bulk artwork workflow that does not exist yet.

## 8. Storage-Mode Behavior

- Storage mode remains limited to the existing two supported modes:
  - `managed_file`
  - `database`
- The choice is made explicitly in the reviewed attach dialog before the attach write occurs.
- Both audio and album art route through the existing `TrackService.set_media_path(...)` logic, so storage semantics and cleanup rules stay centralized.

## 9. Tests Added / Updated

- `tests/test_tag_dialogs.py`
  - updated for the expanded shared review dialog
  - now covers storage-mode selection and the `Open Add Track` path
- `tests/test_tag_service.py`
  - now verifies ambiguous candidate track IDs are preserved for manual resolution
- `tests/app/_app_shell_support.py`
  - added audio unique-match confirmation safety coverage
  - added unmatched and ambiguous audio review coverage
  - added album-art confirmation and storage-mode coverage
  - added shell drop-target and drag-drop routing coverage
- `tests/app/test_app_shell_editor_surfaces.py`
  - wires the new app-shell cases into the main surface suite

## 10. Risks / Caveats

- Audio matching remains conservative and grounded in the existing filename/tag logic; it does not attempt broad fuzzy matching.
- Album-art matching is intentionally filename-driven and conservative to avoid blind attachment.
- Multi-file mixed drops with audio present still flow through the audio attach path, where unsupported non-audio files are ignored safely.
- Shared album-art ownership rules still apply; not every track can be a direct artwork owner.

## 11. Explicit Final Statement

Media attachment now verifies candidate matches first, resolves ambiguities explicitly, requires user confirmation before any write even on unique matches, preserves explicit storage-mode choice, and safely supports drag-and-drop from the OS shell into the application workspace.
