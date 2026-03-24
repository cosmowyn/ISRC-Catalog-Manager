# Kaizen UI Workflow Streamlining Handoff

Date: 2026-03-24

## Status

This handoff documents the completed KAIZEN UI and workflow streamlining pass implemented on 2026-03-23, plus the follow-up cohesion updates completed on 2026-03-24 for diagnostics, progress overlays, derivative-ledger discoverability, ledger drill-ins, and font-stack cleanup.

The pass is intentionally narrow:

- regroup the main menus around real user workflows instead of historical action placement
- apply only a small set of user-facing renames where the old wording was actively noisy or misleading
- unify workspace panel opening so docked tools behave the same way and expose consistent panel attributes
- shorten the catalog row context menu by moving repeated action families into named submenus
- compact the highest-friction dense surfaces instead of trying to restyle every dialog in one pass
- finish the follow-up pass by making diagnostics scroll-safe, exposing history storage budget status directly inside diagnostics, widening long-running progress overlays, and making the derivative ledger reachable as an explicit workspace entry
- finish the second follow-up pass by adding derivative-ledger drill-ins, auditing the remaining custom loading overlays, and removing the hardcoded help-font fallback that triggered Qt alias warnings during tests
- keep test changes focused on menu structure, context menus, workspace panels, dialog sizing behavior, and theme preview behavior

This is not a broad terminology rewrite, not a full visual redesign, and not a shell architecture replacement.

## 1. Original Scatter / Clutter Findings

The highest-friction scatter patterns found in the codebase before implementation were:

- `File` mixed profile lifecycle, import/export workflows, and audio utilities in the same flat surface.
- `Catalog` exposed related workflows as separate historical islands instead of one intention-led hierarchy.
- workspace tools opened through slightly different code paths and stored inconsistent `*_dialog` references even when they were dock panels.
- the catalog row context menu mixed editing, licensing, audio delivery, authenticity, storage conversion, and file actions in one long scan path.
- track-facing actions still used `Entry` language in several high-frequency places, which blurred the user’s real mental model.
- dense dialogs, especially settings, spent too much width on permanently exposed helper copy and side-by-side layout instead of the active task.

## 2. Top-Level Workflow Map

The current app organizes around these top-level workflows:

- profile and storage lifecycle
- track entry and editing
- docked repertoire workspaces
- metadata and standards operations
- audio import, delivery, and authenticity
- history, diagnostics, and recovery

The primary user flows surfaced in code are:

- add or edit tracks in the main catalog
- move into releases, works, parties, contracts, rights, and deliverables from the same workspace shell
- import/export catalog and exchange data
- attach media, export derivatives, and verify authenticity
- repair or inspect quality, diagnostics, and history state

## 3. Menu / Entry-Point Restructuring

This pass keeps the top-level menu bar stable and restructures the menu contents around user intent.

## Main Information Architecture

### File menu

`File` is now grouped into four workflow buckets:

1. `Profiles`
2. `Import & Exchange`
3. `Export`
4. `Profile Maintenance`

The intent is:

- profile switching and lifecycle actions stay together
- inbound exchange flows read as imports instead of living beside maintenance actions
- outbound exchange flows read as exports instead of being split between unrelated top-level menus
- backup, restore, and integrity operations are clearly maintenance work on the current profile

The implemented `File` breakdown is:

- `Profiles`
  - `New Profile…`
  - `Open Profile…`
  - `Reload Profile List`
  - `Remove Selected Profile…`
- `Import & Exchange`
  - `Import Catalog XML…`
  - `Catalog Exchange >`
    - `Import CSV…`
    - `Import XLSX…`
    - `Import JSON…`
    - `Import ZIP Package…`
    - `Reset Saved Import Choices…`
  - `Contracts and Rights >`
    - `Import Contracts and Rights JSON…`
    - `Import Contracts and Rights XLSX…`
    - `Import Contracts and Rights CSV Bundle…`
    - `Import Contracts and Rights ZIP Package…`
- `Export`
  - `Export Selected Catalog XML…`
  - `Export Full Catalog XML…`
  - `Catalog Exchange >`
    - selected and full CSV, XLSX, JSON, ZIP package variants
  - `Contracts and Rights >`
    - JSON, XLSX, CSV bundle, ZIP package variants
- `Profile Maintenance`
  - `Backup Database`
  - `Restore from Backup…`
  - `Verify Integrity`

`Quit` remains a direct `File` action after the grouped sections.

### Catalog menu

`Catalog` is now organized around daily workspace flow instead of legacy action accumulation.

