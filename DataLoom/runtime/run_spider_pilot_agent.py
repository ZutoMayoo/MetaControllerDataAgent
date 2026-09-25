"""Container entrypoint for one frozen Spider2.0-DBT factorial condition."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/signalpilot/gateway")
sys.path.insert(0, "/runner")

from benchmark.agent.sdk_runner import run_sdk_agent
from spider_conditions import audit_observed_run, validate_condition_manifest


WORK = Path("/workspace/task")
MANIFEST = Path("/experiment/manifest.json")
OUTPUT = WORK / "dataloom_agent_output.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authorable_snapshot() -> dict[str, str]:
    return {
        path.relative_to(WORK).as_posix(): digest(path)
        for path in sorted(WORK.rglob("*"))
        if path.is_file()
        and not {"target", "logs", "dbt_packages"}.intersection(path.relative_to(WORK).parts)
        and path.suffix.casefold() in {".sql", ".yml", ".yaml"}
    }


async def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_condition_manifest(manifest)
    evidence_text = ""
    evidence_mounted = False
    if manifest["evidence"]:
        evidence_path = Path(manifest["evidence"]["path"])
        if digest(evidence_path) != manifest["evidence"]["sha256"]:
            raise RuntimeError("mounted evidence digest mismatch")
        evidence_text = evidence_path.read_text(encoding="utf-8")
        evidence_mounted = True

    injected = []
    skill_texts = []
    for skill in manifest["skills"]:
        path = Path(skill["path"])
        if digest(path) != skill["sha256"]:
            raise RuntimeError(f"mounted skill digest mismatch: {skill['name']}")
        injected.append(skill["name"])
        skill_texts.append(f"\n\n## Fixed procedural skill: {skill['name']}\n{path.read_text(encoding='utf-8')}")
    observed = {"evidence_mounted": evidence_mounted, "activated_skills": injected}
    audit_observed_run(manifest, observed)

    system_prompt = """You are the sole dbt implementation agent in an isolated benchmark task.
Use only the mounted public task project and task-local DuckDB. Do not access the web,
other tasks, benchmark evaluation code, Gold answers, logs, or prior candidates. Implement
the requested dbt models, run focused dbt builds/tests, and finish once the project output
is executable. Do not use or request dynamic skills; any allowed procedural guidance is
already included below. Do not modify the task instruction or database file.""" + "".join(skill_texts)
    prompt = f"Public instruction:\n{manifest['instruction']}\n"
    if evidence_text:
        prompt += f"\nHost-validated structured project evidence:\n{evidence_text}\n"
    else:
        prompt += "\nNo host-generated structured project evidence is provided in this condition. Inspect the public project yourself.\n"
    prompt += "\nComplete the dbt project in /workspace/task."

    before = authorable_snapshot()
    result = await run_sdk_agent(
        prompt, WORK, manifest["model"],
        max_turns=int(manifest["budget"]["max_turns"]),
        timeout=int(manifest["budget"]["timeout_seconds"]),
        label=f"dataloom-{manifest['condition'].lower()}-dbt-agent",
        system_prompt=system_prompt,
        tools=list(manifest["tool_policy"]["allowed"]),
        allowed_tools=list(manifest["tool_policy"]["allowed"]),
        disallowed_tools=list(manifest["tool_policy"]["disallowed"]),
        mcp_server_names=["signalpilot"],
        strict_mcp_config=True,
        disable_slash_commands=True,
        phase="SPIDER_PILOT",
        loop_breaker_enabled=True,
    )
    dynamic_skills = [call for call in result.get("tool_calls", []) if call.get("name") == "Skill"]
    if dynamic_skills:
        raise RuntimeError("dynamic Skill call bypassed condition policy")
    after = authorable_snapshot()
    changed = [
        {"path": path, "sha256": value, "change": "created" if path not in before else "modified"}
        for path, value in after.items() if before.get(path) != value
    ]
    removed = sorted(set(before) - set(after))
    output = {
        "run_id": manifest["run_id"], "task_id": manifest["task_id"],
        "condition": manifest["condition"], "manifest_sha256": manifest["manifest_sha256"],
        "observed_condition": observed, "success": bool(result.get("success")),
        "changed_files": changed, "removed_files": removed, "agent_result": result,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    candidate = {key: output[key] for key in ("run_id", "task_id", "condition", "manifest_sha256", "changed_files", "removed_files")}
    candidate_path = WORK / "candidate.json"
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    candidate_digest = digest(candidate_path)
    digest_path = WORK / "candidate.sha256"
    digest_path.write_text(candidate_digest + "\n", encoding="ascii")
    candidate_path.chmod(stat.S_IREAD)
    digest_path.chmod(stat.S_IREAD)
    return 0 if result.get("success") else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
