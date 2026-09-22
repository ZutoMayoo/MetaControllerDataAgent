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

    def __init__(self, root: Path, expected_revision: str | None = None) -> None:
        self.component = ExternalComponent("DataAgent", root, "Apache-2.0", expected_revision)

    @property
    def package_root(self) -> Path:
        return self.component.root / "runtime/dataagent"

    def probe(self, *, import_check: bool = False) -> dict[str, Any]:
        files = [self.component.root / path for path in (self.ENTRY, self.README)]
        manifest = self.component.manifest(files)
        manifest.update({
            "available": all(path.is_file() for path in files),
            "interface": f"{sys.executable} -m {self.MODULE}",
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

    def command(self, arguments: Iterable[str]) -> list[str]:
        return [sys.executable, "-m", self.MODULE, *list(arguments)]

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