The new top-level grouping is:

1. `Workspace`
2. `Metadata & Standards`
3. `Legacy`
4. `Audio`
5. `Quality & Repair`

The implemented `Catalog` breakdown is:

- `Workspace`
  - `Catalog Managers…`
  - `Release Browser…`
  - `Work Manager…`
  - `Party Manager…`
  - `Contract Manager…`
  - `Rights Matrix…`
  - `Deliverables & Asset Versions…`
  - `Derivative Ledger…`
  - `Global Search and Relationships…`
  - `Show Add Track Panel`
  - `Show Catalog Table`
- `Metadata & Standards`
  - `GS1 Metadata…`
- `Legacy`
  - `Legacy License Archive >`
    - `License Browser…`
    - `Migrate Legacy Licenses to Contracts…`
- `Audio`
  - `Import & Attach >`
    - `Bulk Attach Audio Files…`
    - `Import Metadata from Audio Files…`
  - `Delivery & Conversion >`
    - `Export Audio Derivatives…`
    - `Convert External Audio Files…`
    - `Export Tagged Audio Copies…`
  - `Authenticity & Provenance >`
    - `Export Authentic Masters…`
    - `Export Provenance Copies…`
    - `Export Forensic Watermarked Audio…`
    - `Inspect Forensic Watermark…`
    - `Verify Audio Authenticity…`
- `Quality & Repair`
  - `Data Quality Dashboard…`

Two intentional outcomes matter here:

- workspace tools now read like one docked operating surface instead of separate modal-era features
- audio actions are grouped by import, delivery, and authenticity rather than mixed with metadata and legacy operations
- the derivative export ledger is no longer hidden behind the deliverables surface alone; it now has a direct workspace entry that opens the same deliverables dock on the ledger tab

## 4. Naming Normalization Decisions

This pass deliberately keeps renames limited to places where wording was causing friction.

Implemented wording changes include:

- `Show Add Data Panel` -> `Show Add Track Panel`
- `Asset Version Registry…` -> `Deliverables & Asset Versions…`
- table and row action wording shifted from generic `Entry` language to `Track` language where the action is explicitly track-scoped
- storage wording is exposed as direct user outcomes instead of hidden inside mixed file-action stacks

Concrete track-language updates now visible in the shell:

- `Delete Selected Entry` -> `Delete Selected Track`
- context menu `Edit Entry` -> `Edit Track`
- context menu bulk edit copy now reads `Bulk Edit <n> Selected Tracks…`
- context menu `Delete Entry` -> `Delete Track`

Concrete storage labels now visible in the row context menu:

- `Store in Database`
- `Store as Managed File`

This is intentionally not a full vocabulary rewrite. The pass does not rename every internal object, every help chapter, or every historic service class.

## Shared Workspace Panel Opening

The docked catalog tools now open through a shared workspace-panel helper instead of each opener duplicating the same sequence.

The shared opener centralizes:

- dock creation and `show_panel()` usage
- optional per-panel configuration before returning the panel
- optional selection-scope refresh for panels that depend on live catalog selection
- canonical panel attribute assignment on the app shell
- backward-compatible legacy attribute aliases so existing call sites do not all need to move at once

Canonical panel attributes introduced through the shared opener:

- `catalog_managers_panel`
- `release_browser_panel`
- `work_manager_panel`
- `party_manager_panel`
- `contract_manager_panel`
- `rights_matrix_panel`
- `asset_registry_panel`
- `global_search_panel`
- `license_browser_panel`

Legacy aliases intentionally preserved in parallel:

- `catalog_managers_dialog`
- `release_browser_dialog`
- `work_browser_dialog`
- `party_manager_dialog`
- `contract_manager_dialog`
- `rights_browser_dialog`
- `asset_browser_dialog`
- `global_search_dialog`
- `licenses_browser_dialog`

Why this matters:

- panel openers now behave consistently
- focused configuration stays local to each opener
- the shell can move toward `*_panel` naming without forcing a single large compatibility break
- tests can assert the canonical workspace surface while older code paths continue to function

## 5. Context-Menu Restructuring

The catalog row context menu was previously too flat. This pass keeps the high-value row actions visible and moves repeated action families under named submenus.

### Top-level row actions

The top of the menu stays focused on row-level workflow:

- `Edit Track`
- `GS1 Metadata…`
- `Open Primary Release…` when available
- `Open Linked Work(s)…` when available
- `Link Selected Track(s) to Work…`
- `Delete Track`

