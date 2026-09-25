"""Deterministic, Gold-free evidence packages for Spider2.0-DBT projects."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


DBT_EVIDENCE_SCHEMA_VERSION = "dbt-0.1"


class DbtEvidenceError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_scanner(script: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("dataloom_pinned_signalpilot_scan", script)
    if spec is None or spec.loader is None:
        raise DbtEvidenceError(f"cannot load scanner: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _source_ref(root: Path, path: Path, lines: Iterable[int]) -> dict[str, Any]:
    selected = sorted(set(lines))
    if not selected:
        raise DbtEvidenceError(f"no provenance lines for {path}")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "line_start": selected[0],
        "line_end": selected[-1],
    }


def _matching_lines(path: Path, patterns: Iterable[str]) -> list[int]:
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    return [
        number
        for number, line in enumerate(_text(path).splitlines(), 1)
        if any(pattern.search(line) for pattern in compiled)
    ]


def _project_files(root: Path) -> list[Path]:
    skipped = {".git", ".claude", "dbt_packages", "target", "__pycache__"}
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and not any(part in skipped for part in path.relative_to(root).parts)
    )


def _model_definition_refs(root: Path, model: str) -> list[dict[str, Any]]:
    refs = []
    pattern = rf"^\s*-\s*name:\s*['\"]?{re.escape(model)}['\"]?\s*$"
    for path in sorted([*root.rglob("*.yml"), *root.rglob("*.yaml")]):
        if "dbt_packages" in path.parts:
            continue
        content = _text(path).splitlines()
        starts = [number for number, line in enumerate(content, 1) if re.search(pattern, line, re.IGNORECASE)]
        for start in starts:
            start_indent = len(content[start - 1]) - len(content[start - 1].lstrip())
            end = len(content)
            for number in range(start + 1, len(content) + 1):
                line = content[number - 1]
                stripped = line.lstrip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(line) - len(stripped)
                if indent == 0 or (indent <= start_indent and re.match(r"-\s*name:\s*", stripped)):
                    end = number - 1
                    break
            refs.append(_source_ref(root, path, range(start, end + 1)))
    return refs


def _sql_ref(root: Path, model: str) -> list[dict[str, Any]]:
    refs = []
    for path in root.rglob(f"{model}.sql"):
        if "dbt_packages" not in path.parts:
            line_count = max(1, len(_text(path).splitlines()))
            refs.append(_source_ref(root, path, range(1, line_count + 1)))
    return refs


def _dependency_refs(root: Path, model: str, dependencies: list[str]) -> list[dict[str, Any]]:
    refs = []
    patterns = [rf"ref\(\s*['\"]{re.escape(dep)}['\"]\s*\)" for dep in dependencies]
    for path in root.rglob(f"{model}.sql"):
        lines = _matching_lines(path, patterns)
        if lines:
            refs.append(_source_ref(root, path, lines))
    return refs


def build_dbt_evidence_package(
    *, task_id: str, instruction: str, project: Path, scanner_script: Path,
    scanner_revision: str, scanner_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic package using the pinned SignalPilot scanner implementation."""
    root = project.resolve(strict=True)
    if not (root / "dbt_project.yml").is_file():
        raise DbtEvidenceError("project has no dbt_project.yml")
    script = scanner_script.resolve(strict=True)
    actual_scanner_sha = _sha256(script)
    if scanner_sha256 and scanner_sha256 != actual_scanner_sha:
        raise DbtEvidenceError("SignalPilot scanner SHA-256 mismatch")
    scanner = _load_scanner(script)

    yml_models: set[str] = set()
    columns: dict[str, list[str]] = {}
    descriptions: dict[str, str] = {}
    materializations: dict[str, str] = {}
    sources: list[str] = []
    yml_files = sorted([*root.rglob("*.yml"), *root.rglob("*.yaml")])
    for path in yml_files:
        if "dbt_packages" in path.parts:
            continue
        content = _text(path)
        yml_models.update(scanner._extract_model_names(content))
        columns.update(scanner._extract_columns(content))
        descriptions.update(scanner._extract_descriptions(content))
        materializations.update(scanner._extract_materializations(content))
        sources.extend(scanner._extract_sources(content))

    complete_sql, stubs = scanner.classify_sql_models(root)
    sql_models = complete_sql | stubs
    missing = yml_models - sql_models
    complete = yml_models & complete_sql
    orphans = sql_models - yml_models
    dependencies = scanner._extract_deps_from_sql(root)
    macros = scanner.scan_macros(root)
    date_hazards = scanner.scan_current_date(root)

    def model_records(names: Iterable[str], include_sql: bool) -> list[dict[str, Any]]:
        records = []
        for name in sorted(names):
            refs = _model_definition_refs(root, name)
            if include_sql:
                refs.extend(_sql_ref(root, name))
            records.append({
                "name": name,
                "materialized": materializations.get(name, "table"),
                "required_columns": columns.get(name, []),
                "description": descriptions.get(name, ""),
                "source_refs": refs,
            })
        return records

    source_records = []
    for source in sorted(set(sources)):
        tokens = re.findall(r"source\('([^']+)'|tables:\s*(.*)$", source)
        names = [part for pair in tokens for part in pair if part]
        patterns = [rf"\b{re.escape(name.strip())}\b" for name in names for name in name.split(",")]
        refs = []
        for path in yml_files:
            lines = _matching_lines(path, patterns)
            if lines:
                refs.append(_source_ref(root, path, lines))
        source_records.append({"declaration": source.strip(), "source_refs": refs})

    macro_records = []
    for name, _body in macros:
        refs = []
        for path in (root / "macros").rglob("*.sql"):
            lines = _matching_lines(path, [rf"macro\s+{re.escape(name)}\s*\("])
            if lines:
                refs.append(_source_ref(root, path, lines))
        macro_records.append({"name": name, "source_refs": refs})

    dependency_records = [
        {"model": model, "depends_on": deps, "source_refs": _dependency_refs(root, model, deps)}
        for model, deps in sorted(dependencies.items())
    ]
    hazard_records = []
    for hit in date_hazards:
        match = re.match(r"\s*(.+?):(\d+):\s*(.*)", hit)
        if match:
            path = root / match.group(1)
            hazard_records.append({
                "path": match.group(1).replace("\\", "/"),
                "line": int(match.group(2)),
                "text": match.group(3),
                "source_ref": _source_ref(root, path, [int(match.group(2))]),
            })

    files = _project_files(root)
    package: dict[str, Any] = {
        "schema_version": DBT_EVIDENCE_SCHEMA_VERSION,
        "task_id": task_id,
        "instruction": instruction,
        "public_input_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "project_digest": _canonical_digest({p.relative_to(root).as_posix(): _sha256(p) for p in files}),
        "models": {
            "missing": model_records(missing, False),
            "stubs": model_records(stubs, True),
            "complete": model_records(complete, True),
            "orphans": model_records(orphans, True),
        },
        "dependencies": dependency_records,
        "sources": source_records,
        "macros": macro_records,
        "date_hazards": hazard_records,
        "project_files": [
            {"path": p.relative_to(root).as_posix(), "sha256": _sha256(p)} for p in files
        ],
        "producer": {
            "role": "dbt-project-understanding",
            "adapter": "signalpilot-dbt-evidence",
            "component": "SignalPilot",
            "revision": scanner_revision,
            "scan_project_sha256": actual_scanner_sha,
        },
    }
    package["artifact_sha256"] = _canonical_digest(package)
    validate_dbt_evidence_package(package, root)
    return package


