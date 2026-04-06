# Contract Template Workspace Final Bug Fix

## 1. Exact Remaining Failure Symptoms Reproduced

- After deleting old saved layouts, saving a fresh Contract Templates layout, and loading it again, the workspace could still come back looking effectively empty:
  - the fill preview might stay visible
  - other docked panels appeared gone or unrecoverable
  - `Reset Layout` only reshaped blank regions
  - hidden panels were not reliably recoverable through `Panels`
- The HTML preview still had a real `Fit View` failure:
  - clicking `Fit View` could keep ratcheting zoom downward
  - after manually zooming back to `100%`, pressing `Fit View` again could restart the outward zoom drift
  - parent/layout churn could still perturb zoom after fit ownership should have been settled

## 2. Real Root Cause For Disappearing Docks

- The remaining dock failure was not just stale `toggleViewAction()` wiring. The deeper problem was that the workspace tab layouts themselves were still structurally wrong in two places:
  - several default dock reset builders used the wrong split order, creating split trees that left a large central canvas or off-screen central geometry instead of a fully occupied dock layout
  - size-sensitive dock normalization still ran too early for some hosts, before the host had a stable visible size
- There was also a second-generation save corruption path in the nested layout model:
  - if a tab host had a pending restored layout that had not been applied yet because the tab was still inactive, `capture_layout_state()` could overwrite that pending state with a fresh `saveState()` from the hidden host
  - hidden/inactive tab hosts were also being serialized with every dock marked hidden because plain `isVisible()` reflects parent-tab visibility, not whether the user actually hid the dock
- There was a matching save corruption path one level higher in the outer workspace dock shell:
  - if `CatalogWorkspaceDock` had a pending restored panel state that had not been reapplied yet because the whole workspace dock was hidden or not ready, saving again could overwrite that pending state with a sparse live panel snapshot
  - in practice that meant a named layout could be restored, the workspace dock could stay hidden/inactive, and the next save would silently replace the real nested panel state with an incomplete `import`-only snapshot
- There was also a restore-time reentrancy flaw:
  - the outer workspace dock could refresh the live panel while nested restore state was still pending
  - the Contract Templates panel could also refresh the fill form and request HTML preview reloads while its own dock restore was still in progress
  - that meant `QWebEngineView` could be asked to reload during the middle of a dock restore lifecycle, which is the same seam that lines up with the observed compositor/null-texture failures and the “empty shells plus dead controls” feel in real use
- The later live JSONL traces narrowed the remaining named-layout failure further:
  - the freshly saved Contract Templates named-layout payload was valid and stable on disk
  - the outer Contract Templates dock still survived named-layout load and remained materialized
  - the nested `fill` host also remained registered with all 8 docks visible
  - the first divergence happened immediately after the outer main-window `restoreState()` step, before nested Contract Templates restore replay
  - nested restore could temporarily return the `fill` host to the correct saved dock-state digest, but post-restore churn then mutated that digest again before settling back
  - the named-layout loader was also restoring/materializing the nested Contract Templates panel while outer dock updates were globally suppressed, which matches the “dock tree is logically there, but the visible dock shells are blank” behavior from the screenshots
- The latest trace also showed a persistence timing bug:
  - named-layout apply forced an immediate `_save_main_dock_state()` while the `fill` host was still on a transient post-restore digest
  - a later debounced save corrected the digest once the host settled, which proves the immediate save was capturing the wrong phase of the restore lifecycle
- The newest user-provided JSONL isolated one more restore seam in the outer dock shell:
  - the saved named-layout payload still carried the correct nested `fill` digest
  - the first visible divergence happened at outer `restoreState()` when `contractTemplateWorkspaceDock` was forced through a hide/reshow cycle
  - during that visibility churn the live Contract Templates panel was still being auto-refreshed/materialized before the nested panel snapshot had been reapplied
  - the nested `fill` docks were still registered, but their `toggleViewAction()` state and visibility briefly churned off/on during that premature outer-dock refresh
  - this means the latest remaining failure seam was not payload loss, but eager outer-dock panel refresh while app-wide restore was still active
