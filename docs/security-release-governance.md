# Security, Release, And Governance Status

This document records the current governance alignment for the Python 3.14.4 release lane.

## CI Status

Checked on `2026-05-27` with GitHub Actions for `cosmowyn/ISRC-Catalog-Manager` on `main`.

- Latest `CI` run before this pass: green, run `26476792637`.
- Latest `Version Bump` run before this pass: green, run `26476792520`.
- Latest `Dependency Graph` run before this pass: green, run `26476809111`.
- Latest `Release Builds` run before this pass: green, run `26476809881`.

No red online CI job was observed during the pre-change audit, so no failure-specific CI fix was
made. CI gates must stay strict: Python `3.14.4`, compileall, Ruff, Black, mypy, grouped tests,
dependency audit, branch-aware coverage, and release packaging checks should not be weakened to make
governance changes pass.

## Version And Dependency Sources

`pyproject.toml` `[project].version` is the canonical application version. The production
version-bump workflow updates that value, regenerates release metadata, and runs
`scripts/sync_version_docs.py --check` so current public version markers fail fast if they drift.

Current public references are intentionally limited to:

- `README.md` marker block
- `docs/release-builds.md` marker block
- `RELEASE_NOTES.md` current release header
- `docs/releases/latest.json`

Historical `docs/releases/vX.Y.Z.md` files, changelog history, examples, and implementation
handoffs are not rewritten as current documentation.

PyInstaller is pinned consistently in `pyproject.toml` and `requirements.txt`; release-build docs
refer to that shared pin instead of carrying a separate dependency version claim.

## Release Availability

The latest GitHub Release observed before this pass was `v3.16.0`, published on `2026-05-26`, with
downloadable assets for:

- Windows x64: `ISRCManager-v3.16.0-windows-x64.zip`
- macOS arm64: `ISRCManager-v3.16.0-macos-arm64.zip`
- Linux x64: `ISRCManager-v3.16.0-linux-x64.tar.gz`
- release-scoped `latest.json`
- `SHA256SUMS.txt`

The correct public user download route is the repository's GitHub Releases page:
`https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/latest`.

If a future release is missing one or more platform archives, `latest.json`, or checksums, do not
claim release availability. Re-run or repair the `Release Builds` workflow, verify all expected
assets, and document the missing platform or manifest before announcing the release.

## Branch Ownership

`.github/CODEOWNERS` is present for documentation and accountability only:

```text
* @movdkleut
```

Branch protection, required pull requests, required code-owner review, restricted pushes, and
rulesets are intentionally not configured in this pass, so direct maintainer/Codex pushes to `main`
are not blocked by the CODEOWNERS file.

Recommended future branch protection when collaborators are added:

- require the `CI` workflow to pass before merge
- require the release/version metadata check for release-bound changes
- require at least one approving review for non-maintainer PRs
- require CODEOWNERS review only after collaborators and emergency bypass rules are defined
- keep administrator or maintainer bypass documented for urgent security releases
