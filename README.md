# ISRC Catalog Manager

Current product version: `2.0.0`

ISRC Catalog Manager is a local-first desktop catalog and repertoire operations workspace for artists, labels, managers, and catalog owners who need more than a basic track list.

It combines recording metadata, releases, musical works, contracts, rights, parties, documents, assets, GS1 product data, import/export tooling, diagnostics, and durable history into one serious working system. Everything stays on your machine, in your files, and under your control.

![Workspace overview](docs/screenshots/workspace-overview.png)

## What This App Is For

Most catalog tools stop at track metadata or release scheduling. ISRC Catalog Manager is built for the day-to-day operational layer that sits around a real catalog.

It helps you maintain:

- recordings and release metadata
- releases as first-class product records
- works and composition metadata
- parties, licensees, and reusable contact entities
- contracts, obligations, and managed documents
- rights positions and source-agreement links
- deliverables, masters, artwork, and derived assets
- custom metadata, GS1 workbook data, and exchange-ready fields
- diagnostics, recovery points, and managed local storage

The result is a product that can answer practical questions quickly:

- Which recordings belong to this release, and in what order?
- Which work is linked to this track?
- Which contract and document govern this right?
- Which party granted or retained this territory?
- Which asset is the approved master?
- Which records are incomplete, broken, duplicated, or unsafe to export?
- Which external metadata file can be merged into the current catalog without starting over?

## What Makes It Different

### Local-first by design

Your catalog lives in SQLite profile databases on your own machine. The app does not depend on a hosted backend, recurring subscriptions, or third-party platforms to remain usable.

### Flexible attachment storage

File-backed records no longer have to follow a single storage rule. The app now supports two storage modes across the catalog:

- `Database` mode stores the raw file data directly in the profile database
- `Managed file` mode copies the file into an app-controlled local storage folder and stores the managed path in the database

This applies across standard track media, release artwork, custom binary fields, license PDFs, contract documents, asset versions, and GS1 workbook templates. Existing records remain readable, and supported records can be converted between modes without changing the normal UI workflow for preview, export, replace, or delete.

### Built for real catalog operations

This is not just a metadata sheet with a prettier front end. It is designed for recurring catalog work:

- importing and reconciling external metadata into an existing catalog
- matching incoming rows against existing tracks and releases
- normalizing identifiers, dates, and durations
- attaching files in either database or managed-file mode
- keeping releases, works, contracts, rights, and assets connected
- verifying readiness before export, delivery, or review
- preserving recoverable history, snapshots, backups, and repair paths

### A richer model than a basic release manager

The app is intentionally broader than a track/release tool and intentionally narrower than a royalty system. It is not trying to be a royalty accounting platform, distributor dashboard, payment tool, or DSP pitching system. It is focused on being an exceptional repertoire and catalog knowledge system.

## Core Capabilities

### Recording and release catalog

Create and maintain:

- single-track entries from the docked Add Data panel
- multi-track projects through the Add Album workflow
- first-class release records with ordered track lists
- UPC/EAN, catalog number, explicit flags, artwork, and release sequencing
- import/export-ready track metadata with portable media attachments in database or managed-file storage

The main catalog table supports fast searching, bulk selection, bulk edit, contextual actions, and direct handoff into related workflows.

### A docked catalog workspace instead of popup juggling

The app now treats the most track-table-dependent catalog tools as part of the main workspace rather than forcing you through a chain of blocking popups.

Docked workspace panels include:

- Release Browser
- Work Manager
- Catalog Managers
- License Browser
- Party Manager
- Contract Manager
- Rights Matrix
- Deliverables and Asset Versions
- Global Search and Relationships

These panels open as tabbed workspace surfaces alongside the main catalog table so you can keep browsing tracks, changing selections, filtering the table, opening related records, and moving between catalog tools without closing one window to use the next.

### Works, rights, contracts, and parties

The app models repertoire beyond recordings:

