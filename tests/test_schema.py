"""Pins the canonical schema shape the storage layer and dashboard rely on."""
import unittest

from scrapers.core.schema import CANONICAL_COLS, blank_row


class SchemaTest(unittest.TestCase):
    def test_27_columns(self):
        self.assertEqual(len(CANONICAL_COLS), 27)

    def test_odstraneno_dne_sits_right_after_stav(self):
        self.assertIn("Odstraněno dne", CANONICAL_COLS)
        self.assertEqual(
            CANONICAL_COLS.index("Odstraněno dne"),
            CANONICAL_COLS.index("Stav") + 1,
        )

    def test_blank_row_covers_every_column(self):
        row = blank_row()
        self.assertEqual(set(row), set(CANONICAL_COLS))
        self.assertTrue(all(v == "" for v in row.values()))


if __name__ == "__main__":
    unittest.main()
