# Python 3.14.4 CI Compatibility Handoff

Date: 2026-04-26

## Summary

Python 3.14.4 is now an explicit compatibility and release-packaging target while preserving the
existing Python 3.10 minimum runtime and Python 3.13 CI lane. Release packages are built online
with exact Python 3.14.4 on Windows, macOS, and Linux.

## Files Changed

- `.github/workflows/ci.yml`
  - Adds Python 3.14.4 to compile coverage.
  - Runs Ruff, Black, and mypy on Python 3.13 and 3.14.4.
  - Adds a Python 3.14.4 `catalog-services` test shard.
  - Moves packaging smoke to Python 3.14.4 and includes the new compatibility tests.
  - Installs Linux Qt runtime libraries for packaging smoke because the compatibility tests import
    PySide6-backed modules.
- `.github/workflows/release-build.yml`
  - Builds release packages with exact Python 3.14.4.
  - Verifies `sys.version_info[:3] == (3, 14, 4)` before dependency installation.
  - Runs the Python 3.14.4 compatibility tests before packaging on Windows, macOS, and Linux.
- `pyproject.toml`
  - Adds Python 3.14 classifier while keeping `requires-python = ">=3.10"`.
  - Pins build extra to `pyinstaller==6.19.0`.
  - Adds missing setuptools package entries for `isrc_manager.catalog_table` and
    `isrc_manager.code_registry`.
- `requirements.txt`
  - Mirrors the PyInstaller 6.19.0 pin.
- `build.py`
  - Preserves suffixes on staged directory artifacts, so macOS release zips contain a real `.app`
    bundle instead of a suffixless folder.
- `isrc_manager/versioning.py`
  - Adds a SemVer hash consistent with equality that ignores build metadata.
- `scripts/release_automation.py`
  - Restricts pyproject version rewrites to the `[project]` section.
- `tests/test_python_314_compatibility.py`
  - Adds Python 3.14 metadata, release workflow, dependency, package metadata, runtime import, and
    SQLite schema initialization checks.
- `tests/test_build_requirements.py`
  - Covers macOS `.app` suffix preservation and packaged zip layout.
- `tests/test_release_automation.py`
  - Covers section-safe pyproject version updates.
- `tests/test_versioning.py`
  - Covers SemVer hash/equality consistency for build metadata.
- `tests/ci_groups.py`
  - Adds the new compatibility test module to `catalog-services`.
- `README.md`, `docs/release-builds.md`,
  `docs/implementation_handoffs/cross-platform-github-release-builds.md`
  - Documents Python 3.14.4 compatibility and release packaging behavior.

## Supported Python Policy

- Minimum supported source runtime: Python 3.10.
- Primary compatibility lane retained: Python 3.13.
- Current compatibility and release packaging lane: exact Python 3.14.4.
- Ruff, Black, and mypy still target Python 3.10 syntax/type assumptions so the minimum runtime is
  not accidentally raised by tooling.

## Python 3.14.4 Testing

CI now validates Python 3.14.4 through:

- compile job matrix
- Ruff, Black, and mypy matrices
- `catalog-services` grouped test shard
- packaging smoke
- release-build matrix for Windows, macOS, and Linux

Release builds pin exact `3.14.4`, not floating `3.14.x`.

## Dependency Compatibility

- PyInstaller moved from 6.15.0 to 6.19.0 so the build lane includes fixes that mention
  Python 3.14.4 compatibility in PyInstaller's upstream changelog.
- Existing runtime pins install and import locally under Python 3.14.4:
  - PySide6 6.11.0
  - pillow 12.0.0
  - numpy 2.2.6
  - scipy 1.15.3
  - soundfile 0.13.1
  - cryptography 46.0.5

No lock file is used by this repository.

## Build And Packaging Notes

`build.py` was validated locally under Python 3.14.4 with PyInstaller 6.19.0. The generated macOS
release package contains `ISRCManager-3.4.0-macos.app/Contents/Info.plist`.

## QA

```bash
.venv/bin/python -m pip install -e '.[dev,build]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_python_314_compatibility tests.test_versioning tests.test_release_automation tests.test_build_requirements -v
.venv/bin/python -m tests.ci_groups catalog-services --verify
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
.venv/bin/python -m compileall -q ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests
.venv/bin/python -m PyInstaller --version
QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group catalog-services --coverage --module-timeout-seconds 120 --group-timeout-seconds 600
QT_QPA_PLATFORM=offscreen .venv/bin/python build.py
```

Results:

- Targeted compatibility/build/version tests passed: 52 tests.
- Group ownership verification passed.
- Ruff, Black, mypy, and compileall passed.
- PyInstaller reported `6.19.0`.
- Python 3.14.4 `catalog-services` shard passed in 47 seconds.
- Local macOS package build passed with Python 3.14.4 and PyInstaller 6.19.0.

## Limitations

- Full UI/app-shell grouped tests were not rerun locally in this pass; they remain covered by the
  existing CI 3.13 shard. The new Python 3.14.4 shard intentionally covers service/runtime,
  packaging, imports, release automation, and SQLite schema compatibility without duplicating the
  heaviest Qt WebEngine UI lane.
- GitHub Actions execution of exact Python 3.14.4 must still be observed after push.

## Future Recommendations

- Once GitHub 3.14.4 CI has run green for several releases, consider moving more non-UI shards to
  Python 3.14.4.
- Revisit UI/app-shell Python 3.14.4 coverage after any upstream PySide6/Qt WebEngine offscreen
  instability has settled.
