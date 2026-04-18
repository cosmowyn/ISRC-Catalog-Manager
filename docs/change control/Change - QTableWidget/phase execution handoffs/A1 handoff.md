# Phase A1 Handoff

## Scope executed

This pass executed **Phase A1 only** from `docs/change control/Change - QTableWidget/Engineering plan.md`.

The work stayed inside the approved A1 scaffolding scope:

- created the new `isrc_manager/catalog_table/` package
- created all approved A1 module files
- created a public package surface through `isrc_manager/catalog_table/__init__.py`
- kept the new package importable and structurally real
- did **not** wire any production runtime path to the new package
- did **not** start any A2, A3, or Phase B implementation

## What was created and why

The following files were created to establish the catalog-table migration surface without changing live behavior:

- `isrc_manager/catalog_table/__init__.py`
  - exposes the approved public package surface for later phases
- `isrc_manager/catalog_table/models.py`
  - defines the planned snapshot dataclasses and role constants:
    - `CatalogColumnSpec`
    - `CatalogCellValue`
    - `CatalogRowSnapshot`
    - `CatalogSnapshot`
    - `SortRole`
    - `SearchTextRole`
    - `TrackIdRole`
    - `ColumnKeyRole`
    - `RawValueRole`
- `isrc_manager/catalog_table/table_model.py`
  - adds an import-safe `CatalogTableModel(QAbstractTableModel)` scaffold
  - includes the approved public methods:
    - `set_snapshot()`
    - `column_spec()`
    - `track_id_for_source_row()`
    - `source_row_for_track_id()`
  - keeps `data()` intentionally dormant so no live model behavior was pulled forward
- `isrc_manager/catalog_table/filter_proxy.py`
  - adds an import-safe `CatalogFilterProxyModel(QSortFilterProxyModel)` scaffold
  - includes the approved public methods:
    - `set_search_text()`
    - `set_search_column_key()`
    - `set_explicit_track_ids()`
  - keeps `filterAcceptsRow()` intentionally permissive and dormant
- `isrc_manager/catalog_table/header_state.py`
  - adds `CatalogHeaderStateManager`
  - uses explicit `NotImplementedError` placeholders so the later A3 landing zone is clear without pretending the logic exists
- `isrc_manager/catalog_table/controller.py`
  - adds `CatalogTableController(QObject)`
  - stores only minimal bindings and leaves live selection/context/double-click behavior for later phases
- `isrc_manager/catalog_table/zoom.py`
  - adds `CatalogZoomController(QObject)`
  - records the planned zoom constants and a minimal dormant state holder only

## Files added

- `isrc_manager/catalog_table/__init__.py`
- `isrc_manager/catalog_table/models.py`
- `isrc_manager/catalog_table/table_model.py`
- `isrc_manager/catalog_table/filter_proxy.py`
- `isrc_manager/catalog_table/header_state.py`
- `isrc_manager/catalog_table/controller.py`
- `isrc_manager/catalog_table/zoom.py`
- `docs/change control/Change - QTableWidget/phase execution handoffs/A1 handoff.md`

## Files modified

No existing application/runtime files were modified for the scaffolding pass.

Per the execution prompt, `docs/change control/Milestones.md` is updated immediately after this handoff as the required append-only completion record.

## Existing files touched and why

No existing production code files were touched.

The repository was inspected only as needed to keep the scaffolding aligned with current conventions:

- `docs/change control/Change - QTableWidget/Engineering plan.md`
  - source of truth for scope and structure
- `isrc_manager/__init__.py`
  - package convention check
- `isrc_manager/code_registry/__init__.py`
  - public surface / `__all__` convention check
- `isrc_manager/code_registry/models.py`
  - dataclass / model convention check
- `isrc_manager/selection_scope.py`
  - current typing/docstring/layout style check
- `ISRC_manager.py`
  - limited inspection of current catalog dataset and table methods to avoid speculative scaffolding
- `pyproject.toml`
  - package and Python-version convention check only

## Scope control and why this remained A1-only

The implementation was kept deliberately shallow:

- no import was added from live runtime code to `isrc_manager.catalog_table`
- no existing shell construction or widget wiring was changed
- no `QTableWidget` logic was replaced
- no proxy filtering logic was implemented
- no model role population logic was implemented
- no header persistence logic was implemented
- no controller cutover logic was implemented
- no zoom application/persistence logic was implemented
- no deprecation markers were added to monolith functions
- no cleanup or removal of monolith logic was performed

