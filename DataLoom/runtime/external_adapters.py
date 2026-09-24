"""Pinned subprocess adapters for reusable SignalPilot and DataAgent modules."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from context_projection import project_text


class AdapterError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "UNAVAILABLE"


@dataclass(frozen=True)
class ExternalComponent:
    name: str
    root: Path
    license: str
    expected_revision: str | None = None
    revision_root: Path | None = None

    def manifest(self, files: Iterable[Path]) -> dict[str, Any]:
        root = self.root.resolve(strict=True)
        revision = _git_revision((self.revision_root or root).resolve(strict=True))
        if self.expected_revision and revision != self.expected_revision:
            raise AdapterError(
                f"{self.name} revision mismatch: expected {self.expected_revision}, found {revision}"
            )
        components = []
        for path in files:
            resolved = path.resolve(strict=True)
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError as exc:
                raise AdapterError(f"component file escapes {self.name} root: {path}") from exc
            components.append({"path": relative, "sha256": _sha256(resolved)})
        return {
            "name": self.name,
            "root": str(root),
            "revision": revision,
            "license": self.license,
            "components": components,
        }


class SignalPilotDbtAdapter:
    SCAN = Path("benchmark/signalpilot-plugin/skills/dbt-workflow/scan_project.py")
    VALIDATE = Path("benchmark/signalpilot-plugin/skills/dbt-workflow/validate_project.py")
    SKILL = Path("benchmark/signalpilot-plugin/skills/dbt-workflow/SKILL.md")

    def __init__(self, root: Path, expected_revision: str | None = None) -> None:
        self.component = ExternalComponent(
            "SignalPilot", root, "Apache-2.0", expected_revision, root.parent
        )

    def probe(self) -> dict[str, Any]:
        files = [self.component.root / path for path in (self.SCAN, self.VALIDATE, self.SKILL)]
        manifest = self.component.manifest(files)
        manifest["available"] = all(path.is_file() for path in files)
        manifest["interface"] = "python subprocess: scan_project.py / validate_project.py"
        return manifest

    def scan(self, project: Path, *, timeout: int = 60) -> dict[str, Any]:
        script = self.component.root / self.SCAN
        result = subprocess.run(
            [sys.executable, str(script), str(project.resolve(strict=True))],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "observation": project_text((result.stdout or "") + (result.stderr or "")),
            "component": self.probe(),
        }

    def validate(self, project: Path, *, timeout: int = 60) -> dict[str, Any]:
        script = self.component.root / self.VALIDATE
        result = subprocess.run(
            [sys.executable, str(script), str(project.resolve(strict=True)), str(timeout)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 10,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "observation": project_text((result.stdout or "") + (result.stderr or "")),
            "component": self.probe(),
        }


class DataAgentBirdAdapter:
    MODULE = "dataagent.core.suite.builtin_suites.bird_benchmark.run_bird"
    ENTRY = Path("runtime/dataagent/dataagent/core/suite/builtin_suites/bird_benchmark/run_bird.py")
    README = Path("runtime/dataagent/dataagent/core/suite/builtin_suites/bird_benchmark/README.md")

    def __init__(
        self,
        root: Path,
        expected_revision: str | None = None,
        python_executable: Path | None = None,
    ) -> None:
        self.component = ExternalComponent("DataAgent", root, "Apache-2.0", expected_revision)
        isolated = root / "runtime/dataagent/.venv-dataloom-bird/Scripts/python.exe"
        self.python_executable = (
            python_executable.resolve(strict=True)
            if python_executable is not None
            else isolated.resolve() if isolated.is_file()
            else Path(sys.executable).resolve()
        )

    @property
    def package_root(self) -> Path:
        return self.component.root / "runtime/dataagent"

    def probe(self, *, import_check: bool = False) -> dict[str, Any]:
        files = [self.component.root / path for path in (self.ENTRY, self.README)]
        manifest = self.component.manifest(files)
        manifest.update({
            "available": all(path.is_file() for path in files),
            "interface": f"{self.python_executable} -m {self.MODULE}",
            "isolated_environment": ".venv-dataloom-bird" in self.python_executable.parts,
            "gold_isolation": self.audit_gold_isolation(),
            "import_check": {"attempted": False},
        })
        if import_check:
            result = self._run(["--help"], timeout=30)
            manifest["import_check"] = {
                "attempted": True,
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "observation": project_text((result.stdout or "") + (result.stderr or ""), max_chars=4000),
            }
        return manifest

    def audit_gold_isolation(self) -> dict[str, Any]:
        """Fail closed when the upstream runner materializes Gold before inference.

        Importability is not sufficient for a production benchmark adapter. The
        pinned upstream runner currently writes both the full question object
        and ``gold.sql`` before ``agent.chat``. This deterministic audit keeps
        live execution blocked until a split-process adapter is in place.
        """
        source_path = self.component.root / self.ENTRY.parent / "test_bird_e2e.py"
        source = source_path.read_text(encoding="utf-8")
        chat = source.find("agent.chat(")
        findings: list[dict[str, Any]] = []
        markers = {
            "GOLD_FILE_BEFORE_INFERENCE": '(case_dir / "gold.sql").write_text',
            "FULL_QUESTION_BEFORE_INFERENCE": '_write_json(case_dir / "question.json", item)',
        }
        for code, marker in markers.items():
            position = source.find(marker)
            if position >= 0 and chat >= 0 and position < chat:
                findings.append({
                    "code": code,
                    "line": source.count("\n", 0, position) + 1,
                    "source": source_path.relative_to(self.component.root).as_posix(),
                })
        worker_source = (self.component.root / self.ENTRY).read_text(encoding="utf-8")
        worker_marker = "_write(question_path, questions[index::count])"
        worker_position = worker_source.find(worker_marker)
        if worker_position >= 0:
            findings.append({
                "code": "FULL_QUESTION_COPIED_TO_WORKER",
                "line": worker_source.count("\n", 0, worker_position) + 1,
                "source": self.ENTRY.as_posix(),
            })
        split_runner = Path(__file__).with_name("bird_gold_safe.py")
        remediation = {
            "status": "READY_FOR_CANARY" if split_runner.is_file() else "NOT_IMPLEMENTED",
            "runner": str(split_runner),
            "runner_sha256": _sha256(split_runner) if split_runner.is_file() else None,
            "sanitized_bundle": split_runner.is_file(),
            "isolated_container": split_runner.is_file(),
            "frozen_candidate_digest": split_runner.is_file(),
            "host_only_evaluation": split_runner.is_file(),
            "live_canary_completed": False,
        }
        return {
            "status": "BLOCKED" if findings else "PASS",
            "safe_for_live_inference": not findings,
            "findings": findings,
            "dataloom_remediation": remediation,
            "required_remediation": (
                "complete one Gold-safe isolated canary before exposing live inference"
                if remediation["status"] == "READY_FOR_CANARY"
                else "sanitized inference bundle in an isolated process/container, followed by host-only evaluation"
                if findings else None
            ),
        }

    def command(self, arguments: Iterable[str]) -> list[str]:
        return [str(self.python_executable), "-m", self.MODULE, *list(arguments)]

    def dry_run(self, arguments: Iterable[str], *, timeout: int = 60) -> dict[str, Any]:
        args = list(arguments)
        if "--dry-run" not in args:
            args.append("--dry-run")
        result = self._run(args, timeout=timeout)
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "command": self.command(args),
            "observation": project_text((result.stdout or "") + (result.stderr or "")),
            "component": self.probe(),
        }

    def _run(self, arguments: Iterable[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        old_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(self.package_root) + (os.pathsep + old_path if old_path else "")
        return subprocess.run(
            self.command(arguments),
            cwd=self.package_root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
