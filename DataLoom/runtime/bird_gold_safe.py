"""Gold-separated BIRD case preparation, inference, and host evaluation.

The three phases are intentionally separate commands.  The inference phase
accepts only a validated public bundle; the original question file and Gold SQL
are accepted only by the host-side evaluation phase.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
import sys
import time
from pathlib import Path
from typing import Any


BUNDLE_SCHEMA_VERSION = "0.1"
PUBLIC_TASK_FIELDS = frozenset({"question_id", "db_id", "question", "evidence"})
ALLOWED_BUNDLE_FILES = frozenset({"manifest.json", "task.json", "database/database.sqlite"})


class GoldIsolationError(ValueError):
    """Raised when an artifact violates the Gold isolation contract."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _new_directory(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise GoldIsolationError(f"output directory must be absent or empty: {resolved}")
    else:
        resolved.mkdir(parents=True)
    return resolved


def _load_questions(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise GoldIsolationError("question source must be a JSON array of objects")
    return value


def _select_question(path: Path, db_id: str, question_id: str) -> dict[str, Any]:
    matches = [
        item for item in _load_questions(path)
        if str(item.get("db_id")) == db_id and str(item.get("question_id")) == question_id
    ]
    if len(matches) != 1:
        raise GoldIsolationError(
            f"expected exactly one question for db_id={db_id!r}, question_id={question_id!r}; "
            f"found {len(matches)}"
        )
    return matches[0]


def prepare_bundle(
    *, question_source: Path, sqlite_source: Path, db_id: str, question_id: str, bundle_dir: Path
) -> dict[str, Any]:
    """Create the only directory that may be mounted into inference."""
    item = _select_question(question_source.resolve(strict=True), db_id, question_id)
    missing = [field for field in PUBLIC_TASK_FIELDS if field not in item]
    if missing:
        raise GoldIsolationError(f"public task fields missing: {', '.join(sorted(missing))}")
    task = {field: item[field] for field in sorted(PUBLIC_TASK_FIELDS)}
    if not str(task["question"]).strip():
        raise GoldIsolationError("question must not be empty")

    root = _new_directory(bundle_dir)
    database_dir = root / "database"
    database_dir.mkdir()
    task_path = root / "task.json"
    database_path = database_dir / "database.sqlite"
    _write_json(task_path, task)
    shutil.copy2(sqlite_source.resolve(strict=True), database_path)
    database_path.chmod(stat.S_IREAD)

    manifest = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "purpose": "bird-gold-free-inference",
        "task_identity": {"db_id": db_id, "question_id": question_id},
        "allowed_files": {
            "task.json": _sha256(task_path),
            "database/database.sqlite": _sha256(database_path),
        },
        "gold_present": False,
    }
    manifest["artifact_sha256"] = _canonical_sha256(manifest)
    _write_json(root / "manifest.json", manifest)
    audit_bundle(root)
    return manifest


def audit_bundle(bundle_dir: Path) -> dict[str, Any]:
    root = bundle_dir.resolve(strict=True)
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise GoldIsolationError(f"bundle must not contain symlinks: {path}")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != ALLOWED_BUNDLE_FILES:
        raise GoldIsolationError(
            f"bundle file set mismatch; expected {sorted(ALLOWED_BUNDLE_FILES)}, found {sorted(actual)}"
        )

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    recorded = manifest.pop("artifact_sha256", None)
    if recorded != _canonical_sha256(manifest):
        raise GoldIsolationError("bundle manifest digest mismatch")
    manifest["artifact_sha256"] = recorded
    if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION or manifest.get("gold_present") is not False:
        raise GoldIsolationError("invalid bundle schema or Gold declaration")

    task = json.loads((root / "task.json").read_text(encoding="utf-8"))
    if not isinstance(task, dict) or set(task) != PUBLIC_TASK_FIELDS:
        raise GoldIsolationError("task.json contains missing or non-public fields")
    for relative, digest in manifest.get("allowed_files", {}).items():
        if relative not in ALLOWED_BUNDLE_FILES - {"manifest.json"}:
            raise GoldIsolationError(f"manifest contains unexpected file: {relative}")
        if _sha256(root / relative) != digest:
            raise GoldIsolationError(f"bundle file digest mismatch: {relative}")
    if set(manifest.get("allowed_files", {})) != ALLOWED_BUNDLE_FILES - {"manifest.json"}:
        raise GoldIsolationError("manifest allowed_files is incomplete")

    uri = f"file:{(root / 'database/database.sqlite').as_posix()}?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.execute("PRAGMA schema_version").fetchone()
    return {"safe": True, "manifest": manifest, "task": task}


