# Splash Version Stamping And Overlay Polish

Date: 2026-04-17

## What changed

- `build.py` now stamps the packaged splash image at build time using the version from `pyproject.toml`.
- The stamped label format is:
  - `Version: x.x.x-ddmmyyyy.seconds_since_midnight`
- The stamp is written into `build/generated_assets/splash.png` so the source splash asset stays unchanged.
- The runtime splash overlay was refined so it no longer paints a solid background card.
- Only the splash-screen loading text and percentage are recolored to `RGB(85, 100, 117)`.
- The progress bar remains inset from the splash edges and keeps its own bar colors.

## Files touched

- `build.py`
- `isrc_manager/startup_splash.py`
- `tests/test_build_requirements.py`
- `tests/test_startup_splash.py`

## Validation

- `python3 -m unittest tests.test_build_requirements`
- `python3 -m unittest tests.test_startup_splash`

## Notes

- Splash stamp placement is aligned from the divider line detected in the artwork, with a fallback position if the line cannot be detected.
- The splash overlay changes are scoped to `isrc_manager/startup_splash.py`; other loading screens were not recolored.