- first-class musical works with creator roles, shares, alternate titles, ISWC, and local registration numbers
- reusable party records for writers, publishers, labels, managers, lawyers, licensees, and organizations
- lifecycle-aware contracts with signature/effective/start/end/renewal/notice/reversion dates
- obligations and reminders such as approvals, notice windows, and delivery requirements
- versioned contract documents including drafts, signed finals, amendments, appendices, exhibits, and correspondence
- rights records for master, publishing, sync, mechanical, performance, neighboring, promotional, and custom right types
- conflict checks for overlapping exclusivity and missing source contracts

This gives independent artists and labels a practical way to keep legal and operational context tied directly to the catalog.

Just as importantly, those richer catalog surfaces are no longer isolated from the rest of the workflow. The managers for releases, works, parties, contracts, rights, assets, licenses, and global relationships can stay open as docked tabs while you continue working in the track table.

### Asset and deliverable management

Tracks and releases can carry multiple managed asset versions, including:

- main masters
- radio edits
- instrumentals
- clean and explicit variants
- alternate masters
- hi-res deliverables
- MP3 derivatives
- artwork variants
- promotional assets

You can track approval state, mark the primary asset, preserve derivation relationships, validate broken or duplicate asset references, and choose whether the underlying asset file lives in the database or in app-managed local storage.

### Quality control and operational readiness

The Data Quality Dashboard helps you audit the catalog before export, delivery, or review. It can flag:

- missing or duplicate identifiers
- invalid barcodes
- missing artwork or media
- missing works or creators
- invalid work split totals
- contract lifecycle gaps
- unsigned final documents
- rights conflicts
- duplicate parties
- broken asset references
- missing approved masters
- blocked or incomplete repertoire items

This is designed to surface action items, not abstract diagnostics.

### GS1 workflow support

The app includes a dedicated GS1 workflow for maintaining product metadata and exporting to official workbook templates. It verifies workbook structure, stores profile-specific defaults, and now lets the configured workbook template live either inside the profile database or as a managed local file so the export setup remains stable even if the original source file is moved.

### Import and reconcile external metadata

The import layer is designed as a rule-driven workbench rather than a generic file picker.

For structured exchange import, the app can:

- inspect incoming `CSV`, `XLSX`, `JSON`, and `ZIP package` sources before import
- preview incoming rows and choose the CSV delimiter when needed
- map source columns to supported catalog fields or active `custom::<name>` text fields
- save and reload mapping presets for repeat imports
- choose between `dry_run`, `create`, `update`, `merge`, and `insert_new`
- match against existing data by internal ID, ISRC, UPC plus title, and optional title/artist heuristics
- normalize names, titles, and durations where the importer supports it
- upsert linked release data as part of the same flow
- round-trip packaged media while preserving database-backed versus managed-file-backed storage

That makes the app useful for bringing in structured exports from labels, catalog administrators, collection-society workflows, and PRO-style metadata sources such as BUMA, STEMRA, SENA, and similar organizations, as long as those exports can be delivered in one of the supported formats. The support is format-based and mapping-based, not a direct third-party integration.

The app also includes:

- a separate XML import path for supported XML catalog files
- audio tag import/export for reading embedded tags and writing metadata to exported copies
- a separate repertoire exchange workflow for works, parties, contracts, rights, assets, and their relationships

### Trust, recovery, and maintenance

ISRC Catalog Manager treats recovery and maintenance as product features, not hidden engineering details.

The app includes:

- persistent undo/redo history for supported reversible actions
- manual snapshots and restore paths for heavier operations
- a dedicated Backups tab plus cleanup and trim flows for older artifacts
- a quality dashboard for operational catalog issues
- diagnostics for schema, storage, integrity, managed files, and history health
- repair actions for supported issues such as history reconciliation and storage-layout migration
- a staged app-data migration path for older storage layouts

Imports, restore flows, legacy license migration, and other higher-risk operations are designed to be recoverable rather than one-way.

### Theme builder and advanced QSS

The app ships with a full visual theme builder covering typography, surfaces, buttons, inputs, navigation, data views, and geometry controls, plus starter themes bundled with the application:

- Apple Light
- Apple Dark
- High Visibility
- Aeon Emerald Gold
- Subconscious Cosmos
- VS Code Dark
- Pastel Studio

It also includes a dedicated BLOB icon builder for stored media indicators:

