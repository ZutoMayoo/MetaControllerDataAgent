"""Offline tests for reusable DataLoom runtime foundations."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))

from capabilities import Action, ActionRouter, CapabilityError, CapabilityManifest, CapabilityRegistry
from contracts import canonical_json_sha256, evidence_readiness, sha256_file
from protocols import HandoffRecord, ProtocolError
from skill_loader import SkillError, SkillLoader
from workspace_guard import WorkspaceGuard, WorkspaceViolation


class CapabilityTests(unittest.TestCase):
    def test_dependencies_are_resolved_before_dependants(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilityManifest("evidence", "1", (Action("collect", lambda p: p),)))
        registry.register(CapabilityManifest("sql", "1", (Action("generate", lambda p: p),), ("evidence",)))
        self.assertEqual([item.name for item in registry.resolve(["sql"])], ["evidence", "sql"])

    def test_duplicate_actions_are_rejected(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilityManifest("one", "1", (Action("run", lambda p: p),)))
        with self.assertRaisesRegex(CapabilityError, "already registered"):
            registry.register(CapabilityManifest("two", "1", (Action("run", lambda p: p),)))

    def test_router_enforces_scope_guard_and_idempotency(self) -> None:
        calls: list[int] = []
        def positive(payload):
            if payload["value"] <= 0:
                raise CapabilityError("value must be positive")
        registry = CapabilityRegistry()
        registry.register(CapabilityManifest("math", "1", (Action(
            "double", lambda p: calls.append(p["value"]) or p["value"] * 2,
            guards=(positive,), required_scopes=frozenset({"execute"}),
        ),)))
        router = ActionRouter(registry)
        with self.assertRaisesRegex(CapabilityError, "missing scopes"):
            router.dispatch("double", {"value": 2})
        first = router.dispatch("double", {"value": 2}, scopes={"execute"}, idempotency_key="x")
        second = router.dispatch("double", {"value": 2}, scopes={"execute"}, idempotency_key="x")
        self.assertEqual(first["observation"], 4)
        self.assertTrue(second["replayed"])
        self.assertEqual(calls, [2])


class SkillAndWorkspaceTests(unittest.TestCase):
    def test_skill_allowlist_and_hash_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("trusted", "ignored"):
                (root / name).mkdir()
                (root / name / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: test\n---\n# {name}\n", encoding="utf-8"
                )
            loaded = SkillLoader(root, {"trusted"}).activate(["trusted"])
            self.assertEqual(loaded[0].name, "trusted")
            self.assertEqual(len(loaded[0].sha256), 64)
            with self.assertRaises(SkillError):
                SkillLoader(root, {"trusted"}).activate(["ignored"])

    def test_parent_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guard = WorkspaceGuard(Path(directory))
            with self.assertRaises(WorkspaceViolation):
                guard.resolve("../secret.txt", must_exist=False)


class ProtocolTests(unittest.TestCase):
    def _package(self, root: Path, ready: bool = True) -> dict:
        source = root / "policy.py"
        source.write_text("def decide(x):\n    return x > 0\n", encoding="utf-8")
        package = {
            "schema_version": "0.2", "task_id": "task-1", "repository_revision": "rev",
            "rules": [{
                "rule_id": "decision", "claim": "positive values pass",
                "status": "SUPPORTED" if ready else "UNRESOLVED", "criticality": "CORE",
                "source_refs": [{
                    "path": "policy.py", "sha256": sha256_file(source), "line_start": 1, "line_end": 2,
                    "symbol": "decide", "evidence_kind": "PRODUCTION_CODE",
                    "supports": "DECISION_IMPLEMENTATION",
                }],
                "decision_semantics": {
                    "inputs": [{"name": "x", "role": "SUBJECT", "fields": ["value"]}],
                    "predicate": "x > 0", "boundary_behavior": "zero is rejected",
                },
                "database_mapping": [],
            }],
            "unresolved_questions": [], "producer": {"role": "test"},
        }
        package["readiness"] = evidence_readiness(package)
        package["artifact_sha256"] = canonical_json_sha256(package)
        return package

    def test_ready_handoff_and_stale_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = HandoffRecord("task-1")
            package = self._package(Path(directory))
            record.submit_evidence(package, expected_revision=0)
            self.assertEqual(record.state, "SQL_GENERATION")
            with self.assertRaisesRegex(ProtocolError, "stale evidence"):
                record.complete_sql(evidence_sha256="wrong", expected_revision=1)
            record.complete_sql(evidence_sha256=package["artifact_sha256"], expected_revision=1)
            self.assertEqual(record.state, "COMPLETE")

    def test_incomplete_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = HandoffRecord("task-1")
            with self.assertRaisesRegex(ProtocolError, "INCOMPLETE"):
                record.submit_evidence(self._package(Path(directory), ready=False), expected_revision=0)


if __name__ == "__main__":
    unittest.main()
