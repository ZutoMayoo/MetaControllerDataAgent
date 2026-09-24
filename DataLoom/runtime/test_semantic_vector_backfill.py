from __future__ import annotations

import unittest

from semantic_vector_backfill import build_update


class SemanticVectorBackfillTests(unittest.TestCase):
    def test_table_uses_name_only_when_description_is_empty(self) -> None:
        payload, source, fallback = build_update(
            "data_table", {"table_description": "", "table_name": "customers"}
        )
        self.assertEqual(payload, {"tableDescription": "customers"})
        self.assertEqual(source, "table_name")
        self.assertTrue(fallback)

    def test_column_preserves_existing_description(self) -> None:
        payload, source, fallback = build_update(
            "data_column", {"column_description_short": "customer identifier"}
        )
        self.assertEqual(
            payload,
            {
                "columnDescriptionShort": "customer identifier",
                "columnDescription": "customer identifier",
            },
        )
        self.assertEqual(source, "column_description_short")
        self.assertFalse(fallback)

    def test_value_copies_value_into_empty_description(self) -> None:
        payload, source, fallback = build_update(
            "data_column_value", {"description": "", "value": "EUR"}
        )
        self.assertEqual(payload, {"description": "EUR", "value": "EUR"})
        self.assertEqual(source, "value")
        self.assertTrue(fallback)

    def test_value_requires_a_non_empty_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "no usable value"):
            build_update("data_column_value", {"description": "currency", "value": ""})


if __name__ == "__main__":
    unittest.main()
