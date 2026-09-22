"""Trusted, auditable SKILL.md discovery and activation.

The design follows DataAgent's useful discovery model while deliberately not
executing commands embedded in a Skill. DataLoom injects selected Skill text as
instructions; runtime tools remain controlled by the host adapter.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from workspace_guard import WorkspaceGuard


class SkillError(ValueError):
    """Raised for invalid, duplicate, or untrusted skills."""


_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    description: str
    path: str
    sha256: str
    content: str

    def audit_record(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path, "sha256": self.sha256}


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md requires YAML frontmatter")
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return metadata
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise SkillError(f"unsupported frontmatter line: {line}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("'\"")
    raise SkillError("SKILL.md frontmatter is not closed")


class SkillLoader:
    def __init__(self, root: Path, allowlist: Iterable[str]) -> None:
        self.guard = WorkspaceGuard(root)
        self.allowlist = frozenset(allowlist)

    def discover(self) -> dict[str, LoadedSkill]:
        discovered: dict[str, LoadedSkill] = {}
        for skill_file in sorted(self.guard.root.glob("*/SKILL.md")):
            content = skill_file.read_text(encoding="utf-8")
            metadata = _frontmatter(content)
            name = metadata.get("name", skill_file.parent.name)
            if not _NAME.fullmatch(name):
                raise SkillError(f"invalid skill name: {name}")
            if name not in self.allowlist:
                continue
            if name in discovered:
                raise SkillError(f"duplicate skill name: {name}")
            discovered[name] = LoadedSkill(
                name=name,
                description=metadata.get("description", ""),
                path=self.guard.relative(skill_file),
                sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                content=content,
            )
        return discovered

    def activate(self, selected: Iterable[str]) -> list[LoadedSkill]:
        catalog = self.discover()
        names = list(selected)
        if len(names) != len(set(names)):
            raise SkillError("a skill may be activated only once per run")
        missing = [name for name in names if name not in catalog]
        if missing:
            raise SkillError(f"skills are not trusted or not found: {', '.join(missing)}")
        return [catalog[name] for name in names]

