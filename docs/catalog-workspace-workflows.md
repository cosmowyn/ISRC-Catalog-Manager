# Catalog Workspace Workflows

This guide mirrors the in-app help chapters for the main workspace, catalog managers, releases, media preview, and reviewed media attachment.

Use `Help > Help Contents` for the integrated manual. This page is the repository-side companion for that workflow.

## Workspace Model

The main window is built as a working catalog surface rather than a sequence of blocking dialogs.

- the catalog table stays central for browsing, filtering, and multi-selection
- the catalog table is backed by the model/proxy view path, so filtering works on the visible proxy rows instead of hidden widget rows
- the catalog zoom slider changes table density only; it does not reload catalog data, and saved layouts restore the zoom level
- high-value tools open as docked workspace panels beside the table
- tabbed docking keeps related managers available without taking over the window
- saved layout state restores the workspace structure you actually use

## Core Workspace Panels

The docked catalog workspace includes:

- Code Registry Workspace
- Release Browser
- Work Manager
- Party Manager
- Contract Manager
- Rights Matrix
- Deliverables and Asset Versions
- Global Search and Relationships

These panels are meant to stay in the same workflow loop as the table. You can review a release, change the current table selection, inspect the linked work, and move into rights or assets without closing one tool to reach another.

## Code Registry Workspace

`Code Registry Workspace` keeps app-managed internal business codes and external catalog identifiers visible beside the rest of the catalog workflow.

Its tabs are:

- `Internal Registry`: inspect issued internal values, filter by category and year, generate the next code, generate a `Registry SHA-256 Key`, review usage, link an unassigned value later, and delete an unused Registry SHA-256 Key
- `External Identifiers`: review foreign/non-conforming identifier values, inspect shared usage counts, and promote or reclassify canonical candidates
- `Categories`: manage built-in prefixes and custom categories

Repeated catalog identifiers are intentionally shared. When multiple tracks in the same album use the same catalog number, the workspace keeps one unique identifier row and shows how many tracks or releases reference it.

## Release And Selection Workflows

Release work is centered on the current selection.

- create a release from the current track selection
- add selected tracks to an existing release
- inspect release order and release membership in Release Browser
- filter the table to a selected release

This keeps release maintenance grounded in the actual catalog rows rather than in a disconnected product editor.

Catalog-number fields in `Add Track`, `Add Album`, `Edit Track`, and `Release Editor` use the same registry-aware control:

- choose `Internal Registry` to select an existing managed value or generate the next one
- choose `External Identifier` to keep a third-party or non-conforming value without forcing it into the internal numbering rules

If a code was generated earlier without an owner, the workspace can assign it later with `Link Selected Value`.

## Deliverables And Asset Review

`Deliverables and Asset Versions` combines two related views:

- `Asset Registry` for masters, alternates, artwork variants, approval state, and primary-version control
- `Derivative Ledger` for managed export batches, derived outputs, lineage, retained output paths, and explicit cleanup controls

The ledger stays layered for practical review:

- batch list first
- derivative list second
- details, lineage, and admin follow-up as focused tabs

## Media Attachment

Catalog media attachment uses reviewed workflows rather than silent writes.

- `Catalog > Audio > Import & Attach > Bulk Attach Audio Files…` inspects local audio against existing tracks, shows the proposed matches, lets you reassign or skip, and requires confirmation before attachment
- `Catalog > Audio > Import & Attach > Attach Album Art File…` applies the same reviewed pattern to a single image file
- drag-and-drop routes into the same reviewed media-attachment workflow
- storage mode is chosen at attachment time, using the same database-versus-managed-file model used elsewhere in the app

## Media Preview

Preview stays close to the catalog workflow.

- audio preview supports transport controls, waveform scrubbing, export, and track-aware navigation
- image preview supports pan and zoom inspection plus export
- both previews remain real top-level windows so they can be revisited naturally while you keep working in the catalog

## Recommended In-App Help Topics

- `Main Window`
- `Code Registry Workspace`
- `Catalog Table`
- `Releases`
- `Works, Rights, and Contracts`
- `Media Preview`
- `Bulk Audio Attach`
