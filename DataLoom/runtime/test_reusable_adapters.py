"""Offline/probe tests for context governance and external adapters."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))
WORKSPACE = RUNTIME.parents[2]

from benchmark_router import BenchmarkRouter, RoutingError
from context_projection import ProjectionPolicy, project_search_matches
from external_adapters import DataAgentBirdAdapter, SignalPilotDbtAdapter
from orchestrator import DataLoomOrchestrator
from run_project_understanding_qwen import ReadOnlyRepository


class ProjectionTests(unittest.TestCase):
    def test_projection_preserves_evidence_coordinates_and_reports_truncation(self) -> None:
        matches = [{"path": f"src/{index}.py", "line": index + 1, "text": "x" * 50} for index in range(5)]
        result = project_search_matches(matches, ProjectionPolicy(max_items=2, max_chars=1000, max_item_chars=10))
        self.assertEqual(result["matches"][0]["path"], "src/0.py")
        self.assertEqual(result["matches"][0]["line"], 1)
        self.assertTrue(result["matches"][0]["text_truncated"])
        self.assertEqual(result["truncation"]["omitted_items"], 3)

    def test_native_qwen_repository_uses_bounded_search_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("\n".join(f"needle_{i}" for i in range(100)), encoding="utf-8")
            result = ReadOnlyRepository(root).grep("needle", limit=80)
            self.assertLessEqual(len(str(result)), 14000)
            self.assertTrue(result["truncation"]["truncated"])


class AdapterProbeTests(unittest.TestCase):
    def test_signalpilot_probe_and_filesystem_scan(self) -> None:
        adapter = SignalPilotDbtAdapter(WORKSPACE / "P4" / "SignalPilot")
        probe = adapter.probe()
        self.assertTrue(probe["available"])
        self.assertEqual(probe["license"], "Apache-2.0")
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "dbt_project.yml").write_text("name: sample\n", encoding="utf-8")
            result = adapter.scan(project)
            self.assertTrue(result["success"])
            self.assertIn("dbt Project Scan", result["observation"]["text"])

    def test_dataagent_bird_probe_without_importing_optional_dependencies(self) -> None:
        adapter = DataAgentBirdAdapter(WORKSPACE / "external" / "DataAgent")
        probe = adapter.probe(import_check=False)
        self.assertTrue(probe["available"])
        self.assertFalse(probe["import_check"]["attempted"])
        self.assertIn("bird_benchmark.run_bird", probe["interface"])
        self.assertEqual(probe["gold_isolation"]["status"], "BLOCKED")
        codes = {finding["code"] for finding in probe["gold_isolation"]["findings"]}
        self.assertEqual(
            codes,
            {"GOLD_FILE_BEFORE_INFERENCE", "FULL_QUESTION_BEFORE_INFERENCE", "FULL_QUESTION_COPIED_TO_WORKER"},
        )
        isolated = WORKSPACE / "external" / "DataAgent" / "runtime" / "dataagent" / ".venv-dataloom-bird"
        if isolated.is_dir():
            self.assertTrue(probe["isolated_environment"])


class RouterTests(unittest.TestCase):
    def test_routes_all_target_benchmarks(self) -> None:
        router = BenchmarkRouter()
        self.assertEqual(router.select("CodeAware").adapter, "dataloom-native-qwen")
        self.assertEqual(router.select("Spider-2.0-DBT").adapter, "signalpilot-dbt")
        self.assertEqual(router.select("BIRD").adapter, "dataagent-bird")
        with self.assertRaises(RoutingError):
            router.select("unknown")

    def test_orchestrator_exposes_pinned_reusable_capabilities(self) -> None:
        orchestrator = DataLoomOrchestrator()
        names = {item["name"] for item in orchestrator.registry.catalog()}
        self.assertEqual(names, {"project-understanding", "dbt-project-understanding", "nl2sql"})
        self.assertTrue(orchestrator.probe("spider2-dbt")["available"])
        self.assertTrue(orchestrator.probe("bird")["available"])


if __name__ == "__main__":
    unittest.main()
