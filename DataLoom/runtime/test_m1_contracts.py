"""Offline regression tests for M1's provenance and gold-isolation boundary."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))

from codeaware_adapter import public_task_statement, repository_root, task_spec  # noqa: E402


class GoldIsolationTests(unittest.TestCase):
    def test_public_statement_stops_before_expected_answer(self) -> None:
        source = """# Example
## 问题
列出有效记录。
## 预期答案
SECRET-GOLD
## 验收
运行 validation.sql。
"""
        self.assertEqual(public_task_statement(source), "列出有效记录。")

    def test_real_task_spec_contains_no_authoring_leakage(self) -> None:
        spec = task_spec("snipe-it", "SNP-AVAILABLE-CHECKOUT-001")
        rendered = str(spec).casefold()
        self.assertNotIn("caw-out-ready", rendered)
        self.assertNotIn("validation.sql", rendered)
        self.assertNotIn("evidence.md", rendered)
        self.assertNotIn("fixture.md", rendered)
        self.assertNotIn("预期答案", rendered)
        self.assertTrue(spec["extensions"]["task_markdown"])

    def test_shared_source_layout_resolves_heldout_saleor(self) -> None:
        root = repository_root("saleor")
        self.assertTrue((root / "saleor").is_dir())

    def test_saleor_inline_gold_is_removed_without_losing_question(self) -> None:
        spec = task_spec("saleor", "SLR-STOCK-RESERVATION-007")
        statement = spec["extensions"]["task_markdown"].casefold()
        self.assertIn("active_reserved_quantity", statement)
        self.assertNotIn("gold", statement)

    def test_task_without_question_heading_stops_before_inline_expected_result(self) -> None:
        spec = task_spec("inventree", "IVT-IN-STOCK-001")
        rendered = spec["extensions"]["task_markdown"].casefold()
        self.assertNotIn("caw-stock-attention", rendered)
        self.assertNotIn("source pin", rendered)


if __name__ == "__main__":
    unittest.main()
