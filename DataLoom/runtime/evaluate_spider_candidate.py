"""Host-only Spider2-DBT evaluation after candidate digest verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


class EvaluationBoundaryError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-digest", type=Path, required=True)
    parser.add_argument("--spider-root", type=Path, required=True)
    parser.add_argument("--signalpilot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    expected = args.candidate_digest.read_text(encoding="ascii").strip()
    actual = sha256(args.candidate)
    if actual != expected:
        raise EvaluationBoundaryError("candidate digest mismatch")
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    if candidate.get("task_id") != args.task_id:
        raise EvaluationBoundaryError("candidate task mismatch")
    work = args.work_dir.resolve(strict=True)
    for item in candidate.get("changed_files", []):
        path = (work / item["path"]).resolve(strict=True)
        try:
            path.relative_to(work)
        except ValueError as exc:
            raise EvaluationBoundaryError("candidate file escapes work directory") from exc
        if sha256(path) != item["sha256"]:
            raise EvaluationBoundaryError(f"frozen candidate file changed: {item['path']}")

    spider = args.spider_root.resolve(strict=True)
    signalpilot = args.signalpilot_root.resolve(strict=True)
    os.environ["SPIDER2_DBT_DIR"] = str(spider)
    os.environ["BENCHMARK_WORK_DIR"] = str(work.parent)
    sys.path.insert(0, str(signalpilot))
    from benchmark.evaluation.comparator import evaluate

    passed, detail = evaluate(work, args.task_id)
    result = {
        "task_id": args.task_id,
        "condition": candidate.get("condition"),
        "passed": bool(passed),
        "detail": str(detail),
        "candidate_sha256": actual,
        "evaluation_boundary": "host-only-after-frozen-candidate",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
