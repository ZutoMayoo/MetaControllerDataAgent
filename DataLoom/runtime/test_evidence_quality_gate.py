"""Regression tests for the EvidencePackage 0.2 production-evidence gate."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))

from contracts import (  # noqa: E402
    ContractError,
    canonical_json_sha256,
    evidence_readiness,
    require_ready_for_handoff,
    sha256_file,
    validate_evidence_package,
)


class EvidenceQualityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name)
        (self.repository / "src").mkdir()
        (self.repository / "tests").mkdir()
        (self.repository / "src" / "policy.py").write_text(
            "def eligible(record, policy):\n"
            "    return record.active and record.score >= policy.minimum\n",
            encoding="utf-8",
        )
        (self.repository / "tests" / "test_policy.py").write_text(
            "def test_eligible():\n"
            "    assert eligible(active_record, policy)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _package(self, evidence_kind: str, supports: str, source: str) -> dict:
        source_path = self.repository / source
        package = {
            "schema_version": "0.2",
            "task_id": "SYNTHETIC-ELIGIBILITY-001",
            "repository_revision": "synthetic-revision",
            "rules": [
                {
                    "rule_id": "eligibility-policy",
                    "claim": "Eligibility is decided from record state and configured policy.",
                    "status": "SUPPORTED",
                    "criticality": "CORE",
                    "source_refs": [
                        {
                            "path": source,
                            "sha256": sha256_file(source_path),
                            "line_start": 1,
                            "line_end": 2,
                            "symbol": "eligible",
                            "evidence_kind": evidence_kind,
                            "supports": supports,
                        }
                    ],
                    "decision_semantics": {
                        "inputs": [
                            {"name": "record", "role": "SUBJECT", "fields": ["active", "score"]},
                            {"name": "policy", "role": "CONFIGURATION", "fields": ["minimum"]},
                        ],
                        "predicate": "record.active and record.score >= policy.minimum",
                        "boundary_behavior": "a score equal to the minimum is accepted",
                    },
                    "database_mapping": [
                        {"relation": "records", "fields": ["active", "score"]},
                        {"relation": "policies", "fields": ["minimum"]},
                    ],
                }
            ],
            "unresolved_questions": [],
            "producer": {"role": "project-understanding", "adapter": "test"},
        }
        package["readiness"] = evidence_readiness(package)
        package["artifact_sha256"] = canonical_json_sha256(package)
        return package

    def test_production_decision_evidence_is_ready_for_handoff(self) -> None:
        package = self._package("PRODUCTION_CODE", "DECISION_IMPLEMENTATION", "src/policy.py")
        validate_evidence_package(package, self.repository)
        require_ready_for_handoff(package)
        self.assertEqual(package["readiness"], {"status": "READY", "blockers": []})

    def test_test_only_core_rule_is_retained_but_blocked(self) -> None:
        package = self._package("TEST", "BEHAVIORAL_EXAMPLE", "tests/test_policy.py")
        validate_evidence_package(package, self.repository)
        with self.assertRaisesRegex(ContractError, "INCOMPLETE"):
            require_ready_for_handoff(package)
        self.assertIn(
            {"code": "NO_PRODUCTION_DECISION_EVIDENCE", "rule_id": "eligibility-policy"},
            package["readiness"]["blockers"],
        )

    def test_model_cannot_override_derived_readiness(self) -> None:
        package = self._package("TEST", "BEHAVIORAL_EXAMPLE", "tests/test_policy.py")
        package["readiness"] = {"status": "READY", "blockers": []}
        package["artifact_sha256"] = canonical_json_sha256({key: value for key, value in package.items() if key != "artifact_sha256"})
        with self.assertRaisesRegex(ContractError, "deterministic quality gate"):
            validate_evidence_package(package, self.repository)
        with self.assertRaisesRegex(ContractError, "not controller-derived"):
            require_ready_for_handoff(package)

    def test_test_path_cannot_be_mislabeled_as_production(self) -> None:
        package = self._package("PRODUCTION_CODE", "DECISION_IMPLEMENTATION", "tests/test_policy.py")
        with self.assertRaisesRegex(ContractError, "test path cannot be classified"):
            validate_evidence_package(package, self.repository)

    def test_legacy_package_remains_valid_but_cannot_reenter_sql_pipeline(self) -> None:
        package = self._package("PRODUCTION_CODE", "DECISION_IMPLEMENTATION", "src/policy.py")
        package["schema_version"] = "0.1"
        package.pop("readiness")
        for rule in package["rules"]:
            rule.pop("criticality")
            rule.pop("decision_semantics")
            for reference in rule["source_refs"]:
                reference.pop("evidence_kind")
                reference.pop("supports")
        package["artifact_sha256"] = canonical_json_sha256({key: value for key, value in package.items() if key != "artifact_sha256"})
        validate_evidence_package(package, self.repository)
        with self.assertRaisesRegex(ContractError, "requires EvidencePackage 0.2"):
            require_ready_for_handoff(package)


if __name__ == "__main__":
    unittest.main()
