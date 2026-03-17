from __future__ import annotations

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class HelpChapter:
    chapter_id: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    content_html: str


HELP_CHAPTERS: tuple[HelpChapter, ...] = (
    HelpChapter(
        chapter_id="overview",
        title="Overview",
        summary="A clear product overview of what the app manages, why it exists, and how the main workflows fit together.",
        keywords=(
            "overview",
            "introduction",
            "menus",
            "workflow",
            "catalog",
            "tracks",
            "album entry",
            "licenses",
            "gs1",
            "bulk edit",
            "action ribbon",
            "quick actions",
            "releases",
            "audio tags",
            "csv",
            "json",
            "xlsx",
            "quality dashboard",
            "background tasks",
            "threading",
        ),
        content_html="""
        <p><strong>ISRC Catalog Manager</strong> is a local-first desktop workspace for building and maintaining a serious music catalog. It brings together recording metadata, release management, musical works, contracts, rights, parties, documents, deliverables, GS1 product data, history, and quality control in one application.</p>
        <p>It is designed for independent artists, labels, managers, and catalog owners who need more than a basic track list and want a reliable system for both metadata and catalog operations.</p>
        <p>The app is organized around a few core ideas:</p>
        <ul>
          <li><strong>Profiles</strong>: each profile is a self-contained catalog database, so separate catalogs remain clean and portable.</li>
          <li><strong>Add Data</strong>: the dockable track-entry workspace for fast single-record creation.</li>
          <li><strong>Add Album</strong>: a structured multi-track workflow for releases that share core metadata.</li>
          <li><strong>Releases</strong>: first-class product records for UPC/EAN, release artwork, ordering, and release-level metadata.</li>
          <li><strong>Works</strong>: a composition layer that stays distinct from recordings so the same work can connect to multiple tracks.</li>
          <li><strong>Parties</strong>: reusable people and companies for writers, publishers, labels, managers, licensees, and organizations.</li>
          <li><strong>Contracts and rights</strong>: lifecycle-aware agreement records, obligations, document versions, and explicit rights positions linked back to the catalog.</li>
          <li><strong>Assets</strong>: managed deliverables and artwork variants with approval and primary-version tracking.</li>
          <li><strong>Catalog Table</strong>: the central browser for searching, selecting, bulk editing, and reviewing recording data.</li>
          <li><strong>Global Search</strong>: a relationship-aware search surface across works, tracks, releases, contracts, rights, parties, documents, and assets.</li>
          <li><strong>Exchange</strong>: CSV, XLSX, JSON, XML, ZIP, and GS1 workflows for sharing, exporting, and archiving the catalog safely.</li>
          <li><strong>Quality Dashboard</strong>: a practical readiness view for metadata gaps, identifier conflicts, broken media links, rights risks, and operational blockers.</li>
          <li><strong>Action Ribbon</strong>: a customizable quick-action strip for your most-used commands.</li>
          <li><strong>Background tasks</strong>: longer scans, imports, exports, snapshots, and file operations run outside the UI thread to keep the workspace responsive.</li>
          <li><strong>Settings and history</strong>: identity, registration settings, themes, undo/redo, snapshots, diagnostics, and logs.</li>
          <li><strong>Media badge icons</strong>: separate visual indicators for stored audio and image BLOBs can be configured with system icons, emoji, or compressed custom images.</li>
        </ul>
        <p>The menu bar mirrors those workflows. <strong>File</strong> handles profiles and exchange, <strong>Edit</strong> focuses on direct catalog actions, <strong>Catalog</strong> opens the richer repertoire tools, <strong>Settings</strong> controls app and profile configuration, <strong>View</strong> manages layout and columns, <strong>History</strong> protects recoverability, and <strong>Help</strong> gives you diagnostics, logs, and this manual.</p>
        """,
    ),
    HelpChapter(
        chapter_id="main-window",
        title="Main Window",
        summary="How the main workspace is laid out, how the docks behave, and how to move through the app efficiently.",
        keywords=(
            "main window",
            "toolbar",
            "profiles",
            "dock",
            "layout",
            "window",
            "action ribbon",
            "quick actions",
        ),
        content_html="""
        <p>The main window is designed as a practical catalog workspace rather than a single fixed screen. By default, the left side contains the <strong>Add Data</strong> workspace and the right side contains the <strong>Catalog Table</strong>, but both can be shown, hidden, floated, and re-docked.</p>
        <ul>
          <li><strong>Action ribbon</strong>: a customizable strip of high-frequency actions. Use <strong>View &gt; Customize Action Ribbon…</strong> to make it match your workflow.</li>
          <li><strong>Profiles toolbar</strong>: switch databases, create a new profile, browse to an external profile, reload the profile list, or remove the selected entry.</li>
          <li><strong>Dockable panes</strong>: keep the window focused on your current task by showing only the panes you need.</li>
          <li><strong>Saved layout</strong>: column layout, dock placement, and visibility preferences are remembered so the app opens the way you work.</li>
        </ul>
        <p>Use the menus when you need the full surface of the product, or stay inside the docked views for everyday entry and review. The window title, branding, and appearance can be customized from <strong>Settings &gt; Application Settings</strong>.</p>
        """,
    ),
    HelpChapter(
        chapter_id="profiles",
        title="Profiles and Databases",
        summary="How catalog profiles work, how to switch between them, and why they make the app safe and portable.",
        keywords=(
            "profiles",
            "database",
            "workspace",
            "browse",
            "create profile",
            "remove profile",
            "switch",
        ),
        content_html="""
        <p>A profile is one self-contained SQLite catalog database. It gives you a clean boundary around a label, artist, catalog, client, or project so your data stays organized and portable.</p>
        <ul>
          <li><strong>New…</strong>: create a fresh local profile database.</li>
          <li><strong>Browse…</strong>: open an existing database file from any location.</li>
          <li><strong>Reload List</strong>: refresh the known profile list from disk.</li>
          <li><strong>Remove…</strong>: remove the selected profile from the list and, if you choose, from disk as well.</li>
        </ul>
        <p>Profile-specific catalog data stays with the profile. Shared app-level conveniences such as saved themes and remembered layout settings stay available across profiles. That balance keeps the product practical for both single-catalog and multi-catalog use.</p>
        """,
    ),
    HelpChapter(
        chapter_id="background-tasks",
        title="Background Tasks",
        summary="How the app keeps long operations responsive and safe without risking the catalog database.",
        keywords=(
            "background tasks",
            "threading",
            "progress",
            "cancel",
            "sqlite",
            "wal",
            "imports",
            "exports",
        ),
        content_html="""
        <p>Long-running operations no longer have to compete with the interface. The app runs heavier workflows outside the UI thread so the workspace stays responsive while real work is happening.</p>
        <ul>
          <li><strong>Central task runner</strong>: imports, exports, ZIP packaging, snapshots, restores, quality scans, tagged-audio export, backup, and integrity checks are dispatched through one shared Qt background-task manager.</li>
          <li><strong>Main-thread UI updates only</strong>: worker threads report back through Qt signals, and dialogs, tables, messages, and status text are updated on the main thread only.</li>
          <li><strong>Per-thread SQLite connections</strong>: background jobs never reuse the main window's SQLite connection. Each worker opens and closes its own connection safely.</li>
          <li><strong>SQLite concurrency</strong>: the app enables WAL mode, foreign-key enforcement, and a busy timeout. Write-heavy jobs are serialized per profile so concurrent background writers do not fight each other.</li>
          <li><strong>Progress and cancellation</strong>: longer jobs show a progress dialog or in-place status text where practical. Some file-based jobs, such as tagged-audio export, can be cancelled safely.</li>
          <li><strong>Safe shutdown</strong>: the app blocks closing while background jobs are still running so restores, imports, and other file/database writes cannot be interrupted mid-operation.</li>
        </ul>
        <p>If a background task fails, the app reports it clearly, logs the details, and rolls database work back cleanly. The result is a system that feels responsive without becoming fragile.</p>
        """,
    ),
    HelpChapter(
        chapter_id="add-data",
        title="Add Data Panel",
        summary="How to add a track quickly, organize the entry flow by tab, and attach the metadata and media needed for a real catalog.",
        keywords=(
            "add data",
            "add track",
            "save track",
            "audio file",
            "album art",
            "release date",
            "isrc",
            "prefix",
            "dsp",
        ),
        content_html="""
        <p>The Add Data panel is the fastest way to create a new recording. It is organized into focused tabs so you can move quickly without losing access to the full metadata path.</p>
        <ul>
          <li><strong>Track</strong>: track title, main artist, additional artists, and genre.</li>
          <li><strong>Release</strong>: album title, release date, and track length.</li>
          <li><strong>Codes</strong>: preview-only generated values such as the future row ID, generated ISRC, and entry date, plus ISWC, UPC/EAN, catalog number, and BUMA work number.</li>
          <li><strong>Media</strong>: attach a local audio file and album art image that the app manages for the selected track.</li>
        </ul>
        <p>Use <strong>Save Track</strong> to create the record, or <strong>Reset Form</strong> to clear the current draft. If ISRC generation is configured, the preview updates automatically from your active settings. If it is not configured yet, the track still saves cleanly and can be completed later.</p>
        """,
    ),
    HelpChapter(
        chapter_id="album-entry",
        title="Add Album Dialog",
        summary="How to create a multi-track release efficiently by entering shared metadata once and saving the whole set together.",
        keywords=(
            "add album",
            "album dialog",
            "multi track",
            "album entry",
            "track sections",
            "shared metadata",
        ),
        content_html="""
        <p>The <strong>Add Album</strong> dialog is built for real release entry. Instead of retyping the same album data over and over, you enter the shared product details once and then complete each track on its own tab.</p>
        <ul>
          <li><strong>Album Overview</strong>: album title, UPC/EAN, genre, catalog number, album art, and the release-year rule used when auto-generating blank ISRC values.</li>
          <li><strong>Track Tabs</strong>: each tab stores one track title, main artist, additional artists, release date, track length, optional ISRC, optional ISWC, optional BUMA work number, and an audio file.</li>
          <li><strong>Dynamic layout</strong>: the dialog opens with two track tabs by default, but you can add more or remove the current tab at any time.</li>
          <li><strong>Blank-tab handling</strong>: completely unused track tabs are ignored when you save, so you do not need to delete every spare tab before closing the dialog.</li>
          <li><strong>Shared album art</strong>: the selected album art is stored once and linked across the saved album tracks automatically.</li>
        </ul>
        <p>If ISRC generation is configured, blank track ISRC fields can be generated automatically during save. If not, the dialog still creates the release and track rows successfully so you can complete identifiers later.</p>
        """,
    ),
    HelpChapter(
        chapter_id="catalog-table",
        title="Catalog Table",
        summary="How to browse, search, select, inspect, and bulk-operate on the existing catalog from the main table.",
        keywords=(
            "catalog table",
            "search",
            "columns",
            "preview",
            "double click",
            "table",
            "records",
            "bulk edit",
            "context menu",
            "multi selection",
        ),
        content_html="""
        <p>The Catalog Table is the operational center of the app once data has been entered. It is built for browsing, cleaning, selecting, and acting on real catalog records at speed.</p>
        <ul>
          <li><strong>Search controls</strong>: choose a target column or search all columns, then enter search text to filter the list.</li>
          <li><strong>Column visibility</strong>: use <strong>View &gt; Columns</strong> to show or hide visible columns without deleting them.</li>
          <li><strong>Double click</strong>: edit a standard row, or open file pickers directly for standard media columns such as Audio File and Album Art.</li>
          <li><strong>Multi-row selection</strong>: select multiple rows and open <strong>Edit Selected</strong> or the context menu to launch bulk edit for the current batch.</li>
          <li><strong>Context menu and shortcuts</strong>: preview media, copy values, open GS1 metadata, and edit/delete the current selection. Right-clicking inside an existing multi-row selection keeps that batch selected.</li>
        </ul>
        <p>Table layout, column widths, ordering, and visibility are remembered so the browser can feel tailored to your workflow rather than generic.</p>
        """,
    ),
    HelpChapter(
        chapter_id="custom-columns",
        title="Custom Columns",
        summary="Create, rename, reorder, remove, and populate custom metadata fields beyond the default track schema.",
        keywords=(
            "custom columns",
            "custom fields",
            "metadata",
            "dropdown",
            "checkbox",
            "date",
            "columns",
        ),
        content_html="""
        <p>Custom columns let you extend the catalog beyond the built-in track fields. Supported field types include text, dropdown, checkbox, and date-based custom values.</p>
        <ul>
          <li><strong>Add Custom Column…</strong>: create a new reusable custom field definition.</li>
          <li><strong>Remove Custom Column…</strong>: permanently remove a custom field definition.</li>
          <li><strong>Manage Custom Columns…</strong>: rename definitions, change types, and update dropdown options.</li>
          <li><strong>BLOB field icons</strong>: custom <code>blob_audio</code> and <code>blob_image</code> fields can inherit the global media badge icons or use their own system icon, emoji, or compressed custom image.</li>
        </ul>
        <p>Custom columns can be visible in the table, exported, imported, and edited per track. The View menu controls whether they are shown, while the custom columns manager controls whether they exist at all.</p>
        """,
    ),
    HelpChapter(
        chapter_id="edit-entry",
        title="Edit Entry",
        summary="How the full editor works for existing tracks, including single-edit, bulk-edit, validation, and related handoff flows.",
        keywords=(
            "edit entry",
            "track editor",
            "edit track",
            "iswc",
            "upc",
            "catalog number",
            "buma",
            "bulk edit",
            "gs1 metadata",
            "release sync",
        ),
        content_html="""
        <p>The Edit Entry dialog is the full maintenance editor for existing records. When one row is selected, it behaves as a detailed track editor. When multiple rows are selected, it switches into <strong>bulk edit</strong> mode and protects fields that should not be overwritten casually.</p>
        <ul>
          <li><strong>Copy buttons</strong>: copy ISO or compact forms of ISRC and ISWC values.</li>
          <li><strong>Media replacement</strong>: browse for new audio or album art files, or clear the currently stored media.</li>
          <li><strong>Bulk edit safeguards</strong>: only fields you actually change are written back to every selected row.</li>
          <li><strong>Bulk edit locked fields</strong>: ISRC, ISWC, Track Title, Audio File, Track Length, and BUMA work number remain view-only during multi-row editing.</li>
          <li><strong>GS1 handoff</strong>: the <strong>GS1 Metadata…</strong> button opens the GS1 dialog for the same current track or selected batch.</li>
          <li><strong>Validation</strong>: duplicate ISRCs, invalid ISWC values, and invalid UPC/EAN values are blocked before save.</li>
        </ul>
        <p>Saving changes updates the relevant rows, records the action in history, and keeps related catalog structures synchronized where shared release-level data is affected.</p>
        """,
    ),
    HelpChapter(
        chapter_id="audio-tags",
        title="Audio Tags",
        summary="Import embedded tags from supported audio files and write catalog metadata back to exported copies.",
        keywords=(
            "audio tags",
            "id3",
            "flac",
            "vorbis",
            "m4a",
            "mp4",
            "wav",
            "aiff",
            "import tags",
            "write tags",
        ),
        content_html="""
        <p>The app can read and write embedded audio metadata so the catalog and exported audio files stay aligned.</p>
        <ul>
          <li><strong>Supported read/write families</strong>: MP3/ID3, FLAC/Vorbis comments, OGG Vorbis/Opus comments, M4A/MP4 atoms, and WAV/AIFF where ID3-style metadata is available.</li>
          <li><strong>Mapped fields</strong>: title, artist, album, album artist, track number, disc number, genre, composer, publisher/label, release date, ISRC, UPC/EAN, comments, lyrics, and artwork.</li>
          <li><strong>Import Tags From Audio…</strong>: open it from the Catalog menu or the table context menu to preview conflicts before catalog values are changed.</li>
          <li><strong>Conflict policy</strong>: choose whether file tags should fill blanks only, override database values, or defer to the existing catalog data.</li>
          <li><strong>Write Tags To Exported Audio…</strong>: exports tagged audio copies to a folder without touching the managed source files in place.</li>
        </ul>
        <p>The app preserves the original audio data when writing tags to exported copies. Unsupported or malformed tags are skipped with warnings instead of crashing the workflow.</p>
        """,
    ),
    HelpChapter(
        chapter_id="releases",
        title="Releases",
        summary="How product-level release records work and why they matter alongside track-level recording data.",
        keywords=(
            "releases",
            "release browser",
            "product",
            "upc",
            "catalog number",
            "disc number",
            "track number",
        ),
        content_html="""
        <p>The app stores releases as first-class product records rather than repeating product metadata across individual tracks. This gives the catalog a cleaner commercial layer and makes exports, ordering, and release maintenance much easier to trust.</p>
        <ul>
          <li><strong>Release fields</strong>: title, subtitle/version, primary artist, album artist, release type, release dates, label, sublabel, catalog number, UPC/EAN, barcode validation status, territory, explicit flag, notes, and release artwork.</li>
          <li><strong>Release order</strong>: releases store disc number, track number, and sequence separately from the track metadata itself.</li>
          <li><strong>Add Album integration</strong>: saving a grouped album entry automatically creates or updates a real release and attaches the created tracks.</li>
          <li><strong>Release Browser…</strong>: browse releases, inspect the ordered track list, duplicate releases, add the current track selection, and filter the main catalog table to a chosen release.</li>
          <li><strong>Single-track workflows</strong>: saving the Add Data panel or the Edit Entry dialog also keeps the corresponding release record synchronized when release-level fields change.</li>
        </ul>
        <p>Older databases are migrated additively. Existing catalog data remains usable, while release records are inferred where possible to give older profiles access to the richer product model without destructive change.</p>
        """,
    ),
    HelpChapter(
        chapter_id="repertoire-knowledge",
        title="Works, Rights, and Contracts",
        summary="How the app expands beyond recordings into a connected repertoire, rights, and agreement system.",
        keywords=(
            "works",
            "compositions",
            "contracts",
            "rights",
            "parties",
            "documents",
            "deliverables",
            "assets",
            "relationship explorer",
        ),
        content_html="""
        <p>The app now models more than recordings and releases. It treats the broader catalog as a connected knowledge system so operational, legal, and creative context can live in the same place.</p>
        <ul>
          <li><strong>Works</strong>: compositions live separately from recordings. A work can store alternate titles, subtitle/version, language, lyrics/instrumental flags, genre/style notes, ISWC, local registration numbers, creator roles, shares, and notes.</li>
          <li><strong>Work creators and splits</strong>: songwriter, composer, lyricist, arranger, adaptor, publisher, and subpublisher roles can all be recorded. Split totals are validated so share mistakes are easy to spot.</li>
          <li><strong>Track-to-work links</strong>: one work can link to many recordings, and one recording can link back to more than one work where needed. Tracks and releases continue to keep their own recording/product metadata.</li>
          <li><strong>Parties</strong>: reusable people and companies can be linked as writers, publishers, contract counterparties, licensors, licensees, and rights holders.</li>
          <li><strong>Contracts</strong>: draft, signature, effective, start, end, renewal, notice, reversion, and termination dates are stored as structured fields. Contracts can link to works, tracks, releases, and parties.</li>
          <li><strong>Obligations and reminders</strong>: delivery, approval, exclusivity, notice, follow-up, and reminder obligations can be stored per contract.</li>
          <li><strong>Document intelligence</strong>: a contract can keep multiple managed documents such as drafts, signed agreements, amendments, appendices, exhibits, correspondence, and scans, with version labels and active/superseded relationships.</li>
          <li><strong>Rights matrix</strong>: rights records store the right type, exclusivity, territory, media/use scope, dates, source contract, and who granted, received, or retained the right.</li>
          <li><strong>Assets and deliverables</strong>: tracks and releases can keep primary masters, alternates, derivatives, artwork variants, and approval state in one registry.</li>
          <li><strong>Global Search and Relationships…</strong>: search across the full model and inspect everything linked to the selected record from one panel.</li>
        </ul>
        <p>This richer model is intentionally catalog-focused. It gives independent teams a practical way to understand what they own, what is linked, and what is ready, without turning the app into a royalty or distribution platform.</p>
        """,
    ),
    HelpChapter(
        chapter_id="exchange-formats",
        title="Exchange Formats",
        summary="How the app moves metadata in and out safely through exchange formats built for both daily operations and durable archives.",
        keywords=(
            "csv",
            "xlsx",
            "json",
            "xml",
            "package",
            "zip",
            "column mapping",
            "dry run",
            "import report",
        ),
        content_html="""
        <p>The exchange layer is designed for real catalog portability. Whether you are sharing data, taking a structured backup, preparing downstream workflows, or moving a project between systems, the app gives you more than a single export button.</p>
        <ul>
          <li><strong>Export formats</strong>: CSV, XLSX, JSON, XML, and ZIP packages containing a JSON manifest plus copied media references.</li>
          <li><strong>Import formats</strong>: CSV, XLSX, JSON, ZIP packages, and XML.</li>
          <li><strong>Import preview</strong>: CSV and XLSX imports open a mapping dialog so you can confirm how source columns map to standard or custom fields before running the import.</li>
          <li><strong>Saved mapping presets</strong>: frequently used column mappings can be saved per format and reused later.</li>
          <li><strong>Import modes</strong>: dry-run validation, create new rows, merge into existing matches, update existing matches only, or insert-new-when-duplicate-exists.</li>
          <li><strong>Matching options</strong>: internal ID, ISRC, UPC/EAN plus title, and optional title/artist heuristics.</li>
          <li><strong>JSON schema versioning</strong>: exported JSON includes an explicit schema version so future migrations stay manageable.</li>
          <li><strong>Repertoire Exchange</strong>: a separate import/export workflow now covers parties, works, contracts, rights, asset versions, and their relationship references as JSON, XLSX, CSV bundles, or ZIP packages with managed files.</li>
        </ul>
        <p>Binary media is referenced in plain tabular exports, while ZIP packages can include copied managed files for portability. Import preview, packaging, export, and extraction all run in the background so larger exchange jobs stay practical.</p>
        """,
    ),
    HelpChapter(
        chapter_id="quality-dashboard",
        title="Quality Dashboard",
        summary="How to audit the profile for real operational issues and move directly from findings to fixes.",
        keywords=(
            "quality dashboard",
            "issues",
            "validation",
            "duplicates",
            "broken media",
            "fixes",
            "export readiness",
        ),
        content_html="""
        <p>The <strong>Data Quality Dashboard</strong> is designed as an operational review surface, not just a validator. It scans the active profile for issues that can materially affect catalog trust, export readiness, delivery, or rights clarity.</p>
        <ul>
          <li><strong>Headline counts</strong>: total issues plus error, warning, and informational totals.</li>
          <li><strong>Rule coverage</strong>: missing or duplicate ISRCs, missing or duplicate release UPC/EANs, invalid barcode checksums, missing titles/artists/dates, missing artwork, broken media references, ordering issues, orphaned licenses, required custom-field gaps, works without creators, invalid split totals, duplicate ISWC values, contract deadline risks, contracts without signed final documents, active rights without source contracts, overlapping exclusive rights, duplicate parties, missing linked works, broken asset references, missing approved masters, and blocked/incomplete repertoire states.</li>
          <li><strong>Filters</strong>: narrow the current issue list by severity, issue type, entity type, or release.</li>
          <li><strong>Open Record</strong>: jump directly to the affected track or release editor from the selected issue row, then use the related managers and search tools to inspect linked works, contracts, rights, parties, and assets.</li>
          <li><strong>Suggested fixes</strong>: regenerate derived values, normalize date formats, relink missing media by filename, or fill blank track values from linked release metadata where appropriate.</li>
          <li><strong>Export</strong>: save the current issue list to CSV or JSON for reporting or offline cleanup planning.</li>
        </ul>
        <p>Quality scans run on demand in the background and are meant to help you move from problem detection to action quickly.</p>
        """,
    ),
    HelpChapter(
        chapter_id="gs1-metadata",
        title="GS1 Metadata",
        summary="How the GS1 workflow connects catalog data, grouped product editing, and verified workbook export.",
        keywords=(
            "gs1",
            "gs1 metadata",
            "workbook",
            "template",
            "export",
            "album groups",
            "official workbook",
        ),
        content_html="""
        <p>The GS1 Metadata dialog turns catalog data into a structured GS1 workflow. It can be opened for a single track or for a selected batch, and it groups the current selection into one or more final product rows depending on release context.</p>
        <ul>
          <li><strong>Single track or batch</strong>: launch it from the Catalog menu, the table context menu, or the edit and bulk edit dialogs.</li>
          <li><strong>Grouped editing</strong>: album-style selections can appear as grouped GS1 product tabs, while singles remain separate export rows.</li>
          <li><strong>Official workbook</strong>: choose the official GS1 workbook from your GS1 environment. The app validates headers and sheet structure before export.</li>
          <li><strong>Python dependency</strong>: GS1 workbook validation and export require the <code>openpyxl</code> package in the same Python environment that starts the app.</li>
        </ul>
        <p>Use <strong>Save</strong> to keep GS1 data in the catalog, <strong>Export Current…</strong> to write the active product, or <strong>Export Batch…</strong> to generate a full workbook from the selected set.</p>
        """,
    ),
    HelpChapter(
        chapter_id="metadata-dates",
        title="Date Picking",
        summary="How date selection works for release dates and custom date fields.",
        keywords=("date picker", "release date", "calendar", "dates"),
        content_html="""
        <p>The app uses calendar pickers for release dates and date-based custom fields. The picker lets you select a date, clear a date where supported, and return the result in ISO <code>yyyy-MM-dd</code> format.</p>
        <p>Release dates can affect generated ISRC previews when the option to use the release year is enabled.</p>
        """,
    ),
    HelpChapter(
        chapter_id="licenses",
        title="Licenses and Managed PDFs",
        summary="Upload signed license PDFs, browse them, update them, download them, and manage licensees.",
        keywords=("licenses", "licensees", "pdf", "upload", "download", "browse licenses"),
        content_html="""
        <p>The app can store signed license PDFs alongside the catalog. The license workflow is split into a few focused dialogs:</p>
        <ul>
          <li><strong>Add License (PDF)</strong>: attach a PDF to a track and assign a licensee.</li>
          <li><strong>Licenses</strong>: browse all stored license records, preview them, download them, edit them, or delete them.</li>
          <li><strong>Manage Licensees</strong>: add, rename, and delete reusable licensee names.</li>
        </ul>
        <p>If you are moving into the richer contract system, <strong>Catalog &gt; Migrate Legacy Licenses to Contracts…</strong> converts the legacy license archive into Party records plus Contract records with managed contract documents. The migration copies each stored PDF into the newer contract-document archive, verifies the copied file, and only then removes the legacy rows and old managed license files. Before/after restore points are captured automatically so the migration can be rolled back safely.</p>
        <p>License actions participate in snapshot-based history so the catalog and managed files remain recoverable when possible.</p>
        """,
    ),
    HelpChapter(
        chapter_id="catalog-managers",
        title="Catalog Managers",
        summary="Manage reusable artist, album, and licensee data from one consolidated manager dialog.",
        keywords=("catalog managers", "artists", "albums", "licensees", "purge unused", "manage"),
        content_html="""
        <p>The consolidated <strong>Catalog Managers</strong> dialog groups catalog maintenance tasks into dedicated tabs.</p>
        <ul>
          <li><strong>Artists</strong>: inspect artist usage counts and remove or purge only artists that are no longer used.</li>
          <li><strong>Albums</strong>: inspect album usage counts and remove or purge unused albums.</li>
          <li><strong>Licensees</strong>: maintain reusable licensee names used by license records.</li>
        </ul>
        <p>These tools are intended for cleanup and normalization. The app prevents deletion of items that are still referenced by tracks or licenses where that would break data integrity.</p>
        """,
    ),
    HelpChapter(
        chapter_id="settings",
        title="Application Settings",
        summary="The central settings workspace for branding, registration values, snapshots, GS1 defaults, and appearance.",
        keywords=(
            "settings",
            "application settings",
            "window title",
            "icon",
            "isrc prefix",
            "snapshot interval",
        ),
        content_html="""
        <p>The Application Settings dialog brings the app's most important configuration into one organized workspace so you do not have to hunt through multiple small dialogs.</p>
        <ul>
          <li><strong>General</strong>: window title, app icon, and core registration details.</li>
          <li><strong>GS1</strong>: template storage and profile defaults for GS1 export workflows.</li>
          <li><strong>Theme</strong>: the full visual theme builder, starter themes, live preview, and advanced QSS.</li>
        </ul>
        <p>Saving settings updates the current app state immediately, while supported settings changes are also recorded in history so major appearance and configuration changes remain recoverable. Media badge icon choices for stored audio and image BLOBs are managed from the Theme workspace but are kept separate from reusable theme presets.</p>
        """,
    ),
    HelpChapter(
        chapter_id="theme-settings",
        title="Theme Settings",
        summary="Use the full visual theme builder to style the entire app, then finish the rare edge cases with advanced QSS.",
        keywords=("theme", "appearance", "font", "colors", "qss", "saved themes", "style"),
        content_html="""
        <p>The Theme page is now a full visual theme builder rather than a small color editor. It is intended to give you real control over the application’s look and feel without forcing you into handwritten stylesheets for normal customization.</p>
        <ul>
          <li><strong>Theme Library</strong>: packaged starter themes and saved custom presets can be loaded, exported, imported, reset, and managed without leaving the dialog.</li>
          <li><strong>Starter presets</strong>: the app ships with Apple Light, Apple Dark, High Visibility, Aeon Emerald Gold, Subconscious Cosmos, VS Code Dark, and Pastel Studio as bundled starting points.</li>
          <li><strong>Typography</strong>: choose the application font and tune dialog titles, section headings, and supporting text sizes separately.</li>
          <li><strong>Surfaces</strong>: style the window, workspace-canvas, panel, group-title, compact-frame, border, tooltip, overlay, accent, and supporting-text palette for the entire app.</li>
          <li><strong>Buttons</strong>: configure normal, hover, pressed, checked, disabled, and round help-button states, plus radius and padding.</li>
          <li><strong>Inputs</strong>: control editor backgrounds, focus styling, disabled states, placeholders, and checkbox/radio indicators.</li>
          <li><strong>Data Views</strong>: theme tables, lists, row hover states, selections, scrollbars, progress bars, progress text, and progress borders.</li>
          <li><strong>Navigation</strong>: theme menu bars, popup menus, toolbars, status bars, dock titles, headers, tab strips, tab panes, and tabs with separate normal, hover, and selected states.</li>
          <li><strong>Blob Icons</strong>: choose separate global icons for stored audio and image BLOBs using platform icons, emoji, or compressed custom images stored in the profile database.</li>
          <li><strong>Live Preview</strong>: preview the current draft inside the settings dialog with a focused preview that follows the active theme section, or enable real-time app-wide preview while editing and revert automatically on cancel.</li>
          <li><strong>Advanced QSS</strong>: append custom Qt stylesheet rules only for the remaining edge cases that are not already covered by the GUI builder.</li>
          <li><strong>Selector Reference</strong>: browse a searchable catalog of selectors harvested from the currently open windows and dialogs, then copy or insert them into the QSS editor.</li>
          <li><strong>Autocomplete</strong>: press <strong>Ctrl+Space</strong> inside the advanced QSS editor for context-aware selector, pseudo-state, subcontrol, property, value, and full-template completion.</li>
        </ul>
        <p>Most users should begin with the visual controls and only use Advanced QSS for the last few selectors that truly need custom rules. The selector reference and autocomplete tools exist to make that final layer safe and efficient rather than mysterious. Media badge icons are intentionally stored outside the reusable theme library so you can refine catalog file indicators without overwriting a saved theme preset.</p>
        """,
    ),
    HelpChapter(
        chapter_id="history",
        title="Undo History and Snapshots",
        summary="How to protect your work with undo, redo, snapshots, and restore paths built for real catalog operations.",
        keywords=("history", "undo", "redo", "snapshots", "restore", "history dialog"),
        content_html="""
        <p>The app includes a persistent history system because catalog work should be recoverable. That matters especially for imports, large edits, settings changes, migrations, and file-backed actions.</p>
        <ul>
          <li><strong>Undo / Redo</strong>: revert or reapply the latest reversible action.</li>
          <li><strong>Show Undo History…</strong>: inspect session and profile history entries.</li>
          <li><strong>Create Snapshot…</strong>: save a manual restore point.</li>
          <li><strong>Restore Snapshot</strong>: roll the profile back to a previous state.</li>
        </ul>
        <p>Snapshots capture the profile database and related managed state where supported, giving heavier workflows a safer recovery path than a simple session-only undo stack.</p>
        """,
    ),
    HelpChapter(
        chapter_id="diagnostics",
        title="Diagnostics",
        summary="Use diagnostics to verify the health of the application, the active profile, and the managed files around it.",
        keywords=("diagnostics", "integrity", "schema", "repair", "managed files", "checks"),
        content_html="""
        <p>The Diagnostics window gives you a high-level health view of both the application environment and the active profile so you can verify that the workspace is still operating cleanly.</p>
        <ul>
          <li><strong>Environment</strong>: app version, schema version, profile path, data folder, log folder, snapshot count, platform, and Python version.</li>
          <li><strong>Checks</strong>: schema validation, SQLite integrity, foreign-key integrity, custom-value integrity, managed files, and snapshot storage.</li>
          <li><strong>Details</strong>: expanded explanation for the currently selected check.</li>
          <li><strong>Repair</strong>: preview or run supported repair actions when a check reports a repairable issue.</li>
        </ul>
        <p>Use Diagnostics after restores, before major exports, when troubleshooting a profile, or any time you want to verify that the catalog and its managed files are still aligned.</p>
        """,
    ),
    HelpChapter(
        chapter_id="application-log",
        title="Application Log",
        summary="Browse the human-readable log and structured trace logs for troubleshooting and auditing.",
        keywords=("application log", "logs", "trace log", "troubleshooting", "open log folder"),
        content_html="""
        <p>The Application Log window lets you inspect the local log files the app writes while it runs.</p>
        <ul>
          <li><strong>Application log</strong>: daily readable log lines for normal troubleshooting.</li>
          <li><strong>Trace log</strong>: structured JSON lines used for detailed event tracing.</li>
          <li><strong>Refresh</strong>: reload the selected log file.</li>
          <li><strong>Open File</strong> and <strong>Open Log Folder</strong>: jump directly to the underlying file or log directory in the operating system.</li>
        </ul>
        <p>Use logs together with Diagnostics when you need to understand what happened during imports, restores, settings changes, or file-management actions.</p>
        """,
    ),
    HelpChapter(
        chapter_id="media-preview",
        title="Media Preview",
        summary="Preview album-art images, audio files, and stored media directly from the catalog.",
        keywords=("media preview", "audio preview", "image preview", "waveform", "album art"),
        content_html="""
        <p>The app can preview managed media directly from the catalog.</p>
        <ul>
          <li><strong>Image preview</strong>: zoom and inspect stored image data such as album art.</li>
          <li><strong>Audio preview</strong>: play attached audio with waveform preview, playhead, and transport controls.</li>
          <li><strong>Standard media columns</strong>: double-click Audio File or Album Art to attach new files, or preview existing media from the table.</li>
        </ul>
        <p>Preview actions are intended to verify attached media quickly without leaving the catalog workflow.</p>
        """,
    ),
    HelpChapter(
        chapter_id="about",
        title="About and Support Information",
        summary="Where to find version information, local support resources, and the built-in tools that help you trust the current workspace.",
        keywords=("about", "version", "workspace", "support", "data folder", "logs folder"),
        content_html="""
        <p>The About dialog summarizes the current version, the local-first design of the app, and where the active workspace data lives on disk.</p>
        <p>Use the Help menu to reach:</p>
        <ul>
          <li><strong>About ISRC Catalog Manager…</strong> for version and workspace context.</li>
          <li><strong>Diagnostics…</strong> for profile health checks and repair paths.</li>
          <li><strong>Application Log…</strong> for readable and structured troubleshooting logs.</li>
          <li><strong>Open Logs Folder…</strong> and <strong>Open Data Folder…</strong> for direct access to local support files.</li>
        </ul>
        """,
    ),
)