Where a later phase needs real behavior, the scaffolding either:

- stores harmless dormant state only, or
- raises `NotImplementedError` with a phase-specific message

That choice was intentional to make the surface auditable without silently starting A2/A3 work early.

## What was intentionally not implemented yet

The following planned work remains unimplemented by design:

- `CatalogTableModel.data()` role handling
- real snapshot-to-model display/sort/search role projection
- proxy-backed search/filter/sort behavior
- header state save/restore compatibility logic
- controller selection, context menu, double-click, and export semantics
- zoom throttling, view-density application, wheel/pinch handling, and layout persistence
- any shell/runtime cutover from `QTableWidget` to `QTableView`
- any production dependency on the new package

## Dormant imports and seams

No dormant imports or seams were introduced into existing live runtime files.

The only intentional dormant seam is the new internal package surface itself:

- package-level re-exports in `isrc_manager/catalog_table/__init__.py`
- type-only Qt imports in modules that need future widget/header/view annotations

## QA checks performed

The following A1-scoped validation was run:

- `python3 -m py_compile isrc_manager/catalog_table/__init__.py isrc_manager/catalog_table/models.py isrc_manager/catalog_table/table_model.py isrc_manager/catalog_table/filter_proxy.py isrc_manager/catalog_table/header_state.py isrc_manager/catalog_table/controller.py isrc_manager/catalog_table/zoom.py`
  - passed
- `python3` import smoke covering package import plus minimal instantiation of:
  - `CatalogSnapshot`
  - `CatalogTableModel`
  - `CatalogFilterProxyModel`
  - `CatalogHeaderStateManager`
  - `CatalogTableController`
  - `CatalogZoomController`
  - passed
- runtime dependency scan for:
  - `isrc_manager.catalog_table`
  - `CatalogTableModel`
  - `CatalogFilterProxyModel`
  - `CatalogHeaderStateManager`
  - `CatalogTableController`
  - `CatalogZoomController`
  - no references found outside `isrc_manager/catalog_table/`

## QC checks performed

- confirmed the engineering plan was read first
- confirmed the work stayed inside the A1 batch
- confirmed only approved A1 package files were created under `isrc_manager/catalog_table/`
- confirmed no live runtime path was switched to the new package
- confirmed no A2/A3/Phase B logic was implemented
- confirmed the new modules are importable and structurally aligned with the plan
- confirmed no worker agents were used, so there was no worker scope drift and no worker cleanup required

## Live behavior status

Live behavior was **not** cut over.

The application still depends on the existing `QTableWidget` path. The new package is present but runtime-dormant.

## Risks and follow-up notes for A2/A3

- `pyproject.toml` currently maintains an explicit package list under `[tool.setuptools]`.
  - `isrc_manager.catalog_table` was **not** added during A1 because the prompt constrained work to the new package plus documentation and forbade widening scope.
  - If build/distribution packaging needs to include the new package before later phases, that metadata will need an intentional follow-up change.
- The current `CatalogSnapshot` / `CatalogCellValue` shapes are intentionally conservative.
  - A2 can refine field usage while keeping the public names stable.
- `CatalogTableModel` currently exposes row/column/header structure and track-id mapping only.
  - A2 still owns real role/data behavior.
- `CatalogFilterProxyModel` currently records requested filter state but does not apply it.
  - A2 still owns proxy semantics.
- `CatalogHeaderStateManager`, `CatalogTableController`, and `CatalogZoomController` are explicit landing zones only.
  - A3 still owns their real implementation.

## Repo-specific conventions discovered

- the codebase uses `from __future__ import annotations` broadly in typed modules
- Qt usage is based on `PySide6`
- internal domain/model modules commonly use `@dataclass(..., slots=True)`
- package surfaces commonly expose a curated `__all__`
- the repository currently targets Python `>=3.10`
- build packaging uses a static setuptools package list rather than automatic package discovery

## Ready state for next phase

Phase A1 leaves the repository ready for:

- A2 implementation of `models.py`, `table_model.py`, and `filter_proxy.py` as pure standalone units
- A3 implementation of `header_state.py`, `controller.py`, and `zoom.py` without live wiring

No rediscovery of package/file layout should be required for the next pass.
