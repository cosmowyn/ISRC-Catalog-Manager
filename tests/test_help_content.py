import unittest

from isrc_manager.help_content import HELP_CHAPTERS, HELP_CHAPTERS_BY_ID, render_help_html


class HelpContentTests(unittest.TestCase):
    def test_chapter_ids_are_unique_and_indexed(self):
        chapter_ids = [chapter.chapter_id for chapter in HELP_CHAPTERS]

        self.assertEqual(len(chapter_ids), len(set(chapter_ids)))
        self.assertEqual(set(chapter_ids), set(HELP_CHAPTERS_BY_ID))
        self.assertIn("overview", HELP_CHAPTERS_BY_ID)
        self.assertIn("audio-authenticity", HELP_CHAPTERS_BY_ID)
        self.assertIn("settings", HELP_CHAPTERS_BY_ID)
        self.assertIn("history", HELP_CHAPTERS_BY_ID)

    def test_rendered_help_contains_contents_index_and_anchors(self):
        html = render_help_html("ISRC Catalog Manager", "1.2.3")

        self.assertIn("Table of Contents", html)
        self.assertIn("Keyword Index", html)
        self.assertIn("Version 1.2.3", html)
        self.assertNotIn("SF Pro Text", html)

        for chapter in HELP_CHAPTERS:
            self.assertIn(f"id='{chapter.chapter_id}'", html)
            self.assertIn(f"href='#{chapter.chapter_id}'", html)

    def test_rendered_help_can_follow_theme_palette(self):
        html = render_help_html(
            "ISRC Catalog Manager",
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

    def test_help_chapters_describe_track_first_governed_creation(self):
        overview = HELP_CHAPTERS_BY_ID["overview"]
        add_data = HELP_CHAPTERS_BY_ID["add-data"]
        album_entry = HELP_CHAPTERS_BY_ID["album-entry"]

        self.assertIn("Add Track", overview.content_html)
        self.assertIn("Add Album", overview.content_html)
        self.assertIn("Work Manager", overview.content_html)
        self.assertEqual(add_data.title, "Add Track")
        self.assertIn("create new work from track", add_data.content_html.lower())
        self.assertIn("Party", add_data.content_html)
        self.assertEqual(album_entry.title, "Add Album")
        self.assertIn(
            "every populated row must resolve work governance before save",
            album_entry.content_html.lower(),
        )

    def test_help_chapters_describe_diagnostics_cleanup_and_window_title_defaults(self):
        cleanup = HELP_CHAPTERS_BY_ID["catalog-managers"]
        diagnostics = HELP_CHAPTERS_BY_ID["diagnostics"]
        settings = HELP_CHAPTERS_BY_ID["settings"]

        self.assertEqual(cleanup.title, "Catalog Cleanup")
        self.assertIn("Diagnostics", cleanup.content_html)
        self.assertIn("Catalog Cleanup", diagnostics.content_html)
        self.assertIn("owner Party company name", settings.content_html)
        self.assertIn("custom value acts as an explicit override", settings.content_html)


if __name__ == "__main__":
    unittest.main()
