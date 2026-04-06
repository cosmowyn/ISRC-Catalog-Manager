# Contract Template Workspace Docking Redesign Handoff

Current product version: `2.0.0`

Date: 2026-04-06

## Previous Workspace Limitations Found

- The Contract Templates workspace used one static top-level tab widget with fixed internal layouts, so users could not meaningfully resize, reorder, float, or re-dock the main work surfaces.
- The old `Admin / Archive`, `Symbol Generator`, and `Fill Form` tabs mixed large workflow sections into single stacked pages, which made long forms and multi-monitor workflows clumsy.
- The Fill Form HTML preview did not participate in a real dock layout and could not act like a professional second-monitor preview surface.
- Nested Contract Templates chrome was not part of the app's real global save/restore model, so inner layout state could not round-trip with the main window layout.
- Lazy workspace materialization meant non-visible inner workspaces were at risk of missing restore timing unless state was explicitly carried forward.
- Layout-loading progress could complete before visible surfaces were truly settled and repainted.

## Dockable / Lockable Control Groups Introduced

The workspace now keeps one outer Contract Templates dock and turns each top-level tab into a lazy inner `QMainWindow` dock workspace.

### Import

- `Import / Admin`
- `Revision Inventory`
- `Placeholder Inventory`
- `Draft Archive`
- `Snapshots / Artifacts`

`Snapshots / Artifacts` is intentionally one combined dock with an internal vertical splitter:

- top pane: snapshots table
- bottom pane: artifacts table plus artifact actions

### Symbol Generator

- `Symbol Generator`
- `Known Database Symbols`
- `Selected Symbol`
- `Manual Symbol Helper`

### Fill Form

- `Form Context`
- `Form Fields`
- `HTML Preview`

Only meaningful work surfaces became docks. Utility strips such as lock controls, panel menus, zoom buttons, and small status rows remain embedded in their owning workspace chrome or parent dock content.

## Tab Order And Naming Changes

- Top tab labels are now exactly:
  - `Import`
  - `Symbol Generator`
  - `Fill Form`
- The previous `Admin / Archive` surface is now represented as the first tab's primary dock title: `Import / Admin`.
- `focus_tab("import")` is the canonical entry point.
- `focus_tab("admin")` remains supported as a compatibility alias to `import`.

## Fill Form Two-Column Design And Preview Interaction Model

The Fill Form workspace now ships as a real two-column docked workspace:

- left column: `Form Context` above `Form Fields`
- right column: `HTML Preview`

The preview remains a true `QWebEngineView` surface and supports:

- fit-to-width auto zoom on initial load and resize until manual zoom occurs
- `Ctrl/Cmd + wheel` zoom
- native pinch / gesture zoom where available
- double-click reset-to-fit
- native mouse and trackpad scrolling
- explicit pan with `Space + left-drag` and middle-button drag
- floating / detachable preview dock placement for multi-monitor use

Dirty edits now mark the preview stale immediately so stale HTML is never shown as current. The stale state does not have to blank the preview; the last rendered page can remain visible as stale context until the refreshed render becomes current.

Live preview refresh uses a preview-only transient session path. It renders from the current editable payload but never persists draft rows, artifact rows, managed draft files, output artifacts, or template files.

If a newer edit arrives while a preview refresh is already in flight, the older result is discarded and deleted instead of replacing the active preview.

## Layout Persistence Integration Details

The redesign extends the app's real global layout persistence model rather than creating a Contract Templates-only side system.

- Outer layout persistence still uses the main-window dock-state save/restore path.
- Nested workspace chrome is now captured in an optional `workspace_panels` payload keyed by workspace dock id.
- Contract Templates exposes generic panel hooks:
  - `capture_layout_state()`
  - `restore_layout_state(state)`
- Nested Contract Templates payload stores chrome only:
  - `schema_version`
  - `current_tab`
  - per-tab `dock_state_b64`
  - per-tab `layout_locked`

No business data is stored in layout state.

- Draft payloads
- selected records
- template content
- artifacts
- export results

are all excluded from the layout model.

Non-visible tab workspaces restore safely through pending per-tab state. A tab does not need to be active during outer restore. When it is materialized later, its default docks are created in deterministic order first, then nested `restoreState()` is applied.

Older saved layouts that do not contain nested Contract Templates state remain compatible. They simply fall back to the shipped default inner layouts and default locked state.

## Layout Loading / Reloading Progress Fixes

Layout restore and named-layout switching now report real nested-workspace progress and hold final completion until visible surfaces are actually stabilized.

The restore flow now:

- applies outer dock state
- applies nested workspace panel state
- materializes visible lazy panels
- applies pending visible inner workspace state
- repaints visible outer and nested surfaces
- loops until geometry snapshots stabilize across consecutive passes, or a bounded stabilization limit is hit

If the bounded stabilization limit is reached, the app logs a warning and emits a truthful capped-stabilization progress message before finishing with the best visible state available.

Final ready / `100%` is emitted only after this visible repaint / geometry stabilization helper finishes.

## Tests Added / Updated

Updated or added coverage now verifies:

- top-level tab order is `Import`, `Symbol Generator`, `Fill Form`
- the first tab's primary dock title is `Import / Admin`
- key Contract Templates work surfaces are represented as stable inner docks
- Fill Form uses the intended two-column dock structure
- the HTML preview dock can float when unlocked
- nested Contract Templates layout state round-trips through the real global layout system
- non-visible inner tab workspaces restore when materialized later
- older saved layouts without nested Contract Templates state fall back safely to defaults
- saved-layout progress includes nested workspace restore and visual stabilization steps
- HTML preview refresh stays out of persisted draft / artifact flows
- theme builder output covers the new workspace chrome and preview surfaces
- existing import, symbol, fill-form, admin, export, and explicit false / zero value logic still behaves correctly

## Risks / Caveats

- Inner dock `objectName` values are now persistence-critical. Renaming them later is a migration-sensitive change.
- Nested restore still depends on Qt's `saveState(1)` / `restoreState(1)` contract, so future docking-policy changes should preserve that compatibility boundary.
- Preview session directories are temporary application-managed state and are cleaned best-effort. The controller prunes old sessions, but temp cleanup is still an operational area to watch if a platform refuses directory deletion.
- Final readiness waits for visible stabilization only. Non-visible lazy tabs keep pending state and restore correctly later, but they do not block startup readiness.

## Final Statement

The Contract Templates workspace now supports real user-controlled docking, tabifying, resizing, reordering, locking, and floating of meaningful internal work surfaces while preserving the existing import, symbol generation, fill-form, draft, export, and admin logic.
