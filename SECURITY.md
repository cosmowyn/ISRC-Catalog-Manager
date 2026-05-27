# Security Policy

ISRC Catalog Manager is a local-first desktop application for catalog, contract,
rights, party, media, and release metadata. Security reports are welcome,
especially when they could expose catalog data, contract records, managed files,
update packages, or release artifacts.

## Supported Versions

Security fixes target the latest published release and the current `main`
branch. The canonical application version is `pyproject.toml`
`[project].version`; release notes and update metadata are generated from that
source during the production version-bump workflow.

| Version line | Security support |
| --- | --- |
| Latest published release | Supported |
| Current `main` branch | Supported for source fixes before release |
| Older releases | Best effort only when the fix is practical and low risk |

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

Security fixes should preserve the Python 3.14.4 CI posture, branch-aware
coverage measurement for `--cov=isrc_manager`, Ruff, Black, mypy, dependency
audit, and release packaging checks. If a report requires temporarily private
fix coordination, the public issue or advisory should be updated after a
release is available.

## Dependency and Build Security

The repository uses pinned Python dependencies for runtime and build
reproducibility. CI runs a Python dependency audit with `pip-audit`, and
Dependabot is configured for Python packages and GitHub Actions. Release
packages should be downloaded from the GitHub Releases page for this repository
and verified by the release manifest and checksum data published with each
release.

Cryptography-sensitive areas are in scope for security review, including
authenticity manifests, watermarking/provenance workflows, update manifests,
checksum verification, and any future signing or notarization work. Public
release packages currently publish SHA256 checksum data; this policy does not
claim platform code signing, notarization, or detached signature coverage unless
those artifacts are explicitly present on a release.

## SBOM Plan

The repository does not commit generated SBOM artifacts. For release or audit
evidence, generate a CycloneDX SBOM from the installed Python environment as a
manual CI-ready step:

```bash
python -m pip install cyclonedx-bom
python -m cyclonedx_py environment --spec-version 1.6 --output-format JSON -o sbom.cdx.json
```

Review the generated `sbom.cdx.json`, attach it to the relevant release or
audit record if needed, and do not commit it to the source tree.
