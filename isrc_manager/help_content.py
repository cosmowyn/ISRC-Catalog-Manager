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
        summary="What the app does, how the workspace is organized, and the main workflows you will use every day.",
        keywords=("overview", "introduction", "menus", "workflow", "catalog", "tracks", "album entry", "licenses", "gs1", "bulk edit", "action ribbon", "quick actions", "releases", "audio tags", "csv", "json", "xlsx", "quality dashboard"),
        content_html="""
        <p><strong>ISRC Catalog Manager</strong> is a local-first desktop application for managing track metadata, first-class releases, optional or generated ISRC values, licensing files, GS1 workbook metadata, custom metadata columns, backups, snapshots, audio tag workflows, exchange formats, and quality checks from one workspace.</p>
        <p>The app is organized around a few core ideas:</p>
        <ul>
          <li><strong>Profiles</strong>: each profile is a separate catalog database.</li>
          <li><strong>Add Data</strong>: the dockable form used to create new tracks.</li>
          <li><strong>Add Album</strong>: a structured dialog for entering shared album metadata once and then saving multiple track rows in one pass.</li>
          <li><strong>Releases</strong>: a first-class release/product layer that keeps UPC/EAN, catalog numbers, release artwork, release order, and product-level metadata together.</li>
          <li><strong>Catalog Table</strong>: the searchable table used to browse, preview, single-edit, and bulk-edit existing tracks.</li>
          <li><strong>Exchange</strong>: CSV, XLSX, JSON, XML, and packaged exports for sharing or archiving the catalog safely.</li>
          <li><strong>Quality Dashboard</strong>: an actionable scan view for missing metadata, duplicate codes, broken media links, and other export-readiness issues.</li>
          <li><strong>Action Ribbon</strong>: a customizable top-row quick-action bar built from your preferred menu actions.</li>
          <li><strong>Settings</strong>: application identity, registration settings, snapshots, and themes.</li>
          <li><strong>History</strong>: undo, redo, manual snapshots, and restore points.</li>
        </ul>
        <p>The menu bar mirrors those workflows. <strong>File</strong> handles profiles and import/export tasks, <strong>Edit</strong> handles direct track actions, <strong>Catalog</strong> now includes releases, tag import, GS1 metadata, quality checks, and reusable catalog data such as artists, albums, and licensees, <strong>Settings</strong> handles app and profile configuration, <strong>View</strong> controls layout and columns, <strong>History</strong> manages undo/snapshots, and <strong>Help</strong> provides diagnostics, logs, and this manual.</p>
        """,
    ),
    HelpChapter(
        chapter_id="main-window",
        title="Main Window",
        summary="The main application window, dock layout, top toolbar, and general navigation.",
        keywords=("main window", "toolbar", "profiles", "dock", "layout", "window", "action ribbon", "quick actions"),
        content_html="""
        <p>The main window is built from dockable panes. By default, the left side contains the <strong>Add Data</strong> form and the right side contains the <strong>Catalog Table</strong>.</p>
        <ul>
          <li><strong>Action ribbon</strong>: a customizable quick-action toolbar at the top of the window. Use <strong>View &gt; Customize Action Ribbon…</strong> to choose which actions appear and in what order.</li>
          <li><strong>Profiles toolbar</strong>: switch between databases, create a new profile, browse to an external database, reload the profile list, or remove the selected profile.</li>
          <li><strong>Dockable panes</strong>: the Add Data view and Catalog Table view can be shown, hidden, floated, and re-docked from the <strong>View</strong> menu.</li>
          <li><strong>Saved layout</strong>: column layout, dock layout, and visibility preferences are remembered and participate in history where supported.</li>
        </ul>
        <p>Use the menus for detailed actions, or work directly inside the docked views. The window title and icon can be customized from <strong>Settings &gt; Application Settings</strong>.</p>
        """,
    ),
    HelpChapter(
        chapter_id="profiles",
        title="Profiles and Databases",
        summary="How profile databases work, how to create, remove, browse, restore, and switch between them.",
        keywords=("profiles", "database", "workspace", "browse", "create profile", "remove profile", "switch"),
        content_html="""
        <p>A profile is a single SQLite catalog database. Each profile keeps its own tracks, settings stored in the profile database, history, and catalog metadata.</p>
        <ul>
          <li><strong>New…</strong>: create a new local profile database.</li>
          <li><strong>Browse…</strong>: open an existing database file outside the default profile folder.</li>
          <li><strong>Reload List</strong>: refresh the known profile list from disk.</li>
          <li><strong>Remove…</strong>: remove the selected profile from the list and optionally from disk.</li>
        </ul>
        <p>Some settings, such as the visual theme library and remembered window layout, are stored in application settings so they remain available across profiles.</p>
        """,
    ),
    HelpChapter(
        chapter_id="add-data",
        title="Add Data Panel",
        summary="How to create a track, fill in standard metadata, generate ISRC values, and attach managed media.",
        keywords=("add data", "add track", "save track", "audio file", "album art", "release date", "isrc", "prefix", "dsp"),
        content_html="""
        <p>The Add Data panel is the primary entry form for new tracks. It is grouped into sections:</p>
        <ul>
          <li><strong>Generated</strong>: preview-only values such as the future row ID, generated ISRC, and automatic entry date.</li>
          <li><strong>Core Details</strong>: track title, artist, additional artists, album title, and genre.</li>
          <li><strong>Release &amp; Codes</strong>: release date, track length, ISWC, UPC/EAN, catalog number, and BUMA work number.</li>
          <li><strong>Managed Media</strong>: attach a local audio file and album art image that the app manages for the selected track.</li>
        </ul>
        <p>Use <strong>Save Track</strong> to create the row, or <strong>Reset Form</strong> to clear the current entry form. If a valid ISRC prefix is configured, the generated ISRC preview updates from the current prefix, artist code, and release-date year rules. If no prefix is configured, the form still saves normally and leaves ISRC blank until you set or import one later.</p>
        """,
    ),
    HelpChapter(
        chapter_id="album-entry",
        title="Add Album Dialog",
        summary="How to enter shared album metadata once and create multiple track rows from one dialog.",
        keywords=("add album", "album dialog", "multi track", "album entry", "track sections", "shared metadata"),
        content_html="""
        <p>The <strong>Add Album</strong> dialog is designed for building a full release in one pass. It starts with shared album metadata at the top, followed by a tabbed track workspace so each track gets its own dedicated page.</p>
        <ul>
          <li><strong>Album Overview</strong>: album title, UPC/EAN, genre, catalog number, album art, and the release-year rule used when auto-generating blank ISRC values.</li>
          <li><strong>Track Tabs</strong>: each tab stores one track title, main artist, additional artists, release date, track length, optional ISRC, optional ISWC, optional BUMA work number, and an audio file.</li>
          <li><strong>Dynamic layout</strong>: the dialog opens with two track tabs by default, but you can add more or remove the current tab at any time.</li>
          <li><strong>Blank-tab handling</strong>: completely unused track tabs are ignored when you save, so you do not need to delete every spare tab before closing the dialog.</li>
          <li><strong>Shared album art</strong>: the selected album art is stored once and linked across the saved album tracks automatically.</li>
        </ul>
        <p>If a valid ISRC prefix is configured, leaving a track ISRC blank lets the dialog auto-generate it during save. If no prefix is configured, blank ISRC values remain blank and the tracks are still created successfully.</p>
        """,
    ),
    HelpChapter(
        chapter_id="catalog-table",
        title="Catalog Table",
        summary="Search, preview, sort, hide columns, and work with existing tracks from the main table view.",
        keywords=("catalog table", "search", "columns", "preview", "double click", "table", "records", "bulk edit", "context menu", "multi selection"),
        content_html="""
        <p>The Catalog Table shows all saved track rows. It supports sorting, filtering, column visibility, header layout persistence, and media preview shortcuts.</p>
        <ul>
          <li><strong>Search controls</strong>: choose a target column or search all columns, then enter search text to filter the list.</li>
          <li><strong>Column visibility</strong>: use <strong>View &gt; Columns</strong> to show or hide visible columns without deleting them.</li>
          <li><strong>Double click</strong>: edit a standard row, or open file pickers directly for standard media columns such as Audio File and Album Art.</li>
          <li><strong>Multi-row selection</strong>: select multiple rows and open <strong>Edit Selected</strong> or the context menu to launch bulk edit for the current batch.</li>
          <li><strong>Context menu and shortcuts</strong>: preview media, copy values, open GS1 metadata, and edit/delete the current selection. Right-clicking inside an existing multi-row selection keeps that batch selected.</li>
        </ul>
        <p>Table layout, column widths, row-height mode, and column ordering can be saved and restored. Those preferences can also be reset or customized from the View menu.</p>
        """,
    ),
    HelpChapter(
        chapter_id="custom-columns",
        title="Custom Columns",
        summary="Create, rename, reorder, remove, and populate custom metadata fields beyond the default track schema.",
        keywords=("custom columns", "custom fields", "metadata", "dropdown", "checkbox", "date", "columns"),
        content_html="""
        <p>Custom columns let you extend the catalog beyond the built-in track fields. Supported field types include text, dropdown, checkbox, and date-based custom values.</p>
        <ul>
          <li><strong>Add Custom Column…</strong>: create a new reusable custom field definition.</li>
          <li><strong>Remove Custom Column…</strong>: permanently remove a custom field definition.</li>
          <li><strong>Manage Custom Columns…</strong>: rename definitions, change types, and update dropdown options.</li>
        </ul>
        <p>Custom columns can be visible in the table, exported, imported, and edited per track. The View menu controls whether they are shown, while the custom columns manager controls whether they exist at all.</p>
        """,
    ),
    HelpChapter(
        chapter_id="edit-entry",
        title="Edit Entry",
        summary="How the full track editor works for existing rows, including standard metadata, media replacement, and validation.",
        keywords=("edit entry", "track editor", "edit track", "iswc", "upc", "catalog number", "buma", "bulk edit", "gs1 metadata", "release sync"),
        content_html="""
        <p>The Edit Entry dialog opens the full editor for an existing track. When multiple table rows are selected, the same dialog switches into <strong>bulk edit</strong> mode and shows mixed-value placeholders where the selected records do not match.</p>
        <ul>
          <li><strong>Copy buttons</strong>: copy ISO or compact forms of ISRC and ISWC values.</li>
          <li><strong>Media replacement</strong>: browse for new audio or album art files, or clear the currently stored media.</li>
          <li><strong>Bulk edit safeguards</strong>: only fields you actually change are written back to every selected row.</li>
          <li><strong>Bulk edit locked fields</strong>: ISRC, ISWC, Track Title, Audio File, Track Length, and BUMA work number remain view-only during multi-row editing.</li>
          <li><strong>GS1 handoff</strong>: the <strong>GS1 Metadata…</strong> button opens the GS1 dialog for the same current track or selected batch.</li>
          <li><strong>Validation</strong>: duplicate ISRCs, invalid ISWC values, and invalid UPC/EAN values are blocked before save.</li>
        </ul>
        <p>Saving changes updates the current row, records the change in history, and keeps related catalog references such as artists, albums, and first-class release metadata synchronized where the edited values are shared at release level.</p>
        """,
    ),
    HelpChapter(
        chapter_id="audio-tags",
        title="Audio Tags",
        summary="Import embedded tags from supported audio files and write catalog metadata back to exported copies.",
        keywords=("audio tags", "id3", "flac", "vorbis", "m4a", "mp4", "wav", "aiff", "import tags", "write tags"),
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
        summary="How first-class release records work, how they connect to tracks, and how to browse or edit them.",
        keywords=("releases", "release browser", "product", "upc", "catalog number", "disc number", "track number"),
        content_html="""
        <p>The app now stores releases as first-class records instead of treating album-style metadata only as repeated track fields. A release can store product-level metadata and a separate ordered track list.</p>
        <ul>
          <li><strong>Release fields</strong>: title, subtitle/version, primary artist, album artist, release type, release dates, label, sublabel, catalog number, UPC/EAN, barcode validation status, territory, explicit flag, notes, and release artwork.</li>
          <li><strong>Release order</strong>: releases store disc number, track number, and sequence separately from the track metadata itself.</li>
          <li><strong>Add Album integration</strong>: saving a grouped album entry automatically creates or updates a real release and attaches the created tracks.</li>
          <li><strong>Release Browser…</strong>: browse releases, inspect the ordered track list, duplicate releases, add the current track selection, and filter the main catalog table to a chosen release.</li>
          <li><strong>Single-track workflows</strong>: saving the Add Data panel or the Edit Entry dialog also keeps the corresponding release record synchronized when release-level fields change.</li>
        </ul>
        <p>Older databases are migrated automatically. Existing album-like track groups remain usable, and the migration infers release records from stored album/release metadata where possible without deleting old track data.</p>
        """,
    ),
    HelpChapter(
        chapter_id="exchange-formats",
        title="Exchange Formats",
        summary="CSV, XLSX, JSON, XML, and packaged export/import workflows.",
        keywords=("csv", "xlsx", "json", "xml", "package", "zip", "column mapping", "dry run", "import report"),
        content_html="""
        <p>Beyond XML and the GS1 workbook workflow, the app now supports broader catalog exchange formats for local-first sharing and archive workflows.</p>
        <ul>
          <li><strong>Export formats</strong>: CSV, XLSX, JSON, XML, and ZIP packages containing a JSON manifest plus copied media references.</li>
          <li><strong>Import formats</strong>: CSV, XLSX, JSON, and XML.</li>
          <li><strong>Import preview</strong>: CSV and XLSX imports open a mapping dialog so you can confirm how source columns map to standard or custom fields before running the import.</li>
          <li><strong>Saved mapping presets</strong>: frequently used column mappings can be saved per format and reused later.</li>
          <li><strong>Import modes</strong>: dry-run validation, create new rows, merge into existing matches, update existing matches only, or insert-new-when-duplicate-exists.</li>
          <li><strong>Matching options</strong>: internal ID, ISRC, UPC/EAN plus title, and optional title/artist heuristics.</li>
          <li><strong>JSON schema versioning</strong>: exported JSON includes an explicit schema version so future migrations stay manageable.</li>
        </ul>
        <p>Binary media is exported by file reference in plain tabular formats. ZIP package exports also copy referenced media into the package so the export remains portable without embedding raw blobs into CSV or XLSX.</p>
        """,
    ),
    HelpChapter(
        chapter_id="quality-dashboard",
        title="Quality Dashboard",
        summary="Scan the profile for metadata, release, media, and integrity issues, then export or fix them.",
        keywords=("quality dashboard", "issues", "validation", "duplicates", "broken media", "fixes", "export readiness"),
        content_html="""
        <p>The <strong>Data Quality Dashboard</strong> scans the active profile for actionable issues and groups them by severity and rule type.</p>
        <ul>
          <li><strong>Headline counts</strong>: total issues plus error, warning, and informational totals.</li>
          <li><strong>Rule coverage</strong>: missing or duplicate ISRCs, missing or duplicate release UPC/EANs, invalid barcode checksums, missing titles/artists/dates, missing artwork, broken media references, ordering issues, orphaned licenses, and required custom-field gaps where rules exist.</li>
          <li><strong>Filters</strong>: narrow the current issue list by severity, issue type, entity type, or release.</li>
          <li><strong>Open Record</strong>: jump directly to the affected track or release editor from the selected issue row.</li>
          <li><strong>Suggested fixes</strong>: regenerate derived values, normalize date formats, relink missing media by filename, or fill blank track values from linked release metadata where appropriate.</li>
          <li><strong>Export</strong>: save the current issue list to CSV or JSON for reporting or offline cleanup planning.</li>
        </ul>
        <p>Quality scans run on demand and are designed to surface practical export-readiness issues instead of generic diagnostics only.</p>
        """,
    ),
    HelpChapter(
        chapter_id="gs1-metadata",
        title="GS1 Metadata",
        summary="How GS1 metadata editing works for single tracks, grouped releases, and official workbook export.",
        keywords=("gs1", "gs1 metadata", "workbook", "template", "export", "album groups", "official workbook"),
        content_html="""
        <p>The GS1 Metadata dialog can be opened for one track or for a selected batch of tracks. The dialog groups the current selection into one or more final GS1 product rows, depending on the release context.</p>
        <ul>
          <li><strong>Single track or batch</strong>: launch it from the Catalog menu, the table context menu, or the edit and bulk edit dialogs.</li>
          <li><strong>Grouped editing</strong>: album-style selections can appear as grouped GS1 product tabs, while singles remain separate export rows.</li>
          <li><strong>Official workbook</strong>: choose the official GS1 workbook from your GS1 environment. The app validates headers and sheet structure before export.</li>
          <li><strong>Python dependency</strong>: GS1 workbook validation and export require the <code>openpyxl</code> package in the same Python environment that starts the app.</li>
        </ul>
        <p>Use <strong>Save</strong> to store GS1 metadata in the catalog, <strong>Export Current…</strong> to export the active product row, or <strong>Export Batch…</strong> to write the full selected batch to one workbook.</p>
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
        summary="The consolidated settings dialog for application identity, registration values, snapshots, and theme configuration.",
        keywords=("settings", "application settings", "window title", "icon", "isrc prefix", "snapshot interval"),
        content_html="""
        <p>The Application Settings dialog combines the app-level and profile-aware settings that used to live in separate dialogs.</p>
        <ul>
          <li><strong>Application</strong>: window title and optional app icon file.</li>
          <li><strong>Registration &amp; Codes</strong>: ISRC prefix, artist code, SENA number, VAT/BTW number, and BUMA/STEMRA identifiers.</li>
          <li><strong>Snapshots</strong>: automatic snapshot enable/disable and interval settings.</li>
          <li><strong>Theme</strong>: typography, colors, saved themes, and advanced QSS.</li>
        </ul>
        <p>Saving settings updates the current app state immediately and records the change in history where supported.</p>
        """,
    ),
    HelpChapter(
        chapter_id="theme-settings",
        title="Theme Settings",
        summary="Customize the app appearance, manage named theme presets, and target controls using advanced QSS.",
        keywords=("theme", "appearance", "font", "colors", "qss", "saved themes", "style"),
        content_html="""
        <p>The Theme page lets you customize the visual appearance of the app.</p>
        <ul>
          <li><strong>Typography</strong>: choose the application font and base font size.</li>
          <li><strong>Contrast guard</strong>: automatically fix unreadable text colors against their backgrounds, unless you disable that guard.</li>
          <li><strong>Application colors</strong>: set the window, text, accent, and selection colors.</li>
          <li><strong>Controls &amp; Tables</strong>: set button, input, and table colors separately.</li>
          <li><strong>Saved Themes</strong>: save the current theme under a name, load a stored theme, or delete saved presets.</li>
          <li><strong>Advanced QSS</strong>: append custom Qt stylesheet rules that target object names or widget types directly.</li>
        </ul>
        <p>All visible controls receive object names automatically so advanced QSS can target specific widgets. Saved theme presets persist between launches and remain selectable from the theme dropdown.</p>
        """,
    ),
    HelpChapter(
        chapter_id="history",
        title="Undo History and Snapshots",
        summary="Use undo/redo, inspect history entries, create snapshots, and restore older states of a profile.",
        keywords=("history", "undo", "redo", "snapshots", "restore", "history dialog"),
        content_html="""
        <p>The app has a persistent history system for core data changes, settings changes, and many file-backed actions.</p>
        <ul>
          <li><strong>Undo / Redo</strong>: revert or reapply the latest reversible action.</li>
          <li><strong>Show Undo History…</strong>: inspect session and profile history entries.</li>
          <li><strong>Create Snapshot…</strong>: save a manual restore point.</li>
          <li><strong>Restore Snapshot</strong>: roll the profile back to a previous state.</li>
        </ul>
        <p>Snapshots capture the profile database, relevant settings, and managed file state where supported. The history dialog separates session-level actions from in-profile history entries.</p>
        """,
    ),
    HelpChapter(
        chapter_id="diagnostics",
        title="Diagnostics",
        summary="Inspect environment details, schema health, managed files, snapshot integrity, and available repair actions.",
        keywords=("diagnostics", "integrity", "schema", "repair", "managed files", "checks"),
        content_html="""
        <p>The Diagnostics window gives you a high-level health view of the current profile and application environment.</p>
        <ul>
          <li><strong>Environment</strong>: app version, schema version, profile path, data folder, log folder, snapshot count, platform, and Python version.</li>
          <li><strong>Checks</strong>: schema validation, SQLite integrity, foreign-key integrity, custom-value integrity, managed files, and snapshot storage.</li>
          <li><strong>Details</strong>: expanded explanation for the currently selected check.</li>
          <li><strong>Repair</strong>: preview or run supported repair actions when a check reports a repairable issue.</li>
        </ul>
        <p>Use Diagnostics when the app reports something unexpected, after a restore, or when you want to verify that the catalog and managed files are still consistent.</p>
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
        summary="Version information, current workspace summary, and where to find local support data such as logs and data folders.",
        keywords=("about", "version", "workspace", "support", "data folder", "logs folder"),
        content_html="""
        <p>The About dialog summarizes the current app version, local-first design, and where your current workspace data lives.</p>
        <p>Use the Help menu to reach:</p>
        <ul>
          <li><strong>About ISRC Catalog Manager…</strong> for the current version and workspace overview.</li>
          <li><strong>Diagnostics…</strong> for health checks and repair options.</li>
          <li><strong>Application Log…</strong> for human and structured logs.</li>
          <li><strong>Open Logs Folder…</strong> and <strong>Open Data Folder…</strong> to inspect files directly.</li>
        </ul>
        """,
    ),
)


