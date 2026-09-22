"""Gold-free, read-only Code-aware Project Understanding runner.

This runner is deliberately small: the model can inspect only a frozen source
tree with Read/Glob/Grep.  The host controller supplies source hashes after the
model identifies its file and line evidence, then validates the resulting
EvidencePackage using the M1 contract.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from contracts import canonical_json_sha256, evidence_readiness, sha256_file, validate_evidence_package


def _last_json_object(messages: list[str]) -> dict[str, Any]:
    """Parse the last JSON object emitted by a model without accepting prose."""
    combined = "\n".join(messages).strip()
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", combined):
        try:
            value, _ = decoder.raw_decode(combined[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        raise ValueError("model did not emit a JSON object")
    return candidates[-1]


def _canonical_relative(path: str, repository: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"source path escapes frozen repository: {path!r}")
    resolved = (repository / candidate).resolve()
    try:
        resolved.relative_to(repository.resolve())
    except ValueError as exc:
        raise ValueError(f"source path escapes frozen repository: {path!r}") from exc
    if not resolved.is_file():
        raise ValueError(f"cited source is not a file: {path!r}")
    return resolved


def _enrich_and_validate(package: dict[str, Any], repository: Path, task_id: str, revision: str) -> dict[str, Any]:
    """Attach deterministic file hashes; reject malformed model evidence."""
    package = dict(package)
    package["schema_version"] = "0.2"
    package["task_id"] = task_id
    package["repository_revision"] = revision
    package.setdefault("unresolved_questions", [])
    package.setdefault("producer", {"role": "project-understanding", "model": os.environ.get("DATALOOM_MODEL", "unknown")})
    if not isinstance(package.get("producer"), dict):
        raise ValueError("producer must be an object")
    rules = package.get("rules")
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("each rule must be an object")
        references = rule.get("source_refs", [])
        if not isinstance(references, list):
            raise ValueError("source_refs must be a list")
        for reference in references:
            if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
                raise ValueError("each source reference needs a relative path")
            source = _canonical_relative(reference["path"], repository)
            reference["path"] = source.relative_to(repository).as_posix()
            reference["sha256"] = sha256_file(source)
    package["readiness"] = evidence_readiness(package)
    package.pop("artifact_sha256", None)
    package["artifact_sha256"] = canonical_json_sha256(package)
    validate_evidence_package(package, repository)
    return package


async def run(prompt: str, repository: Path, model: str, max_turns: int, progress: Path) -> tuple[list[str], list[dict[str, Any]]]:
    options = ClaudeAgentOptions(
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        cwd=str(repository),
        tools=["Read", "Glob", "Grep"],
        allowed_tools=["Read", "Glob", "Grep"],
        disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"],
        extra_args={"disable-slash-commands": None},
    )
    messages: list[str] = []
    transcript: list[dict[str, Any]] = []
    progress.write_text('{"stage":"before_query"}', encoding="utf-8")
    stream = query(prompt=prompt, options=options)
    progress.write_text('{"stage":"stream_created"}', encoding="utf-8")
    async for event in stream:
        progress.write_text(json.dumps({"stage": "event", "type": type(event).__name__}), encoding="utf-8")
        if isinstance(event, AssistantMessage):
            for block in event.content:
                if isinstance(block, TextBlock):
                    messages.append(block.text)
                    transcript.append({"type": "text", "content": block.text})
                else:
                    transcript.append({"type": type(block).__name__})
    return messages, transcript


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-spec", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--skill", type=Path, action="append", default=[],
                        help="trusted project-understanding SKILL.md to inject")
    args = parser.parse_args()
    spec = json.loads(args.task_spec.read_text(encoding="utf-8"))
    extension = spec["extensions"]
    repository = args.repository
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    (output / "runner_started.json").write_text(json.dumps({
        "role": "project-understanding", "model": args.model,
        "repository": str(repository),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = args.prompt.read_text(encoding="utf-8").replace(
        str(extension["repository_root"]), str(repository)
    )
    skill_records = []
    for skill_path in args.skill:
        skill_text = skill_path.read_text(encoding="utf-8")
        skill_records.append({"path": str(skill_path), "sha256": hashlib.sha256(skill_text.encode("utf-8")).hexdigest()})
        prompt += f"\n\nSelected project-understanding skill:\n{skill_text}"
    started = datetime.now(timezone.utc).isoformat()
    try:
        messages, transcript = asyncio.run(run(
            prompt, repository, args.model, args.max_turns, output / "sdk_progress.json"
        ))
    except Exception as exc:
        (output / "failure.json").write_text(json.dumps({
            "role": "project-understanding", "started_at": started,
            "model": args.model, "error_type": type(exc).__name__, "error": str(exc),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    (output / "role_audit.json").write_text(json.dumps({
        "role": "project-understanding", "started_at": started,
        "model": args.model, "allowed_tools": ["Read", "Glob", "Grep"], "skills": skill_records,
        "transcript": transcript,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "raw_model_messages.json").write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    package = _enrich_and_validate(messages and _last_json_object(messages), repository, spec["task_id"], extension["repository_revision"])
    (output / "evidence_package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "run_manifest.json").write_text(json.dumps({
        "run_id": output.name, "task_id": spec["task_id"], "condition": "D",
        "model": {"id": args.model}, "budget": {"max_turns": args.max_turns},
        "source_hashes": {"task_spec_sha256": hashlib.sha256(args.task_spec.read_bytes()).hexdigest()},
        "artifacts": ["role_audit.json", "raw_model_messages.json", "evidence_package.json"],
        "evaluation_feedback_available_during_inference": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
