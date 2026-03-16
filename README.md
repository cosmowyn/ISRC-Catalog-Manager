# ISRC Manager  
Created by **M. van de Kleut**  
22-aug-2025

---

ISRC Manager is a local-first desktop catalog application for managing tracks, first-class releases, musical works, rights, contracts, managed media, audio tag workflows, licenses, backups, snapshots, quality scans, and multi-format exchange workflows from one workspace.

## Preview

<p align="center">
  <img src="docs/screenshots/workspace-overview.png" alt="Workspace overview with docked add-data form and populated catalog table" width="48%" />
  <img src="docs/screenshots/catalog-managers.png" alt="Catalog managers dialog with fictional licensee data" width="48%" />
</p>
<p align="center">
  <img src="docs/screenshots/history-and-snapshots.png" alt="Persistent undo history and snapshot browser" width="48%" />
  <img src="docs/screenshots/help-browser.png" alt="Searchable in-app help manual" width="48%" />
</p>

## Demo Workspace

The repository now includes reproducible demo tooling under [`demo/`](demo/) so you can generate a clean showcase workspace and refresh the README screenshots without using any real catalog data.

All demo data is fictional:
- fictional artist names
- fictional track titles
- fictional artwork
- fictional license PDFs
- no personal or customer information

Create the demo workspace:

```bash
python demo/build_demo_workspace.py
```

Refresh the screenshots:

```bash
python demo/capture_demo_screenshots.py
```

The generated demo workspace is written to `demo/.runtime/` and is excluded from git. The committed screenshots live in `docs/screenshots/`.

---

# IMPORTANT LEGAL NOTICE

To legally generate and assign industry-standard registration codes, you must first acquire the correct registrant prefixes and identifiers from the relevant authorities. These codes are part of international systems for music identification and royalty collection.

Using self-invented or fake codes is strictly prohibited.  
Such codes are invalid and may cause:  
- Rejection by digital distributors  
- Loss of royalty payments  
- Legal and contractual violations  
- Damage to your reputation as an artist or label  

Always ensure your codes are officially registered before use.

---

# Worldwide Standards Overview

## 1. ISRC (International Standard Recording Code)
- Identifies individual sound recordings and music videos.  
- Format: CC-XXX-YY-NNNNN  
- Apply for an ISRC registrant prefix via your national ISRC agency.  
- In countries without a national agency, apply via IFPI:  
  https://isrc.ifpi.org

## 2. UPC / EAN
- Identifies complete releases as products.  
- Required by distributors.  
- Issued by GS1.

## 3. ISWC (International Standard Musical Work Code)
- Identifies compositions (songs).  
- Assigned automatically by your local PRO when registering works.

## 4. IPI/CAE
- Identifies songwriters, composers, and publishers.  
- Assigned when joining your local PRO.

---

# Netherlands-Specific Responsibilities

- ISRC: SENA — https://www.sena.nl  
- UPC/EAN: GS1 Nederland — https://www.gs1.nl  
- ISWC: BUMA/STEMRA — https://www.bumastemra.nl  
- IPI/CAE: Assigned by BUMA/STEMRA  

---

# ISRC Manager: Overview

ISRC Manager is a desktop application for managing ISRCs, metadata, and release information.  
It is designed for independent artists, producers, and small labels who require professional-grade catalog management without complex enterprise tools.