- separate global badge icons for audio and image BLOBs
- platform-native system icons exposed through Qt
- standardized emoji choices for lightweight visual language
- compressed custom-image badges stored directly in the profile database
- per-column overrides for custom `blob_audio` and `blob_image` fields

These media badge settings are intentionally kept separate from theme presets, so you can refine how stored files are represented in the catalog without changing the broader application theme.

Advanced users can go further with a selector reference and syntax-aware QSS editor that supports safe autocomplete, rule templates, pseudo-states, subcontrols, and object-name targeting.

## Power Features Easy To Miss

Some of the strongest workflow features are easy to underestimate from a quick skim:

- the docked workspace keeps Release Browser, Work Manager, Party Manager, Contract Manager, Rights Matrix, Asset Registry, License Browser, Global Search, and Catalog Managers open beside the table as tabbed panels
- layout and dock state are remembered, so the app reopens as a real workstation instead of a fixed single screen
- the action ribbon can be customized around your high-frequency commands
- global search and relationship browsing give the richer catalog model a usable navigation layer
- package exchange can carry managed files and restore their recorded storage mode on import
- audio tag workflows can preview conflicts before writing metadata back to exported copies
- legacy license migration can move older PDF-based license records into the richer contract/document model with snapshot protection
- theme tooling goes beyond colors into starter themes, BLOB badge icons, selector discovery, and QSS autocomplete

## Who It Is For

ISRC Catalog Manager is especially useful for:

- independent artists maintaining their own release history
- boutique labels managing a developing catalog
- catalog managers cleaning up metadata across legacy projects
- publishers and rights coordinators who need a reliable local reference
- teams that want durable, local files instead of browser-only workflows

## Product Scope

The app is designed to be the catalog brain for independent music operations.

It is intentionally not built for:

- royalty accounting
- royalty statement ingestion
- distributor or DSP APIs
- payment workflows
- release pitching or distributor campaign management

That focus is deliberate. The goal is depth and reliability in catalog maintenance, repertoire knowledge, and agreement tracking.

## Workflow Overview

### 1. Build or import the catalog

Use the Add Data panel for single tracks, Add Album for grouped releases, or the exchange import workflows when catalog data already exists elsewhere. Incoming tabular data can be previewed, mapped, matched, merged, or inserted as new records depending on the source and the job.

### 2. Organize the repertoire graph

Create releases, works, parties, contracts, rights, and asset versions as first-class records. Link them across the catalog so tracks, compositions, agreements, deliverables, and supporting documents stay connected.

Use the docked workspace panels to keep those managers open as tabbed companions to the track table rather than as one-at-a-time modal dialogs.

### 3. Review, clean up, and verify

Run the quality dashboard, inspect findings, open the affected records, and use diagnostics when the issue may involve managed files, storage layout, or history artifacts rather than catalog content alone.

### 4. Export, package, or archive safely

Use XML, CSV, XLSX, JSON, GS1 workbook export, repertoire exchange, or ZIP package export depending on the workflow. Snapshots, backups, cleanup, and restore paths help protect the catalog before major operations.

## Screenshots

### Workspace

![Workspace overview](docs/screenshots/workspace-overview.png)

### Custom Fields

![Custom columns](docs/screenshots/custom-columns.png)

### Catalog Managers

![Catalog managers](docs/screenshots/catalog-managers.png)

## Workspace Design

ISRC Catalog Manager is built around a dockable desktop workspace rather than a fixed single-screen layout.

- `Add Data` and the `Catalog Table` remain the two primary day-to-day docks.
- Catalog tools that benefit from live track-table interaction now open as tabbed workspace panels.
- Related views can stay open together, which makes release assignment, work linking, rights review, contract review, license lookup, and relationship browsing much faster.
- Layout and dock state are remembered, so the app reopens the way you work.

The result is a catalog environment that feels closer to a professional desktop workstation than a sequence of forms.

### History and Snapshots

![History and snapshots](docs/screenshots/history-and-snapshots.png)

### In-app Help

![Help browser](docs/screenshots/help-browser.png)

## Documentation

Start with the docs hub in [`docs/README.md`](docs/README.md) for the user-guide reading path.

