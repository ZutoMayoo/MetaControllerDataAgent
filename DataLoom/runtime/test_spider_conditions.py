from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))

from spider_conditions import ConditionError, audit_observed_run, build_condition_manifest


class SpiderConditionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence.json"
        self.evidence.write_text("{}", encoding="utf-8")
        self.skills = {}
        for name in ("dbt-workflow", "dbt-write", "duckdb-sql"):
            path = self.root / name / "SKILL.md"
            path.parent.mkdir()
            path.write_text(f"# {name}\n", encoding="utf-8")
            self.skills[name] = path

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, condition: str):
        return build_condition_manifest(
            run_id=f"pilot-{condition}", task_id="playbook001", condition_name=condition,
            model="qwen3.8-27b", instruction="Build result", project_digest="a" * 64,
            evidence_path=self.evidence if condition in {"S1", "S2"} else None,
            skill_paths=self.skills if condition in {"S2", "S3"} else {},
            max_turns=80, timeout_seconds=1800,
        )

    def test_four_conditions_are_exact_factorial(self) -> None:
        factors = {name: self.build(name)["factors"] for name in ("S0", "S1", "S2", "S3")}
        self.assertEqual(len({json.dumps(value, sort_keys=True) for value in factors.values()}), 4)

    def test_all_conditions_disable_dynamic_skill_tool(self) -> None:
        for name in ("S0", "S1", "S2", "S3"):
            manifest = self.build(name)
            self.assertNotIn("Skill", manifest["tool_policy"]["allowed"])
            self.assertIn("Skill", manifest["tool_policy"]["disallowed"])

    def test_observation_audit_rejects_contamination(self) -> None:
        manifest = self.build("S0")
        with self.assertRaises(ConditionError):
            audit_observed_run(manifest, {"evidence_mounted": False, "activated_skills": ["dbt-workflow"]})
        manifest = self.build("S2")
        with self.assertRaises(ConditionError):
            audit_observed_run(manifest, {"evidence_mounted": True, "activated_skills": ["dbt-workflow"]})
        audit_observed_run(
            manifest,
            {"evidence_mounted": True, "activated_skills": ["dbt-workflow", "dbt-write", "duckdb-sql"]},
        )


if __name__ == "__main__":
    unittest.main()