async def run_inference(
    *,
    bundle_dir: Path,
    output_dir: Path,
    semantic_service_url: str,
    semantic_db_prefix: str,
    model: str,
    api_base: str,
    case_timeout: float | None = None,
) -> dict[str, Any]:
    """Run one Gold-free case.  Invoke this only inside the isolated container."""
    audit = audit_bundle(bundle_dir)
    root = bundle_dir.resolve(strict=True)
    output = _new_directory(output_dir)
    task = audit["task"]

    from dataagent.core.suite.builtin_suites.bird_benchmark.test_bird_e2e import (
        _build_config,
        _chat_with_deadline,
        semantic_db_id,
    )
    from dataagent.interface.sdk.agent import DataAgent

    suffix = secrets.token_hex(3)
    user_id = f"dataloom_bird_{suffix}"
    session_id = f"dataloom_{task['db_id']}_{task['question_id']}_{suffix}"
    workspace = output / "workspace"
    workspace.mkdir()
    config_path = _build_config(
        output_path=output / "agent_config.yaml",
        sqlite_path=root / "database/database.sqlite",
        service_db_id=semantic_db_id(str(task["db_id"]), semantic_db_prefix),
        semantic_service_url=semantic_service_url,
        user_id=user_id,
        session_id=session_id,
        model_name=model,
        api_base=api_base,
        thinking="omit",
        enable_thinking="false",
        reasoning_effort=None,
        extra_body=None,
        llm_timeout=900,
        llm_num_retries=2,
        generator_max_tokens=None,
        llm_max_concurrency=1,
    )
    started = time.perf_counter()
    agent = DataAgent.from_config(str(config_path))
    response = await _chat_with_deadline(
        agent.chat(
            str(task["question"]),
            session_id=session_id,
            workspace=workspace,
            initial_state={
                "user_id": user_id,
                "session_id": session_id,
                "run_id": 0,
                "sub_id": 0,
                "evidence": str(task.get("evidence") or ""),
            },
        ),
        case_timeout,
    )
    final_state = response if isinstance(response, dict) else {"response": response}
    candidate = {
        "schema_version": "0.1",
        "db_id": task["db_id"],
        "question_id": task["question_id"],
        "predicted_sql": str(final_state.get("sql") or "").strip(),
        "bundle_sha256": audit["manifest"]["artifact_sha256"],
        "elapsed_seconds": time.perf_counter() - started,
        "llm_total_tokens": final_state.get("llm_total_tokens", 0),
        "producer": {"component": "External DataAgent", "model": model},
    }
    candidate_path = output / "candidate.json"
    _write_json(candidate_path, candidate)
    digest = _sha256(candidate_path)
    (output / "candidate.sha256").write_text(digest + "\n", encoding="ascii")
    candidate_path.chmod(stat.S_IREAD)
    (output / "candidate.sha256").chmod(stat.S_IREAD)
    return {"candidate": candidate, "candidate_sha256": digest}


def _execute_sql(db_path: Path, sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    if not sql.strip():
        raise GoldIsolationError("SQL is empty")
    uri = f"file:{db_path.resolve(strict=True).as_posix()}?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.execute("PRAGMA query_only = ON")
        denied_actions = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_DETACH,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_INDEX,
            sqlite3.SQLITE_CREATE_TEMP_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
            sqlite3.SQLITE_CREATE_TEMP_VIEW,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_CREATE_VTABLE,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_INDEX,
            sqlite3.SQLITE_DROP_TEMP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_TRIGGER,
            sqlite3.SQLITE_DROP_TEMP_VIEW,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_DROP_VTABLE,
            sqlite3.SQLITE_PRAGMA,
            sqlite3.SQLITE_REINDEX,
            sqlite3.SQLITE_TRANSACTION,
        }
        connection.set_authorizer(
            lambda action, _arg1, _arg2, _database, _trigger: (
                sqlite3.SQLITE_DENY if action in denied_actions else sqlite3.SQLITE_OK
            )
        )
        cursor = connection.execute(sql)
        return [column[0] for column in (cursor.description or [])], cursor.fetchall()


