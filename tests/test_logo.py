import unittest

from nexus.ui.tui import GRADIENT_COLORS, LOGO_GLYPHS, RAW_LOGO, _compose_logo


class NolthiraLogoTests(unittest.TestCase):
    def test_every_glyph_uses_a_fixed_seven_by_seven_cell(self):
        self.assertEqual(set(LOGO_GLYPHS), set("NOLTHIRA"))
        for letter, rows in LOGO_GLYPHS.items():
            with self.subTest(letter=letter):
                self.assertEqual(len(rows), 7)
                self.assertTrue(all(len(row) == 7 for row in rows))

    def test_composed_wordmark_has_aligned_rows_and_shadow(self):
        self.assertEqual(len(RAW_LOGO), 8)
        self.assertEqual(len({len(row) for row in RAW_LOGO}), 1)
        self.assertEqual(len(RAW_LOGO[0]), 71)
        self.assertTrue(any("░" in row for row in RAW_LOGO))
        self.assertTrue(all(len(row) <= 80 for row in RAW_LOGO))

    def test_gradient_rendering_is_safe_for_the_shadow_row(self):
        self.assertGreaterEqual(len(GRADIENT_COLORS), 7)
        self.assertEqual(GRADIENT_COLORS[min(len(RAW_LOGO) - 1, len(GRADIENT_COLORS) - 1)], GRADIENT_COLORS[-1])

    def test_wordmark_builder_rejects_unsupported_characters(self):
        with self.assertRaises(ValueError):
            _compose_logo("NOLTHIRA!")


if __name__ == "__main__":
    unittest.main()
