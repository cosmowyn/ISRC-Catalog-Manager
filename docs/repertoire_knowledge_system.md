# Repertoire Knowledge System

ISRC Catalog Manager is no longer just a track table with a few extra fields. It is designed as a connected repertoire knowledge system for independent artists, labels, and catalog owners who need to understand not only what they have released, but what they control, how it is documented, and what is operationally ready.

This guide explains the product model behind that expansion.

It also reflects the current workspace design: the major catalog-management surfaces for releases, works, licenses, parties, contracts, rights, assets, and relationship search can remain open as tabbed dock panels beside the track table instead of interrupting catalog work as blocking popups.

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
- managed audio
- artwork
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
- artwork
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
- obligations and reminders
- notes and summaries

This makes the contract layer operational, not just archival.

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
- the deliverables register
- the readiness dashboard

That is the product direction behind the repertoire knowledge system.