def evaluate_candidate(
    *,
    bundle_dir: Path,
    candidate_path: Path,
    candidate_digest_path: Path,
    question_source: Path,
    sqlite_source: Path,
    evaluation_dir: Path,
) -> dict[str, Any]:
    """Evaluate only after isolated inference has exited and frozen its candidate."""
    audit = audit_bundle(bundle_dir)
    expected_digest = candidate_digest_path.read_text(encoding="ascii").strip()
    actual_digest = _sha256(candidate_path)
    if not expected_digest or expected_digest != actual_digest:
        raise GoldIsolationError("candidate digest mismatch")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    task = audit["task"]
    if str(candidate.get("db_id")) != str(task["db_id"]) or str(candidate.get("question_id")) != str(
        task["question_id"]
    ):
        raise GoldIsolationError("candidate identity does not match bundle")
    if candidate.get("bundle_sha256") != audit["manifest"]["artifact_sha256"]:
        raise GoldIsolationError("candidate was produced from a different bundle")

    original = _select_question(question_source.resolve(strict=True), str(task["db_id"]), str(task["question_id"]))
    if "SQL" not in original:
        raise GoldIsolationError("host evaluation source has no Gold SQL")
    predicted_columns, predicted_rows = _execute_sql(sqlite_source, str(candidate.get("predicted_sql") or ""))
    gold_columns, gold_rows = _execute_sql(sqlite_source, str(original["SQL"]))
    correct = {tuple(row) for row in predicted_rows} == {tuple(row) for row in gold_rows}
    result = {
        "schema_version": "0.1",
        "db_id": task["db_id"],
        "question_id": task["question_id"],
        "candidate_sha256": actual_digest,
        "predicted_sql": candidate["predicted_sql"],
        "gold_sql": original["SQL"],
        "predicted_columns": predicted_columns,
        "gold_columns": gold_columns,
        "predicted_row_count": len(predicted_rows),
        "gold_row_count": len(gold_rows),
        "correct": correct,
        "evaluation_boundary": "host-only-after-frozen-candidate",
    }
    output = _new_directory(evaluation_dir)
    _write_json(output / "host_evaluation.json", result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--question-source", type=Path, required=True)
    prepare.add_argument("--sqlite-source", type=Path, required=True)
    prepare.add_argument("--db-id", required=True)
    prepare.add_argument("--question-id", required=True)
    prepare.add_argument("--bundle-dir", type=Path, required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--bundle-dir", type=Path, required=True)
    infer = commands.add_parser("infer")
    infer.add_argument("--bundle-dir", type=Path, required=True)
    infer.add_argument("--output-dir", type=Path, required=True)
    infer.add_argument("--semantic-service-url", required=True)
    infer.add_argument("--semantic-db-prefix", default="bird")
    infer.add_argument("--model", required=True)
    infer.add_argument("--api-base", required=True)
    infer.add_argument("--case-timeout", type=float)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--bundle-dir", type=Path, required=True)
    evaluate.add_argument("--candidate", type=Path, required=True)
    evaluate.add_argument("--candidate-digest", type=Path, required=True)
    evaluate.add_argument("--question-source", type=Path, required=True)
    evaluate.add_argument("--sqlite-source", type=Path, required=True)
    evaluate.add_argument("--evaluation-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "prepare":
        value = prepare_bundle(
            question_source=args.question_source,
            sqlite_source=args.sqlite_source,
            db_id=args.db_id,
            question_id=args.question_id,
            bundle_dir=args.bundle_dir,
        )
    elif args.command == "audit":
        value = audit_bundle(args.bundle_dir)
    elif args.command == "infer":
        value = asyncio.run(run_inference(
            bundle_dir=args.bundle_dir,
            output_dir=args.output_dir,
            semantic_service_url=args.semantic_service_url,
            semantic_db_prefix=args.semantic_db_prefix,
            model=args.model,
            api_base=args.api_base,
            case_timeout=args.case_timeout,
        ))
    else:
        value = evaluate_candidate(
            bundle_dir=args.bundle_dir,
            candidate_path=args.candidate,
            candidate_digest_path=args.candidate_digest,
            question_source=args.question_source,
            sqlite_source=args.sqlite_source,
            evaluation_dir=args.evaluation_dir,
        )
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