- The same JSONL also exposed a nested-host restore-churn seam inside `_DockableWorkspaceTab`:
  - while the outer named-layout restore was still in progress, the live `fill` host kept receiving dock `visibilityChanged`, `dockLocationChanged`, and `topLevelChanged` callbacks from Qt
  - `_on_dock_layout_event()` treated those outer-restore callbacks as real user layout edits, queued compaction/normalization, and refreshed the host's stable snapshot during the wrong phase
  - that meant the inner workspace could still rewrite its last-known-good layout during outer restore even though the saved payload and dock registration were both intact
- The newest JSONL finally exposed the visual-break root cause directly:
  - at `app.apply_named_main_window_layout.begin`, the `fill` host docks were all `updates_enabled=True`
  - immediately after entering `_suspend_saved_layout_transition_updates()`, the outer `contractTemplateWorkspaceDock` and all nested `fill` docks dropped to `updates_enabled=False`
  - by `app.apply_named_main_window_layout.end`, the outer workspace dock had come back to `updates_enabled=True`, but every nested `fill` dock was still `updates_enabled=False`
  - the dock tree, visibility, and content widgets were all still present, but the nested workspace had effectively been left with painting/interactivity frozen
  - that explains the real symptom cluster much better than payload loss alone: blank-looking dock shells, dead `Unlock Layout`, dead `Panels` toggles, and a workspace that “exists” in the model but feels broken
- Because those bad default topologies were what got saved into new layouts, deleting old saved layouts did not help. A fresh save could still capture a structurally wrong import/symbol/fill arrangement.
- Because hidden-tab pending state and visibility intent could be corrupted during a fresh save, deleting old named layouts still was not enough. A brand-new saved layout could already contain poisoned nested dock state.
- Because the outer dock shell could also resave pending state incorrectly while hidden, a fresh named-layout save could still be poisoned even after the inner host fixes landed.
- After restore, the dock instances were alive, but the layout model was still invalid enough that the workspace felt empty and `Reset Layout` did not recover into a professional full-panel arrangement.

## 3. Real Root Cause For Unreopenable Hidden Docks

- The panels actions themselves were still the real `toggleViewAction()` objects.
- The unreopenable feeling came from the layout model being wrong after restore, not from action recreation. When the workspace restored into a broken split tree or invalid geometry state, the hidden dock’s action still existed, but the visible workspace arrangement did not behave like a valid recoverable dock surface.
- The restore path also had no authoritative per-dock visibility payload. It was relying entirely on Qt’s nested `restoreState()` result, so if restore came back with docks hidden unexpectedly there was no explicit saved visibility model to reassert.
- The outer restore path also needed one more integrity pass after named-layout/main-window restore so visible workspace docks were revalidated once Qt finished settling geometry.

## 4. Real Root Cause For First-Scroll Zoom Hijack

- `Fit View` was still behaving like a persistent live auto-fit owner instead of a one-shot explicit fit action.
- Once fit mode stayed active, later resize/content callbacks could continue recomputing zoom after the user thought fit had already completed.
- That is why the preview could keep walking downward after `Fit View`: fit ownership was not being finalized after the fit calculation finished.

## 5. Real Root Cause For Parent-Change Zoom Drift

- Parent/layout changes were still able to alter zoom because fit ownership remained active after the fit computation instead of handing control back to normal viewport navigation.
- The preview also needed the fit path to rely on settled measurements rather than repeatedly treating later layout churn as a reason to keep refitting.

## 6. Structural Fixes Landed

- Corrected the dock split tree for each workspace:
  - `import` now splits into columns first, then vertical stacks inside those columns
  - `symbols` now does the same
  - `fill` now establishes its horizontal columns before stacking the left and middle column docks vertically
