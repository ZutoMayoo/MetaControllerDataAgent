"""Build gold-free Code-aware TaskSpec and Project Understanding prompts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_ROOT = ROOT / "P9" / "Code-awareBenchmark"
PROJECT_SOURCE_DIRS = {
    "saleor": "source/saleor-3.23.7",
    "erpnext": "source/erpnext-15.119.3",
}
PROJECT_REVISIONS = {
    # Cal.diy task documents intentionally contain only public questions; its
    # project-level source manifest fixes the repository revision.
    "cal-diy": "176037d0afbe572f870a3c702985e7cd83fe6c0c",
}


def repository_root(project: str) -> Path:
    """Resolve only the frozen source tree declared by the benchmark layout."""
    declared = PROJECT_SOURCE_DIRS.get(project)
    if declared:
        candidate = BENCHMARK_ROOT / declared
        if not candidate.is_dir():
            raise FileNotFoundError(f"Declared source tree missing for project {project!r}: {candidate}")
        return candidate
    candidates = [
        BENCHMARK_ROOT / project / "source",
        BENCHMARK_ROOT / "source" / project,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            children = [path for path in candidate.iterdir() if path.is_dir() and path.name != ".git"]
            return children[0] if len(children) == 1 else candidate
    shared_source = BENCHMARK_ROOT / "source"
    if shared_source.is_dir():
        normalized = project.casefold().replace("-", "")
        matches = [
            path for path in shared_source.iterdir()
            if path.is_dir() and path.name.casefold().replace("-", "").startswith(normalized)
        ]
        if len(matches) == 1:
            return matches[0]
    raise FileNotFoundError(f"No frozen source tree found for project {project!r}")


def task_dir(project: str, task_id: str) -> Path:
    result = BENCHMARK_ROOT / project / "tasks" / task_id
    if not (result / "task.md").is_file():
        raise FileNotFoundError(f"Code-aware task not found: {project}/{task_id}")
    return result


_QUESTION_HEADINGS = ("问题", "question", "task")
_PRIVATE_HEADINGS = re.compile(
    r"(?:预期|答案|expected|gold|验收|validation|业务口径|business\s+rule|"
    r"任务属性|task\s+attributes|反事实|counterfactual|source\s+pin|代码证据|code\s+evidence|"
    r"evidence|fixture)",
    re.I,
)
_PRIVATE_LINE = re.compile(
    r"^\s*(?:[-*>]\s*)?(?:预期|答案|expected|gold|验收|validation|业务口径|"
    r"code\s+necessity|source\s+pin|反事实|counterfactual|代码证据|code\s+evidence|"
    r"evidence|fixture)\b|^\s*(?:预期|业务口径|任务属性)[：:]?",
    re.I,
)


def public_task_statement(markdown: str) -> str:
    """Extract the user question without benchmark-authoring material.

    Code-aware task packages are authoring documents and may contain expected
    answers, fixture instructions, and oracle evidence after the public
    question.  The standard inference adapter must never expose those sections.
    """
    lines = markdown.splitlines()
    start = next(
        (index + 1 for index, line in enumerate(lines)
         if re.match(r"^#{1,6}\s*", line)
         and any(token in re.sub(r"^#{1,6}\s*", "", line).casefold() for token in _QUESTION_HEADINGS)),
        0,
    )
    result: list[str] = []
    for line in lines[start:]:
        if re.match(r"^#{1,6}\s*", line) and _PRIVATE_HEADINGS.search(line):
            break
        if _PRIVATE_LINE.search(line):
            break
        private_match = re.search(r"\b(?:gold|validation\.sql|evidence\.md|fixture\.sql|fixture\.md)\b", line, re.I)
        if private_match:
            prefix = line[:private_match.start()].rstrip(" ：:-")
            if prefix:
                result.append(prefix)
            break
        if start == 0 and (re.match(r"^#", line) or re.match(r"^>\s*\*\*Status:", line, re.I)):
            continue
        result.append(line)
    statement = "\n".join(result).strip()
    if not statement:
        raise ValueError("Task has no safely extractable public question")
    return statement


def task_spec(project: str, task_id: str) -> dict[str, Any]:
    directory = task_dir(project, task_id)
    repository = repository_root(project)
    authoring_markdown = (directory / "task.md").read_text(encoding="utf-8")
    question = public_task_statement(authoring_markdown)
    pin_match = re.search(r"(?:source pin|版本)[：:]?\s*[^\n]*?([0-9a-f]{7,40})", authoring_markdown, re.I)
    return {
        "schema_version": "0.1",
        "task_id": task_id,
        "adapter": "code-aware",
        "task_kind": "code_aware_sql",
        "public_assets": [
            "generated/sanitized_task_statement.md",
            str(repository.relative_to(BENCHMARK_ROOT)).replace("\\", "/"),
        ],
        "access_policy": {
            "repository_read": True,
            "database_read_only": True,
            "gold_and_validation_visible_to_inference": False,
        },
        "evaluator": {
            "mode": "host_only",
            "inference_feedback": False,
        },
        "extensions": {
            "project": project,
            "repository_root": str(repository),
            "repository_revision": pin_match.group(1) if pin_match else PROJECT_REVISIONS.get(project, "UNDECLARED"),
            "task_markdown": question,
        },
    }


def project_understanding_prompt(spec: dict[str, Any]) -> str:
    """Return the M1 role prompt; it names no gold or evaluator artifact."""
    extension = spec["extensions"]
    return f"""You are the DataLoom Project Understanding role for task {spec['task_id']}.

Read only the frozen repository at:
{extension['repository_root']}

Public task statement:
{extension['task_markdown']}

Identify every task-critical decision that can change the answer and trace it to the production implementation. Treat tests, UI code, and documentation as leads or examples, not sufficient evidence for a core production rule. Return one JSON EvidencePackage with schema_version \"0.2\".

Mark each rule criticality as CORE or SUPPORTING. For every source reference, classify evidence_kind and what it supports. Every CORE rule must cite PRODUCTION_CODE that supports DECISION_IMPLEMENTATION and must include decision_semantics with named inputs, each input's role and fields, the predicate, and explicit boundary behavior. Map rules to database relations and fields only when repository evidence supports that mapping. If any core decision cannot be established from production code, mark it UNRESOLVED; the controller will make the package INCOMPLETE and block downstream SQL generation.

Do not use common expectations to fill missing behavior. Do not read, search for, or mention gold answers, validation SQL, fixture expected results, prior experiments, or evaluator outputs.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--format", choices=("task-spec", "prompt"), default="task-spec")
    parser.add_argument("--output-dir", type=Path,
                        help="write sanitized TaskSpec and prompt as inference inputs")
    args = parser.parse_args()
    spec = task_spec(args.project, args.task)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "task_spec.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (args.output_dir / "project_understanding_prompt.txt").write_text(
            project_understanding_prompt(spec), encoding="utf-8"
        )
        return 0
    print(project_understanding_prompt(spec) if args.format == "prompt" else json.dumps(spec, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
