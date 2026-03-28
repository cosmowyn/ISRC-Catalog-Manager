# Audio Preview Responsive Layout Follow-Up

## 1. Previous responsive-layout issues found

- The audio preview already had the broader media-player structure, but the fullscreen and large-window presentation still felt loose.
- The waveform and artwork visuals were still taller than requested for this pass.
- The metadata area only surfaced track title and artist.
- Playback controls were reachable from the theme system, but the transport/export buttons were still being caught by the generic `QToolButton` foreground rule instead of following the dialog's default foreground path cleanly.

## 2. Fullscreen / large-window spacing issue root cause

- The live preview layout had already been moved toward grouped sections, but the remaining polish problem came from how generic button styling and prior sparse group behavior interacted at larger sizes.
- The intended fix stayed within normal Qt layout discipline:
  - grouped sections keep constrained vertical size policies
  - the root stack absorbs spare vertical space below the functional content
  - playback/export groups stay top-aligned instead of visually drifting
- This avoids ad hoc resize math and keeps the dialog anchored at both normal and large window sizes.

## 3. Overlap-prevention logic added

- Kept the preview in a strictly stacked `QVBoxLayout` flow with a dedicated waveform/artwork row, playback-status strip, and controls row.
- Kept waveform, artwork, playback status, playback group, and export group on constrained size policies so the lower sections no longer compete for height with the media row.
- Preserved top alignment for the artwork and controls groups and kept spare height below the content via trailing stretch behavior.
- Added/updated regression assertions that verify the waveform and artwork regions do not intersect the playback or export groups after large-window resize.

## 4. Waveform / album-art height changes

- `_AudioPreviewDialog.WAVEFORM_HEIGHT` is now `200`.
- The waveform widget is fixed to `200` px high.
- The artwork label is fixed to `200 x 200`, keeping the artwork square and aligned with the waveform row.
- The existing shared sizing constant continues to keep both media visuals synchronized.

## 5. Metadata expansion for album info

- The track preview state now carries album information alongside title and artist.
- The header now renders:
  - track title
  - artist
  - album information on a subdued metadata line
- The album label hides cleanly when no album value is present.

## 6. Playback-control theming changes

- The transport buttons already exposed `role="mediaTransportButton"`, the export button already exposed `role="mediaExportButton"`, and the auto-advance checkbox already exposed `role="mediaToggle"`.
- The missing piece was theme behavior, not selector reach:
  - the generic `QToolButton` rule in `theme_builder.py` forced button foregrounds through `button_fg`
  - that prevented the media controls from following the dialog/default foreground path cleanly
- Added role-specific stylesheet overrides so:
  - media transport buttons use the dialog/default foreground
  - the media export button uses the dialog/default foreground
  - the media toggle uses the dialog/default foreground
  - disabled media controls fall back to the secondary text color
- This keeps the controls theme-consistent while preserving theme-builder addressability through existing roles and object names.

## 7. Files changed

- `ISRC_manager.py`
- `isrc_manager/theme_builder.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/test_theme_builder.py`

## 8. Tests added / updated

- Updated preview surface tests to cover:
  - 200 px waveform height
  - 200 px square artwork sizing
  - album metadata presence in the header
  - non-overlap between media row and control groups after large resize
  - coherent top alignment of playback/export groups at larger window sizes
  - theme/QSS selector exposure for transport, export, and toggle roles
- Updated theme-builder stylesheet coverage to assert media-role rules exist for:
  - `QToolButton[role="mediaTransportButton"]`
  - `QToolButton[role="mediaExportButton"]`
  - `QCheckBox[role="mediaToggle"]`
- Validation run:
  - `python3 -m unittest tests.app.test_app_shell_editor_surfaces`
  - `python3 -m unittest tests.test_theme_builder.ThemeBuilderTests.test_stylesheet_covers_expanded_widget_families_and_states`
  - `python3 -m unittest tests.app.test_app_shell_startup_core`
  - `python3 -m unittest tests.test_qss_reference`
  - `python3 -m black --check ISRC_manager.py isrc_manager/theme_builder.py tests/app/_app_shell_support.py tests/app/test_app_shell_editor_surfaces.py tests/test_theme_builder.py`

## 9. Risks / caveats

- The audio preview still uses the existing temp-file-backed `QMediaPlayer` path; this pass only tightened layout, metadata display, and theming behavior.
- The full `tests.test_theme_builder` class currently has an unrelated compact-settings-dialog width assertion elsewhere in the working tree, so validation for this pass stayed on the specific stylesheet test that covers the modified media-control theme surface.
- The preview now uses symbol-based transport text, which improves theme-color inheritance and keeps the controls styleable, but exact glyph rendering still depends on the platform font stack.

## 10. Current product statement

The audio preview dialog now behaves more robustly across window sizes and theme configurations: the media row is reduced to a stable 200 px height, grouped sections stay coherent instead of drifting at large sizes, album metadata is included cleanly, and the playback/export controls now follow the dialog theme while remaining directly addressable through the existing theme-builder/QSS system.