- Nested dock-host capture is now state-aware:
  - hidden tabs with unapplied pending restore state keep that pending state during save instead of being overwritten
  - per-dock visibility is captured explicitly
  - visibility capture now uses logical dock-hidden state instead of parent-tab visibility
- Added host-level dock layout normalization that is tied to the real widget lifecycle:
  - each `_DockableWorkspaceTab` can register a layout normalizer
  - normalization is retried only when the host is visible and sized
  - normalization can stay pending until the layout is actually healthy instead of being consumed too early
- Added an outer-dock pending-state preservation rule in `CatalogWorkspaceDock`:
  - if the workspace panel has unapplied pending restore state and the outer dock is not ready yet, saving now reuses that pending state instead of capturing a sparse live panel snapshot
  - the outer dock also listens for real panel `Show`, `Resize`, and `LayoutRequest` events so pending nested state is applied as soon as the workspace becomes genuinely visible again
- Added quiet-restore behavior around the outer workspace dock:
  - `CatalogWorkspaceDock` no longer refreshes a live panel while pending nested layout restore is still dirty
  - the outer dock now brackets panel restore with `begin_layout_restore()` / `finish_layout_restore()` hooks when a panel provides them
- Added restore-specific preview suspension in the Contract Templates panel:
  - fill-form data can still rebuild during restore
  - but HTML preview refresh requests are suppressed until the outer dock restore has fully completed
  - preview refresh is resumed once, after the dock restore/stabilization boundary, instead of during mid-restore
- Named-layout apply now keeps the outer-shell anti-flicker boundary only around main-window geometry and outer dock restore, then replays/materializes the nested Contract Templates workspace after updates are re-enabled.
  - This targets the exact seam the live JSONL exposed: the dock tree was surviving restore, but the nested Contract Templates content was being rebuilt under outer dock update suppression.
- Named-layout apply no longer forces an immediate `_save_main_dock_state()` / `_save_main_window_geometry()` at the tail of restore.
  - It now returns to the normal debounced persistence path so transient `fill` host digests are not captured before the restore lifecycle settles.
- `CatalogWorkspaceDock` now treats app-wide named-layout restore as a hard boundary for auto-refresh/materialization:
  - `visibilityChanged` no longer auto-materializes the Contract Templates panel while `_is_restoring_workspace_layout` is still true
  - `refresh_panel()` and `show_panel()` now defer live refresh while app-wide restore is active
  - this prevents the outer dock from rebuilding a default/stale live panel before the nested Contract Templates layout payload has been handed over
- Main-window named-layout transition suppression no longer freezes nested workspace shells:
  - `_suspend_saved_layout_transition_updates()` now excludes `CatalogWorkspaceDock` instances from the outer anti-flicker update-suspension set
  - that keeps the Contract Templates outer workspace shell and its nested dock host alive while the main-window restore applies the surrounding dock layout
  - direct toolbars and standard outer docks are still suspended for flicker control, but nested workspace-managed dock systems are left to manage their own lifecycle
- `_DockableWorkspaceTab` now treats app-wide outer restore as a hard boundary for nested dock-layout churn:
  - `showEvent()` and `resizeEvent()` skip pending-state apply and normalization while transient outer restore is active
  - `_notify_layout_changed()` no longer treats outer restore churn as a real layout change
  - `_cache_stable_layout_state_if_ready()` refuses to overwrite the stable snapshot while the top-level window is still restoring
  - `_on_dock_layout_event()` now logs and ignores outer-restore visibility/location churn instead of queueing compaction and rewriting the nested host's stable state
