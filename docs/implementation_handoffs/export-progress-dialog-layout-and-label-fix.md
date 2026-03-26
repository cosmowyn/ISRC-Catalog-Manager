# Export Progress Dialog Layout And Label Fix

Date: 2026-03-26

## Summary Of The Issue

Export-related dialogs had two separate UX problems:

- the audio-derivative format chooser used the wrong primary action label: `Choose Format`
- the shared long-running export progress dialog was still too wide and visually unstable for a compact loading/progress screen

The second issue was mostly a sizing-policy problem, not a missing second dialog system.

## Confirmed Root Cause

- The export format chooser is the shared compact choice helper in `isrc_manager/ui_common.py`, and the wrong button text came from the export caller in `ISRC_manager.py`.
- The running export screen is the shared `QProgressDialog` from `isrc_manager/tasks/manager.py`.
- The chooser was using a conservative width floor plus a left-aligned capped combo box, which made the dialog feel wider and less balanced than necessary.
- The progress dialog was using a hard fixed-width contract of `520..680`, so it never behaved like a compact loading screen.
- Long dynamic export strings were rendered verbatim, with wrapping only, so file/title-heavy messages could bloat the dialog more than necessary.

## Layout Policy

- Keep one shared `QProgressDialog` system.
- Use bounded compact geometry instead of an oversized fixed-width presentation.
- Let wrapped label text change height only.
- Keep buttons fixed and fully visible inside the dialog bounds.
- Abbreviate only very long dynamic strings, not ordinary status text and not the static chooser explanation copy.

## Button Label Fix

- `App._prompt_audio_conversion_format()` now passes `ok_text="Export"` instead of `Choose Format`.
- The shared compact chooser still applies that text through the existing `QDialogButtonBox` helper.

## Geometry Bounds

### Audio Export Format Chooser

- Width bounds now use `320..420`.
- The combo box now expands within the dialog instead of being left-aligned with an extra internal cap.
- This keeps the chooser compact while still leaving enough room for the explanatory copy, the format combo, and the button row.

### Shared Export Progress Dialog

- Width bounds now use `360..480`.
- Height bounds now use `118..220`.
- The initial width is chosen from the parent window, then clamped into that range.
- Progress updates preserve the current width and only refresh height inside the bounded range.

These bounds were chosen because the previous `520..680` contract was visibly too large, while the user-suggested `150..200` range is not viable for a progress bar plus visible action control in the shared `QProgressDialog` layout.

## Wrapping Behavior

- The chooser prompt continues to wrap naturally.
- The shared progress dialog still wraps its label text.
- Progress updates now keep labels top-left aligned and refresh height only.
- The progress bar and button row keep their own fixed-space contract so wrapped text does not push controls outside the dialog.

## Abbreviation Threshold

- Long-string abbreviation now uses a shared middle-elision helper in `isrc_manager/ui_common.py`.
- Threshold: `60` characters.
- Format: first `20` characters + `...` + last `25` characters.
- In the shared progress dialog, abbreviation is applied to very long dynamic status segments.
- If a status line contains a stage prefix such as `Converting 1 of 1: ...`, the prefix is preserved and only the long suffix is abbreviated.

Example:

- input: `Converting 1 of 1: This is a deliberately long export title that should keep its useful start and end`
- output: `Converting 1 of 1: This is a deliberate... its useful start and end`

The threshold was chosen from the real compact bounds landed in this pass: it keeps moderate strings intact while stopping the dialog from growing around filename/title-heavy export updates.

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/ui_common.py`
- `isrc_manager/tasks/manager.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/test_task_manager.py`
- `tests/test_ui_common.py`
- `docs/implementation_handoffs/export-progress-dialog-layout-and-label-fix.md`

## Tests Added Or Updated

- Added export chooser coverage proving the button label is now `Export`.
- Updated progress dialog coverage for the new bounded geometry contract.
- Added coverage for long-status wrapping with bounded height.
- Added exact abbreviation-format coverage for progress messages.
- Added shared helper coverage for middle abbreviation.

Validation run:

- `python3 -m unittest tests.test_ui_common`
- `python3 -m unittest tests.test_task_manager`
- `python3 -m unittest tests.app.test_app_shell_startup_core`
- `python3 -m black --check ISRC_manager.py isrc_manager/ui_common.py isrc_manager/tasks/manager.py tests/test_task_manager.py tests/test_ui_common.py tests/app/_app_shell_support.py tests/app/test_app_shell_startup_core.py`

## Remaining Limitations

- The shared `QProgressDialog` still uses Qt’s native internal row arrangement, so this pass improves the sizing contract and text behavior without replacing that shell.
- The long-string abbreviation policy is now shared by the progress dialog helper path; broader export preview dialogs with tables were intentionally left out of scope.
- If future work wants a more custom visual loading screen than `QProgressDialog` can comfortably provide, that should be treated as a separate UI architecture pass.
