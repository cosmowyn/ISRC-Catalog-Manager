# Repertoire Knowledge System

Current product version: `3.1.0`

ISRC Catalog Manager is no longer just a track table with a few extra fields. It is designed as a connected repertoire knowledge system for independent artists, labels, and catalog owners who need to understand not only what they have released, but what they control, how it is documented, and what is operationally ready.

This guide explains the product model behind that expansion.

It also reflects the current workspace design: the major catalog-management surfaces for releases, works, licenses, parties, contracts, rights, assets, and relationship search can remain open as tabbed dock panels beside the track table instead of interrupting catalog work as blocking popups.

## What This Enables

The repertoire layer matters because it turns the app from a flat recording list into a working system for:

- keeping recordings, releases, works, parties, contracts, rights, documents, and assets connected
- reviewing those linked records inside the docked workspace instead of across separate tools and folders
- moving from track cleanup into rights, contract, or deliverable review without losing context

If you want the workspace side of that model, read [Catalog Workspace Workflows](catalog-workspace-workflows.md). If you want the recovery and maintenance side, read [Diagnostics and Recovery](diagnostics-and-recovery.md).

## Why This Layer Exists

A serious music catalog is made up of more than recordings.

You need to maintain:

- the recording
- the release it belongs to
- the underlying musical work
- the people and companies connected to it
- the contract that governs it
- the rights position that results from that agreement
- the documents that prove it
- the deliverables that are actually approved for use

Most systems scatter that information across spreadsheets, folders, email threads, and memory. ISRC Catalog Manager brings it together in one local-first desktop workspace.

## What The App Models

### Tracks

Tracks remain the recording-level foundation of the catalog. They carry the recording-facing metadata you expect:

- title
- artists
- release date
- ISRC
- genre
- audio stored either in the database or as a managed file
- artwork stored either in the database or as a managed file
- custom metadata

Tracks continue to work exactly as they always have. The richer model expands around them rather than replacing them.

### Releases

Releases are product-level records that group tracks into commercial packages and product identities.

Release records can carry:

- title and subtitle
- primary and album artist
- release type
- UPC/EAN
- catalog number
- release dates
- artwork stored either in the database or as a managed file
- release ordering
- territory and status information

This keeps product-level data separate from track-level recording data, which is essential for clean exports and consistent catalog maintenance.

### Works

Works represent the composition layer.

They exist separately from recordings because one work can lead to multiple recordings, versions, edits, remixes, live cuts, and derivative releases. A work can store:

- work title
- alternate titles
- subtitle/version
- language
- lyrics and instrumental flags
- genre and style notes
- ISWC
- local registration number
- status and readiness flags
- notes

Works can link to multiple tracks, and tracks can link back to one or more works where needed.

### Parties

Parties are the reusable people and companies that appear throughout the catalog.

Instead of repeating free text everywhere, the app lets you maintain one canonical record for:

- artists
- labels
- publishers
- subpublishers
- managers
- producers
- licensees
- lawyers
- organizations
- individuals

Party records can be reused across works, contracts, rights, and other linked records.

### Contracts

Contracts are lifecycle-aware agreement records.

They can track:

- draft, signature, effective, start, and end dates
- renewal, notice, option, reversion, and termination dates
- active, expired, draft, pending-signature, terminated, or superseded status
- linked works, tracks, releases, and parties
- structured obligations and reminders with type, due date, completion state, and notes
- notes and summaries

This makes the contract layer operational, not just archival.

The current contract editor uses a structured obligations workflow rather than a free-form text block, which makes follow-up dates, completion state, and notes safer to maintain over time.

### Contract Documents

A contract record can hold multiple managed documents so the legal paper trail stays usable.

That includes:

- draft agreements
- signed finals
- amendments
- appendices
- exhibits
- correspondence
- scans

Each document can store version labels, received dates, signed state, active state, superseded relationships, checksums, and notes.

Those documents can now live either as database-backed binary records or as managed local files controlled by the app.

### Rights Records

Rights records express the actual control position resulting from agreements.

They can capture:

- right type
- exclusivity
- territory
- media or use type
- start and end dates
- perpetual state
- granted by
- granted to
- retained by
- source contract
- linked work, track, or release

This makes it possible to answer practical questions such as:

