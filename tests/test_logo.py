import unittest

from nexus.ui.tui import LOGO_GLYPHS, RAW_LOGO


class NolthiraLogoTests(unittest.TestCase):
    def test_every_glyph_uses_a_fixed_six_by_six_cell(self):
        self.assertEqual(set(LOGO_GLYPHS), set("NOLTHIRA"))
        for letter, rows in LOGO_GLYPHS.items():
            with self.subTest(letter=letter):
                self.assertEqual(len(rows), 7)
                self.assertTrue(all(len(row) == 5 for row in rows))

    def test_composed_wordmark_has_aligned_rows_and_fits_compact_terminal_width(self):
        self.assertEqual(len(RAW_LOGO), 7)
        self.assertEqual(len({len(row) for row in RAW_LOGO}), 1)
        self.assertEqual(len(RAW_LOGO[0]), 47)


if __name__ == "__main__":
    unittest.main()