def validate_dbt_evidence_package(package: dict[str, Any], project: Path) -> None:
    root = project.resolve(strict=True)
    required = {
        "schema_version", "task_id", "instruction", "public_input_sha256", "project_digest",
        "models", "dependencies", "sources", "macros", "date_hazards", "project_files",
        "producer", "artifact_sha256",
    }
    if set(package) != required:
        raise DbtEvidenceError(f"invalid top-level fields: {sorted(set(package) ^ required)}")
    if package["schema_version"] != DBT_EVIDENCE_SCHEMA_VERSION:
        raise DbtEvidenceError("unsupported dbt evidence schema")
    if package["public_input_sha256"] != hashlib.sha256(package["instruction"].encode("utf-8")).hexdigest():
        raise DbtEvidenceError("public input digest mismatch")
    without_digest = dict(package)
    recorded = without_digest.pop("artifact_sha256")
    if recorded != _canonical_digest(without_digest):
        raise DbtEvidenceError("artifact digest mismatch")
    file_map = {item["path"]: item["sha256"] for item in package["project_files"]}
    for relative, digest in file_map.items():
        path = root / relative
        if not path.is_file() or _sha256(path) != digest:
            raise DbtEvidenceError(f"project file provenance mismatch: {relative}")
    if package["project_digest"] != _canonical_digest(file_map):
        raise DbtEvidenceError("project digest mismatch")
    refs: list[dict[str, Any]] = []
    for group in package["models"].values():
        for item in group:
            refs.extend(item["source_refs"])
    for section in ("dependencies", "sources", "macros"):
        for item in package[section]:
            refs.extend(item["source_refs"])
    refs.extend(item["source_ref"] for item in package["date_hazards"])
    for ref in refs:
        path = root / ref["path"]
        if not path.is_file() or _sha256(path) != ref["sha256"]:
            raise DbtEvidenceError(f"source provenance mismatch: {ref['path']}")
        count = len(_text(path).splitlines())
        if not (1 <= ref["line_start"] <= ref["line_end"] <= count):
            raise DbtEvidenceError(f"invalid source lines: {ref['path']}")
