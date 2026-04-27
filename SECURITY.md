# Security Policy

ISRC Catalog Manager is a local-first desktop application for catalog, contract,
rights, party, media, and release metadata. Security reports are welcome,
especially when they could expose catalog data, contract records, managed files,
update packages, or release artifacts.

## Supported Versions

Security fixes target the latest published release. When practical, fixes may
also be applied to the previous minor release line, but users should expect the
latest release to receive priority for vulnerability fixes and dependency
updates.

## Reporting a Vulnerability

Please do not publish exploitable details in a public issue before the problem
has been triaged.

Preferred reporting paths:

- Use GitHub private vulnerability reporting or a private GitHub Security
  Advisory for this repository when available.
- If private reporting is not available, open a public issue with a minimal
  title such as "Security contact request" and avoid including sensitive
  technical details, sample catalog data, credentials, or private documents.

Useful report details:

- affected version and operating system
- whether the app was run from source or from a packaged release
- impact, such as data disclosure, arbitrary file write, unsafe update
  behavior, code execution, or package integrity failure
- reproduction steps using synthetic data
- any relevant logs, with personal catalog data removed

## Response Expectations

The project aims to acknowledge reports within 7 days and provide an initial
triage result within 14 days. Confirmed vulnerabilities will be fixed in source
first, then shipped in the next practical packaged release.

## Dependency and Build Security

The repository uses pinned Python dependencies for runtime and build
reproducibility. CI runs a Python dependency audit with `pip-audit`, and
Dependabot is configured for Python packages and GitHub Actions. Release
packages should be downloaded from the GitHub Releases page for this repository
and verified by the release manifest and checksum data published with each
release.
