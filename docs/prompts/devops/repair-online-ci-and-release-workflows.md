# Repair online CI and release workflows

## Category

devops

## Original prompt, cleaned

Commit and push everything to `main`. Check the push: the online CI Actions are
failing. Fix all failures and track subsequent pushes until all CI tests and
online Actions workflows are successful.

## Context preserved

- Direct commits and pushes to `main` were explicitly authorised.
- Inspect the real GitHub Actions runs, logs, and failure artifacts.
- Implement and verify fixes rather than only reporting failures.
- Continue monitoring replacement pushes, tag validation, release builds, Help
  publication, and Pages until the complete online workflow surface is green.

## Redactions

None
