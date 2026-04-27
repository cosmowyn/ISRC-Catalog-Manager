# Theme Builder Stylesheet Timeout Fix

## Summary
Reduced the runtime of `tests.test_theme_builder` by avoiding full QApplication stylesheet application inside the lightweight theme-apply test host. Production behavior still applies the generated stylesheet normally through a small wrapper method.

## Root Cause
The grouped runner failure was a module timeout, not an assertion failure. The two theme-apply tests were forcing Qt to repolish the whole application stylesheet under coverage, which made the module slow enough to exceed the 300 second grouped-run boundary on slower machines.

## Changed Files
- `ISRC_manager.py`: added `_set_application_theme_stylesheet()` and routed theme application through it.
- `tests/test_theme_builder.py`: overrides the wrapper in `_ThemeApplyHost` to capture generated stylesheets instead of applying them globally.

## Validation
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_theme_builder.py::ThemeBuilderTests::test_apply_theme_with_loading_prepares_payload_before_ui_apply tests/test_theme_builder.py::ThemeBuilderTests::test_apply_theme_without_explicit_values_uses_saved_theme_settings --durations=2 -q`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group --module tests.test_theme_builder --module-timeout-seconds 300 --group-timeout-seconds 600 --coverage --verbosity 2`
- `.venv/bin/python -m black --check ISRC_manager.py tests/test_theme_builder.py`
- `git diff --check`

The grouped coverage run completed `tests.test_theme_builder` in about 52 seconds after the change.