- Expanded layout-integrity validation so all Contract Templates tabs, not just `fill`, are checked for broken exposed central canvas behavior and invalid restore fallout.
- Tightened the central-canvas detector so off-screen/negative Qt central-widget geometry is not misclassified as visible blank workspace.
- Kept the existing outer-dock deferred nested-restore seam and app-level post-restore workspace validation, then used the stronger per-host integrity checks after restore.
- Added opt-in runtime workspace tracing so live repros can be diagnosed outside the unit suite:
  - `ISRC_CT_WORKSPACE_DEBUG=layout,preview,events`
  - `ISRC_CT_LAYOUT_DEBUG=1`
  - `ISRC_CT_PREVIEW_DEBUG=1`
  - `ISRC_CT_PREVIEW_EVENT_DEBUG=1`
  - `ISRC_CT_WORKSPACE_DEBUG_FILE=/absolute/path/contract-template-workspace.jsonl`
  - `ISRC_CT_DEBUG_STACKS=1`
 - Added a second pass of much finer-grained Contract Templates restore tracing around the real named-layout load path:
   - app-level checkpoints now log before/after main dock restore, nested workspace payload replay, visible panel materialization, stabilization, and delayed post-event-loop checkpoints
   - Contract Templates nested restore now logs per-host dispatch, compatibility rejection reasons, default-layout fallback, visibility replay, and repair attempts
   - workspace-state summaries now include dock-state digests so resaved payload mutations can be compared across events instead of inferred only from payload length
   - workspace-state summaries also now capture `updates_enabled`, scroll-area viewport/content sizes, scrollbar positions, direct visible child-widget counts, fill combo counts, fill field-row counts, and fill status-label text so “blank dock shell” failures can be separated from true dock-registration failures
   - workspace-state summaries now also capture scroll-area viewport/content sizes, scroll positions, direct visible child-widget counts, fill combo counts, fill field-row counts, and status-label text so “blank dock shell” failures can be separated from true dock-registration failures

## 7. QWebEngine / Preview Lifecycle And Input Fixes

- `Fit View` is now a one-shot fit cycle instead of a persistent fit owner:
  - pressing `Fit View` enters fit mode
  - the preview measures and applies fit
  - fit ownership is finalized back to normal viewport ownership immediately after the fit completes
- Plain wheel scrolling still stays out of the zoom path and preserves normal scrolling.
- Explicit zoom controls, Ctrl/Cmd wheel, and real pinch gestures still remain the intended zoom paths.
- Resize/content callbacks now participate only in the pending fit cycle instead of keeping zoom under indefinite fit ownership.

## 8. Dock Lifecycle / Restore Fixes

- Default tab layouts are now structurally sane before they are ever saved into named layouts.
- Restore-time integrity repair now:
  - attempts layout normalization when the restored topology is geometrically wrong
  - repairs scroll-area content visibility/size issues
  - re-registers orphaned docks into their last known area when needed
  - falls back to the corrected default layout when the restored topology is still invalid
- Restore now reapplies the saved per-dock visibility model after nested `restoreState()` so the intended visible/hidden dock set survives restore instead of being inferred from transient Qt widget visibility.
- Hidden docks remain recoverable through `Panels` after restore because the restored host stays part of a valid dock model.
- Outer workspace dock capture now preserves unapplied restored panel state while hidden, so saving a named layout no longer destroys the pending nested Contract Templates workspace model before the next restore.
- The restore path no longer reenters fill-form refresh and preview reload through the outer dock before the pending nested layout has been applied.
- Nested Contract Templates tab hosts now keep a last-known-good stable dock snapshot while they are visible, and later saves reuse that stable snapshot whenever a tab host is hidden or not restore-ready.
  - This closes the remaining hole where a materialized but inactive tab host could still be serialized from a hidden live `QMainWindow`, which is exactly the save path that was still capable of producing blank dock containers and dead toggle behavior after a later restore.

## 9. Tests Added / Updated

- Strengthened Contract Templates layout tests in `tests/contract_templates/test_dialogs.py` for:
  - import/symbol default layouts remaining recoverable without broken blank-canvas behavior
  - outer-workspace save/load keeping import/symbol/fill hosts recoverable
  - hidden import/fill dock restore and reopen behavior
  - preserving hidden-tab pending nested state across a second save before that tab is activated
  - reusing a stable hidden-host snapshot instead of live hidden-host serialization when saving inactive materialized tabs
  - preserving hidden outer-workspace pending nested state across a second save before the dock is shown again
  - explicit per-dock visibility payload capture for hidden preview state
  - repeated `Fit View` stability after manual zoom reset
  - stable preview zoom through layout/visibility churn
  - suppressing nested host stable-state mutation while outer named-layout restore churn is still active
