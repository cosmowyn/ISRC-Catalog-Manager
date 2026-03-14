import unittest

from isrc_manager.help_content import HELP_CHAPTERS, HELP_CHAPTERS_BY_ID, render_help_html


class HelpContentTests(unittest.TestCase):
    def test_chapter_ids_are_unique_and_indexed(self):
        chapter_ids = [chapter.chapter_id for chapter in HELP_CHAPTERS]

        self.assertEqual(len(chapter_ids), len(set(chapter_ids)))
        self.assertEqual(set(chapter_ids), set(HELP_CHAPTERS_BY_ID))
        self.assertIn("overview", HELP_CHAPTERS_BY_ID)
        self.assertIn("settings", HELP_CHAPTERS_BY_ID)
        self.assertIn("history", HELP_CHAPTERS_BY_ID)

    def test_rendered_help_contains_contents_index_and_anchors(self):
        html = render_help_html("ISRC Catalog Manager", "1.2.3")

        self.assertIn("Table of Contents", html)
        self.assertIn("Keyword Index", html)
        self.assertIn("Version 1.2.3", html)

        for chapter in HELP_CHAPTERS:
            self.assertIn(f"id='{chapter.chapter_id}'", html)
            self.assertIn(f"href='#{chapter.chapter_id}'", html)


if __name__ == "__main__":
    unittest.main()
