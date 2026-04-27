# Update Backup Auto-Cleanup And About Donation

## Summary
This pass closes two user-facing gaps:

- Update rollback backups and installer workspaces now clean up automatically after the updated app reaches `startupReady`.
- The About dialog now includes a visible support section with a PayPal donation button.

## Update Cleanup
The previous updater flow retained rollback backups until close, which meant backup artifacts could survive indefinitely if the user kept working, force-quit, or never hit the normal close path. The app now treats `startupReady` as the clean-run confirmation point, marks the update handoff ready, deletes the handoff backup, removes older `.backup-before-v...` app siblings, and clears stale update cache/workspace artifacts. The close path remains as a fallback.

## About Donation
The About dialog now shows a `Support Development` section before the workspace details, so it is visible when the dialog opens. The button uses a PayPal SVG rendered through Qt and opens:

`https://paypal.me/cosmowyn`

## Changed Files
- `ISRC_manager.py`: startup-ready update cleanup orchestration.
- `isrc_manager/update_handoff.py`: backup-sibling and update-cache cleanup helpers.
- `isrc_manager/app_dialogs.py`: About dialog support section and PayPal button.
- `tests/test_update_handoff.py`, `tests/test_update_ui_integration.py`, `tests/test_app_dialogs.py`: regression coverage.

## Validation
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_app_dialogs.py tests/test_update_handoff.py tests/test_update_ui_integration.py -q`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_update_installer.py tests/test_updater_helper.py -q`
- `.venv/bin/python -m black --check ISRC_manager.py isrc_manager/app_dialogs.py isrc_manager/update_handoff.py tests/test_app_dialogs.py tests/test_update_handoff.py tests/test_update_ui_integration.py`
- `git diff --check`