The application provides:
- Automatic ISRC generation in ISO 3901 format  
- Optional blank-ISRC workflows for artists who rely on distributor-assigned or later-imported codes  
- Metadata management with customizable fields  
- A grouped Add Album dialog for entering shared album data once and creating multiple tracks in one pass  
- A first-class release/product layer with release browsing, ordered track placements, UPC/EAN validation, release artwork, and release-level metadata  
- A first-class work/composition layer with creator roles, split handling, duplicate ISWC detection, and work-to-recording linking  
- Reusable party/contact records that can be linked across works, contracts, rights, and asset workflows  
- Contract lifecycle tracking with dates, obligations, linked documents, version chains, and linked works/tracks/releases  
- Rights and ownership records for masters, publishing/composition, sync, mechanical, performance, digital, promotional, and other grant types  
- Deliverables and asset version tracking for masters, alternates, derivatives, artwork variants, and approval state  
- Global search and a relationship explorer for navigating linked records across the complete local knowledge graph  
- Bulk editing for selected catalog rows with field-by-field updates  
- Audio metadata tag import and export for managed audio files, with preview-based conflict resolution  
- CSV, XLSX, JSON, XML, and packaged ZIP exchange workflows  
- A data-quality dashboard with actionable validation checks and safe repair tools across repertoire, contracts, rights, parties, and assets  
- Audio and image preview capabilities  
- Multiple profile support  
- Persistent undo/redo history with manual and automatic snapshots  
- Dockable views for the add-data form and catalog table  
- GS1 metadata editing and grouped workbook export using the official GS1 template workflow  
- Searchable in-app help with contextual help buttons  
- Theme customization with saved presets and advanced QSS  
- Full audit logging and backup system  
- Import/export tools for XML metadata  
- A built-in license management system  
- A cross-platform icon factory for building distributable applications  

---

# Features

## ISRC Code Generation
- Fully compliant with ISO 3901.  
- Supports up to 99 independent profiles (artist/label/sublabel).  
- Tracks last-used designation codes per profile.  
- Automatically assigns ISRC year based on creation date.  
- Allows reuse of the original ISRC year when importing older releases.
- If no ISRC prefix is configured, the app no longer blocks data entry: auto-generation is simply disabled and tracks can be saved with blank ISRC values until codes are available.

## Metadata Management
- Supports standard and custom metadata fields.  
- Built-in support for text, date, checkbox, dropdown, image blob, and audio blob fields.  
- Audio and image files are managed alongside the catalog database with tracked metadata, preview, export, and restore support.
- The Add Album dialog starts with shared album metadata and dynamic track sections so you can add or remove tracks as needed without leaving the main workflow.
- Selected rows can be bulk edited from the catalog table. Mixed values stay untouched unless you explicitly replace them, and protected fields such as ISRC, ISWC, Track Title, Audio File, Track Length, and BUMA work number remain view-only during bulk edit.
- Editing shared album/release fields from the track editor keeps the corresponding release record synchronized where appropriate.

## Audio Metadata Tags
- Reads embedded metadata from MP3/ID3, FLAC, OGG Vorbis/Opus, M4A/MP4, WAV, and AIFF where the format supports tags in practice.
- Maps catalog fields to tags including title, artist, album, album artist, track/disc number, genre, composer, publisher/label, release date, ISRC, UPC/EAN, comments, lyrics, and artwork.
- `Catalog > Import Tags from Audio…` previews tag-to-catalog conflicts before applying changes.
- `Catalog > Write Tags to Exported Audio…` writes catalog metadata to exported audio copies without modifying the managed source files in place.
- The default conflict policy is configurable per application profile and can be changed at import time.

## Releases and Products
- Releases are now stored as first-class records instead of only repeated track fields.
- Each release keeps title, subtitle/version, primary artist, album artist, release type, release dates, label, sublabel, catalog number, UPC/EAN, barcode validation status, territory, explicit flag, notes, and release artwork.
- Track placements are stored separately with disc number, track number, and sequence order.
- `Catalog > Release Browser…` lets you browse releases, inspect track order, duplicate a release, add the current track selection, and filter the main catalog table to a release.
- `Add Album` and normal track-save/edit flows automatically create or update release records when release-level metadata is present.

## Repertoire, Rights, and Contracts
- `Catalog > Work Manager…` stores compositions separately from recordings so one work can connect to many linked tracks.
- Works support alternate titles, subtitles/versions, lyrics vs instrumental flags, language, style notes, ISWC, local registration numbers, creator roles, split percentages, and operational status.
- `Catalog > Party Manager…` keeps one canonical person/company record per important counterparty and reuses it across works, contracts, and rights.
- `Catalog > Contract Manager…` tracks draft/signature/effective/start/end/renewal/notice/reversion/termination dates, linked parties, obligations, and document version chains.
- `Catalog > Rights Matrix…` stores ownership and grant records linked to works, tracks, releases, and source contracts, including exclusivity, territories, media-use scope, and control summaries.
- `Catalog > Asset Version Registry…` tracks masters, alternates, derivatives, artwork variants, approval state, and primary deliverable designation.
- `Catalog > Global Search and Relationships…` searches across works, tracks, releases, contracts, rights, parties, documents, and assets, then shows everything linked to the selected record.

