# Catalog Workspace Workflows

This guide explains the docked workspace as it exists in the app today: a working area built for reviewing, comparing, and updating catalog records without forcing you into popup-driven navigation.

## What This Enables

The main value of the docked workspace is continuity. You can keep the catalog table in view while one or more related manager panels stay open beside it. That makes it easier to inspect a selected record, switch between related surfaces, and keep moving without constantly reopening dialogs.

This is especially useful when you are:

- reviewing a release while cross-checking tracks, works, rights, or parties
- assigning selected tracks to a release
- comparing catalog data against related documents or asset versions
- keeping global search open while you clean up or verify records
- returning to the same workspace layout after relaunching the app

## Docked Workspace Model

The workspace is built around dock widgets rather than isolated modal windows.

- `Add Data` and `Catalog Table` are the persistent base docks.
- The profiles toolbar can be shown or hidden from `View > Show Profiles Ribbon`, and that choice is remembered with the rest of the workspace state.
- Release, work, party, contract, rights, asset, license, search, and catalog-manager surfaces are opened as docked workspace panels.
- Related panels can remain visible while you continue using the catalog table.
- The app prefers tabbed docking for these workspace surfaces, so multiple tools can share the same side of the window instead of spreading across the screen.

In practice, that means the table stays usable while the surrounding review tools stay available. You do not have to close one surface to continue in another.

## Tabbed Managers

Several catalog tools are intentionally exposed as tabbed dock panels:

- Release Browser
- Work Manager
- Party Manager
- Contract Manager
- Rights Matrix
- Deliverables and Asset Versions
- License Browser
- Global Search
- Catalog Managers

The tabbed layout matters because these surfaces are not isolated utilities. They are part of the same workflow loop as the table. For example, you can inspect a release, switch to the selected tracks in the table, then move to rights or party review without losing your place.

## Release Assignment From Selection

The release workflow is centered on the current track selection.

- The Release Browser can show the ordered track list for a release.
- You can add the current track selection to a chosen release.
- You can also filter the main catalog table to a specific release.

That makes release work practical for both creation and review. A release is not just a stored record; it is a live container you can inspect against the tracks that belong to it.

## Review Surfaces

The docked managers exist to support real catalog review, not just browsing.

- `Work Manager` is for connected composition data.
- `Party Manager` is for reusable people and organizations.
- `Contract Manager` is for structured agreement data and managed documents.
- `Rights Matrix` is for rights positions and scope.
- `Deliverables and Asset Versions` keeps `Asset Registry` and `Derivative Ledger` together for asset review, export-batch tracking, and derivative inspection.

These panels help you answer questions like:

- Which work is linked to this recording?
- Which party appears in this contract or rights record?
- Which asset version is approved or primary?
- Which catalog items are connected to the selected record?

## Deliverables And Derivative Review

The `Deliverables and Asset Versions` workspace is designed as one connected deliverables surface instead of separate disconnected dialogs.

- `Asset Registry` stays focused on the registered asset versions attached to tracks and releases.
- `Derivative Ledger` tracks managed export batches and the derivative rows that were registered for each batch.
- The deliverables workspace stays docked and tabbed like the other managers, so it remains part of the same workspace strip rather than drifting into a separate one-off window.

The `Derivative Ledger` is intentionally layered for practical browsing:

- a compact search and filter strip stays visible at the top
- `Export Batches` remains visible as its own browsing pane
- the selected batch opens a secondary workspace with `Derivatives`, `Details`, `Lineage`, and `Admin` tabs

That layout matters because it keeps batch review usable while still exposing the deeper inspection surface:

- `Derivatives` keeps the registered outputs visible and lets you open the linked track, open the linked release, or launch authenticity verification
- `Details` turns batch and output metadata into structured fields instead of one long text dump
- `Lineage` keeps hashes, manifests, package members, retained paths, and source lineage readable without crowding the day-to-day review tab
- `Admin` isolates conservative cleanup actions away from normal browsing

The cleanup semantics are intentionally explicit:

- deleting a derivative ledger row removes the database record only
- deleting a batch removes the related database rows only
- deleting retained output files removes only the listed files and clears those retained-path references while keeping the ledger row itself

That makes the deliverables workspace useful both for normal browsing and for cleaning up stale or test export history without implying broader filesystem changes than the app actually performs.

## Saved Layout

Workspace placement is remembered.

- Dock placement is persisted.
- Panel visibility is persisted.
- The app restores its main dock state on startup when possible.
- The saved layout also preserves the benefit of tabified workspace panels.

The practical result is that a user can build a layout around the parts of the catalog they work in most often, then return to that layout on the next launch.

## Action Ribbon Customization

The action ribbon is a configurable quick-action strip.

