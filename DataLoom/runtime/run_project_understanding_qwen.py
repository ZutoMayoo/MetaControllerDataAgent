"""Native-Qwen fallback for the gold-free Project Understanding role.

The existing Claude Agent SDK image is reused first.  This adapter is used only
when that SDK cannot complete a Qwen-compatible session.  It exposes exactly
three deterministic, repository-confined read tools to the model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts import canonical_json_sha256, evidence_readiness, sha256_file, validate_evidence_package


TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb", ".php", ".cs", ".sql", ".md", ".yml", ".yaml", ".json"}
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", ".venv", "__pycache__"}


def inside(path: str, root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path must be repository-relative")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("path escapes repository") from exc
    return resolved


class ReadOnlyRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _files(self):
        for path in self.root.rglob("*"):
            if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                continue
            if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES:
                yield path

    def read_file(self, path: str, line_start: int = 1, line_end: int = 240) -> dict[str, Any]:
        source = inside(path, self.root)
        if not source.is_file() or source.suffix.casefold() not in TEXT_SUFFIXES:
            raise ValueError("requested path is not an allowed text source file")
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(line_start)); end = min(len(lines), max(start, int(line_end)))
        return {"path": source.relative_to(self.root).as_posix(), "line_start": start, "line_end": end,
                "content": "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))}

    def glob(self, pattern: str, limit: int = 100) -> dict[str, Any]:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError("glob pattern escapes repository")
        paths = []
        for path in self.root.glob(pattern):
            if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                continue
            if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES:
                paths.append(path.relative_to(self.root).as_posix())
        return {"paths": sorted(paths)[:max(1, min(int(limit), 100))]}

    def grep(self, query: str, path_glob: str = "**/*", limit: int = 80) -> dict[str, Any]:
        if len(query) > 300:
            raise ValueError("query is too long")
        expression = re.compile(query, re.I)
        matches = []
        for path in self.root.glob(path_glob):
            if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                continue
            if not path.is_file() or path.suffix.casefold() not in TEXT_SUFFIXES:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if expression.search(line):
                    matches.append({"path": path.relative_to(self.root).as_posix(), "line": line_number, "text": line[:500]})
                    if len(matches) >= max(1, min(int(limit), 80)):
                        return {"matches": matches}
        return {"matches": matches}


TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read inclusive one-based lines from a repository source file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "line_start": {"type": "integer"}, "line_end": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "glob", "description": "List repository source files matching a relative glob pattern.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "grep", "description": "Regex-search repository source files and return matching lines.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "path_glob": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
]


def invoke(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_final(messages: list[dict[str, Any]]) -> dict[str, Any]:
    content = "\n".join(str(message.get("content") or "") for message in messages if message.get("role") == "assistant")
    decoder = json.JSONDecoder(); values = []
    for match in re.finditer(r"\{", content):
        try:
            value, _ = decoder.raw_decode(content[match.start():])
            if isinstance(value, dict): values.append(value)
        except json.JSONDecodeError:
            pass
    if not values:
        raise ValueError("model did not emit a JSON EvidencePackage")
    for value in reversed(values):
        if isinstance(value.get("rules"), list):
            return value
    raise ValueError("model JSON did not contain a rules list")


def normalize_model_package(value: dict[str, Any]) -> dict[str, Any]:
    """Losslessly map common model aliases to the public EvidencePackage shape.

    This is a schema adapter, not an evidence generator: it only renames fields,
    parses explicit line ranges, and preserves model-provided claims and paths.
    """
    normalized: dict[str, Any] = {key: value[key] for key in
                                  ("schema_version", "task_id", "repository_revision", "producer")
                                  if key in value}
    unresolved = list(value.get("unresolved_questions", [])) if isinstance(value.get("unresolved_questions", []), list) else []
    rules = value.get("rules")
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    converted = []
    for raw in rules:
        if not isinstance(raw, dict):
            raise ValueError("rule must be an object")
        refs = raw.get("source_refs", raw.get("evidence", []))
        if not isinstance(refs, list):
            raise ValueError("rule evidence must be a list")
        source_refs = []
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError("evidence reference must be an object")
            line_start, line_end = ref.get("line_start"), ref.get("line_end")
            if line_start is None or line_end is None:
                lines = ref.get("lines", "")
                if isinstance(lines, list) and len(lines) == 2 and all(isinstance(item, int) for item in lines):
                    line_start, line_end = lines
                else:
                    match = re.fullmatch(r"\s*(\d+)\s*(?:-|–|—)\s*(\d+)\s*", str(lines))
                    if not match:
                        raise ValueError("evidence reference needs an explicit line range")
                    line_start, line_end = int(match.group(1)), int(match.group(2))
            source_ref = {"path": ref.get("path"), "line_start": line_start, "line_end": line_end}
            for key in ("symbol", "evidence_kind", "supports"):
                if isinstance(ref.get(key), str):
                    source_ref[key] = ref[key]
            source_refs.append(source_ref)
        mappings = raw.get("database_mapping", raw.get("db_mapping", raw.get("schema_mapping", [])))
        if mappings is None:
            mappings = []
        if isinstance(mappings, dict):
            mappings = [mappings]
        if not isinstance(mappings, list):
            raise ValueError("database mapping must be an object or list")
        database_mapping = []
        for item in mappings:
            if not isinstance(item, dict):
                continue
            relations = item.get("relations", [item.get("relation")])
            if isinstance(relations, str): relations = [relations]
            if not isinstance(relations, list): raise ValueError("database relations must be a string or list")
            database_mapping.extend({"relation": relation, "fields": item.get("fields")} for relation in relations)
        rule = {
            "rule_id": raw.get("rule_id", raw.get("id")),
            "claim": raw.get("claim", raw.get("statement", raw.get("description"))),
            "status": raw.get("status"),
            "criticality": raw.get("criticality"),
            "source_refs": source_refs,
            "database_mapping": database_mapping,
        }
        if isinstance(raw.get("decision_semantics"), dict):
            semantics = raw["decision_semantics"]
            inputs = []
            if isinstance(semantics.get("inputs"), list):
                for item in semantics["inputs"]:
                    if isinstance(item, dict):
                        inputs.append({key: item.get(key) for key in ("name", "role", "fields")})
            rule["decision_semantics"] = {
                "inputs": inputs,
                "predicate": semantics.get("predicate"),
                "boundary_behavior": semantics.get("boundary_behavior"),
            }
        for key in ("conditions", "exceptions"):
            if isinstance(raw.get(key), list) and all(isinstance(item, str) for item in raw[key]):
                rule[key] = raw[key]
        if isinstance(raw.get("uncertainty"), str):
            unresolved.append(f"{rule['rule_id']}: {raw['uncertainty']}")
        if isinstance(raw.get("unresolved_reason"), str):
            unresolved.append(f"{rule['rule_id']}: {raw['unresolved_reason']}")
        converted.append(rule)
    normalized["rules"] = converted
    normalized["unresolved_questions"] = unresolved
    return normalized


def enrich(package: dict[str, Any], root: Path, task_id: str, revision: str, model: str) -> dict[str, Any]:
    package = dict(package); package.update({"schema_version": "0.2", "task_id": task_id, "repository_revision": revision})
    package.setdefault("unresolved_questions", []); package.setdefault("producer", {"role": "project-understanding", "model": model, "adapter": "native-qwen-readonly"})
    if not isinstance(package.get("rules"), list): raise ValueError("rules must be a list")
    for rule in package["rules"]:
        if not isinstance(rule, dict): raise ValueError("rule must be an object")
        refs = rule.get("source_refs", [])
        if not isinstance(refs, list): raise ValueError("source_refs must be a list")
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str): raise ValueError("source ref needs path")
            source = inside(ref["path"], root)
            if not source.is_file(): raise ValueError("cited source is not a file")
            ref["path"] = source.relative_to(root).as_posix(); ref["sha256"] = sha256_file(source)
    package["readiness"] = evidence_readiness(package)
    package.pop("artifact_sha256", None); package["artifact_sha256"] = canonical_json_sha256(package)
    validate_evidence_package(package, root)
    return package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-spec", type=Path, required=True); parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True); parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", required=True); parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--skill", type=Path, action="append", default=[], help="trusted project-understanding SKILL.md to inject")
    parser.add_argument("--conversation", type=Path, help="offline recovery from a previously audited model conversation")
    args = parser.parse_args(); output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    spec = json.loads(args.task_spec.read_text(encoding="utf-8")); extension = spec["extensions"]; root = args.repository.resolve()
    prompt = args.prompt.read_text(encoding="utf-8").replace(str(extension["repository_root"]), str(root))
    skill_records = []
    for skill_path in args.skill:
        skill_text = skill_path.read_text(encoding="utf-8")
        skill_records.append({"path": str(skill_path), "sha256": hashlib.sha256(skill_text.encode("utf-8")).hexdigest()})
        prompt += f"\n\nSelected project-understanding skill:\n{skill_text}"
    prompt += "\nUse at most 8 tool turns, then return JSON only with at most 5 rules. The controller will compute source SHA-256 values; provide path and exact line ranges. For schema 0.2 include criticality, evidence_kind, supports, and complete decision_semantics for every CORE rule."
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]; audit: list[dict[str, Any]] = []
    repository = ReadOnlyRepository(root); endpoint = os.environ.get("DATALOOM_QWEN_URL", "http://host.docker.internal:18020/v1/chat/completions")
    status = "FAILED"
    try:
        if args.conversation:
            messages = json.loads(args.conversation.read_text(encoding="utf-8"))
            if not isinstance(messages, list): raise ValueError("conversation must be a JSON list")
            audit.append({"turn": "offline-contract-recovery", "tool_calls": []})
        for turn in ([] if args.conversation else range(1, args.max_turns + 1)):
            result = invoke(endpoint, {"model": args.model, "messages": messages, "tools": TOOLS, "tool_choice": "auto", "max_tokens": 4096})
            message = result["choices"][0]["message"]; assistant = {key: message.get(key) for key in ("role", "content", "tool_calls") if message.get(key) is not None}
            messages.append(assistant); audit.append({"turn": turn, "finish_reason": result["choices"][0].get("finish_reason"), "tool_calls": assistant.get("tool_calls", [])})
            calls = assistant.get("tool_calls", [])
            if not calls: break
            for call in calls:
                try:
                    arguments = json.loads(call["function"]["arguments"]); handler = getattr(repository, call["function"]["name"])
                    observation: Any = handler(**arguments)
                except Exception as exc:
                    observation = {"error": f"{type(exc).__name__}: {exc}"}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(observation, ensure_ascii=False)})
            if turn >= min(8, args.max_turns - 1):
                messages.append({"role": "user", "content": "Tool budget is complete. Do not call tools. Return only one concise schema 0.2 JSON EvidencePackage now. Keep a core rule unresolved rather than using test, UI, or documentation as its production implementation."})
                final = invoke(endpoint, {"model": args.model, "messages": messages, "max_tokens": 8192})
                final_message = final["choices"][0]["message"]
                messages.append({"role": final_message.get("role", "assistant"), "content": final_message.get("content")})
                audit.append({"turn": "finalizer", "finish_reason": final["choices"][0].get("finish_reason"), "tool_calls": []})
                break
        else:
            if not args.conversation:
                raise RuntimeError("tool-turn budget exhausted")
        package = enrich(normalize_model_package(parse_final(messages)), root, spec["task_id"], extension["repository_revision"], args.model)
        (output / "evidence_package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        status = "SUCCESS"
    except Exception as exc:
        status = "FAILED"; (output / "failure.json").write_text(json.dumps({"error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        (output / "role_audit.json").write_text(json.dumps({"role": "project-understanding", "adapter": "native-qwen-readonly", "model": args.model, "status": status, "allowed_tools": ["read_file", "glob", "grep"], "skills": skill_records, "audit": audit}, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "conversation.json").write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
