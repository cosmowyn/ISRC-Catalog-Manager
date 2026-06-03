import unittest
from collections import Counter

from isrc_manager.help_content import (
    HELP_CHAPTER_SCREENSHOT_BASES,
    HELP_CHAPTER_SCREENSHOT_EXEMPT_IDS,
    HELP_CHAPTERS,
    HELP_CHAPTERS_BY_ID,
    HELP_SCREENSHOT_MAX_WIDTH_PERCENT,
    HELP_SCREENSHOT_REFERENCES,
    HELP_SECTION_ORDER,
    HELP_SECTION_SUMMARIES,
    help_chapter_requires_screenshot,
    help_section_for_chapter,
    help_section_toc_title,
    iter_help_sections,
    render_help_html,
    representative_screenshot_for_chapter,
)


class HelpContentTests(unittest.TestCase):
    def test_chapter_ids_are_unique_and_indexed(self):
        chapter_ids = [chapter.chapter_id for chapter in HELP_CHAPTERS]

        self.assertEqual(len(chapter_ids), len(set(chapter_ids)))
        self.assertEqual(set(chapter_ids), set(HELP_CHAPTERS_BY_ID))
        self.assertIn("overview", HELP_CHAPTERS_BY_ID)
        self.assertIn("audio-authenticity", HELP_CHAPTERS_BY_ID)
        self.assertIn("code-registry", HELP_CHAPTERS_BY_ID)
        self.assertIn("conversion", HELP_CHAPTERS_BY_ID)
        self.assertIn("settings", HELP_CHAPTERS_BY_ID)
        self.assertIn("history", HELP_CHAPTERS_BY_ID)
        self.assertIn("keyboard-shortcuts", HELP_CHAPTERS_BY_ID)
        self.assertIn("application-updates", HELP_CHAPTERS_BY_ID)
        self.assertIn("soundcloud-publishing", HELP_CHAPTERS_BY_ID)
        self.assertIn("application-storage-admin", HELP_CHAPTERS_BY_ID)
        self.assertNotIn("visual-ui-reference", HELP_CHAPTERS_BY_ID)

    def test_help_chapter_screenshot_mapping_uses_specific_ui_surfaces(self):
        chapter_ids = {chapter.chapter_id for chapter in HELP_CHAPTERS}
        screenshot_required_ids = chapter_ids - HELP_CHAPTER_SCREENSHOT_EXEMPT_IDS
        screenshot_filenames = {reference.filename for reference in HELP_SCREENSHOT_REFERENCES}
        base_counts = Counter(HELP_CHAPTER_SCREENSHOT_BASES.values())

        self.assertEqual(set(HELP_CHAPTER_SCREENSHOT_BASES), screenshot_required_ids)
        self.assertFalse(set(HELP_CHAPTER_SCREENSHOT_BASES.values()) - screenshot_filenames)
        self.assertLessEqual(base_counts["main_window.png"], 3)
        self.assertGreaterEqual(len(base_counts), 24)
        self.assertFalse(help_chapter_requires_screenshot("overview"))
        self.assertFalse(help_chapter_requires_screenshot("main-window"))
        self.assertFalse(help_chapter_requires_screenshot("keyboard-shortcuts"))
        self.assertTrue(help_chapter_requires_screenshot("add-data"))
        self.assertEqual(
            representative_screenshot_for_chapter("add-data"), "add_track_workspace.png"
        )
        self.assertEqual(
            representative_screenshot_for_chapter("soundcloud-publishing"),
            "soundcloud_publish_dialog.png",
        )
        self.assertEqual(
            representative_screenshot_for_chapter("accounting-royalties"),
            "invoice_workspace.png",
        )

    def test_rendered_help_contains_contents_index_and_anchors(self):
        html = render_help_html("Music Catalog Manager", "1.2.3")

        self.assertIn("Table of Contents", html)
        self.assertIn("Keyword Index", html)
        self.assertIn("Version 1.2.3", html)
        self.assertIn('id="top"', html)
        self.assertIn('href="#contents"', html)
        self.assertNotIn("SF Pro Text", html)
        self.assertIn("Part 1: Getting Started", html)
        self.assertIn("Part 5: Repertoire, Rights, and Assets", html)
        self.assertNotIn("Visual UI Reference", html)

        for chapter in HELP_CHAPTERS:
            self.assertIn(f"id='{chapter.chapter_id}'", html)
            self.assertIn(f"href='#{chapter.chapter_id}'", html)

    def test_rendered_help_uses_controlled_screenshot_blocks(self):
        html = render_help_html("Music Catalog Manager", "1.2.3")

        self.assertNotIn("<figure", html)
        self.assertNotIn("figcaption", html)
        self.assertIn('<div class="help-screenshot">', html)
        self.assertIn('class="help-screenshot-image"', html)
        self.assertIn('class="help-screenshot-caption"', html)
        self.assertIn(f"max-width: {HELP_SCREENSHOT_MAX_WIDTH_PERCENT}%;", html)
        self.assertIn("clear: both;", html)
        self.assertIn("chapter-lead-with-media", html)
        self.assertIn("Back to Table of Contents", html)
        self.assertNotIn("screenshots/chapter_overview.png", html)
        self.assertNotIn("screenshots/chapter_main-window.png", html)
        self.assertNotIn("screenshots/chapter_keyboard-shortcuts.png", html)
        self.assertIn("screenshots/chapter_add-data.png", html)

    def test_rendered_help_can_follow_theme_palette(self):
        html = render_help_html(
            "Music Catalog Manager",
            "1.2.3",
            theme={
                "input_bg": "#0F172A",
                "window_fg": "#E2E8F0",
                "panel_bg": "#13243B",
                "border_color": "#29507A",
                "secondary_text": "#8BA3C2",
                "header_bg": "#17324E",
                "header_fg": "#F8FAFC",
                "link_color": "#38BDF8",
                "font_family": "Courier New",
            },
        )

        self.assertIn("background: #0F172A", html)
        self.assertIn("background: #13243B", html)
        self.assertIn("color: #E2E8F0", html)
        self.assertIn("background: #17324E", html)
        self.assertIn("color: #38BDF8", html)
        self.assertIn('font-family: "Courier New", sans-serif', html)

    def test_audio_authenticity_help_chapter_mentions_direct_and_lineage_scope(self):
        chapter = HELP_CHAPTERS_BY_ID["audio-authenticity"]

        self.assertIn("AIFF", chapter.content_html)
        self.assertIn("Provenance", chapter.content_html)
        self.assertIn("separate managed export workflow", chapter.content_html.lower())
        self.assertIn("Registry SHA-256 Key", chapter.content_html)

    def test_code_registry_help_chapter_covers_shared_usage_and_distinction(self):
        chapter = HELP_CHAPTERS_BY_ID["code-registry"]

        self.assertIn("Link Selected Value", chapter.content_html)
        self.assertIn("usage count", chapter.content_html.lower())
        self.assertIn("Registry SHA-256 Key", chapter.content_html)
        self.assertIn("not an audio-authenticity key", chapter.content_html.lower())

    def test_conversion_help_chapter_covers_template_mapping_and_export_scope(self):
        chapter = HELP_CHAPTERS_BY_ID["conversion"]

        self.assertIn("File &gt; Conversion…", chapter.content_html)
        self.assertIn("Current Profile Tracks", chapter.content_html)
        self.assertIn("Saved templates", chapter.content_html)
        self.assertIn("SENA", chapter.content_html)
        self.assertIn("CSV", chapter.content_html)
        self.assertIn("XLSX", chapter.content_html)
        self.assertIn("XML", chapter.content_html)
        self.assertIn(
            "does not write into the catalog database",
            HELP_CHAPTERS_BY_ID["import-workflows"].content_html,
        )

    def test_help_chapters_are_grouped_into_subject_sections(self):
        grouped = list(iter_help_sections())

        self.assertEqual(grouped[0][0], HELP_SECTION_ORDER[0])
        self.assertEqual(set(HELP_SECTION_SUMMARIES), set(HELP_SECTION_ORDER))
        self.assertEqual(help_section_toc_title(1, grouped[0][0]), "Part 1: Getting Started")
        grouped_ids = {
            section: {chapter.chapter_id for chapter in chapters} for section, chapters in grouped
        }
        self.assertIn("overview", grouped_ids["Getting Started"])
        self.assertIn("keyboard-shortcuts", grouped_ids["Getting Started"])
        self.assertIn("edit-entry", grouped_ids["Catalog Entry and Editing"])
        self.assertIn("media-preview", grouped_ids["Catalog Review and Media"])
        self.assertIn("code-registry", grouped_ids["Releases and Registries"])
        self.assertIn("repertoire-knowledge", grouped_ids["Repertoire, Rights, and Assets"])
        self.assertIn("conversion", grouped_ids["Import, Export, and Storage"])
        self.assertIn("soundcloud-publishing", grouped_ids["Publishing and Authenticity"])
        self.assertIn("diagnostics", grouped_ids["Operations and Recovery"])
        self.assertIn("application-storage-admin", grouped_ids["Operations and Recovery"])
        self.assertIn("application-updates", grouped_ids["Operations and Recovery"])
        self.assertEqual(help_section_for_chapter("theme-settings"), "Settings and Reference")

    def test_keyboard_shortcuts_chapter_lists_primary_shortcuts(self):
        chapter = HELP_CHAPTERS_BY_ID["keyboard-shortcuts"]

        self.assertIn("Bulk Attach Audio Files", chapter.content_html)
        self.assertIn("Derivative Ledger", chapter.content_html)
        self.assertIn("Ctrl+Alt+V", chapter.content_html)
        self.assertIn("F1", chapter.content_html)
        self.assertIn("Shift+F2", chapter.content_html)
        self.assertIn("Shift+F3", chapter.content_html)

    def test_help_chapters_describe_track_first_governed_creation(self):
        overview = HELP_CHAPTERS_BY_ID["overview"]
        add_data = HELP_CHAPTERS_BY_ID["add-data"]
        album_entry = HELP_CHAPTERS_BY_ID["album-entry"]
        releases = HELP_CHAPTERS_BY_ID["releases"]

        self.assertIn("Add Track", overview.content_html)
        self.assertIn("Add Album", overview.content_html)
        self.assertIn("Work Manager", overview.content_html)
        self.assertEqual(add_data.title, "Add Track")
        self.assertIn("create new work from track", add_data.content_html.lower())
        self.assertIn("track number", add_data.content_html.lower())
        self.assertIn("Party", add_data.content_html)
        self.assertEqual(album_entry.title, "Add Album")
        self.assertIn(
            "every populated row must resolve work governance before save",
            album_entry.content_html.lower(),
        )
        self.assertIn("local numbering defaults", album_entry.content_html.lower())
        self.assertIn("stored track number", releases.content_html.lower())

    def test_help_chapters_describe_diagnostics_cleanup_and_window_title_defaults(self):
        cleanup = HELP_CHAPTERS_BY_ID["catalog-managers"]
        diagnostics = HELP_CHAPTERS_BY_ID["diagnostics"]
        settings = HELP_CHAPTERS_BY_ID["settings"]
        application_log = HELP_CHAPTERS_BY_ID["application-log"]

        self.assertEqual(cleanup.title, "Catalog Cleanup")
        self.assertIn("Diagnostics", cleanup.content_html)
        self.assertIn("Catalog Cleanup", diagnostics.content_html)
        self.assertIn("owner Party company name", settings.content_html)
        self.assertIn("custom value acts as an explicit override", settings.content_html)
        self.assertIn("Export Settings", settings.content_html)
        self.assertIn("Sounds", settings.content_html)
        self.assertIn("Remember database password", settings.content_html)
        self.assertIn("Do not warn when opening unencrypted profiles", settings.content_html)
        self.assertIn("30 days", settings.content_html)
        self.assertIn("SQLCipher", HELP_CHAPTERS_BY_ID["profiles"].content_html)
        self.assertIn("migration path", HELP_CHAPTERS_BY_ID["profiles"].content_html)
        self.assertIn(
            "only when you open that profile", HELP_CHAPTERS_BY_ID["profiles"].content_html
        )
        self.assertIn("app backups folder", HELP_CHAPTERS_BY_ID["profiles"].content_html)
        self.assertIn("choose the profile to delete", HELP_CHAPTERS_BY_ID["profiles"].content_html)
        self.assertIn(
            "preserves the original schema version", HELP_CHAPTERS_BY_ID["profiles"].content_html
        )
        self.assertIn("Invalid legacy ISRC values", HELP_CHAPTERS_BY_ID["profiles"].content_html)
        self.assertIn("suppresses future warnings", HELP_CHAPTERS_BY_ID["profiles"].content_html)
        self.assertIn("secure-memory locking", HELP_CHAPTERS_BY_ID["profiles"].content_html)
        self.assertIn("database-at-rest encryption", HELP_CHAPTERS_BY_ID["profiles"].content_html)
        self.assertIn("SoundCloud", settings.content_html)
        self.assertIn("OS keychain/keyring availability", settings.content_html)
        self.assertIn("Aeon Cosmowyn", settings.content_html)
        self.assertIn("GTIN contracts CSV", settings.content_html)
        self.assertIn("Automatic Reporting", application_log.content_html)
        self.assertIn(
            "unfrozen development runs skip this startup crash-report check",
            application_log.content_html,
        )
        self.assertIn("Submit Report", application_log.content_html)
        self.assertIn("unchecked option", application_log.content_html)
        self.assertIn("read-only native log queries", application_log.content_html)
        self.assertIn("resources/reporting.json", application_log.content_html)
        self.assertIn("report proxy", application_log.content_html)
        self.assertIn("reports folder", application_log.content_html)

    def test_media_preview_help_documents_audio_player_capabilities(self):
        chapter = HELP_CHAPTERS_BY_ID["media-preview"]

        self.assertEqual(chapter.title, "Audio Player and Image Preview")
        self.assertIn("Now Playing", chapter.content_html)
        self.assertIn("Play Next", chapter.content_html)
        self.assertIn("Album playlist", chapter.content_html)
        self.assertIn("Auto Advance", chapter.content_html)
        self.assertIn("smooth meter and spectrum fade-out", chapter.content_html)
        self.assertIn("forensic watermarked audio", chapter.content_html)

    def test_application_updates_help_documents_installer_workflow(self):
        chapter = HELP_CHAPTERS_BY_ID["application-updates"]
        html = render_help_html("Music Catalog Manager", "3.6.5")

        self.assertIn("Download and Install", chapter.content_html)
        self.assertIn("SHA-256", chapter.content_html)
        self.assertIn("updater-helper mode", chapter.content_html)
        self.assertIn("App Translocation", chapter.content_html)
        self.assertIn("/Applications", chapter.content_html)
        self.assertIn("updates", chapter.content_html)
        self.assertIn("Application Updates", html)

    def test_soundcloud_publishing_help_documents_secure_publish_workflow(self):
        chapter = HELP_CHAPTERS_BY_ID["soundcloud-publishing"]
        html = render_help_html("Music Catalog Manager", "3.6.5")

        self.assertIn("Catalog &gt; Publish &gt; SoundCloud", chapter.content_html)
        self.assertIn("Publish to SoundCloud", chapter.content_html)
        self.assertIn("Choose tracks", chapter.content_html)
        self.assertIn("private", chapter.content_html)
        self.assertIn("downloadable", chapter.content_html)
        self.assertIn("streamable", chapter.content_html)
        self.assertIn("OS keychain/keyring", chapter.content_html)
        self.assertIn("Session-only fallback", chapter.content_html)
        self.assertIn("watermarked WAV", chapter.content_html)
        self.assertIn("remote_urn", chapter.content_html)
        self.assertIn("Publish history", chapter.content_html)
        self.assertIn("Metadata comparison", chapter.content_html)
        self.assertIn("SoundCloud Publishing", html)

    def test_application_storage_admin_help_documents_safe_cleanup(self):
        chapter = HELP_CHAPTERS_BY_ID["application-storage-admin"]
        about = HELP_CHAPTERS_BY_ID["about"]

        self.assertIn("Help &gt; Application Storage Admin", chapter.content_html)
        self.assertIn("Preview before cleanup", chapter.content_html)
        self.assertIn("Active-profile safety", chapter.content_html)
        self.assertIn("manual database backups", chapter.content_html)
        self.assertIn("warning-protected recovery points", chapter.content_html)
        self.assertIn("managed media", chapter.content_html)
        self.assertIn("Application Storage Admin", about.content_html)


if __name__ == "__main__":
    unittest.main()
