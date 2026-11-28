import unittest

from nexus.ui.tui import GRADIENT_COLORS, LOGO_GLYPHS, RAW_LOGO, _compose_logo


class NolthiraLogoTests(unittest.TestCase):
    def test_glyphs_follow_the_original_six_row_outline_style(self):
        self.assertEqual(set(LOGO_GLYPHS), set("NOLTHIRA"))
        for letter, rows in LOGO_GLYPHS.items():
            with self.subTest(letter=letter):
                self.assertEqual(len(rows), 6)
                self.assertGreater(max(map(len, rows)), 0)

    def test_composed_wordmark_is_aligned_and_fits_an_eighty_column_terminal(self):
        self.assertEqual(len(RAW_LOGO), 6)
        self.assertEqual(len({len(row) for row in RAW_LOGO}), 1)
        self.assertEqual(len(RAW_LOGO[0]), 75)
        self.assertTrue(all(len(row) <= 80 for row in RAW_LOGO))

    def test_gradient_palette_covers_every_logo_row(self):
        self.assertGreaterEqual(len(GRADIENT_COLORS), len(RAW_LOGO))

    def test_wordmark_builder_rejects_unsupported_characters(self):
        with self.assertRaises(ValueError):
            _compose_logo("NOLTHIRA!")


if __name__ == "__main__":
    unittest.main()