## GS1 Metadata Workflow
- Open GS1 metadata from the Catalog menu, the table context menu, or directly from the bulk edit dialog.
- Works with single tracks and multi-track selections, including grouped album-style GS1 export rows where applicable.
- Uses the official GS1 workbook template from your GS1 environment and validates the workbook structure before export.
- Requires the `openpyxl` dependency from `requirements.txt` in the same Python environment that launches the app.

## Database & Profile Handling
- Independent ISRC sequences per profile.  
- Each profile can store unique settings and field layouts.  
- SQLite backend for stability and portability.
- Background tasks now open their own SQLite connections instead of reusing the UI connection.
- The app configures SQLite for `WAL` mode, `foreign_keys=ON`, and a busy timeout so long-running reads and writes remain safer under concurrent background work.

## Responsive Background Tasks
- Heavy workflows now run through a centralized Qt background-task manager instead of blocking the UI thread.
- Long-running tasks report status through Qt signals and update the UI only on the main thread.
- Write-heavy background jobs use per-profile write coordination so imports, snapshot restores, and other database mutations are serialized safely.
- Each worker thread opens and closes its own SQLite connection. Connections are never shared across threads.
- Failed worker writes roll back cleanly, and file-writing tasks still use history-aware rollback where supported.
- The app prevents closing while background tasks are still running so database restores, imports, exports, snapshots, and other file/database operations cannot be interrupted unsafely.

## Media Previews
- Built-in audio preview window with waveform on macOS and Windows via the app's Qt multimedia decoder stack.  
- Image preview window for artwork and promotional assets.  
- Spacebar quick preview shortcut.

## Auditing, Backups, and Logging
- Automatic timestamped backups in the app data `backups/` folder.  
- Daily human-readable logs plus structured trace logs in the app data `logs/` folder.  
- Pre-restore backup creation before applying imported data.

## Import/Export
- Export metadata to XML for distribution or archival.  
- Import XML catalogs with an optional dry-run validation mode.  
- Detailed import result report with pass/fail breakdown.  
- If the XML includes unknown custom fields, the app can offer to create those definitions before continuing with import.
- Blank ISRC values in imported XML are accepted, matching the optional-ISRC workflow used in the main entry forms.
- Export selected catalog rows to CSV, XLSX, JSON, or a ZIP package containing a JSON manifest plus referenced media copies.
- Import CSV and XLSX through a column-mapping dialog with reusable mapping presets.
- JSON exchange uses an explicit schema version and includes release data, custom fields, and media references.
- Import modes now include dry run, create, merge, update existing matches only, and insert-new-when-duplicate-exists.
- Match detection can use internal IDs, ISRC, UPC/EAN plus title, and optional title/artist heuristics.
- Exchange inspections, imports, exports, packaged ZIP creation/extraction, XML import/export, database backup/restore, manual snapshots, snapshot restores, tagged-audio export, and quality scans now run off the main thread so the workspace stays responsive during heavier jobs.
- `File > Repertoire Exchange` exports and imports the extended local knowledge model for parties, works, contracts, rights, assets, and relationship references as JSON, XLSX, CSV bundles, or ZIP packages with managed files.

## Data Quality Dashboard
- `Catalog > Data Quality Dashboard…` scans the active profile for metadata, release, media, and integrity issues.
- Checks include missing or duplicate ISRCs, missing or duplicate release UPC/EANs, invalid barcode checksums, missing release titles/dates/artwork, missing audio files, broken media references, ordering problems, orphaned licenses, required custom-field gaps, works without creators, invalid splits, duplicate ISWCs, contracts near notice deadlines, missing signed final contract documents, rights conflicts, duplicate parties, missing linked works, broken asset references, missing approved masters, and blocked/incomplete repertoire items.
- Suggested fixes include regenerating derived values, normalizing dates, relinking missing media by filename, and filling blank track fields from linked release metadata.
- Issue lists can be exported to CSV or JSON for reporting or cleanup planning.

---

# License Management System