- Who controls this master?
- What rights are active in this territory?
- Which contract granted this right?

### Asset Versions

Asset versions give the app a real deliverables registry rather than a single file attachment slot.

You can track:

- main masters
- radio edits
- instrumentals
- clean versions
- explicit versions
- alternate masters
- hi-res files
- MP3 derivatives
- artwork variants
- promotional assets

Each asset can store checksum, format, technical details, derivation links, approval state, primary designation, and notes.

Asset versions can also switch between database-backed and managed-file-backed storage without changing the surrounding workflow for approval, preview, export, or validation.

Operationally, that work now lives in the docked `Deliverables and Asset Versions` workspace:

- `Asset Registry` keeps approved masters, alternates, artwork variants, and primary-version control together
- `Derivative Ledger` keeps managed export batches, registered derivative outputs, lineage, authenticity context, and explicit cleanup actions in the same review flow

## Attachment Storage Modes

The richer repertoire model now uses one dual-storage rule for file-backed records across the application.

Where appropriate, the app can store a file-backed record in one of two ways:

- `Database` mode keeps the raw file bytes in the profile database
- `Managed file` mode copies the file into an app-controlled local storage area and stores the managed path

This applies across track media, release artwork, custom binary values, license PDFs, contract documents, asset versions, and GS1 workbook templates.

The important operational result is consistency:

- existing records stay readable even if they predate explicit storage-mode tracking
- managed-file mode never depends on the original user-selected file staying in place
- supported records can be converted between modes safely
- package export/import preserves the intended storage mode instead of flattening everything into one representation

## How The Model Connects

The system is designed as a graph, not a stack of isolated tables.

Typical relationships look like this:

- a release contains many tracks
- a track can point to one or more works
- a work can have many contributors and publisher relationships
- a contract can link to works, tracks, releases, and parties
- a rights record can point back to a source contract
- a contract can carry multiple governing documents over time
- a track or release can carry multiple asset versions

This is why the app includes both global search and a relationship explorer: once the model becomes richer, navigation needs to become richer as well.

That same logic now shapes the workspace itself. The principal catalog managers can stay open beside the table as docked tabs, which means you can move from track selection to releases, works, rights, contracts, parties, licenses, and assets without closing one window to reach the next.

## Workflow State And Operational Readiness

The app also tracks where an item stands operationally.

Works, tracks, and releases can store workflow and readiness signals such as:

- idea
- demo
- in production
- final master received
- metadata incomplete
- contract pending
- contract signed
- rights verified
- cleared
- blocked
- archived

Readiness flags, linked assets, linked works, creator presence, and other validation signals are surfaced through the quality dashboard and related services.

## Quality And Risk Detection

The richer model powers much more useful validation.

The app can now detect:

- duplicate ISWC values
- missing work creators
- invalid split totals
- duplicate or ambiguous parties
- contracts with risky notice windows
- contracts without signed final documents
- rights records missing source contracts
- overlapping exclusive rights
- broken asset references
- missing approved masters
- tracks missing linked works where composition metadata exists

This is one of the most important advantages of the repertoire layer: it turns scattered information into something that can be checked, trusted, and acted on.

## Legacy Compatibility

The expansion is additive and backward-safe.

Older databases remain valid because:

- track and release workflows still work
- legacy data is not destructively reinterpreted
- new tables are added only where missing
- new workflow fields are appended safely
- older profiles can remain simple if the user wants them to

The older license and licensee archive is also still supported for lightweight use. Users who want the richer model can explicitly migrate legacy licenses into structured parties, contracts, and contract documents with checksum verification and snapshot protection.

## What This System Is Not

The repertoire model is intentionally deep, but it remains focused.

It is not:

- a royalty accounting engine
- a payment system
- a distributor dashboard
- a DSP API client
- a pitching or campaign platform

Its job is to be the best possible local catalog system for maintaining music metadata, relationships, rights context, and operational readiness.

## In Practice

For an independent catalog owner, this means one application can now serve as:

- the recording catalog
- the release register
- the docked catalog workspace for releases, works, licenses, and relationships
- the composition register
- the contract diary
- the rights matrix
- the party/contact registry
- the document archive
- the deliverables register plus derivative-ledger review surface
- the readiness dashboard

That is the product direction behind the repertoire knowledge system.