### Grouped submenu structure

When a track row has the relevant data, the menu now branches into:

- `Licenses`
  - `Add License to this Track…`
  - `View Licenses for this Track…`
- `Audio`
  - `Import Metadata from Audio Files…`
  - `Export Tagged Audio Copies…`
  - `Export Audio Derivatives…`
  - authenticity and provenance export / inspect / verify actions
- `File`
  - `Preview File…`
  - `Attach/Replace File…`
  - `Export '<name>'…`
  - `Delete File…`
- `Storage`
  - `Store in Database`
  - `Store as Managed File`

Filter and copy actions remain directly reachable:

- `Set Filter: '<cell text>'`
- `Copy`
- `Copy with Headers`

This split keeps four concerns separate:

- row editing and navigation
- licensing
- audio workflows
- file and storage operations

That separation is the main KAIZEN win for the context menu. The functionality remains, but the menu stops reading like one uninterrupted action dump.

## 6. Dialog / Surface Cleanup Decisions

This pass applies measurable compaction rules to the dense surfaces that were most likely to feel oversized during everyday work.

### Shared rules

Shared dialog helpers remain the foundation:

- compact control heights are normalized through `_apply_compact_dialog_control_heights(...)`
- shared width clamping remains available through `_apply_dialog_width_constraints(...)`
- scroll-safe content wrappers are used where bottom actions or long forms need to remain reachable on smaller windows

The pass uses those helpers to reduce sprawl without turning dense editors into cramped popups.

### Progress overlays and loading surfaces

The follow-up pass also tightened the sizing behavior for background-task progress overlays so long status lines do not collapse into undersized dialogs.

Implemented measurable progress-surface rules:

- progress dialogs now clamp to a `420` pixel minimum width instead of the previous undersized compact width
- dialogs can expand up to `680` pixels, or scale down relative to the parent window when the main shell is smaller
- wrapped status labels, progress bars, and cancel buttons now inherit wider internal bounds so long export labels remain readable without clipping

This specifically addresses the too-small long-running export/loading surfaces shown during forensic watermark export and similar media tasks.

### Diagnostics dialog

Diagnostics now behaves like an inspection workspace rather than a fixed-size static sheet.

Implemented measurable diagnostics rules:

- dialog size remains `1080 x 780` with a `980 x 680` minimum
- the overview content now lives inside a dedicated scroll area so environment, checks, and details remain reachable without maximizing the window
- a new `History Storage` section exposes the same storage-budget story surfaced in History Cleanup:
  - current usage
  - configured budget
  - over-budget amount
  - safe reclaimable space
  - retention level
  - automatic cleanup status
- a direct `Open History Cleanup…` action now links diagnostics to the repair/cleanup workflow immediately

The intent is that diagnostics can now answer “what is using space, how far over budget are we, and where do I fix it?” without forcing a second mental jump.

The final loading-surface audit found that the main remaining non-`QProgressDialog` loading surface was the diagnostics loading strip. That strip now scales with the dialog instead of keeping a narrow fixed-width progress bar.

The startup splash was also hardened so longer milestone text is elided cleanly inside the bottom status band instead of overrunning the available width.

### Application settings dialog

The settings surface remains broad because it now includes workflow settings, GS1 defaults, and theme editing, but the pass constrains the inputs more aggressively.

Implemented measurable settings rules:

- dialog minimum size stays at `1040 x 720`
- initial size stays at `1180 x 820`
- short metadata edits generally stay in the `180..320` width range
- path-style fields use wider but still bounded inputs, typically `360..420`
- theme preset controls stay bounded at `240..340`
- theme font-family control stays bounded at `260..360`
- the preview pane is optional and off by default

The important behavioral change is that the settings dialog no longer assumes the preview surface should always consume half the page. Editors get the full working area by default, and the preview pane is available only when the user explicitly asks for side-by-side testing.

### Release editor

The release editor is kept as a substantial editor, but it is no longer treated as an unbounded wide form.

Implemented measurable release-editor rules:

- default size `960 x 720`
- minimum size `880 x 640`
- metadata content remains scroll-safe
- compact control heights are applied after the tabbed layout is built
- editable combo boxes remain available for the safe metadata fields without forcing oversized full-width rows

The target outcome is a dialog that still supports dense release data entry but does not feel like it needs an unnecessarily large window just to remain usable.

### Catalog managers

Catalog managers are now treated as a docked workspace surface that should stay usable in a tighter tabified layout.

Implemented measurable catalog-manager rules:

- default size `1020 x 700`
- minimum size `920 x 620`
- tab panes use scroll-safe content containers
- bottom actions remain inside each tab’s scroll content so they are still reachable when the dock is shorter
- focused layout checks are run at `980 x 620` to confirm the controls still stay inside the intended surfaces

This matters because catalog managers are part of the tabbed workspace model now, not a detached wide maintenance island.

### Deliverables and derivative ledger workspace

The deliverables workspace now includes two first-class tabs:

- `Asset Registry`
- `Derivative Ledger`

The new ledger tab is read-only by design and focuses on review rather than editing. It shows:

- derivative export batches
- registered derivative entries for the selected batch
- output hashes, file names, workflow kind, watermark state, and package context

To keep discoverability explicit without adding another dock type, the shell now exposes a dedicated `Derivative Ledger…` workspace action that opens the existing deliverables dock directly on the ledger tab.

The second follow-up pass adds optional drill-ins from a selected derivative row:

- `Open Track…`
- `Open Primary Release…`
- `Verify Output Authenticity…` when the exported file is still available on disk

These actions keep the ledger review-first, but they stop the user from hitting a dead end when the next step is to continue into the related catalog or authenticity workflow.

## 7. Progressive-Disclosure Strategy

Theme editing now has two separate preview controls with intentionally different scope:

- `Preview changes across the app while editing`
- `Show preview pane while editing`

The first toggle is about live application styling.

The second toggle is about exposing a local side-by-side preview surface inside the settings dialog.

The preview pane is:

- hidden by default
- available on demand for focused visual verification
- synchronized to the active theme-builder tab
- intended as a compact local proving ground, not a permanent second column that every theme edit must pay for

This split prevents the theme editor from staying visually heavy for users who only want to adjust a few tokens, while still supporting richer preview work when someone is actively tuning the theme surface.

## 8. Tests Added / Updated

The test strategy for this pass is intentionally focused rather than broad.

The main coverage areas are:

- app-shell menu grouping and panel toggles
- workspace dock behavior and tabified panel opening
- catalog row context-menu structure
- dialog surface structure and compaction expectations
- theme builder payload, preview-tab sync, and optional preview behavior

Primary test modules to keep aligned with this pass:

- `tests.app.test_app_shell_startup_core`
- `tests.app.test_app_shell_workspace_docks`
- `tests.app.test_app_shell_editor_surfaces`
- `tests.test_repertoire_dialogs`
- `tests.test_theme_builder`
- `tests.test_ui_common`

These tests should continue to verify:

- the new `File` and `Catalog` menu information architecture
- the limited rename set, especially track wording and workspace labels
- the shared workspace-panel opening model
- the `Licenses`, `Audio`, `File`, and `Storage` context-menu split
- compact but still reachable controls on release editor and catalog-manager surfaces
- the optional nature of the theme preview pane and the builder-tab-to-preview-tab mapping
- diagnostics scroll behavior, history storage budget summary visibility, and cleanup-link routing
- progress dialog width constraints for longer-running media workflows
- derivative-ledger workspace discoverability through the workspace menu and shared deliverables dock
- derivative-ledger drill-ins into track, release, and authenticity surfaces
- help rendering without the hardcoded `SF Pro Text` fallback path that previously triggered Qt font-alias warnings during dialog tests

## 9. Remaining KAIZEN Opportunities

The next safe opportunities after this pass are:

- normalize a second, carefully controlled wave of wording in lower-frequency dialogs and help text
- decide whether forensic inspection should stay in the row-scoped `Audio` submenu or move to the canonical catalog-level authenticity menu only
- apply the same compact section pattern to more editor dialogs once their workflow groupings are mapped explicitly
- continue retiring legacy `*_dialog` naming internally after downstream callers stop depending on compatibility aliases
- add one more layer of workflow tests around action-ribbon customization persistence and advanced audio entry-point discoverability
- consider whether derivative-ledger drill-ins should eventually link directly to related track, authenticity, or release surfaces from within the ledger details view
- consider whether ZIP-packaged derivative batches should eventually support one-click temporary extraction for authenticity verification directly from the ledger

## Out Of Scope

This pass intentionally does not try to do all of the following at once:

- rename every historic internal variable or dialog attribute
- rewrite all help content around the new menu names in one step
- convert every remaining large dialog into a compact editor
- collapse all storage vocabulary into a brand-new model
- change service boundaries just because the UI wording moved

The value of this KAIZEN pass is that the shell and its highest-friction surfaces now read more clearly without forcing a risky full-application rewrite.