The License Manager allows you to:
- Store multiple license records linked to track titles  
- Associate licenses with profiles
- Manage Licensee parties
- See how many licenses are linked to a licensee

---

# Icon Factory (Cross-Platform)

A complete icon creation tool is integrated into the build workflow.  
It supports:

- macOS: `.icns`  
- Windows: `.ico`  
- Linux: `.png` (512×512)

Features:
- GUI file picker using Tkinter  
- Automatic square cropping  
- Optional centre-crop if the selected image is not 1:1  
- Upscaling to meet platform-specific resolutions  
- Multi-size ICO generation for Windows  
- Automatic output directory grouping by OS  

This allows users to generate branded application icons during the build process without external tools.

---

# Build Script (build.py)

The build script is designed to work safely on clean systems with no preinstalled dependencies.  
It automatically handles:

- Virtual environment creation  
- Requirements installation  
- PyInstaller setup  
- Optional icon generation  
- Application packaging  
- Installation to a user-writable directory  

## New Startup Workflow

When launching the script, the user is presented with two options:

### 1. Create Environment Only
- Creates `.venv` inside the project  
- Installs all required dependencies  
- Skips PyInstaller build  
- Skips icon generation  
- Exits cleanly after environment setup  
- Safe for users who want to prepare a development environment without building the app

### 2. Full Build (Build Application Binary)
- Performs everything in option 1  
- Prompts for an icon (or uses the icon factory)  
- Builds a distributable application using PyInstaller  
- Prompts the user for an installation directory  
- Copies the built app to the selected target  
- Recreates the Windows project structure if applicable  

Both flows use Tkinter dialogs when available and automatically fall back to console prompts if GUI elements are unavailable.

---

# Installation

## Prerequisites
- macOS, Windows, or Linux  
- Python 3.10+  

## Running the Installer

Navigate to the project folder and run:

```
python build.py
```

You will be prompted to choose:

- Create environment only  
- Or build the full distributable application  

After a successful build, the installer will ask for a destination folder and install the packaged app there.

The install process will never overwrite your existing Database folder.

## Development Checks

Run the lightweight verification suite with:

```
python -m unittest discover -s tests -v
python -m py_compile ISRC_manager.py build.py icon_factory.py
```

GitHub Actions also runs these checks automatically on pushes and pull requests.

---

# Usage

## Starting the Application
You may start the app by either:
- launching the built executable  
- or running `python ISRC_manager.py` directly in the project environment  

Upon first launch you will:
- choose a project directory  
- allow the database to initialize automatically  

## Profiles
Each profile maintains:
- its own ISRC sequences  
- custom metadata layout  
- license associations  
- appearance settings  

Switch between profiles at any time.

## Adding Records
- Use the Add Data panel to create a single track. If a valid ISRC prefix is configured, the form previews and auto-generates the next code on save.
- If no ISRC prefix is configured, the form still saves normally and leaves ISRC blank until you set or import one later.
- Use `Edit > Add Album…`, the Add Album button, or the action ribbon to open the grouped album-entry dialog.
- In Add Album, enter shared album fields once, then add or remove track sections as needed. Leaving a track ISRC blank will auto-generate it only when ISRC generation is configured.
- Attach audio or artwork directly to the record if desired.

## Editing Existing Records
- Double-click a standard row in the catalog table to open the full editor for a single track.
- Select multiple rows and use `Edit Selected`, the Edit menu, or the table context menu to open the bulk edit dialog.
- Right-clicking inside an existing multi-row selection keeps that selection intact so bulk actions stay available from the context menu.
- Use the `GS1 Metadata…` button from the edit dialog or bulk edit dialog to continue directly into the GS1 workflow for the same selected tracks.

## Custom Fields
Available field types:
- Text  
- Checkbox  
- Date  
- Dropdown  
- Blob_image  
- Blob_audio  

Custom fields appear as new columns in the table view and are stored in the database.

## Backups
Backups are created automatically and stored under:
- `/Database/backups/`  
Logs are stored in:
- `/Database/logs/`  