- It is meant for the commands you use most often.
- It can be customized from the View settings.
- It keeps high-frequency actions visible without forcing you into menus.

This is a small feature with a large workflow impact because it reduces the number of steps needed for repeat tasks.

## Bulk Audio Attachment

The catalog workflow now includes a dedicated batch media-intake path for existing tracks.

- `Catalog > Audio > Import & Attach > Bulk Attach Audio Files…` inspects selected local audio files before anything is written.
- The dialog can suggest matches from filenames and embedded tags, show the detected artist/title, and let you skip or manually reassign individual files.
- You choose whether the attached audio should be stored in the database or as managed local files.
- One optional artist value can be applied across the matched set when you are cleaning up a consistent batch.
- The final attach step is recorded as one history-wrapped mutation so the batch stays recoverable.

This workflow is useful when the track rows already exist and the remaining job is to connect the right audio files quickly and safely.

## Audio Export From The Catalog

The catalog menu exposes the main audio export families directly from the workspace, and the rule is consistent across them: when a workflow exports catalog-backed audio, it automatically attempts to embed trustworthy catalog metadata into the exported copy.

- `Catalog > Audio > Delivery & Conversion > Export Audio Derivatives…` transcodes selected catalog audio into managed derivative formats, writes catalog metadata when available, hashes the final outputs, and registers them in the Derivative Ledger.
- `Catalog > Audio > Delivery & Conversion > Export Catalog Audio Copies…` writes original-format catalog audio copies without touching the stored source audio, then embeds catalog metadata into those exported copies when the target container supports it.
- `Catalog > Audio > Delivery & Conversion > Convert External Audio Files…` is intentionally different: it strips inherited source metadata, does not invent catalog metadata, and does not create derivative or authenticity records.

## Audio Authenticity From The Catalog

The catalog menu also exposes the audio authenticity workflow directly from the main workspace.

- `Catalog > Audio > Authenticity & Provenance > Export Authentic Masters…` uses the current track selection to build signed WAV/FLAC/AIFF master export copies without changing the original canonical source audio.
- Those exported copies carry:
  - a compact keyed watermark token
  - a sibling signed manifest sidecar
  - normal embedded audio metadata tags when the catalog already has those values available
- `Catalog > Audio > Authenticity & Provenance > Export Provenance Copies…` copies supported lossy derivatives as-is, writes the available metadata tags, and saves a signed lineage sidecar that points back to a previously verified watermarked master.
- `Catalog > Audio > Authenticity & Provenance > Verify Audio Authenticity…` can work in two ways:
  - verify the currently selected track audio when one supported direct/provenance source is selected
  - verify any external direct/provenance-supported file through the file picker

These authenticity exports do not create managed `Derivative Ledger` rows. They remain direct file-and-sidecar exports, with history and audit entries capturing the operation separately from the managed derivative registry.

This matters in the workspace because authenticity review is not limited to files that are already attached to the current profile. You can stay in the catalog when a track is selected, but you can also inspect an outside delivery or export copy without first importing or attaching it.

## Global Search And Relationship Explorer

Global Search is more than a simple text lookup.

- It searches across the connected catalog model.
- It can stay open as part of the docked workspace.
- It supports relationship-oriented review rather than only record lookup.

The relationship explorer is what makes search especially useful for power users:

- you can inspect linked works, tracks, releases, contracts, rights, parties, documents, and assets from one place
- you can move from search results into related records without starting over
- you can use the search surface as a review hub while another panel remains open

This is one of the strongest reasons the app works well as a catalog operations workspace rather than only a data-entry tool.

## Saved Searches

Saved searches are a practical way to preserve repeated review patterns.

Use them when you routinely return to:

- a specific subset of releases
- records missing key metadata
- items that still need rights, contract, or asset review
- relationship-heavy records that you inspect frequently

Saved searches matter because the app is designed around recurring operational questions, not one-off lookup.

## Practical Workflow Pattern

A common power-user loop looks like this:

1. Open the Catalog Table and one or more docked managers.
2. Filter or select the record you want to review.
3. Inspect the related release, work, party, contract, rights, or asset surface.
4. Keep the deliverables workspace open when you need to compare approved assets, managed export batches, lineage, or retained outputs against the selected catalog record.
5. Use Global Search or the relationship explorer if you need wider context.
6. Keep the layout open and continue to the next record.

That pattern is why the docked workspace is a core product feature. It reduces context switching while keeping the catalog model visible.

## What To Keep In Mind

- The catalog table remains the primary browsing surface.
- Docked panels are for review, inspection, and linked-record work.
- The app favors tabbed workspace surfaces so related tools stay available together.
- The workspace is meant to accelerate catalog operations, not replace the underlying data model with a single flat screen.
