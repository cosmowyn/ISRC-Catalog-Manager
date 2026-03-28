# Audio Preview Full Media-Control Expansion

## 1. Old dialog limitations found

- The previous audio preview was a small utility-style dialog with text buttons for play, pause, and stop plus a basic timeline slider.
- The header used explanatory utility copy instead of a media-style now-playing presentation.
- The waveform area carried redundant title and helper text instead of relying on the visual itself.
- There was no previous-track, next-track, rewind, or fast-forward transport support.
- The dialog did not expose the app's existing track export methods from inside the preview surface.
- Album artwork was not integrated into the preview layout.
- Audio and image previews were opened as one-off dialogs instead of reusable singleton media windows.
- The image preview used a modal `exec()` flow, and the audio preview was recreated each time, which made the media surfaces feel transient instead of behaving like durable OS-level media windows.

## 2. New media-control layout

- Rebuilt the audio preview into a compact media-player style dialog with three clear regions:
  - a now-playing header
  - a waveform-first main row
  - a transport/export controls section
- The header now shows only the current track title and artist for a cleaner presentation.
- Text-labeled playback buttons were replaced with standard Qt media icons for:
  - previous
  - rewind
  - play
  - pause
  - stop
  - fast forward
  - next
- Removed the old waveform title, runtime explanation text, and extra control helper copy so the layout reads visually instead of narratively.

## 3. Track-navigation behavior

- Added previous-track and next-track controls to the audio preview.
- Track navigation follows the logical catalog order from the current visible catalog/table ordering via the app's existing visible-track ordering path.
- Navigation is filtered to tracks that actually have previewable media for the active preview source:
  - standard `audio_file`
  - custom `blob_audio`
- When no previous or next previewable track exists, the matching navigation controls disable.
- The same navigation logic is reused by manual previous/next controls, keyboard shortcuts, and auto-advance.

## 4. Artwork display behavior

- Added a square artwork panel on the right side of the waveform row.
- The artwork container tracks the waveform area's height so the visual reads as a balanced waveform-plus-art layout.
- When effective artwork exists for the current track, it is displayed and scaled inside the square panel.
- When no artwork exists, the artwork container is hidden completely so the preview keeps a deliberate waveform-first layout without an empty placeholder.

## 5. Waveform interaction changes

- The waveform remains the main visual focus of the preview surface.
- Added click-to-seek and drag-to-scrub support on the waveform itself.
- Added wheel and trackpad scrubbing over the waveform so pointer scrolling moves playback position instead of only moving a viewport.
- Added keyboard transport/scrub shortcuts:
  - `Left` / `Right` for small scrubs
  - `Shift+Left` / `Shift+Right` for 10-second jumps
  - `Meta+Left` / `Meta+Right` for previous/next track on macOS
  - `Space` to toggle play/pause

## 6. Export-control integration

- Added a compact export panel next to the transport controls instead of introducing a new export subsystem.
- The export menu is populated from the app's existing per-track export flows and only exposes methods already supported by the application.
- Supported preview-surface exports now include the relevant existing actions for the current track and source, including:
  - direct current-audio export
  - catalog audio copies
  - managed audio derivatives
  - authentic masters
  - provenance copies
  - forensic watermarked audio
  - custom-field blob export where the preview source is a custom `blob_audio` field

## 7. Auto-advance behavior

- Added an `Auto-advance` checkbox to the transport controls.
- Auto-advance defaults to ON.
- When enabled, end-of-media advances to the next previewable track using the same logical next-track behavior as the manual next button.
- When disabled, playback stops on the current track at end-of-media.

## 8. Media window lifecycle fix

- The audio preview dialog and image preview dialog now both open as real top-level non-modal windows using `Qt.Window`.
- Both previews keep `WA_DeleteOnClose` disabled so the app can reuse their existing instances instead of discarding them on close/focus changes.
- Relaunching a media preview now restores, raises, and activates the existing window instead of leaving it effectively hidden or creating a detached duplicate.
- The image preview no longer relies on a modal `exec()` lifecycle and instead behaves like a normal media window.

## 9. Singleton behavior for audio and image dialogs

- Added one reusable app-owned audio preview window instance.
- Added one reusable app-owned image preview window instance.
- Opening the same media dialog type again now:
  - updates the existing window's content/state
  - restores it if minimized
  - shows it if hidden
  - raises and activates it
- This singleton behavior is scoped to the media preview windows only and does not broaden to unrelated dialogs.

## 10. Files changed

- `ISRC_manager.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`

## 11. Tests added / updated

- Added app-shell regression coverage for:
  - now-playing header and artwork visibility behavior
  - icon-based transport controls being present
  - previous/next navigation following visible catalog order
  - auto-advance defaulting ON and advancing only when enabled
  - waveform wheel scrubbing
  - required keyboard shortcut wiring
  - preview export menu routing to existing export methods
  - singleton, top-level, non-modal behavior for audio and image preview windows
- Validation run:
  - `python3 -m unittest tests.app.test_app_shell_editor_surfaces tests.app.test_app_shell_startup_core`
  - `python3 -m black --check ISRC_manager.py tests/app/_app_shell_support.py tests/app/test_app_shell_editor_surfaces.py`

## 12. Risks / caveats

- Track-to-track preview navigation intentionally follows the currently visible catalog ordering, so sorting/filtering in the main catalog affects the navigation path by design.
- The audio preview still uses the existing temp-file-backed `QMediaPlayer` loading path; this pass improves control surface, lifecycle, and navigation behavior without replacing the playback engine.
- Export availability inside the preview reflects the app's existing action enablement and the current media source type, so some advanced export actions remain conditionally available rather than always shown as active.

## 13. Current product statement

Media dialogs now behave like fuller, singleton real windows: the audio preview provides a more professional media-control layout with truthful catalog-based navigation, waveform scrubbing, artwork when available, integrated existing export actions, and auto-advance, while both audio and image previews now reopen by restoring and focusing their existing top-level window instances instead of spawning transient duplicates.
