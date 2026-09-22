"""Minimal, dependency-free DataLoom contract validation for M1.

This module deliberately validates provenance before any candidate SQL is
generated.  It contains no evaluator or gold-answer loading path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.2"
SUPPORTED_SCHEMA_VERSIONS = {"0.1", SCHEMA_VERSION}
RULE_STATUSES = {"SUPPORTED", "INFERRED", "UNRESOLVED", "CONFLICTING"}
EVIDENCE_KINDS = {"PRODUCTION_CODE", "TEST", "UI", "CONFIGURATION", "DOCUMENTATION"}
EVIDENCE_SUPPORTS = {
    "DECISION_IMPLEMENTATION",
    "SCHEMA_MAPPING",
    "BEHAVIORAL_EXAMPLE",
    "CONFIGURATION_SURFACE",
}
RULE_CRITICALITIES = {"CORE", "SUPPORTING"}
INPUT_ROLES = {"SUBJECT", "EXISTING_STATE", "CONFIGURATION", "CONTEXT"}
READINESS_STATUSES = {"READY", "INCOMPLETE"}


class ContractError(ValueError):
    """Raised when an artifact does not meet the M0 public contract."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require(value: Any, label: str) -> None:
    if value is None or value == "" or value == []:
        raise ContractError(f"missing required field: {label}")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_evidence_package(package: dict[str, Any], repository_root: Path) -> None:
    """Validate source provenance and rule status semantics.

    A SUPPORTED rule is accepted only when every cited source file is inside the
    frozen repository, has an exact hash, and has a valid one-based line range.
    """
    for field in ("schema_version", "task_id", "repository_revision", "rules", "producer"):
        _require(package.get(field), field)
    if "unresolved_questions" not in package or not isinstance(package["unresolved_questions"], list):
        raise ContractError("unresolved_questions must be a list")
    if package["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise ContractError(f"unsupported EvidencePackage schema: {package['schema_version']}")
    if not isinstance(package["rules"], list):
        raise ContractError("rules must be a list")

    for index, rule in enumerate(package["rules"]):
        if not isinstance(rule, dict):
            raise ContractError(f"rules[{index}] must be an object")
        for field in ("rule_id", "claim", "status"):
            _require(rule.get(field), f"rules[{index}].{field}")
        if "database_mapping" not in rule or not isinstance(rule["database_mapping"], list):
            raise ContractError(f"rules[{index}].database_mapping must be a list")
        status = rule["status"]
        if status not in RULE_STATUSES:
            raise ContractError(f"rules[{index}] has invalid status: {status}")
        refs = rule.get("source_refs")
        if refs is None:
            raise ContractError(f"missing required field: rules[{index}].source_refs")
        if not isinstance(refs, list):
            raise ContractError(f"rules[{index}].source_refs must be a list")
        if status == "SUPPORTED" and not refs:
            raise ContractError(f"SUPPORTED rule {rule['rule_id']} has no source reference")
        for ref_index, ref in enumerate(refs):
            _validate_source_ref(ref, repository_root, f"rules[{index}].source_refs[{ref_index}]")

    if package["schema_version"] == SCHEMA_VERSION:
        _validate_v02_quality_gate(package)

    without_digest = dict(package)
    recorded = without_digest.pop("artifact_sha256", None)
    if recorded and recorded != canonical_json_sha256(without_digest):
        raise ContractError("artifact_sha256 does not match canonical EvidencePackage content")


def _validate_source_ref(reference: dict[str, Any], repository_root: Path, label: str) -> None:
    if not isinstance(reference, dict):
        raise ContractError(f"{label} must be an object")
    for field in ("path", "sha256", "line_start", "line_end"):
        _require(reference.get(field), f"{label}.{field}")
    relative = Path(str(reference["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError(f"{label}.path escapes repository")
    source = repository_root / relative
    if not _inside(source, repository_root) or not source.is_file():
        raise ContractError(f"{label}.path is not a repository file: {relative}")
    if reference["sha256"] != sha256_file(source):
        raise ContractError(f"{label}.sha256 does not match {relative}")
    line_start = reference["line_start"]
    line_end = reference["line_end"]
    if not isinstance(line_start, int) or not isinstance(line_end, int) or line_start < 1 or line_end < line_start:
        raise ContractError(f"{label} has invalid line range")
    line_count = len(source.read_text(encoding="utf-8", errors="replace").splitlines())
    if line_end > line_count:
        raise ContractError(f"{label}.line_end exceeds source length")


def evidence_readiness(package: dict[str, Any]) -> dict[str, Any]:
    """Derive whether evidence is safe to hand to a downstream reasoning role.

    The result is structural and deterministic. It does not decide whether a
    model found every rule in a repository; the tracing skill remains
    responsible for discovery. It prevents test/UI-only claims or vague prose
    from being represented as production-grounded decision evidence.
    """
    blockers: list[dict[str, str]] = []
    rules = package.get("rules", [])
    core_rules = [rule for rule in rules if isinstance(rule, dict) and rule.get("criticality") == "CORE"]
    if not core_rules:
        blockers.append({"code": "NO_CORE_RULE", "rule_id": ""})
    for rule in core_rules:
        rule_id = str(rule.get("rule_id", ""))
        if rule.get("status") != "SUPPORTED":
            blockers.append({"code": "CORE_RULE_NOT_SUPPORTED", "rule_id": rule_id})
        refs = rule.get("source_refs", [])
        if not any(
            isinstance(ref, dict)
            and ref.get("evidence_kind") == "PRODUCTION_CODE"
            and ref.get("supports") == "DECISION_IMPLEMENTATION"
            for ref in refs
        ):
            blockers.append({"code": "NO_PRODUCTION_DECISION_EVIDENCE", "rule_id": rule_id})
        semantics = rule.get("decision_semantics")
        if not _complete_decision_semantics(semantics):
            blockers.append({"code": "INCOMPLETE_DECISION_SEMANTICS", "rule_id": rule_id})
    return {"status": "INCOMPLETE" if blockers else "READY", "blockers": blockers}


def _complete_decision_semantics(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not all(isinstance(value.get(key), str) and value[key].strip() for key in ("predicate", "boundary_behavior")):
        return False
    inputs = value.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        return False
    for item in inputs:
        if not isinstance(item, dict):
            return False
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            return False
        if item.get("role") not in INPUT_ROLES:
            return False
        fields = item.get("fields")
        if not isinstance(fields, list) or not fields or not all(isinstance(field, str) and field.strip() for field in fields):
            return False
    return True


def _validate_v02_quality_gate(package: dict[str, Any]) -> None:
    for index, rule in enumerate(package["rules"]):
        criticality = rule.get("criticality")
        if criticality not in RULE_CRITICALITIES:
            raise ContractError(f"rules[{index}] has invalid or missing criticality")
        for ref_index, ref in enumerate(rule["source_refs"]):
            if ref.get("evidence_kind") not in EVIDENCE_KINDS:
                raise ContractError(f"rules[{index}].source_refs[{ref_index}] has invalid or missing evidence_kind")
            if ref.get("supports") not in EVIDENCE_SUPPORTS:
                raise ContractError(f"rules[{index}].source_refs[{ref_index}] has invalid or missing supports")
            if (
                rule.get("status") == "SUPPORTED"
                and ref.get("evidence_kind") == "PRODUCTION_CODE"
                and ref.get("supports") == "DECISION_IMPLEMENTATION"
            ):
                if not isinstance(ref.get("symbol"), str) or not ref["symbol"].strip():
                    raise ContractError(f"rules[{index}].source_refs[{ref_index}] production decision evidence needs a symbol")
                normalized_path = str(ref.get("path", "")).replace("\\", "/").casefold()
                path_parts = normalized_path.split("/")
                filename = path_parts[-1]
                if (
                    any(part in {"test", "tests", "__tests__", "spec", "specs"} for part in path_parts[:-1])
                    or filename.startswith("test_")
                    or ".test." in filename
                    or ".spec." in filename
                ):
                    raise ContractError(
                        f"rules[{index}].source_refs[{ref_index}] test path cannot be classified as production decision evidence"
                    )
        semantics = rule.get("decision_semantics")
        if semantics is not None and not _complete_decision_semantics(semantics):
            raise ContractError(f"rules[{index}].decision_semantics is incomplete")

    readiness = package.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("status") not in READINESS_STATUSES:
        raise ContractError("v0.2 EvidencePackage requires readiness.status")
    derived = evidence_readiness(package)
    if readiness != derived:
        raise ContractError("readiness does not match the deterministic quality gate")


def require_ready_for_handoff(package: dict[str, Any]) -> None:
    """Reject legacy or incomplete evidence before SQL generation."""
    if package.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"SQL handoff requires EvidencePackage {SCHEMA_VERSION}")
    readiness = package.get("readiness")
    if readiness != evidence_readiness(package):
        raise ContractError("EvidencePackage readiness is not controller-derived")
    if not isinstance(readiness, dict) or readiness.get("status") != "READY":
        raise ContractError("EvidencePackage is INCOMPLETE and cannot be handed to SQL generation")