- Updated preview-owner expectations to match the corrected one-shot fit lifecycle.
- Strengthened `tests/test_catalog_workspace.py` to cover hidden materialized outer-dock pending-state preservation.
- Strengthened `tests/test_catalog_workspace.py` to cover restore-before-refresh ordering and outer-dock restore hooks.
- Strengthened `tests/test_catalog_workspace.py` again to cover:
  - deferring panel materialization when a workspace dock first becomes visible during app-wide restore
  - suppressing live panel refresh for an already-materialized workspace dock while app-wide restore is still active
- Added `tests/test_app_bootstrap.py` coverage proving `_suspend_saved_layout_transition_updates()` skips `CatalogWorkspaceDock` shells so nested Contract Templates docks do not get stuck with `updatesEnabled=False`.
- Added `tests/test_workspace_debug.py` coverage for topic-list debug flags and JSONL runtime trace capture.
- Added Contract Templates coverage proving preview refresh resumes only after restore suspension is lifted.

## 10. Real Workflow Verification Performed

- Ran the focused Contract Templates suite:
  - `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.contract_templates.test_dialogs -v`
- Ran the catalog workspace outer-restore suite:
  - `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_catalog_workspace -v`
- Ran a direct save-after-restore probe against the real panel classes:
  - restored a saved layout while `fill` stayed inactive
  - captured a second saved layout before activating `fill`
  - verified the hidden tab’s pending nested state was preserved instead of mutated
  - restored that second-generation save and verified both `import` and `fill` remained fully recoverable
- Ran a direct outer-dock save/load probe using the real `CatalogWorkspaceDock` and `ContractTemplateWorkspacePanel` classes:
  - materialized `import`, `symbols`, and `fill`
  - captured panel layout state
  - restored it into a fresh outer dock
  - verified all three tabs finished with `before_ok == validate_ok == after_ok == True`
  - verified docks remained registered, visible/hidden intent was preserved, and `Panels` could still recover hidden docks
- Ran a direct hidden-outer-dock resave probe using the real `CatalogWorkspaceDock` and `ContractTemplateWorkspacePanel` classes:
  - restored a real Contract Templates panel state into a hidden outer dock
  - saved again before reopening that dock
  - verified the resaved payload still matched the original nested workspace state
  - then reopened the dock and confirmed `fill_integrity == True`, `fill_visible_count == 8`, and dock toggles still worked
- Ran an opt-in runtime JSONL trace with:
  - `ISRC_CT_WORKSPACE_DEBUG=layout,preview,events`
  - `ISRC_CT_WORKSPACE_DEBUG_FILE=/tmp/ct_probe4.jsonl`
  - and verified that during restore the fill form may rebuild once, but the HTML preview no longer starts a web reload until after `catalog_workspace_dock.restore.applied` and `workspace_panel.finish_layout_restore`
- Added live-app restore trace checkpoints for future repros:
  - `app.apply_named_main_window_layout.after_ensure_shells`
  - `app.apply_named_main_window_layout.after_main_dock_state`
  - `app.apply_named_main_window_layout.after_transition_updates_resumed`
  - `app.apply_named_main_window_layout.after_workspace_panel_snapshot`
  - `app.apply_named_main_window_layout.after_materialize_visible_panels`
  - `app.apply_named_main_window_layout.checkpoint` with delayed `0/25/100/250/1000ms` snapshots
  - matching `app.restore_workspace_layout_on_first_show.*` checkpoints during startup restore