### User Guides

- [Documentation Hub](docs/README.md)
- [Import and Merge Workflows](docs/import-and-merge-workflows.md)
- [Catalog Workspace Workflows](docs/catalog-workspace-workflows.md)
- [Diagnostics and Recovery](docs/diagnostics-and-recovery.md)
- [Attachment Storage Modes](docs/file_storage_modes.md)
- [Repertoire Knowledge System](docs/repertoire_knowledge_system.md)
- [GS1 Workflow Guide](docs/gs1_workflow.md)
- [Theme Builder Guide](docs/theme_builder.md)
- [Undo, History, and Snapshots](docs/undo_redo_strategy.md)

### Developer / Internal Docs

- [Modularization Strategy](docs/modularization_strategy.md)
- [Implementation Handoffs](docs/implementation_handoffs/)

The application itself also includes a searchable in-app help browser that mirrors the major workflows, including import setup, history cleanup, diagnostics, and app-data migration behavior.

## Demo Workspace

The repository includes a demo database and sample media in the `demo/` folder so you can explore the workflow without starting from an empty profile.

## Installation

### Option 1: Build a release package

Run:

```bash
python build.py
```

The build script now follows a deterministic release workflow:

- use the current project metadata and `ISRC_manager.py` as the fixed entrypoint
- resolve packaged branding from `build_assets/icons/app_logo.*`
- bundle the runtime splash asset from `build_assets/splash.*`
- build with PyInstaller using the platform policy in the script
- stage the release artifact under `dist/release/`
- write a `dist/release_manifest.json` alongside the staged output

To customize the packaged branding, replace the files in `build_assets/icons/` and `build_assets/` with the same filenames and extensions you want the build to use.

Typical asset layout:

```text
build_assets/
  icons/
    app_logo.png
    app_logo.ico
    app_logo.icns
  splash.png
```

The build flow is designed not to package or overwrite your existing profile databases.

### Option 2: Run from source

Create an environment, install dependencies, and start the app directly:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python ISRC_manager.py
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\activate
```

## Typical Use

Once launched, you can:

- create a new profile database
- browse to an existing profile
- add tracks and grouped album data
- maintain releases, works, parties, contracts, rights, and assets
- import or export metadata
- open GS1 metadata for a single track or a selected batch
- run quality checks and repair workflows
- preview media, inspect logs, and create snapshots

## Standards and Responsibility

The app helps manage recognized industry identifiers and workflows such as ISRC, ISWC, UPC/EAN, GS1 workbook exports, and local registration metadata. It does not replace the responsibilities of your collection society, label operations, legal review, or official registration authority. It is best understood as the organized local system where you maintain and verify those details.

## Technology

ISRC Catalog Manager is built with:

- Python
- PySide6
- SQLite
- openpyxl
- mutagen
- pillow

The architecture is local-first, desktop-native, and designed for safe background task execution with SQLite-aware threading patterns.

## Developer Workflow

Install developer tooling with:

```bash
python -m pip install -r requirements-dev.txt
```

Run the main quality checks with:

```bash
python -m ruff check build.py isrc_manager tests
python -m black --check build.py isrc_manager tests
python -m mypy
python -m unittest discover -s tests -p 'test_*.py'
python -m coverage run -m unittest discover -s tests -p 'test_*.py'
python -m coverage report
```

Or use the bundled shortcuts:

```bash
make lint
make format-check
make type-check
make test
make coverage
make all-checks
```

## CI and Reliability

GitHub Actions verifies the project with:

- byte-compilation checks
- Ruff linting
- Black formatting checks
- mypy type checking
- unit and integration tests on multiple Python versions
- headless Qt app-shell coverage
- coverage thresholds
- packaging smoke validation

The test suite includes service-level coverage, dialog/controller tests, app-shell integration coverage, workflow integration tests, migration coverage, and background-task safety checks.

## Support

If you find a bug or want to improve the project, open an issue or pull request on GitHub. The application is especially suitable for self-managed and independent catalog operations, and the repository is structured to support continued expansion without losing its local-first character.

## License

See [license.md](license.md).
