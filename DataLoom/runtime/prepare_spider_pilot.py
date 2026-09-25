"""Create a task-local Spider2-DBT inference copy without materialized targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


class PreparationError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--spider-root", type=Path, required=True)
    parser.add_argument("--signalpilot-root", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = args.destination.resolve() if args.destination.exists() else args.destination.absolute()
    if destination.exists():
        raise PreparationError(f"destination already exists: {destination}")
    spider = args.spider_root.resolve(strict=True)
    os.environ["SPIDER2_DBT_DIR"] = str(spider)
    sys.path.insert(0, str(args.signalpilot_root.resolve(strict=True)))
    from benchmark.core.tasks import load_eval_config

    config = load_eval_config(args.task_id)
    if not config:
        raise PreparationError("evaluation config not found")
    params = config["evaluation"]["parameters"]
    targets = list(params.get("condition_tabs") or [])
    if not targets:
        raise PreparationError("evaluation config has no explicit condition_tabs; fail closed")
    shutil.copytree(source, destination)
    databases = list(destination.glob("*.duckdb"))
    if len(databases) != 1:
        raise PreparationError(f"expected one DuckDB file, found {len(databases)}")
    import duckdb
    connection = duckdb.connect(str(databases[0]))
    removed = []
    try:
        existing = {
            row[0]: row[1]
            for row in connection.execute(
                "select table_name, table_type from information_schema.tables where table_schema = 'main'"
            ).fetchall()
        }
        for target in targets:
            if target in existing:
                quoted = '"' + target.replace('"', '""') + '"'
                object_kind = "view" if existing[target].upper() == "VIEW" else "table"
                connection.execute(f"drop {object_kind} {quoted}")
                removed.append(target)
    finally:
        connection.close()
    remaining = duckdb.connect(str(databases[0]), read_only=True)
    try:
        remaining_tables = [row[0] for row in remaining.execute("show tables").fetchall()]
    finally:
        remaining.close()
    if set(targets) & set(remaining_tables):
        raise PreparationError("target relation remains in inference database")
    audit = {
        "task_id": args.task_id,
        "source": str(source),
        "destination": str(destination),
        "target_relations_removed": removed,
        "target_relations_absent": sorted(set(targets) - set(removed)),
        "remaining_tables": remaining_tables,
        "database_sha256": sha256(databases[0]),
        "agent_visible": False,
    }
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"task_id": args.task_id, "removed_count": len(removed), "status": "READY"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
