"""Pins the canonical schema shape the storage layer and dashboard rely on."""
import unittest

from scrapers.core.schema import CANONICAL_COLS, blank_row


class SchemaTest(unittest.TestCase):
    def test_28_columns(self):
        self.assertEqual(len(CANONICAL_COLS), 28)

    def test_odstraneno_dne_sits_right_after_stav(self):
        self.assertIn("Odstraněno dne", CANONICAL_COLS)
        self.assertEqual(
            CANONICAL_COLS.index("Odstraněno dne"),
            CANONICAL_COLS.index("Stav") + 1,
        )

    def test_pocet_valcu_sits_right_after_typ_motoru(self):
        """#24: ICE-only cylinder count column, kept next to the other engine
        columns (after 'Typ motoru', before 'Hybrid typ')."""
        self.assertIn("Počet válců", CANONICAL_COLS)
        self.assertEqual(
            CANONICAL_COLS.index("Počet válců"),
            CANONICAL_COLS.index("Typ motoru") + 1,
        )
        self.assertEqual(
            CANONICAL_COLS.index("Hybrid typ"),
            CANONICAL_COLS.index("Počet válců") + 1,
        )

    def test_verze_replaces_vybava(self):
        """Verze column plumbing: canonical column renamed, count unchanged."""
        self.assertIn("Verze", CANONICAL_COLS)
        self.assertNotIn("Výbava", CANONICAL_COLS)

    def test_blank_row_covers_every_column(self):
        row = blank_row()
        self.assertEqual(set(row), set(CANONICAL_COLS))
        self.assertTrue(all(v == "" for v in row.values()))


if __name__ == "__main__":
    unittest.main()