- Parsed the user-provided `contract-template-workspace-debug.jsonl` and confirmed:
  - the saved `Layout 2` snapshot carried the correct fill digest
  - the first digest divergence happened at `app.apply_named_main_window_layout.after_main_dock_state`
  - nested Contract Templates restore temporarily repaired the `fill` host digest
  - the named-layout loader then saved a transient `fill` digest before later checkpoints showed the host had settled back to the correct digest
  - the remaining visible failure is therefore narrowed to post-restore paint/content state in the Contract Templates `fill` workspace, not to the named-layout payload being missing or the dock tree being deleted
- Parsed the newer user-provided `contract-template-workspace-debug.jsonl` and confirmed:
  - the saved `Layout 1` snapshot still carried the correct `fill` digest (`8546a088b2e8`)
  - outer main-window `restoreState()` forced `contractTemplateWorkspaceDock` through a visible false/true cycle before nested panel replay
  - the nested `fill` docks remained registered, but their toggle/visible state churned during that outer-dock visibility cycle
  - the right fix was therefore to stop outer-dock auto-refresh/materialization while app-wide restore is still active, then let the nested panel payload apply first
- Parsed the same trace one level deeper and confirmed:
  - the nested `fill` host was still receiving dock-layout callbacks during the outer restore visibility cycle
  - those callbacks were being treated as real layout edits even though they were only Qt restore churn
  - the latest fix now suppresses nested host mutation during that transient restore window instead of only guarding the outer dock shell
- Parsed the latest user-provided JSONL and confirmed:
  - the restored `fill` host looked structurally healthy at the end of named-layout restore
  - however, all nested `fill` docks were still `updates_enabled=False` long after `app.apply_named_main_window_layout.after_transition_updates_resumed`
  - the final fix therefore had to target the outer transition update-suspension boundary, not just payload replay and nested restore ordering
- Ran a direct hidden-host stable-snapshot probe using the real `CatalogWorkspaceDock` and `ContractTemplateWorkspacePanel` classes:
  - focused the live `fill` tab to establish a stable nested snapshot
  - switched back to `import`, hid the outer dock, and captured layout state
  - verified the hidden `fill` tab reused the same stable snapshot instead of trying to serialize the hidden live host
  - restored that captured state into a fresh dock and confirmed `import`, `symbols`, and `fill` all validated cleanly, `Panels` toggles worked, and `Unlock Layout` still flipped into unlocked mode
- Ran direct default-layout probes against the real workspace classes and confirmed `import`, `symbols`, and `fill` no longer report visible exposed central canvas after the corrected split-tree/layout lifecycle changes.

## 11. Risks / Caveats

- The existing full app-shell `App()` harness is still an honest environment boundary in this machine/runtime, so the strongest end-to-end verification here remains the real dock/panel class probes plus the focused Qt suites.
- Headless Qt WebEngine still emits Chromium GPU/offscreen noise during tests. Those logs are environment noise, not a Contract Templates behavior regression.
- The new runtime debug flags are intentionally opt-in and are meant for real interactive repros where the app shell still exposes behavior that narrower headless tests miss.
- The full `App()` harness still segfaults during startup in this environment before the app-shell restore cases can run, so the strongest verification remains the real dock/panel probes, the runtime JSONL traces, and the focused Contract Templates Qt suites.

## 12. Current Outcome Statement

- The zoom failure is fixed.
- The named-layout payload corruption failures identified earlier are fixed.
- The remaining Contract Templates saved-layout failure is now narrowed to the named-layout post-restore lifecycle:
  - outer `restoreState()` perturbs the `fill` host
  - nested restore can repair it
  - the app was still letting nested host layout callbacks mutate stable state during that transient outer-restore churn
- The latest code change now guards both layers:
  - the outer dock shell no longer refreshes/materializes early during app-wide restore
  - the nested workspace host no longer treats outer-restore dock callbacks as real layout edits
- The latest code change also removes the update-freeze seam:
  - workspace dock shells are no longer pulled into main-window transition update suspension
  - direct real-class probing now shows the Contract Templates outer dock and all eight `fill` docks stay `updatesEnabled=True` throughout that transition boundary
- One more live repro is still required before claiming the blank-dock visual failure is fully closed.
