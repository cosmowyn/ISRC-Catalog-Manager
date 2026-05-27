# QA Scope Governance

This document records intentional static-analysis and coverage scope decisions for the Python
`3.14.4` QA lane. It does not weaken the configured gates.

## mypy Scope

`pyproject.toml` keeps `follow_imports = "skip"` intentionally. This avoids turning a targeted
typed-module gate into a broad PySide6/UI migration while the project is still improving coverage
and controller boundaries.

The current mypy file list focuses on:

- domain helpers and domain models
- structured model modules
- selected service modules with stable type surfaces
- update/version helpers

This pass expanded mypy only for low-risk modules that already pass under the existing settings:

- `isrc_manager/assets/models.py`
- `isrc_manager/contracts/models.py`
- `isrc_manager/domain/repertoire.py`
- `isrc_manager/forensics/models.py`
- `isrc_manager/parties/models.py`
- `isrc_manager/promo_codes/models.py`
- `isrc_manager/rights/models.py`
- `isrc_manager/search/models.py`
- `isrc_manager/services/gs1_models.py`
- `isrc_manager/services/track_artist_sql.py`
- `isrc_manager/works/models.py`

Staged expansion plan:

1. Domain/models: add remaining dataclass and pure normalization modules first.
2. Services: add narrow repository/service helpers after row-shape and optional-value typing is
   clarified.
3. Controllers: add workflow controllers after host protocols are stable.
4. UI/dialogs: add PySide6-heavy modules last, grouped by feature, because Qt enum and signal
   stubs still create noisy type work.

Modules tried but deferred in this pass include `selection_scope.py`, `services/schema.py`,
`services/import_governance.py`, `services/import_repair_queue.py`, and
`services/repertoire_status.py`.

## Coverage Omission Rationale

Coverage remains scoped to `--cov=isrc_manager` only. Do not add `--cov=ISRC_manager`. The strict
coverage report still keeps branch coverage enabled and the configured fail-under remains `95`.

Current `[tool.coverage.run].omit` entries:

| File | Current rationale | Follow-up |
| --- | --- | --- |
| `isrc_manager/app_dialogs.py` | GUI-heavy application dialogs with modal prompts, rich Qt layout, environment/about/help/update surfaces, and several paint/layout-adjacent branches. Some behavior is tested elsewhere, but measuring every branch now would add brittle GUI coverage. | Reintroduce by extracting prompt/update/help logic into testable helpers and adding headless dialog state tests. |
| `isrc_manager/assets/dialogs.py` | GUI-heavy asset editor/registry dialogs with file pickers, message boxes, table widgets, and storage-mode UI. | Reintroduce after service-backed payload, duplicate/conflict, and file-picker cancellation tests are in place. |
| `isrc_manager/contracts/dialogs.py` | GUI-heavy contract dialogs with file IO, template comparison, table widgets, and cross-feature party/code-registry selection. | Reintroduce in focused batches around validation, file-picker cancellation, managed-file failure, and payload construction. |
| `isrc_manager/parties/dialogs.py` | GUI-heavy party dialogs with import/export, menus, prompts, and table-widget state. | Reintroduce after party import/export and duplicate/conflict branches are covered through direct widget assertions. |
| `isrc_manager/gs1_dialog.py` | GUI-heavy GS1 editor/export dialog with validation, file dialogs, template dependencies, and table-widget interactions. | Reintroduce after GS1 service behavior remains covered and dialog tests can focus on user-decision and export failure paths. |
| `isrc_manager/history/dialogs.py` | GUI-heavy history/snapshot UI with destructive prompts and table state. Core history behavior is better measured through services first. | Reintroduce with fake app/history services for undo/redo, cleanup, and blocked-cleanup prompt behavior. |
| `isrc_manager/rights/dialogs.py` | GUI-heavy rights matrix dialogs with linked party/contract selectors, duplicate/conflict prompts, and table-widget state. | Reintroduce after service conflict paths and direct editor payload assertions are covered. |
| `isrc_manager/tags/dialogs.py` | GUI-heavy tag preview/conflict dialogs with policy choices, party authority lookups, and table state. | Reintroduce through focused conflict-resolution and invalid-tag policy tests. |
| `isrc_manager/tasks/history_helpers.py` | Background-task history helper with rollback/cleanup branches that are valuable but require dedicated fake history managers and filesystem-state failure cases. | Should be reintroduced later with rollback, cleanup failure, no-op history, and file-state mutation tests. |

No new coverage omissions were added in this pass. The omitted files should be reintroduced through
meaningful behavioral tests, not by chasing paint-only, impossible-layout, or platform-defensive
branches.
