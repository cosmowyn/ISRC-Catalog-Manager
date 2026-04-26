# Cross-Platform GitHub Release Builds Handoff

Date: 2026-04-26

## Summary

GitHub Actions now has a tag-triggered release packaging workflow for Windows, macOS, and Linux.
When a `vX.Y.Z` tag is pushed, native runner jobs build platform packages with `build.py`, upload
those packages as workflow artifacts, and a single publish job creates or updates the matching
GitHub Release with the archives and `SHA256SUMS.txt`.

## Files Changed

- `.github/workflows/release-build.yml`
  - Adds native `windows-latest`, `macos-latest`, and `ubuntu-latest` release builds on `v*` tags.
  - Runs compile, Ruff, Black, mypy, release automation tests, and build packaging tests before
    PyInstaller packaging.
  - Publishes downloaded platform artifacts from one final job to avoid matrix release-upload races.
- `build.py`
  - Adds architecture-aware release asset naming.
  - Creates upload-ready `.zip` packages for Windows/macOS and `.tar.gz` packages for Linux.
  - Extends `dist/release_manifest.json` with architecture, package path, and release asset name.
- `tests/test_build_requirements.py`
  - Covers architecture normalization, release asset naming, manifest package metadata, zip
    packaging, and tarball packaging.
- `README.md`
  - Documents compressed release packages and tag-triggered GitHub Release builds.
- `docs/README.md`
  - Links to the release-build automation guide.
- `docs/release-builds.md`
  - Adds maintainer documentation for trigger behavior, platform matrix, QA, package naming,
    publishing, checksums, update-check integration, and limitations.
- `.gitignore`
  - Ignores generated `*.egg-info/` metadata from editable installs.

## Release Trigger Behavior

The workflow runs on:

```yaml
on:
  push:
    tags:
      - "v*"
```

Each build job validates the tag as SemVer-style `vX.Y.Z` before building. The existing
`version-bump.yml` workflow already creates these tags after updating `pyproject.toml`,
`isrc_manager/version.py`, `docs/releases/`, `RELEASE_NOTES.md`, and `docs/releases/latest.json`.

## Platform Matrix

The release build matrix covers:

- `windows-latest`
- `macos-latest`
- `ubuntu-latest`

Linux installs the Qt runtime packages already used by the CI test matrix.

## Python Version

Release builds use Python `3.13`, matching the repository's current primary CI packaging smoke
coverage. Local verification was also run with the repo `.venv`, which is Python `3.14.4`.

## Dependency Installation

Each platform job installs:

```bash
python -m pip install -e ".[dev,build]"
```

This uses the existing `pyproject.toml` optional extras and keeps PyInstaller versioning centralized.

## QA Before Packaging

Each release build job runs:

```bash
python -m compileall -q ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests
python -m ruff check build.py isrc_manager scripts tests
python -m black --check build.py isrc_manager scripts tests
python -m mypy
python -m unittest tests.test_build_requirements tests.test_release_automation -v
```

The existing CI workflow still runs the broader grouped test matrix on pushes.

## Build Command

Each platform job runs:

```bash
python build.py
```

`build.py` cleans `build/` and `dist/`, runs PyInstaller, stages the output under `dist/release/`,
creates a package under `dist/release/packages/`, and writes `dist/release_manifest.json`.

## Asset Naming

Assets are named:

```text
ISRCManager-v<version>-<platform>-<architecture>.<archive>
```

Examples:

```text
ISRCManager-v3.3.3-windows-x64.zip
ISRCManager-v3.3.3-macos-arm64.zip
ISRCManager-v3.3.3-linux-x64.tar.gz
```

The architecture comes from the native runner. macOS currently follows `macos-latest`; the workflow
does not yet create a universal app.

## GitHub Release Publishing

Matrix jobs upload packages as workflow artifacts. The `publish` job downloads the artifacts, creates
`SHA256SUMS.txt`, then uses GitHub CLI with the repository `GITHUB_TOKEN` to create or update the
release and upload assets with `--clobber`.

The workflow uses:

```yaml
permissions:
  contents: write
```

It does not publish from pull requests.

## Release Notes Source

The publish job chooses release notes in this order:

1. `docs/releases/vX.Y.Z.md`
2. `RELEASE_NOTES.md`
3. Minimal fallback text

## Checksums

`SHA256SUMS.txt` is generated from the final downloaded platform archives and attached to the same
GitHub Release.

## Update Check Interaction

The app's updater continues to read `docs/releases/latest.json`. The release-build workflow attaches
the downloadable packages to the GitHub Release for the same tag, keeping release notes, update
metadata, and platform packages aligned by version.

## Tests Added Or Changed

`tests/test_build_requirements.py` now validates:

- common runner architecture normalization,
- release asset basename format,
- manifest package fields,
- macOS/Windows-style zip package creation,
- Linux tarball package creation,
- main build flow coordination with the new package and manifest steps.

## Local QA

Passed locally:

```bash
.venv/bin/python -m unittest tests.test_build_requirements tests.test_release_automation -v
.venv/bin/python -m py_compile build.py tests/test_build_requirements.py
.venv/bin/python -m compileall -q ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests
.venv/bin/python -m ruff check build.py isrc_manager scripts tests
.venv/bin/python -m black --check build.py isrc_manager scripts tests
.venv/bin/python -m mypy
.venv/bin/python -m PyInstaller --version
ruby -e 'require "yaml"; YAML.load_file(ARGV.fetch(0)); puts "YAML parsed"' .github/workflows/release-build.yml
git diff --check
```

Also passed a full local macOS PyInstaller build:

```bash
.venv/bin/python build.py
```

That produced:

```text
dist/release/packages/ISRCManager-v3.3.3-macos-arm64.zip
```

## Known Limitations

- The release workflow has not run online yet; it will run after these changes are pushed and a new
  `vX.Y.Z` tag is created.
- macOS output is not code signed, notarized, packaged as a DMG, or built as a universal binary.
- Windows output is zipped rather than packaged as an installer or MSIX.
- Linux output is a tarball rather than AppImage, deb, rpm, or Flatpak.
- Release assets are attached to GitHub Releases; the in-app updater does not yet download and
  install platform packages automatically.

## Future Improvements

- Add code signing and notarization for macOS.
- Add Windows signing and installer generation.
- Add a Linux AppImage or distro package path.
- Add a release metadata extension that advertises platform download URLs directly to the app.
- Consider macOS universal builds if both x64 and arm64 artifacts become a product requirement.