HELP_CHAPTERS_BY_ID = {chapter.chapter_id: chapter for chapter in HELP_CHAPTERS}


def help_topic_title(chapter_id: str) -> str:
    chapter = HELP_CHAPTERS_BY_ID.get(chapter_id)
    return chapter.title if chapter is not None else "Help"


def render_help_html(
    app_name: str,
    version_text: str = "",
    theme: dict[str, object] | None = None,
) -> str:
    toc_items = []
    keyword_map: dict[str, list[HelpChapter]] = {}
    chapter_blocks = []

    for chapter in HELP_CHAPTERS:
        toc_items.append(
            f"<li><a href='#{escape(chapter.chapter_id)}'>{escape(chapter.title)}</a> - {escape(chapter.summary)}</li>"
        )
        for keyword in chapter.keywords:
            keyword_map.setdefault(keyword.lower(), []).append(chapter)
        chapter_blocks.append(
            f"""
            <section class='chapter' id='{escape(chapter.chapter_id)}'>
              <h2>{escape(chapter.title)}</h2>
              <p class='summary'>{escape(chapter.summary)}</p>
              {chapter.content_html}
            </section>
            """
        )

    keyword_rows = []
    for keyword in sorted(keyword_map):
        links = ", ".join(
            f"<a href='#{escape(chapter.chapter_id)}'>{escape(chapter.title)}</a>"
            for chapter in keyword_map[keyword]
        )
        keyword_rows.append(f"<tr><th>{escape(keyword)}</th><td>{links}</td></tr>")

    version_line = f"<p class='version'>Version {escape(version_text)}</p>" if version_text else ""
    palette = dict(theme or {})
    body_bg = str(palette.get("input_bg") or "#f8fafc")
    body_fg = str(palette.get("window_fg") or "#18212b")
    panel_bg = str(palette.get("panel_bg") or "#ffffff")
    panel_border = str(palette.get("border_color") or "#dbe4ee")
    heading_fg = str(palette.get("window_fg") or "#0f172a")
    summary_fg = str(palette.get("secondary_text") or "#475569")
    version_fg = str(palette.get("secondary_text") or "#52606d")
    table_header_bg = str(palette.get("header_bg") or "#edf2f7")
    table_header_fg = str(palette.get("header_fg") or heading_fg)
    link_fg = str(palette.get("link_color") or "#0f62fe")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(app_name)} Help</title>
  <style>
    body {{
      font-family: "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial, sans-serif;
      margin: 24px;
      line-height: 1.55;
      color: {body_fg};
      background: {body_bg};
    }}
    h1, h2, h3 {{ color: {heading_fg}; }}
    h1 {{ margin-bottom: 0.2em; }}
    .summary {{ color: {summary_fg}; }}
    .hero, .panel, .chapter {{
      background: {panel_bg};
      border: 1px solid {panel_border};
      border-radius: 12px;
      padding: 18px 20px;
      margin-bottom: 18px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
    }}
    .hero p, .panel p, .chapter p {{ margin: 0.55em 0; }}
    .version {{ color: {version_fg}; margin-top: 0; }}
    ul {{ margin-top: 0.4em; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      background: {panel_bg};
    }}
    th, td {{
      border: 1px solid {panel_border};
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      width: 24%;
      background: {table_header_bg};
      color: {table_header_fg};
    }}
    a {{
      color: {link_fg};
      text-decoration: none;
    }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <section class="hero">
    <h1>{escape(app_name)} Help</h1>
    {version_line}
    <p>This manual is the in-app guide to the full product. Use the table of contents to orient yourself, the keyword index to jump to a feature quickly, and the help viewer search tools to move straight to the workflow you need.</p>
  </section>

  <section class="panel" id="contents">
    <h2>Table of Contents</h2>
    <ol>
      {"".join(toc_items)}
    </ol>
  </section>

  <section class="panel" id="index">
    <h2>Keyword Index</h2>
    <table>
      <tbody>
        {"".join(keyword_rows)}
      </tbody>
    </table>
  </section>

  {"".join(chapter_blocks)}
</body>
</html>
"""
