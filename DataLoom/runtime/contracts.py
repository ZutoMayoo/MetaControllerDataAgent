"""Minimal, dependency-free DataLoom contract validation for M1.

This module deliberately validates provenance before any candidate SQL is
generated.  It contains no evaluator or gold-answer loading path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.1"
RULE_STATUSES = {"SUPPORTED", "INFERRED", "UNRESOLVED", "CONFLICTING"}


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
    for field in ("schema_version", "task_id", "repository_revision", "rules", "unresolved_questions", "producer"):
        _require(package.get(field), field)
    if package["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"unsupported EvidencePackage schema: {package['schema_version']}")
    if not isinstance(package["rules"], list):
        raise ContractError("rules must be a list")

    for index, rule in enumerate(package["rules"]):
        if not isinstance(rule, dict):
            raise ContractError(f"rules[{index}] must be an object")
        for field in ("rule_id", "claim", "status", "database_mapping"):
            _require(rule.get(field), f"rules[{index}].{field}")
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
