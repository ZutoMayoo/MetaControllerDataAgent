"""Auditable 2x2 condition isolation for Spider2.0-DBT pilots."""

from __future__ import annotations

import hashlib
import json
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConditionError(ValueError):
    pass


@dataclass(frozen=True)
class SpiderCondition:
    name: str
    structured_evidence: bool
    dbt_skills: bool


CONDITIONS = {
    "S0": SpiderCondition("S0", False, False),
    "S1": SpiderCondition("S1", True, False),
    "S2": SpiderCondition("S2", True, True),
    "S3": SpiderCondition("S3", False, True),
}
ALLOWED_DBT_SKILLS = ("dbt-workflow", "dbt-write", "duckdb-sql")
BASE_TOOLS = ("Read", "Bash", "Write", "Edit")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_condition_manifest(
    *, run_id: str, task_id: str, condition_name: str, model: str,
    instruction: str, project_digest: str, evidence_path: Path | None, skill_paths: dict[str, Path],
    max_turns: int, timeout_seconds: int,
) -> dict[str, Any]:
    condition = CONDITIONS.get(condition_name)
    if condition is None:
        raise ConditionError(f"unknown condition: {condition_name}")
    if condition.structured_evidence != (evidence_path is not None):
        raise ConditionError("evidence path does not match condition")
    if condition.dbt_skills != bool(skill_paths):
        raise ConditionError("skill paths do not match condition")
    if set(skill_paths) - set(ALLOWED_DBT_SKILLS):
        raise ConditionError("untrusted dbt skill requested")
    evidence = None
    if evidence_path is not None:
        evidence = {
            "path": "/experiment/evidence.json",
            "sha256": _sha256(evidence_path.resolve(strict=True)),
        }
    skills = [
        {"name": name, "path": f"/experiment/skills/{name}/SKILL.md", "sha256": _sha256(path.resolve(strict=True))}
        for name, path in sorted(skill_paths.items())
    ]
    # Skills are host-injected from the exact hashed files below. Dynamic Skill
    # discovery stays disabled in every condition so no undeclared plugin can
    # contaminate the factor comparison.
    tools = list(BASE_TOOLS)
    disallowed = ["Skill", "Agent", "Task", "WebFetch", "WebSearch", "AskUserQuestion"]
    manifest = {
        "schema_version": "spider-condition-0.1",
        "run_id": run_id,
        "task_id": task_id,
        "instruction": instruction,
        "public_input_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "condition": condition.name,
        "factors": {
            "structured_project_evidence": condition.structured_evidence,
            "dbt_skills": condition.dbt_skills,
        },
        "model": model,
        "project_digest": project_digest,
        "evidence": evidence,
        "skills": skills,
        "tool_policy": {"allowed": tools, "disallowed": disallowed},
        "budget": {"max_turns": max_turns, "timeout_seconds": timeout_seconds},
        "evaluation_feedback_available_during_inference": False,
    }
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    validate_condition_manifest(manifest)
    return manifest


def validate_condition_manifest(manifest: dict[str, Any]) -> None:
    condition = CONDITIONS.get(str(manifest.get("condition")))
    if condition is None:
        raise ConditionError("manifest has unknown condition")
    instruction = manifest.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ConditionError("manifest instruction is missing")
    if manifest.get("public_input_sha256") != hashlib.sha256(instruction.encode("utf-8")).hexdigest():
        raise ConditionError("manifest instruction digest mismatch")
    factors = manifest.get("factors", {})
    if factors != {
        "structured_project_evidence": condition.structured_evidence,
        "dbt_skills": condition.dbt_skills,
    }:
        raise ConditionError("condition factor mismatch")
    evidence = manifest.get("evidence")
    skills = manifest.get("skills")
    policy = manifest.get("tool_policy", {})
    if bool(evidence) != condition.structured_evidence:
        raise ConditionError("condition evidence mismatch")
    if bool(skills) != condition.dbt_skills:
        raise ConditionError("condition skill mismatch")
    if condition.dbt_skills:
        names = {item.get("name") for item in skills}
        if not names or names - set(ALLOWED_DBT_SKILLS):
            raise ConditionError("skill audit list is invalid")
    if "Skill" in policy.get("allowed", []) or "Skill" not in policy.get("disallowed", []):
        raise ConditionError("dynamic Skill tool must stay disabled")
    recorded = manifest.get("manifest_sha256")
    body = dict(manifest)
    body.pop("manifest_sha256", None)
    actual = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if recorded != actual:
        raise ConditionError("condition manifest digest mismatch")


def audit_observed_run(manifest: dict[str, Any], observed: dict[str, Any]) -> None:
    """Fail closed when actual mounts or Skill calls differ from the frozen condition."""
    validate_condition_manifest(manifest)
    expected_evidence = bool(manifest["evidence"])
    if bool(observed.get("evidence_mounted")) != expected_evidence:
        raise ConditionError("observed evidence mount differs from manifest")
    expected = {item["name"] for item in manifest["skills"]}
    activated = set(observed.get("activated_skills", []))
    if activated - expected:
        raise ConditionError("unapproved Skill activation observed")
    if expected and activated != expected:
        raise ConditionError("declared Skill was not activated")
    if not expected and activated:
        raise ConditionError("Skill activation observed in no-skill condition")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="qwen3.8-27b")
    parser.add_argument("--max-turns", type=int, default=80)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    if evidence.get("task_id") != args.task_id:
        raise ConditionError("evidence task id mismatch")
    skill_paths = {name: args.skill_root / name / "SKILL.md" for name in ALLOWED_DBT_SKILLS}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in CONDITIONS:
        manifest = build_condition_manifest(
            run_id=f"spider-pilot-{args.task_id}-{name.lower()}",
            task_id=args.task_id,
            condition_name=name,
            model=args.model,
            instruction=evidence["instruction"],
            project_digest=evidence["project_digest"],
            evidence_path=args.evidence if name in {"S1", "S2"} else None,
            skill_paths=skill_paths if name in {"S2", "S3"} else {},
            max_turns=args.max_turns,
            timeout_seconds=args.timeout_seconds,
        )
        path = args.output_dir / f"{name}.manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
