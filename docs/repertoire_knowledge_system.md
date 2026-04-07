# Repertoire Knowledge System

This guide mirrors the in-app help chapter `Works, Rights, and Contracts`.

Use `Help > Help Contents` for the integrated manual. This page summarizes the product model that sits underneath the catalog workspace.

## The Model

ISRC Catalog Manager treats a music catalog as a connected system rather than as a flat track sheet.

The main layers are:

- `Track`: the recording-level catalog entity
- `Release`: the product layer for grouped commercial delivery
- `Code Registry`: authoritative internal business codes plus separate external catalog identifiers
- `Work`: the composition layer
- `Party`: reusable people and companies
- `Contract`: structured agreements and obligations
- `Rights`: the resulting control position for a use, territory, or term
- `Document`: supporting files tied to contract and legal workflows
- `Asset / Asset Version`: approved masters, artwork variants, alternates, and derivatives

## Why The Separation Matters

The model stays explicit because these concepts answer different questions.

- a `Track` tells you what recording you have
- a `Release` tells you how it is packaged
- a `Work` tells you what composition it is linked to
- a `Contract` tells you which agreement governs the relationship
- a `Rights` record tells you what control position follows from that agreement
- an `Asset` tells you which file is approved for use

That separation keeps the catalog trustworthy when multiple recordings point to one work, one release contains many tracks, or one contract governs a limited rights scope.

## Works And Track Governance

The app uses governed musical entry.

- `Add Track` requires each new recording to link to an existing Work or create a new Work before save
- `Add Album` applies the same rule row by row for grouped entry
- Work Manager remains the follow-up surface for creators, splits, alternate titles, and registration details

## Parties, Contracts, And Rights

The legal and operational layer is meant to stay usable, not archival only.

- Parties keep canonical people and companies reusable across the catalog
- Contracts track dates, obligations, and counterparties as structured fields
- Contracts can also carry registry-backed contract numbers, license numbers, and a distinct `Registry SHA-256 Key`
- Contract documents preserve draft, signed, amended, and supporting files in the same system
- Rights records express type, exclusivity, territory, dates, and source-agreement lineage

## Assets And Deliverables

Assets represent the file/version layer around tracks and releases.

- tracks with attached real audio can be reflected automatically in the asset-version system
- asset versions can track primary state, approval, derivation, checksums, and storage mode
- deliverables and derivatives remain reviewable from the docked deliverables workspace

## Where To Read More

Use the in-app help for the deeper workflow detail:

- `Works, Rights, and Contracts`
- `Code Registry Workspace`
- `Releases`
- `File Storage Modes`
- `Import and Merge Workflows`
- `Audio Authenticity`
