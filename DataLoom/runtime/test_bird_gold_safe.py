"""Offline regression tests for the split-process BIRD Gold boundary."""

from __future__ import annotations

import hashlib
import json
import contextlib
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))

from bird_gold_safe import (
    GoldIsolationError,
    _enforce_zero_few_shot_config,
    audit_bundle,
    evaluate_candidate,
    prepare_bundle,
)


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class BirdGoldSafeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.questions = self.root / "dev.json"
        _json(self.questions, [{
            "question_id": 7,
            "db_id": "sample",
            "question": "Which names are active?",
            "evidence": "active means enabled = 1",
            "SQL": "SELECT name FROM items WHERE enabled = 1",
            "difficulty": "simple",
        }])
        self.database = self.root / "sample.sqlite"
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE items(name TEXT, enabled INTEGER)")
            connection.executemany("INSERT INTO items VALUES (?, ?)", [("A", 1), ("B", 0)])
            connection.commit()
        self.bundle = self.root / "bundle"

    def tearDown(self) -> None:
        copied_database = self.bundle / "database/database.sqlite"
        if copied_database.exists():
            copied_database.chmod(stat.S_IWRITE | stat.S_IREAD)
        self.temporary.cleanup()

    def _prepare(self) -> dict:
        return prepare_bundle(
            question_source=self.questions,
            sqlite_source=self.database,
            db_id="sample",
            question_id="7",
            bundle_dir=self.bundle,
        )

    def test_prepare_bundle_contains_only_public_fields_and_read_only_database(self) -> None:
        manifest = self._prepare()
        task = json.loads((self.bundle / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(set(task), {"question_id", "db_id", "question", "evidence"})
        self.assertNotIn("SQL", task)
        self.assertNotIn("difficulty", task)
        self.assertFalse(manifest["gold_present"])
        self.assertFalse((self.bundle / "database/database.sqlite").stat().st_mode & stat.S_IWRITE)
        self.assertTrue(audit_bundle(self.bundle)["safe"])

    def test_audit_rejects_extra_gold_file(self) -> None:
        self._prepare()
        (self.bundle / "gold.sql").write_text("SELECT 1", encoding="utf-8")
        with self.assertRaisesRegex(GoldIsolationError, "file set mismatch"):
            audit_bundle(self.bundle)

    def test_audit_rejects_task_tampering(self) -> None:
        self._prepare()
        task_path = self.bundle / "task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["SQL"] = "SELECT 1"
        _json(task_path, task)
        with self.assertRaises(GoldIsolationError):
            audit_bundle(self.bundle)

    def test_host_evaluation_requires_frozen_candidate_digest(self) -> None:
        manifest = self._prepare()
        candidate = self.root / "candidate.json"
        _json(candidate, {
            "schema_version": "0.1",
            "db_id": "sample",
            "question_id": 7,
            "predicted_sql": "SELECT name FROM items WHERE enabled = 1",
            "bundle_sha256": manifest["artifact_sha256"],
        })
        digest = self.root / "candidate.sha256"
        digest.write_text(hashlib.sha256(candidate.read_bytes()).hexdigest() + "\n", encoding="ascii")
        result = evaluate_candidate(
            bundle_dir=self.bundle,
            candidate_path=candidate,
            candidate_digest_path=digest,
            question_source=self.questions,
            sqlite_source=self.database,
            evaluation_dir=self.root / "evaluation",
        )
        self.assertTrue(result["correct"])
        self.assertEqual(result["evaluation_boundary"], "host-only-after-frozen-candidate")

        candidate.chmod(stat.S_IWRITE | stat.S_IREAD)
        candidate.write_text(candidate.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(GoldIsolationError, "candidate digest mismatch"):
            evaluate_candidate(
                bundle_dir=self.bundle,
                candidate_path=candidate,
                candidate_digest_path=digest,
                question_source=self.questions,
                sqlite_source=self.database,
                evaluation_dir=self.root / "evaluation-tampered",
            )

    def test_host_evaluation_rejects_candidate_database_mutation(self) -> None:
        manifest = self._prepare()
        candidate = self.root / "candidate.json"
        _json(candidate, {
            "schema_version": "0.1",
            "db_id": "sample",
            "question_id": 7,
            "predicted_sql": "DELETE FROM items",
            "bundle_sha256": manifest["artifact_sha256"],
        })
        digest = self.root / "candidate.sha256"
        digest.write_text(hashlib.sha256(candidate.read_bytes()).hexdigest() + "\n", encoding="ascii")
        with self.assertRaises(sqlite3.DatabaseError):
            evaluate_candidate(
                bundle_dir=self.bundle,
                candidate_path=candidate,
                candidate_digest_path=digest,
                question_source=self.questions,
                sqlite_source=self.database,
                evaluation_dir=self.root / "evaluation-mutation",
            )
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0], 2)

    def test_inference_config_disables_sql_few_shot(self) -> None:
        config_path = self.root / "agent.yaml"
        config_path.write_text("CORE:\n  generator:\n    icl_top_k: 3\n", encoding="utf-8")
        _enforce_zero_few_shot_config(config_path)
        self.assertIn("icl_top_k: 0", config_path.read_text(encoding="utf-8"))

    def test_isolated_runner_sets_provider_api_key(self) -> None:
        runner = RUNTIME.parent / "scripts" / "run_dataagent_bird_isolated.ps1"
        source = runner.read_text(encoding="utf-8")
        self.assertIn("-e DEEPSEEK_API_KEY=local-qwen", source)


if __name__ == "__main__":
    unittest.main()
