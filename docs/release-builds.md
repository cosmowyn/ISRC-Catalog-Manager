# Release Build Automation

GitHub Actions builds public release packages from immutable version tags.

## Trigger

The normal release path is:

```text
push to main
version-bump workflow updates release metadata
version-bump workflow creates vX.Y.Z
release-build workflow builds and publishes packages for that tag
```

The release workflow is `.github/workflows/release-build.yml` and runs only for tags matching
`v*`. It also runs after the `Version Bump` workflow completes successfully, resolves the generated
tag from `docs/releases/latest.json`, and builds that tag when it points at the current `main` tip.
This second trigger is important because GitHub does not start new workflows from tags pushed by a
workflow using the repository `GITHUB_TOKEN`. In both paths, the resolved tag is validated as
SemVer-style before packaging.

## Platforms

Each tag build runs natively on:

- `windows-latest`
- `macos-latest`
- `ubuntu-latest`

Release builds use exact Python `3.14.4` through `actions/setup-python`. Each platform job also
asserts `sys.version_info[:3] == (3, 14, 4)` before dependency installation so public release
packages cannot silently fall back to a different interpreter. Linux installs the same Qt runtime
libraries used by CI before running tests or PyInstaller.

## QA Before Packaging

Each platform job installs the project with build and developer extras:

```bash
python -m pip install -e ".[dev,build]"
```

The build extra pins PyInstaller `6.19.0`, which keeps the packaging lane on a release with
Python 3.14.4 fixes while release builds move to exact Python 3.14.4.

Before `build.py` runs, the workflow executes:

```bash
python -m compileall -q ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests
python -m ruff check build.py isrc_manager scripts tests
python -m black --check build.py isrc_manager scripts tests
python -m mypy
python -m unittest tests.test_build_requirements tests.test_release_automation tests.test_python_314_compatibility -v
```

The broader CI workflow still runs its full grouped test matrix on repository pushes.

## Build And Assets

The platform jobs run:

```bash
python build.py
```

`build.py` cleans stale local `build/` and `dist/`, runs PyInstaller, stages the platform output
under `dist/release/`, creates an upload-ready archive under `dist/release/packages/`, and writes
`dist/release_manifest.json`.

Package names include:

- app name
- version tag
- operating system
- runner architecture
- archive type

Examples:

```text
ISRCManager-v3.3.3-windows-x64.zip
ISRCManager-v3.3.3-macos-arm64.zip
ISRCManager-v3.3.3-linux-x64.tar.gz
```

The macOS architecture follows the selected `macos-latest` runner. This workflow does not yet
produce a universal binary, DMG, code-signed app, or notarized app.

## Publishing

Matrix jobs upload their platform package as workflow artifacts. A single final `publish` job then:

1. downloads all platform artifacts,
2. chooses release notes from `docs/releases/vX.Y.Z.md`, then `RELEASE_NOTES.md`, then a minimal fallback,
3. creates `SHA256SUMS.txt`,
4. creates or updates the matching GitHub Release,
5. uploads all platform archives and checksums with `gh release upload --clobber`.

The workflow uses the repository `GITHUB_TOKEN` with `contents: write`; it is not triggered from
pull requests.

## Update Check Integration

The existing version-bump workflow continues to update `docs/releases/latest.json`, which the app
uses for update checks. Release packages are attached to the GitHub Release for the same tag, so
release notes and downloadable builds share one version identity.

## Local Verification

A maintainer can smoke-test the same package collection path locally:

```bash
python -m pip install -e ".[dev,build]"
python -m unittest tests.test_build_requirements tests.test_release_automation -v
python build.py
```

Local builds produce packages only for the current operating system.
