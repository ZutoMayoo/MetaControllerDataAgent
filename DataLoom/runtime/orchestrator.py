"""Unified DataLoom entry point for Code-aware, Spider2-DBT, and BIRD."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from benchmark_router import BenchmarkRouter
from capabilities import Action, ActionRouter, CapabilityManifest, CapabilityRegistry
from external_adapters import DataAgentBirdAdapter, SignalPilotDbtAdapter
from skill_loader import SkillLoader


SIGNALPILOT_REVISION = "71dc57e4d915ebc2475d4cd27c6d5f8c405e5cf3"
DATAAGENT_REVISION = "8208e7cbbc0c3351c76a4c292737ca05ab92cb4f"
TRUSTED_PROJECT_SKILLS = frozenset({
    "business-rule-tracing", "schema-code-mapping", "boundary-and-exception-analysis"
})


def _configure_stdout_utf8(stream: Any | None = None) -> Any:
    """Keep JSON CLI output stable on Windows hosts whose default is GBK."""
    target = stream or sys.stdout
    reconfigure = getattr(target, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    return target


def _need(*names: str):
    def guard(payload: Mapping[str, Any]) -> None:
        missing = [name for name in names if payload.get(name) in (None, "")]
        if missing:
            raise ValueError(f"missing action fields: {', '.join(missing)}")
    return guard


@dataclass(frozen=True)
class RuntimePaths:
    workspace: Path
    signalpilot: Path
    dataagent: Path

    @classmethod
    def defaults(cls) -> "RuntimePaths":
        workspace = Path(__file__).resolve().parents[3]
        return cls(workspace, workspace / "P4" / "SignalPilot", workspace / "external" / "DataAgent")


class DataLoomOrchestrator:
    def __init__(self, paths: RuntimePaths | None = None, *, enforce_pins: bool = True) -> None:
        self.paths = paths or RuntimePaths.defaults()
        self.routes = BenchmarkRouter()
        signalpilot = SignalPilotDbtAdapter(
            self.paths.signalpilot, SIGNALPILOT_REVISION if enforce_pins else None
        )
        dataagent = DataAgentBirdAdapter(
            self.paths.dataagent, DATAAGENT_REVISION if enforce_pins else None
        )
        registry = CapabilityRegistry()
        registry.register(CapabilityManifest(
            name="project-understanding", version="0.2.0",
            actions=(Action("code-aware.project-understanding", self._run_codeaware,
                            guards=(_need("task_spec", "prompt", "repository", "output_dir", "model"),)),),
            benchmarks=frozenset({"code-aware"}), roles=frozenset({"project-understanding"}),
        ))
        registry.register(CapabilityManifest(
            name="dbt-project-understanding", version="signalpilot-pinned",
            actions=(
                Action("spider2-dbt.scan", lambda payload: signalpilot.scan(Path(payload["project"])),
                       guards=(_need("project"),)),
                Action("spider2-dbt.validate", lambda payload: signalpilot.validate(Path(payload["project"])),
                       guards=(_need("project"),)),
                Action(
                    "spider2-dbt.evidence",
                    lambda payload: signalpilot.evidence_package(
                        task_id=str(payload["task_id"]),
                        instruction=str(payload["instruction"]),
                        project=Path(payload["project"]),
                    ),
                    guards=(_need("task_id", "instruction", "project"),),
                ),
                Action("spider2-dbt.probe", lambda payload: signalpilot.probe()),
            ),
            benchmarks=frozenset({"spider2-dbt"}), roles=frozenset({"project-understanding"}),
        ))
        registry.register(CapabilityManifest(
            name="nl2sql", version="dataagent-pinned",
            actions=(
                Action("bird.dry-run", lambda payload: dataagent.dry_run(payload.get("arguments", ["run"])),
                       required_scopes=frozenset({"execute"})),
                Action("bird.probe", lambda payload: dataagent.probe(import_check=bool(payload.get("import_check")))),
            ),
            benchmarks=frozenset({"bird"}), roles=frozenset({"sql-generation"}),
        ))
        self.registry = registry
        self.actions = ActionRouter(registry)

    def probe(self, benchmark: str, *, import_check: bool = False) -> dict[str, Any]:
        route = self.routes.select(benchmark)
        if route.benchmark == "code-aware":
            return {
                "route": vars(route),
                "available": (Path(__file__).parent / "run_project_understanding_qwen.py").is_file(),
                "capabilities": self.registry.catalog(),
            }
        action = f"{route.benchmark}.probe"
        result = self.actions.dispatch(action, {"import_check": import_check})
        return {"route": vars(route), **result["observation"]}

    def run(self, benchmark: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        route = self.routes.select(benchmark)
        action = {
            "code-aware": "code-aware.project-understanding",
            "spider2-dbt": "spider2-dbt.scan",
            "bird": "bird.dry-run",
        }[route.benchmark]
        return self.actions.dispatch(action, payload, scopes={"execute"})

    def _run_codeaware(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        command = [
            sys.executable, str(Path(__file__).parent / "run_project_understanding_qwen.py"),
            "--task-spec", str(payload["task_spec"]), "--prompt", str(payload["prompt"]),
            "--repository", str(payload["repository"]), "--output-dir", str(payload["output_dir"]),
            "--model", str(payload["model"]), "--max-turns", str(payload.get("max_turns", 20)),
        ]
        skill_root = Path(__file__).resolve().parent.parent / "skills"
        selected = SkillLoader(skill_root, TRUSTED_PROJECT_SKILLS).activate(payload.get("skills", []))
        for skill in selected:
            command.extend(["--skill", str(skill_root / skill.path)])
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return {"success": result.returncode == 0, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr, "command": command,
                "skills": [skill.audit_record() for skill in selected]}


def main() -> int:
    _configure_stdout_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog")
    probe = commands.add_parser("probe")
    probe.add_argument("--benchmark", required=True, choices=("code-aware", "spider2-dbt", "bird"))
    probe.add_argument("--import-check", action="store_true")
    scan = commands.add_parser("scan-dbt")
    scan.add_argument("--project", type=Path, required=True)
    validate = commands.add_parser("validate-dbt")
    validate.add_argument("--project", type=Path, required=True)
    evidence = commands.add_parser("evidence-dbt")
    evidence.add_argument("--task-id", required=True)
    evidence.add_argument("--instruction", required=True)
    evidence.add_argument("--project", type=Path, required=True)
    evidence.add_argument("--output", type=Path)
    bird = commands.add_parser("dry-run-bird")
    bird.add_argument("--bird-data-dir", type=Path, required=True)
    bird.add_argument("--dev-json", type=Path, required=True)
    bird.add_argument("--db-id", required=True)
    bird.add_argument("--question-id", required=True)
    bird.add_argument("--model", required=True)
    bird.add_argument("--api-base", required=True)
    bird.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    orchestrator = DataLoomOrchestrator()
    if args.command == "catalog":
        value = {"routes": orchestrator.routes.catalog(), "capabilities": orchestrator.registry.catalog()}
    elif args.command == "probe":
        value = orchestrator.probe(args.benchmark, import_check=args.import_check)
    elif args.command in {"scan-dbt", "validate-dbt"}:
        action = "spider2-dbt.scan" if args.command == "scan-dbt" else "spider2-dbt.validate"
        value = orchestrator.actions.dispatch(action, {"project": str(args.project)}, scopes={"execute"})
    elif args.command == "evidence-dbt":
        value = orchestrator.actions.dispatch(
            "spider2-dbt.evidence",
            {"task_id": args.task_id, "instruction": args.instruction, "project": str(args.project)},
            scopes={"execute"},
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(value["observation"], ensure_ascii=False, indent=2), encoding="utf-8"
            )
    else:
        arguments = [
            "run", "--mode", "limited",
            "--bird-data-dir", str(args.bird_data_dir), "--dev-json", str(args.dev_json),
            "--db-id", args.db_id, "--question-id", args.question_id,
            "--model", args.model, "--api-base", args.api_base,
            "--run-dir", str(args.run_dir), "--preprocess", "skip", "--no-retry",
        ]
        value = orchestrator.run("bird", {"arguments": arguments})
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
