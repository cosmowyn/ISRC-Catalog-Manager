# Audio Preview Layout, Theming, and macOS Window Follow-Up

## 1. Previous layout / theming / window issues found

- The audio preview already had the broader media-player controls from the earlier pass, but the layout still read as one loose surface rather than a set of clearly grouped sections.
- The waveform widget was still locked to `220` pixels instead of the requested `250`, which left the main visual region a little undersized and inconsistent with the artwork column sizing.
- The metadata area was just a free header row, not a dedicated grouped container.
- Playback and export controls were adjacent, but not visually separated into their own containers.
- The time-position label still lived in the slider row instead of on the left above the media controls.
- The new visible regions were not all exposed through stable object names and roles for QSS/theme-builder discovery.
- The preview dialogs were still created with the main window as their Qt parent, which is acceptable for lifetime management but weak for macOS-style independent window presence and switching behavior.

## 2. Layout grouping changes made

- Added a top `Now Playing` group container for track metadata.
- Added a named waveform panel container for the waveform/status region.
- Added a dedicated `Playback` group container for transport controls and playback state.
- Added a dedicated `Export` group container so export actions no longer visually float beside playback controls.
- Kept the existing overall dialog concept and media workflow intact; this pass only refined grouping and placement.

## 3. Waveform height lock implementation

- Changed `_AudioPreviewDialog.WAVEFORM_HEIGHT` from `220` to `250`.
- Kept the waveform width flexible with the window size.
- Applied a fixed vertical size policy by setting the waveform widget to a fixed height of `250`.
- The artwork label remains sized from the same constant so the artwork column continues to track the waveform height.

## 4. Theme-builder exposure changes

- Added stable object names for the new visible group surfaces:
  - `audioPreviewMetadataGroup`
  - `audioPreviewWaveformPanel`
  - `audioPreviewPlaybackGroup`
  - `audioPreviewExportGroup`
  - `audioPreviewExportLabel`
- Kept existing stable object names for the dialog, waveform, artwork, transport buttons, time label, export button, and auto-advance checkbox.
- Added a shared `role="mediaTransportButton"` property on the transport buttons so they can be targeted as a family in QSS/theme customization.
- Reused the existing theme/QSS infrastructure rather than adding a new theming path:
  - global `QGroupBox` theme treatment from `theme_builder.py`
  - object-name and role discovery via `qss_reference.py`

## 5. macOS window lifecycle / presence fix

- Changed audio and image preview dialogs to be created as parentless singleton windows instead of parenting them to the main window.
- Kept them as non-modal top-level `Qt.Window` dialogs with persistent reuse via `WA_DeleteOnClose = False`.
- Strengthened the bring-to-front helper so it restores minimized windows, preserves top-level window flags, and requests activation through the underlying window handle when available.
- Added explicit close/minimize window-button flags so the previews behave more like normal standalone application windows on macOS.

## 6. Files changed

- `ISRC_manager.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`

## 7. Tests added / updated

- Added preview layout/theming regression coverage for:
  - metadata group existence at the top of the dialog
  - waveform panel existence
  - playback group existence
  - export group existence
  - waveform fixed height of `250`
  - auto-advance living inside the playback group
  - time-position label living in the left-aligned row above the playback controls
  - QSS/theme reference exposure for the new group surfaces and transport-button role
- Expanded media-window lifecycle coverage to assert that audio and image preview dialogs:
  - remain singleton instances
  - are top-level windows
  - are non-modal
  - have no Qt parent widget
  - expose a native window handle
  - keep minimize-button window flags
- Validation run:
  - `python3 -m unittest tests.app.test_app_shell_editor_surfaces`
  - `python3 -m unittest tests.app.test_app_shell_startup_core tests.test_qss_reference`
  - `python3 -m black --check ISRC_manager.py tests/app/_app_shell_support.py tests/app/test_app_shell_editor_surfaces.py`

## 8. Risks / caveats

- Parentless preview dialogs are the right direction for macOS window presence, but exact behavior in the macOS app/window switcher still depends on the host Qt/macOS integration layer; this pass fixes the Qt-side ownership and activation setup rather than introducing any native Cocoa-specific customization.
- The audio preview still uses the existing temp-file-backed `QMediaPlayer` path; this pass does not alter playback engine internals.
- The new group containers rely on the repo's existing `QGroupBox` theming model, so any future dialog-specific visual treatment should be layered on top of the stable object names added here rather than replacing the generic group styling.

## 9. Current product statement

The audio/media preview dialog now has stronger layout control, better theming exposure, and proper macOS window presence: the waveform is locked to `250` pixels, metadata/playback/export areas are clearly grouped, the new visible surfaces are addressable through the existing theme/QSS system, and the singleton preview windows now behave more like real top-level macOS application windows instead of parent-owned transient dialogs.
