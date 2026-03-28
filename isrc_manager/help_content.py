from __future__ import annotations

from dataclasses import dataclass
from html import escape

try:
    from PySide6.QtWidgets import QApplication
except Exception:  # pragma: no cover - optional in non-Qt documentation contexts
    QApplication = None


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
            "bulk attach audio",
            "retention",
            "startup splash",
            "quality dashboard",
            "background tasks",
            "threading",
        ),
        content_html="""
        <p><strong>ISRC Catalog Manager</strong> is a local-first desktop workspace for building and maintaining a serious music catalog. It brings together recording metadata, releases, musical works, contracts, rights, parties, documents, deliverables, GS1 product data, diagnostics, history, and quality control in one application.</p>
        <p>It is designed for independent artists, labels, managers, and catalog owners who need more than a basic track list and want a reliable system for both metadata and catalog operations.</p>
        <p>The app is organized around a few core ideas:</p>
        <ul>
          <li><strong>Profiles</strong>: each profile is a self-contained catalog database, so separate catalogs remain clean and portable.</li>
          <li><strong>Add Track</strong>: the primary single-track creation entry point. Every new track must either link to an existing Work or create a new Work from the track before save.</li>
          <li><strong>Add Album</strong>: the primary batch-entry surface. It behaves as batch Add Track, so each populated row resolves Work governance before the album save completes.</li>
          <li><strong>Work Manager</strong>: the parent governance and management surface for work metadata, ownership, contributions, and linked tracks after or alongside track-first entry.</li>
          <li><strong>Releases</strong>: first-class product records for UPC/EAN, release artwork, ordering, and release-level metadata.</li>
          <li><strong>Works</strong>: a composition layer that stays distinct from recordings so the same work can connect to multiple tracks.</li>
          <li><strong>Parties</strong>: reusable people and companies for writers, publishers, labels, managers, licensees, and organizations.</li>
          <li><strong>Contracts and rights</strong>: lifecycle-aware agreement records, obligations, document versions, and explicit rights positions linked back to the catalog.</li>
          <li><strong>Assets</strong>: managed deliverables and artwork variants with approval and primary-version tracking.</li>
          <li><strong>Catalog Table</strong>: the central browser for searching, selecting, bulk editing, and reviewing recording data.</li>
          <li><strong>Global Search</strong>: a relationship-aware search surface across works, tracks, releases, contracts, rights, parties, documents, and assets.</li>
          <li><strong>Docked catalog workspace</strong>: release, work, license, party, contract, rights, deliverables, and search panels can stay open as tabbed workspace surfaces beside the catalog table.</li>
          <li><strong>Import and exchange</strong>: CSV, XLSX, JSON, XML, ZIP, audio-tag, bulk audio attach, and GS1 workflows for bringing data in, reconciling it, attaching media, exporting it, and archiving it safely.</li>
          <li><strong>Quality Dashboard</strong>: a practical readiness view for metadata gaps, identifier conflicts, broken media links, rights risks, and operational blockers.</li>
          <li><strong>Diagnostics and recovery</strong>: snapshots, backups, cleanup, trim, diagnostics, repair paths, and logs keep heavier workflows recoverable.</li>
          <li><strong>Action Ribbon</strong>: a customizable quick-action strip for your most-used commands.</li>
          <li><strong>Background tasks</strong>: longer scans, imports, exports, snapshots, and file operations run outside the UI thread to keep the workspace responsive.</li>
          <li><strong>Settings and history</strong>: identity, registration settings, themes, undo/redo, snapshots, diagnostics, and logs.</li>
          <li><strong>Startup feedback</strong>: a Qt-native splash reports milestone-based startup progress while storage reconciliation and workspace restore complete.</li>
          <li><strong>Flexible file storage</strong>: file-backed records can be kept as database BLOBs or as managed local files without changing the surrounding UI workflow.</li>
          <li><strong>Media badge icons</strong>: separate visual indicators for stored audio and image BLOBs can be configured with system icons, emoji, or compressed custom images.</li>
        </ul>
        <p>The menu bar mirrors those workflows. <strong>File</strong> handles profiles and exchange, <strong>Edit</strong> starts governed musical entry with <strong>Add Track</strong> and <strong>Add Album</strong> and edits the current selection, <strong>Catalog</strong> opens the richer repertoire tools, <strong>Settings</strong> controls app and profile configuration, <strong>View</strong> manages layout and helper surfaces, <strong>History</strong> protects recoverability, and <strong>Help</strong> gives you diagnostics, logs, and this manual.</p>
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
        <p>The main window is designed as a practical catalog workspace rather than a single fixed screen. The <strong>Catalog Table</strong> stays central, <strong>Add Track</strong> and <strong>Add Album</strong> are the primary governed entry points for new musical items, and <strong>Work Manager</strong> stays available as the governance and follow-up surface once those entries exist.</p>
        <ul>
          <li><strong>Action ribbon</strong>: a customizable strip of high-frequency actions. Use <strong>View &gt; Customize Action Ribbon…</strong> to make it match your workflow.</li>
          <li><strong>Profiles toolbar</strong>: switch databases, create a new profile, browse to an external profile, reload the profile list, or remove the selected entry.</li>
          <li><strong>Profiles ribbon toggle</strong>: use <strong>View &gt; Show Profiles Ribbon</strong> when you want that toolbar visible or hidden, and the choice is remembered with the rest of the workspace.</li>
          <li><strong>Dockable panes</strong>: keep the window focused on your current task by showing only the panes you need.</li>
          <li><strong>Tabbed catalog tools</strong>: Release Browser, Work Manager, Party Manager, Contract Manager, Rights Matrix, Deliverables and Asset Versions, and Global Search open as docked tabs beside the table so you can keep using the catalog inventory while those panels remain open.</li>
          <li><strong>Diagnostics cleanup tools</strong>: stored artist and album cleanup now lives with Diagnostics instead of the Catalog workspace, so integrity and cleanup follow-up stay together.</li>
          <li><strong>Saved layout</strong>: column layout, dock placement, and visibility preferences are remembered so the app opens the way you work.</li>
        </ul>
        <p>Use the menus when you need the full surface of the product, or stay inside the docked views for everyday entry and review. The window title, branding, and appearance can be customized from <strong>Settings &gt; Application Settings</strong>. When you open multiple catalog tools, the app prefers tabbed docking so the workspace stays compact and easier to navigate while the table remains usable.</p>
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
        <p>Profile-specific catalog data stays with the profile. Shared app-level conveniences such as saved themes and remembered layout settings stay available across profiles. On first launch, the app can also offer to open <strong>Application Settings</strong> so you can configure registration values, snapshot posture, and appearance before deeper catalog work begins.</p>
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
          <li><strong>Central task runner</strong>: imports, exports, ZIP packaging, snapshots, restores, quality scans, catalog-audio copy export, backup, and integrity checks are dispatched through one shared Qt background-task manager.</li>
          <li><strong>Main-thread UI updates only</strong>: worker threads report back through Qt signals, and dialogs, tables, messages, and status text are updated on the main thread only.</li>
          <li><strong>Per-thread SQLite connections</strong>: background jobs never reuse the main window's SQLite connection. Each worker opens and closes its own connection safely.</li>
          <li><strong>SQLite concurrency</strong>: the app enables WAL mode, foreign-key enforcement, and a busy timeout. Write-heavy jobs are serialized per profile so concurrent background writers do not fight each other.</li>
          <li><strong>Progress and cancellation</strong>: longer jobs show a progress dialog or in-place status text where practical. Some file-based jobs, such as catalog-audio copy export, can be cancelled safely.</li>
          <li><strong>Safe shutdown</strong>: the app blocks closing while background jobs are still running so restores, imports, and other file/database writes cannot be interrupted mid-operation.</li>
        </ul>
        <p>If a background task fails, the app reports it clearly, logs the details, and rolls database work back cleanly. The result is a system that feels responsive without becoming fragile.</p>
        """,
    ),
    HelpChapter(
        chapter_id="add-data",
        title="Add Track",
        summary="How the primary single-track entry flow works, how Work governance is required before save, and how shared metadata seeds a new Work automatically.",
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
        <p><strong>Add Track</strong> is the primary single-item musical creation workflow in the main window. Before a new track can be saved, it must either link to an existing <strong>Work</strong> or create a new <strong>Work</strong> from the track. That keeps the recording entry flow fast while preventing new orphan tracks.</p>
        <ul>
          <li><strong>Track</strong>: track title, main artist, additional artists, and genre.</li>
          <li><strong>Release</strong>: album title, release date, and track length.</li>
          <li><strong>Codes</strong>: preview-only generated values such as the future row ID, generated ISRC, and entry date, plus ISWC, UPC/EAN, catalog number, and BUMA work number.</li>
          <li><strong>Media</strong>: attach a local audio file and album art image, then choose whether each file should be stored in the database or in managed local storage.</li>
        </ul>
        <p>Use <strong>Save Track</strong> to save the governed track currently in progress, or <strong>Clear Draft</strong> to reset the current Add Track draft. In <strong>Create New Work From Track</strong> mode, the app seeds the new parent Work directly from the track title, ISWC, and registration number you already entered, then links the track immediately as the first governed original. In <strong>Link to Existing Work</strong> mode, you choose the parent Work plus the child relationship type and optional parent track before save.</p>
        <p>Main artist names resolve through the <strong>Party</strong> layer on save, so when a Party-backed artist is selected the stored artist display comes from that authoritative Party record instead of loose text. Later track edits do not silently overwrite Work metadata, but the initial creation flow avoids making you enter the same shared concepts twice.</p>
        """,
    ),
    HelpChapter(
        chapter_id="album-entry",
        title="Add Album",
        summary="How the governed batch-entry surface works as batch Add Track, with per-row Work decisions and automatic Work seeding for new rows.",
        keywords=(
            "add album",
            "album dialog",
            "multi track",
            "album entry",
            "track sections",
            "shared metadata",
        ),
        content_html="""
        <p><strong>Add Album</strong> is batch Add Track. Instead of retyping the same album data over and over, you enter the shared product details once and then complete each track on its own tab. Every populated row must resolve Work governance before save: either link that row to an existing Work, or create a new Work from that row so the track saves as its first governed original.</p>
        <ul>
          <li><strong>Work Governance</strong>: each populated track row chooses its own governed outcome. You can link a row to an existing Work or create a new Work from that row without leaving the album workflow.</li>
          <li><strong>Album Overview</strong>: album title, UPC/EAN, genre, catalog number, album art, album-art storage choice, and the release-year rule used when auto-generating blank ISRC values.</li>
          <li><strong>Track Tabs</strong>: each tab stores one track title, main artist, additional artists, release date, track length, optional ISRC, optional ISWC, optional BUMA work number, an audio file, and its storage choice.</li>
          <li><strong>Dynamic layout</strong>: the dialog opens with two track tabs by default, but you can add more or remove the current tab at any time.</li>
          <li><strong>Blank-tab handling</strong>: completely unused track tabs are ignored when you save, so you do not need to delete every spare tab before closing the dialog.</li>
          <li><strong>Shared album art</strong>: the selected album art is stored once and linked across the saved album tracks automatically.</li>
        </ul>
        <p>If ISRC generation is configured, blank track ISRC fields can be generated automatically during save. If not, the dialog still creates the release and track rows successfully so you can complete identifiers later. Shared album metadata is entered once, while each row still governs itself explicitly so the batch never creates floating orphan tracks and does not force you to repeat Work metadata when a new Work is created from a row.</p>
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
        title="Edit Track",
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
        <p>The Edit Track dialog is the full maintenance editor for existing records. When one row is selected, it behaves as a detailed track editor. When multiple rows are selected, it switches into <strong>bulk edit</strong> mode and protects fields that should not be overwritten casually.</p>
        <ul>
          <li><strong>Copy buttons</strong>: copy ISO or compact forms of ISRC and ISWC values.</li>
          <li><strong>Media replacement</strong>: browse for new audio or album art files, choose database or managed-file storage for replacements, or clear the currently stored media.</li>
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
        summary="Import embedded tags from supported audio files and understand how catalog-backed audio exports embed metadata automatically.",
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
        <p>The app can read embedded audio metadata into the catalog, and catalog-backed audio exports automatically attempt to embed trustworthy catalog metadata into the exported copy.</p>
        <ul>
          <li><strong>Supported read/write families</strong>: MP3/ID3, FLAC/Vorbis comments, OGG Vorbis/Opus comments, M4A/MP4 atoms, and WAV/AIFF where ID3-style metadata is available.</li>
          <li><strong>Mapped fields</strong>: title, artist, album, album artist, track number, disc number, genre, composer, publisher/label, release date, ISRC, UPC/EAN, comments, lyrics, and artwork.</li>
          <li><strong>Import Metadata from Audio Files…</strong>: open it from the Catalog menu or the table context menu to preview extracted tags and conflicts before catalog values are changed.</li>
          <li><strong>Conflict policy</strong>: choose whether file tags should fill blanks only, override database values, or defer to the existing catalog data.</li>
          <li><strong>Export Catalog Audio Copies…</strong>: exports original-format catalog audio copies to a folder and embeds catalog metadata automatically without touching the stored source audio.</li>
          <li><strong>Other catalog-backed audio exports</strong>: <strong>Export Audio Derivatives…</strong>, <strong>Export Authentic Masters…</strong>, <strong>Export Provenance Copies…</strong>, and <strong>Export Forensic Watermarked Audio…</strong> also embed catalog metadata automatically when trustworthy catalog values are available.</li>
          <li><strong>Plain external conversion</strong>: <strong>Convert External Audio Files…</strong> strips inherited source metadata and does not invent catalog metadata, watermarking, or derivative registration.</li>
        </ul>
        <p>The app preserves the original stored audio when exporting copies. If catalog metadata is unavailable, ambiguous, or cannot be written safely into the target container, the export still succeeds and the metadata step is skipped with warnings instead of crashing the workflow. When the track rows already exist and the job is to attach local files in bulk, use <strong>Catalog &gt; Bulk Attach Audio Files…</strong> instead.</p>
        """,
    ),
    HelpChapter(
        chapter_id="bulk-audio-attach",
        title="Bulk Audio Attach",
        summary="Attach many local audio files to existing tracks by reviewing filename and tag matches before one batch apply.",
        keywords=(
            "bulk attach audio",
            "attach audio files",
            "filename matching",
            "apply artist",
            "storage mode",
            "matched tracks",
        ),
        content_html="""
        <p><strong>Catalog &gt; Bulk Attach Audio Files…</strong> is the fastest way to connect a large batch of local audio files to tracks that already exist in the catalog.</p>
        <ul>
          <li><strong>Match suggestions</strong>: the workflow inspects filenames and embedded tags to suggest likely track matches.</li>
          <li><strong>Review before write</strong>: the dialog shows the detected title, detected artist, current matched artist, and source file so you can confirm the batch before anything is saved.</li>
          <li><strong>Skip or reassign</strong>: any file can be skipped or manually reassigned to another track from the same review surface.</li>
          <li><strong>Storage mode choice</strong>: attached audio can be stored in the database or as managed local files.</li>
          <li><strong>Optional shared artist update</strong>: when the batch is consistent, one artist value can be applied across the matched tracks during the same operation.</li>
          <li><strong>Recoverable batch</strong>: the final apply step is recorded as one history-backed mutation rather than as a chain of separate row edits.</li>
        </ul>
        <p>This workflow is separate from exchange import and from audio-tag import. Use it when the catalog rows already exist and you mainly need to connect the right audio files quickly and safely.</p>
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
          <li><strong>Album batch integration</strong>: saving a governed grouped album entry automatically creates or updates a real release and attaches the created tracks.</li>
          <li><strong>Release Browser…</strong>: browse releases, inspect the ordered track list, duplicate releases, add the current track selection, and filter the main catalog table to a chosen release.</li>
          <li><strong>Docked workflow</strong>: the Release Browser stays open as a tabbed workspace panel, so you can keep changing the track-table selection while assigning or reviewing releases.</li>
          <li><strong>Single-track workflows</strong>: saving the Add Track panel or the Edit Track dialog also keeps the corresponding release record synchronized when release-level fields change.</li>
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
          <li><strong>Obligations and reminders</strong>: delivery, approval, exclusivity, notice, follow-up, and reminder obligations are edited as structured rows with due dates, completion state, and notes.</li>
          <li><strong>Document intelligence</strong>: a contract can keep multiple managed documents such as drafts, signed agreements, amendments, appendices, exhibits, correspondence, and scans, with version labels and active/superseded relationships.</li>
          <li><strong>Rights matrix</strong>: rights records store the right type, exclusivity, territory, media/use scope, dates, source contract, and who granted, received, or retained the right.</li>
          <li><strong>Assets and deliverables</strong>: tracks and releases can keep primary masters, alternates, derivatives, artwork variants, and approval state in one registry.</li>
          <li><strong>Derivative Ledger</strong>: managed export batches can be filtered by batch ID, track, output file, format, derivative kind, and status, then reviewed through layered Derivatives, Details, Lineage, and Admin tabs.</li>
          <li><strong>Global Search and Relationships…</strong>: search across the full model and inspect everything linked to the selected record from one panel.</li>
          <li><strong>Docked managers</strong>: Work Manager, Party Manager, Contract Manager, Rights Matrix, Deliverables and Asset Versions, and Global Search now stay available as tabbed workspace panels instead of blocking dialogs.</li>
        </ul>
        <p>This richer model is intentionally catalog-focused. It gives independent teams a practical way to understand what they own, what is linked, and what is ready, without turning the app into a royalty or distribution platform.</p>
        """,
    ),
    HelpChapter(
        chapter_id="storage-modes",
        title="File Storage Modes",
        summary="How database-backed and managed-file-backed attachments work across the catalog, and how conversions stay backward-safe.",
        keywords=(
            "storage mode",
            "database mode",
            "managed file",
            "blob",
            "attachment",
            "convert storage",
            "license pdf",
            "contract document",
            "asset file",
            "gs1 template",
        ),
        content_html="""
        <p>The app now supports two storage modes for file-backed records across the catalog.</p>
        <ul>
          <li><strong>Database mode</strong>: the raw file bytes are stored directly inside the profile database.</li>
          <li><strong>Managed file mode</strong>: the app copies the file into an app-controlled local storage folder and stores the managed path in the database.</li>
          <li><strong>Covered record types</strong>: standard track audio, track and album artwork, release artwork, custom <code>blob_audio</code> and <code>blob_image</code> values, license PDFs, contract documents, asset versions, and GS1 workbook templates.</li>
          <li><strong>Safe imports</strong>: managed-file mode never depends on the original file staying in place after import. The app stores its own managed copy first.</li>
          <li><strong>Conversions</strong>: supported editors, browser panels, and context menus can move existing records between the two modes while keeping open, preview, export, replace, and delete behavior consistent.</li>
          <li><strong>Legacy compatibility</strong>: older records remain readable because the app can infer storage mode from existing BLOB or managed-path data when a legacy row has no explicit mode yet.</li>
          <li><strong>Portable packages</strong>: ZIP package export/import materializes both database-backed and managed-file-backed records into portable files and preserves the recorded storage mode on import.</li>
        </ul>
        <p>The storage layer preserves the file bytes plus catalog metadata such as filename, MIME type, size, and checksums where supported. Format-aware tag writing happens during catalog-backed audio export, not during storage conversion itself, so changing storage mode never silently rewrites the managed source file.</p>
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
            "mapping preset",
            "package import",
        ),
        content_html="""
        <p>The exchange layer is designed for real catalog portability. Whether you are sharing data, taking a structured backup, preparing downstream workflows, or moving a project between systems, the app gives you more than a single export button.</p>
        <ul>
          <li><strong>Export formats</strong>: CSV, XLSX, JSON, XML, and ZIP packages containing a JSON manifest plus materialized attachment copies.</li>
          <li><strong>Import formats</strong>: CSV, XLSX, JSON, ZIP packages, and XML.</li>
          <li><strong>Import setup</strong>: CSV, XLSX, JSON, ZIP package, and XML imports all open the same exchange setup surface so you can review preview rows, match rules, and field targets before running the job.</li>
          <li><strong>Saved mapping presets</strong>: frequently used column mappings can be saved per format and reused later.</li>
          <li><strong>Saved choices</strong>: per-format import choices can be remembered and later cleared from <strong>File &gt; Import &amp; Exchange &gt; Catalog Exchange &gt; Reset Saved Import Choices…</strong>.</li>
          <li><strong>Skip targets</strong>: any incoming field can be marked as <strong>Skip this field</strong> when you want it inspected but not applied.</li>
          <li><strong>Import modes</strong>: dry-run validation, create new rows, merge into existing matches, update existing matches only, or insert-new-when-duplicate-exists.</li>
          <li><strong>Matching options</strong>: internal ID, ISRC, UPC/EAN plus title, and optional title/artist heuristics.</li>
          <li><strong>JSON schema versioning</strong>: exported JSON includes an explicit schema version so future migrations stay manageable.</li>
          <li><strong>Repertoire Exchange</strong>: a separate import/export workflow now covers parties, works, contracts, rights, asset versions, and their relationship references as JSON, XLSX, CSV bundles, or ZIP packages with managed files.</li>
        </ul>
        <p>Binary media is referenced in plain tabular exports, while ZIP packages materialize both database-backed and managed-file-backed records into portable files and preserve the recorded storage mode on import. Import preview, mapping, packaging, export, and extraction all run in the background so larger exchange jobs stay practical. For the matching, merge, delimiter, and XML specifics, see <strong>Import and Merge Workflows</strong> in this manual.</p>
        """,
    ),
    HelpChapter(
        chapter_id="import-workflows",
        title="Import and Merge Workflows",
        summary="How exchange import, XML import, and audio-tag workflows differ, and how matching, merge, mapping, and dry runs actually work.",
        keywords=(
            "import workflows",
            "merge",
            "mapping preset",
            "delimiter",
            "package import",
            "dry run",
            "xml import",
            "buma",
            "stemra",
            "sena",
            "custom::",
        ),
        content_html="""
        <p>The app has two catalog ingest surfaces plus audio-tag import: exchange import for structured rows, packages, and supported XML shapes; and audio-tag import for embedded file metadata. They overlap in the fields they can touch, but they are not the same workflow.</p>
        <ul>
          <li><strong>Exchange import</strong>: supports <code>XML</code>, <code>CSV</code>, <code>XLSX</code>, <code>JSON</code>, and <code>ZIP package</code>. CSV import can auto-detect comma, semicolon, tab, or pipe delimiters, while the shared exchange setup surface can map or skip supported fields across all supported catalog import formats.</li>
          <li><strong>Mapping presets</strong>: reusable CSV/XLSX mappings can be saved and loaded again for recurring imports.</li>
          <li><strong>Saved import choices</strong>: each exchange format can remember its preferred mode, match rules, custom-field creation behavior, and CSV delimiter choice until you reset those saved choices.</li>
          <li><strong>Exchange modes</strong>: <code>dry_run</code> checks setup without writing, <code>create</code> creates new tracks, <code>update</code> updates matched tracks only, <code>merge</code> updates matched tracks while preserving many existing populated values, and <code>insert_new</code> creates only unmatched rows and skips duplicates.</li>
          <li><strong>Exchange matching</strong>: matching can use internal ID, ISRC, UPC plus title, and optional title/artist heuristics. The importer is deterministic and does not provide a row-by-row manual assignment queue.</li>
          <li><strong>Release upsert and package restore</strong>: exchange import can update or create linked releases from supplied release fields, while ZIP package import restores packaged files and their recorded storage mode.</li>
          <li><strong>XML import</strong>: supported catalog XML shapes now flow through the same exchange setup surface as the tabular formats. The XML parser still performs schema-aware inspection first, surfaces duplicate ISRCs and custom-field conflicts, and can create missing custom fields when allowed before the mapped import runs.</li>
          <li><strong>Bulk audio attach</strong>: <strong>Catalog &gt; Bulk Attach Audio Files…</strong> is the better fit when track rows already exist and you need to match local files onto them in one reviewed batch.</li>
          <li><strong>Audio tags</strong>: read embedded tags from supported audio files and preview conflicts before writing to the catalog. Catalog-backed audio export workflows embed metadata automatically, while the plain external conversion workflow stays metadata-free.</li>
        </ul>
        <p>This workflow is useful for structured exports from labels, catalog administrators, collection societies, and PRO-style sources such as BUMA, STEMRA, SENA, and similar organizations, provided the data can be exported into a supported format. That support is format-based and mapping-based, not a direct third-party integration.</p>
        <p>Keep the current limits in mind: blob custom fields are not tabular import targets, JSON and ZIP package imports do not use CSV delimiter controls because their source structure is already defined, standard exchange <code>dry_run</code> is a conservative preflight rather than a full validation engine, and matched release rows can be updated from imported release data.</p>
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
        <p>Quality scans run on demand in the background and are meant to help you move from problem detection to action quickly. Use Diagnostics when the question is about storage health, schema integrity, history artifacts, or managed files rather than catalog content itself.</p>
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
          <li><strong>Official workbook</strong>: choose the official GS1 workbook from your GS1 environment. The app validates headers and sheet structure before export, then keeps the template either in the database or as a managed local file.</li>
          <li><strong>Python dependency</strong>: GS1 workbook validation and export require the <code>openpyxl</code> package in the same Python environment that starts the app.</li>
        </ul>
        <p>Use <strong>Save</strong> to keep GS1 data in the catalog, <strong>Export Current…</strong> to write the active product, or <strong>Export Batch…</strong> to generate a full workbook from the selected set. If storage needs change later, the saved template can be converted between database and managed-file storage without reselecting the original source workbook.</p>
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
        chapter_id="catalog-managers",
        title="Catalog Cleanup",
        summary="Review stored artist and album names from Diagnostics and remove only data that is no longer in use.",
        keywords=("catalog managers", "artists", "albums", "purge unused", "manage"),
        content_html="""
        <p>The stored artist and album cleanup tools now live in <strong>Help &gt; Diagnostics…</strong> under the <strong>Catalog Cleanup</strong> area, because they are maintenance and integrity-adjacent tools rather than primary catalog workspaces.</p>
        <ul>
          <li><strong>Artists</strong>: inspect artist usage counts and remove or purge only artists that are no longer used.</li>
          <li><strong>Albums</strong>: inspect album usage counts and remove or purge unused albums.</li>
        </ul>
        <p>These tools are intended for cleanup and normalization. The app prevents deletion of items that are still referenced by tracks where that would break data integrity, and keeps the actual cleanup actions alongside the rest of the diagnostics and repair surfaces.</p>
        """,
    ),
    HelpChapter(
        chapter_id="audio-authenticity",
        title="Audio Authenticity",
        summary="Export direct master authenticity copies, export provenance-only derivatives, manage signing keys, and verify authenticity honestly inside the catalog.",
        keywords=(
            "audio authenticity",
            "watermark",
            "authenticity",
            "signed manifest",
            "ed25519",
            "verify audio authenticity",
            "watermarked audio",
            "authenticity keys",
            "wav",
            "flac",
            "aiff",
            "provenance",
        ),
        content_html="""
        <p>The audio authenticity workflow combines two layers: a compact keyed watermark embedded into exported audio plus an Ed25519-signed manifest that carries the real authenticity claim. The watermark links the file back to the catalog record; the signature proves which manifest was issued.</p>
        <ul>
          <li><strong>Settings &gt; Audio Authenticity Keys…</strong>: generate or review local signing keys. Public keys are stored in the profile, while private keys stay as local key files under the app settings root.</li>
          <li><strong>Catalog &gt; Export Authenticity Watermarked Audio…</strong>: write WAV, FLAC, or AIFF master copies that keep the original canonical source unchanged, embed a compact keyed watermark token, write the catalog metadata tags that are already available for the track, and save a sibling <code>.authenticity.json</code> sidecar with the signed direct-authenticity manifest.</li>
          <li><strong>Catalog &gt; Export Authenticity Provenance Audio…</strong>: copy supported lossy derivatives as-is, write the available catalog tags, and save a signed provenance sidecar that binds the exported derivative back to a previously verified watermarked master.</li>
          <li><strong>Catalog &gt; Audio &gt; Authenticity &amp; Provenance &gt; Verify Audio Authenticity…</strong>: inspect either selected catalog audio or a chosen external file, then either verify the direct watermark path for WAV/FLAC/AIFF or verify a signed provenance lineage sidecar for supported derivatives.</li>
          <li><strong>Deliverables and Asset Versions &gt; Derivative Ledger</strong>: review managed export batches after the export moment, filter by format/kind/status, inspect derivatives, details, and lineage, and launch authenticity verification directly from the selected derivative.</li>
        </ul>
        <p>This feature is <strong>not DRM</strong> and does not promise forensic certainty. A watermark always changes the waveform slightly, so the goal is perceptual transparency rather than mathematical identity. The strongest in-app verification happens when the open profile still contains the original reference audio, because the app can compare the inspected export against that stored source directly.</p>
        <p>Direct embedded authenticity verification is intentionally limited to WAV, FLAC, and AIFF. Lossy formats such as MP3, OGG/OGA, Opus, and M4A/MP4/AAC are not treated as direct authenticity masters in this workflow; use provenance lineage sidecars or the separate forensic export workflow when you need lossy delivery copies.</p>
        <p>Recipient-specific forensic watermarking for leak tracing is now a separate managed export workflow. It remains distinct from authenticity: authenticity proves signed linkage to a canonical master record, while forensic delivery exports focus on tracing shared copies and use conservative inspection semantics.</p>
        """,
    ),
    HelpChapter(
        chapter_id="settings",
        title="Application Settings",
        summary="The central settings workspace for branding, registration values, snapshots, retention posture, GS1 defaults, and appearance.",
        keywords=(
            "settings",
            "application settings",
            "window title",
            "icon",
            "isrc prefix",
            "snapshot interval",
            "retention",
            "storage budget",
        ),
        content_html="""
        <p>The Application Settings dialog brings the app's most important configuration into one organized workspace so you do not have to hunt through multiple small dialogs.</p>
        <ul>
          <li><strong>General</strong>: current profile context, an optional custom window title override, app icon, core registration details, automatic snapshots, retention and safety level, automatic cleanup, and history storage budget controls.</li>
          <li><strong>GS1</strong>: template storage mode plus profile defaults for GS1 export workflows.</li>
          <li><strong>Theme</strong>: the full visual theme builder, starter themes, hint-text and preview-pane controls, live preview, and advanced QSS.</li>
        </ul>
        <p>If you leave the window-title field blank, the app uses the current owner Party company name automatically when one is available and otherwise falls back to the application name. Entering a custom value acts as an explicit override and is preserved until you clear it again. Saving settings updates the current app state immediately, while supported settings changes are also recorded in history so major appearance and configuration changes remain recoverable. On first launch, the app can offer to open this dialog so you can configure registration and recovery posture early. Media badge icon choices for stored audio and image BLOBs are managed from the Theme workspace but are kept separate from reusable theme presets, and the Theme page also includes builder-only controls for hint visibility and preview-surface visibility while you edit.</p>
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
          <li><strong>Hint Text</strong>: show or hide the softer instructional hint labels while keeping the builder layout itself intact.</li>
          <li><strong>Preview Pane</strong>: keep the side-by-side preview visible while editing or hide it temporarily when you want more room for the builder tabs.</li>
          <li><strong>Live Preview</strong>: preview the current draft inside the settings dialog with a focused preview that follows the active theme section, or enable real-time app-wide preview while editing and revert automatically on cancel.</li>
          <li><strong>Advanced QSS</strong>: append custom Qt stylesheet rules only for the remaining edge cases that are not already covered by the GUI builder.</li>
          <li><strong>Selector Reference</strong>: browse a searchable catalog of selectors harvested from the currently open windows and dialogs, then copy or insert them into the QSS editor.</li>
          <li><strong>Autocomplete</strong>: press <strong>Ctrl+Space</strong> inside the advanced QSS editor for context-aware selector, pseudo-state, subcontrol, property, value, and full-template completion.</li>
        </ul>
        <p>Most users should begin with the visual controls and only use Advanced QSS for the last few selectors that truly need custom rules. The selector reference and autocomplete tools exist to make that final layer safe and efficient rather than mysterious. Media badge icons are intentionally stored outside the reusable theme library so you can refine catalog file indicators without overwriting a saved theme preset, and the hint/preview controls stay builder-only so they do not change the saved preset payload.</p>
        """,
    ),
    HelpChapter(
        chapter_id="history",
        title="Undo History and Snapshots",
        summary="How to protect your work with undo, redo, snapshots, and restore paths built for real catalog operations.",
        keywords=(
            "history",
            "undo",
            "redo",
            "snapshots",
            "restore",
            "history dialog",
            "cleanup",
            "backups",
            "trim history",
        ),
        content_html="""
        <p>The app includes a persistent history system because catalog work should be recoverable. That matters especially for imports, large edits, settings changes, migrations, and file-backed actions.</p>
        <ul>
          <li><strong>Undo / Redo</strong>: revert or reapply the latest reversible action.</li>
          <li><strong>Show Undo History…</strong>: inspect session and profile history entries.</li>
          <li><strong>Create Snapshot…</strong>: save a manual restore point.</li>
          <li><strong>Restore Snapshot</strong>: roll the profile back to a previous state.</li>
          <li><strong>Backups</strong>: review registered backup files that were created manually or as restore safety copies.</li>
          <li><strong>Cleanup…</strong>: preview safe-to-delete snapshots, backup artifacts, archived snapshot bundles, file-state bundles, and stale session snapshots.</li>
          <li><strong>Trim History</strong>: keep the most recent reversible actions on the active branch while removing older history rows and newly unreferenced storage artifacts.</li>
          <li><strong>Retention and safety controls</strong>: the General settings page can store Maximum Safety, Balanced, Lean, or Custom cleanup posture for the active profile.</li>
          <li><strong>Budget-aware prompts</strong>: snapshot, restore, and related flows can warn when the profile is over its configured history storage budget and open cleanup directly.</li>
        </ul>
        <p>Snapshots capture the profile database and related managed state where supported, giving heavier workflows a safer recovery path than a simple session-only undo stack. Cleanup previews exactly which artifacts are eligible, protects anything still required by undo, redo, snapshot restore, backup restore, or session restore, and leaves protected items untouched. Manual snapshots and protected restore points stay protected by default, while automatic cleanup focuses on safe auto-generated artifacts only. If Diagnostics reports missing or inconsistent history artifacts, repair those issues first before trimming storage.</p>
        """,
    ),
    HelpChapter(
        chapter_id="diagnostics",
        title="Diagnostics",
        summary="Use diagnostics to verify the health of the application, the active profile, and the managed files around it.",
        keywords=(
            "diagnostics",
            "integrity",
            "schema",
            "repair",
            "managed files",
            "checks",
            "storage budget",
            "migration",
            "legacy promoted field",
        ),
        content_html="""
        <p>The Diagnostics window gives you a high-level health view of both the application environment and the active profile so you can verify that the workspace is still operating cleanly. Use it when the issue may involve storage, schema, managed files, history artifacts, migration state, or catalog cleanup follow-up rather than day-to-day track entry.</p>
        <ul>
          <li><strong>Environment</strong>: app version, schema version, profile path, data folder, log folder, snapshot count, platform, and Python version.</li>
          <li><strong>Checks</strong>: storage layout, schema validation, SQLite integrity, foreign-key integrity, custom-value integrity, managed files for path-backed records, history storage, and history storage budget pressure.</li>
          <li><strong>Details</strong>: expanded explanation for the currently selected check.</li>
          <li><strong>Catalog Cleanup</strong>: stored artist and album maintenance tools for reviewing usage counts and removing only values that are no longer in use.</li>
          <li><strong>Repair</strong>: preview or run supported repair actions when a check reports a repairable issue, including storage-layout migration, history artifact reconciliation, and the conservative legacy promoted-field merge repair.</li>
          <li><strong>Responsive loading</strong>: heavier diagnostics reports and supported repairs run through the background task system so the window stays responsive during refresh.</li>
        </ul>
        <p>Use Diagnostics after restores, before major exports, when troubleshooting a profile, or any time you want to verify that the catalog and its managed files are still aligned. If a legacy app-data layout is detected, Diagnostics can guide a staged migration into the preferred app-named folder structure without deleting the legacy copy. Migration will not start while background tasks are still running, closes the active managed profile before copying, stages the new layout first, rewrites known internal paths, verifies the migrated databases, and only then switches the app over to the preferred root. If the preferred root is already valid, the app can adopt it directly, and if a preserved staged migration is still valid, the app can resume from that stage instead of starting over.</p>
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
        <p>The app can preview file-backed media directly from the catalog regardless of whether the underlying record is stored in the database or as a managed file.</p>
        <ul>
          <li><strong>Image preview</strong>: inspect stored image data such as album art, zoom with trackpad pinch or <code>Ctrl</code>/<code>Cmd</code> + scroll, double-click to reset the view to fit, and export the current image from the preview controls.</li>
          <li><strong>Audio preview</strong>: play attached audio with waveform preview, playhead, transport controls, and in-preview export actions.</li>
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
    app = QApplication.instance() if QApplication is not None else None
    fallback_body_font = (
        app.font().family().replace('"', '\\"').strip() if app is not None else "Arial"
    )
    body_font = (
        str(palette.get("font_family") or "").replace('"', '\\"').strip() or fallback_body_font
    )
    font_family_css = f'"{body_font}", sans-serif'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(app_name)} Help</title>
  <style>
    body {{
      font-family: {font_family_css};
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
