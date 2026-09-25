from __future__ import annotations

import unittest

from semantic_vector_backfill import SemanticApi, build_update


class PagingApi(SemanticApi):
    def __init__(self, pages) -> None:
        super().__init__("http://semantic.invalid", 1)
        self.pages = pages
        self.requests = []

    def _json(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        return {"entities": self.pages.get(payload["offset"], [])}


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
                "columnNameDesc": "customer identifier",
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

    def test_entities_reads_every_page(self) -> None:
        first = [{"guid": f"g{i}"} for i in range(1000)]
        second = [{"guid": "g1000"}]
        api = PagingApi({0: first, 1000: second})

        self.assertEqual(api.entities("data_column_value"), first + second)
        self.assertEqual([request[2]["offset"] for request in api.requests], [0, 1000])

    def test_entities_rejects_duplicate_page(self) -> None:
        page = [{"guid": f"g{i}"} for i in range(1000)]
        api = PagingApi({0: page, 1000: page})

        with self.assertRaisesRegex(RuntimeError, "duplicate page"):
            api.entities("data_column_value")


if __name__ == "__main__":
    unittest.main()