## Import/Export
- Export to XML, CSV, XLSX, JSON, or a packaged ZIP archive  
- Import XML, CSV, XLSX, and JSON with preview/mapping where applicable  
- Import validates field structure, reports warnings/skips/failures, and can update or merge existing rows  
- Use `File > Repertoire Exchange` to import or export parties, works, contracts, rights, deliverables, and their relationship references without mixing those flows into the regular track-exchange workflow.

## Releases
- Use `Catalog > Release Browser…` to browse or edit release/product records directly.
- Saving `Add Album` creates a first-class release and ordered release-track rows automatically.
- Single-track save/edit workflows also keep release-level values such as release title, UPC/EAN, release date, and artwork synchronized when possible.

## Works, Rights, and Contracts
- Use `Catalog > Work Manager…` to create and validate compositions separately from recordings, including linked creators and split totals.
- Use `Catalog > Party Manager…` to maintain reusable songwriter, publisher, label, licensee, manager, lawyer, or organization records.
- Use `Catalog > Contract Manager…` to track lifecycle dates, obligations, linked assets, and the currently governing signed/amended contract document version.
- Use `Catalog > Rights Matrix…` to record which party controls master, publishing, sync, mechanical, performance, or other rights in each territory.
- Use `Catalog > Asset Version Registry…` to register the primary master, derivatives, alternates, and artwork variants for one track or release.
- Use `Catalog > Global Search and Relationships…` to search across the full local knowledge model and inspect linked records from one place.

## Audio Tag Workflows
- Use `Catalog > Import Tags From Audio…` to read embedded tags from the managed audio attached to the current selection.
- Right-click a track row to import tags, open the linked release, or export tagged audio copies from the context menu.
- Tagged audio export is available directly from `Catalog > Write Tags to Exported Audio…` and from the main table context menu for tracks that already have managed audio attached.

## Quality Dashboard
- Use `Catalog > Data Quality Dashboard…` to scan the current profile and jump directly to affected tracks or releases.
- Export the current issue list to CSV or JSON from the dashboard.
- The dashboard now also flags work-split problems, contract/document lifecycle gaps, party duplicates, rights conflicts, asset issues, and blocked/incomplete repertoire readiness.

## Automatic Migration
- Existing profile databases are migrated automatically on open.
- Older album-style metadata is preserved and used to infer release records safely where possible.
- Older track rows remain valid and usable; the migration does not destroy legacy data.
- The repertoire/rights/contracts expansion is additive: older databases keep their existing track, release, and license data while new works, parties, rights, contracts, documents, assets, and saved searches are added through safe schema migration.

## Runtime Dependencies
- `PySide6`: GUI framework
- `audioread`: legacy waveform/audio decode fallback
- `openpyxl`: XLSX exchange and official GS1 workbook handling
- `pillow`: image processing and icon tooling
- `mutagen`: audio metadata tag read/write across common formats

## Developer Quality Checks

Install the development toolchain:

```bash
python -m pip install -r requirements-dev.txt
```

Run the checks individually:

```bash
python -m ruff check build.py isrc_manager tests
python -m black --check build.py isrc_manager tests
python -m mypy
python -m unittest discover -s tests -p 'test_*.py'
python -m coverage run -m unittest discover -s tests -p 'test_*.py'
python -m coverage report
python -m coverage xml
```

Apply formatting fixes:

```bash
python -m black build.py isrc_manager tests
```

Or use the bundled `Makefile` shortcuts:

```bash
make lint
make format-check
make type-check
make test
make coverage
make all-checks
```

## CI Quality Gates

GitHub Actions now runs separate jobs for:
- Python byte-compilation sanity checks
- Ruff linting
- Black formatting checks
- mypy type checking on the curated service/domain scope
- unittest on Python 3.10 and 3.13
- coverage XML generation with an 80% package-level threshold
- a lightweight packaging smoke check for PyInstaller availability

---

# Keyboard Shortcuts

Audio Preview:
- Space: Play / Pause  
- Escape: Close  
- Left Arrow: Scrub backwards  
- Right Arrow: Scrub forwards  

---

# Support
- Bug reports may be submitted via GitHub Issues.  
- Pull requests are welcome.  
- This project is primarily intended for personal and independent use.

---

# License
Provided "as is" without warranty. Free to use, copy, and distribute for any purpose, provided that original credits are retained. Not for resale.
