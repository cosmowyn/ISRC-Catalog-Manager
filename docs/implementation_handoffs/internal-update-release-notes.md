# Internal Update Release Notes Handoff

Date: 2026-04-26

## Summary

The update-available prompt no longer opens GitHub directly when the user chooses Release Notes. It now loads the markdown release notes through the update service and presents them in a native in-app dialog.

## Files Changed

- `ISRC_manager.py`
  - Routes the update prompt's Release Notes button to an internal loader.
  - Loads release notes as a background network task so the UI stays responsive.
  - Falls back to an internal summary dialog if the note body cannot be loaded.
- `isrc_manager/update_checker.py`
  - Adds release-note fetching with HTTPS validation, size limits, UTF-8 decoding, and GitHub blob-to-raw URL resolution.
- `isrc_manager/app_dialogs.py`
  - Adds `ReleaseNotesDialog`, a native dialog with update summary and markdown-rendered release notes.
- `tests/test_update_checker.py`
  - Covers GitHub release-note URL resolution, markdown fetch/decoding, and non-HTTPS rejection.
- `tests/test_update_ui_integration.py`
  - Covers the update prompt routing to the internal release-note path and the background loader handoff.
- `isrc_manager/help_content.py`
  - Documents that update release notes open inside the app.
- `README.md`
  - Updates the versioning/update-check documentation to describe the internal release-note viewer.

## Behavior

- The manifest still provides `release_notes_url`.
- GitHub URLs of the form `https://github.com/.../blob/.../*.md` are converted to `https://raw.githubusercontent.com/...` before fetching.
- The app never launches the browser just to show update release notes.
- If fetching fails, the user still sees an internal dialog with the manifest summary and source URL text.

## QA

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_update_checker.py tests/test_update_ui_integration.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_update_checker tests.test_update_ui_integration
QT_QPA_PLATFORM=offscreen .venv/bin/python -m coverage run -m unittest tests.test_update_checker tests.test_update_ui_integration
.venv/bin/python -m ruff check isrc_manager/update_checker.py tests/test_update_checker.py tests/test_update_ui_integration.py
.venv/bin/python -m black --check tests/test_update_checker.py tests/test_update_ui_integration.py isrc_manager/update_checker.py isrc_manager/app_dialogs.py isrc_manager/help_content.py
.venv/bin/python -m mypy isrc_manager/update_checker.py
.venv/bin/python -m py_compile ISRC_manager.py isrc_manager/update_checker.py isrc_manager/app_dialogs.py isrc_manager/help_content.py tests/test_update_checker.py tests/test_update_ui_integration.py
git diff --check
```

All targeted commands passed on the local Python 3.14.4 virtual environment.

Additional CI-aligned Python 3.13 validation was run in a temporary venv outside the repository:

```bash
QT_QPA_PLATFORM=offscreen /tmp/isrc-ci313-venv/bin/python -m unittest tests.test_update_checker tests.test_update_ui_integration
QT_QPA_PLATFORM=offscreen /tmp/isrc-ci313-venv/bin/python -m coverage run -m unittest tests.test_update_checker tests.test_update_ui_integration
/tmp/isrc-ci313-venv/bin/python -m ruff check isrc_manager/update_checker.py tests/test_update_checker.py tests/test_update_ui_integration.py
/tmp/isrc-ci313-venv/bin/python -m black --check tests/test_update_checker.py tests/test_update_ui_integration.py isrc_manager/update_checker.py isrc_manager/app_dialogs.py isrc_manager/help_content.py
/tmp/isrc-ci313-venv/bin/python -m mypy isrc_manager/update_checker.py
```

All Python 3.13 targeted commands passed.

`QT_QPA_PLATFORM=offscreen PYTHON=.venv/bin/python make check` passed compile, Ruff, Black, and mypy locally, then the full test discovery segfaulted before the first app-shell test body completed. The faulthandler stack points to PySide6 signal connection during `App` construction at `ISRC_manager.py:7849`; this is outside the update release-notes path and did not reproduce in the targeted update tests.

## Notes

Release-note links inside the rendered markdown are not opened automatically by the dialog. This keeps the update-check path local to the app and avoids accidental browser launches from the update prompt.