HELP_CHAPTERS_BY_ID = {chapter.chapter_id: chapter for chapter in HELP_CHAPTERS}


def help_topic_title(chapter_id: str) -> str:
    chapter = HELP_CHAPTERS_BY_ID.get(chapter_id)
    return chapter.title if chapter is not None else "Help"


def render_help_html(app_name: str, version_text: str = "") -> str:
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
        keyword_rows.append(
            f"<tr><th>{escape(keyword)}</th><td>{links}</td></tr>"
        )

    version_line = f"<p class='version'>Version {escape(version_text)}</p>" if version_text else ""
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
      color: #18212b;
      background: #f8fafc;
    }}
    h1, h2, h3 {{ color: #0f172a; }}
    h1 {{ margin-bottom: 0.2em; }}
    .summary {{ color: #475569; }}
    .hero, .panel, .chapter {{
      background: #ffffff;
      border: 1px solid #dbe4ee;
      border-radius: 12px;
      padding: 18px 20px;
      margin-bottom: 18px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
    }}
    .hero p, .panel p, .chapter p {{ margin: 0.55em 0; }}
    .version {{ color: #52606d; margin-top: 0; }}
    ul {{ margin-top: 0.4em; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      background: #ffffff;
    }}
    th, td {{
      border: 1px solid #dbe4ee;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      width: 24%;
      background: #edf2f7;
    }}
    a {{
      color: #0f62fe;
      text-decoration: none;
    }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <section class="hero">
    <h1>{escape(app_name)} Help</h1>
    {version_line}
    <p>This manual is the full local help reference for the app. Use the table of contents to jump to a chapter, the keyword index to find a feature quickly, or the in-app Help viewer to search through the content.</p>
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
