# Expand Theme Icon Picker Full Library

## 1. Previous picker restriction behavior found

- The theme settings Blob Icons page already reused a shared picker widget: `BlobIconEditorWidget` in `isrc_manager/blob_icons.py`.
- That widget populated its platform icon combo from `system_blob_icon_choices(kind)` and its emoji combo from `emoji_blob_icon_presets(kind)`.
- Both helpers were strongly kind-filtered.
  - `audio_*` kinds only saw the audio subset.
  - `image_*` kinds only saw the image subset.
- This meant users could only pick from the category-specific subset exposed for that editor, even though the app already had a broader built-in icon pool.
- The freeform emoji text field already allowed typing any emoji manually, but the picker UI itself did not make the full bundled library easy to browse.

## 2. Icon sources exposed

- Emoji icons come from the existing `EMOJI_BLOB_ICON_PRESETS` catalog in `isrc_manager/blob_icons.py`.
- System icons come from the existing `SYSTEM_BLOB_ICON_SPECS` catalog in `isrc_manager/blob_icons.py`, which maps Qt `QStyle.StandardPixmap` values to user-facing choices.
- This pass did not add a second icon source or a second picker subsystem.
- Instead, it exposes the full available emoji and system icon catalogs through the existing picker controls.

## 3. Suggested/default icon grouping retained

- Suggested icons were preserved and intentionally kept prominent.
- The picker now treats the exact default for the current kind as the first recommended entry.
  - Example: `audio_database` still leads with `💽`.
  - Example: `image_database` still leads with `🗃️`.
- Recommended system icons for the current kind still appear first in the platform icon combo.
- Recommended emoji icons for the current kind still appear first in the emoji combo.
- Both combos now visually separate:
  - recommended choices first
  - full library after a separator

## 4. Full-library expansion behavior implemented

- The platform icon picker now shows:
  - recommended kind-specific system icons first
  - a separator
  - the remaining full available system icon catalog
- The emoji picker now shows:
  - the current kind's recommended/default emojis first
  - a separator
  - the remaining full bundled emoji catalog
- The emoji picker also keeps the existing freeform emoji field, so users can still type any emoji directly.
- Hard per-category restriction was removed from the picker experience.
  - Users still get guided defaults first.
  - Once the picker is open, they can choose across the full available library without being locked to only the original category subset.
- The UI change was intentionally minimal:
  - no full theme settings redesign
  - no new picker dialog
  - no removal of existing defaults
  - just clearer notes plus expanded choice lists inside the existing controls

## 5. Files changed

- `isrc_manager/blob_icons.py`
- `tests/test_blob_icons.py`
- `tests/test_theme_builder.py`
- `docs/implementation_handoffs/expand-theme-icon-picker-full-library.md`

## 6. Tests added / updated

- `tests/test_blob_icons.py`
  - verifies recommended emoji defaults stay first
  - verifies the full emoji library is present in the picker
  - verifies recommended system icons stay first
  - verifies the full system icon library is present in the picker
  - verifies selection can use icons that were previously outside the original kind subset
- `tests/test_theme_builder.py`
  - verifies the theme settings dialog saves full-library picker selections correctly through `dialog.values()`

## 7. Risks / caveats

- The picker now exposes the full bundled icon library, so users can intentionally choose cross-category icons such as an image icon for an audio badge or vice versa.
- That is by design for this feature pass, but it also means semantic guidance now depends more on the recommended section than on hard restrictions.
- System icon appearance can still vary by platform because Qt standard pixmaps are OS/theme dependent.

## 8. Explicit outcome statement

Users can now choose from the full available icon library while still seeing recommended icons first. The existing theme-settings picker remains guided and familiar, but it no longer hard-locks users into narrow category-only subsets once opened.
