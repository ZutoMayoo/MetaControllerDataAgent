"""Host orchestrator for one isolated, frozen Spider2-DBT pilot condition."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {command[0]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--condition", choices=("S0", "S1", "S2", "S3"), required=True)
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args()

    dataloom = Path(__file__).resolve().parent.parent
    workspace = dataloom.parents[1]
    spider = workspace / "P1/Spider-Agent-TC/Spider2/spider2-dbt"
    signalpilot = workspace / "P4/SignalPilot"
    source = spider / "examples" / args.task_id
    run_name = f"{args.condition}-{args.attempt}"
    work = dataloom / "runs/spider2-dbt/sm2/work" / args.task_id / run_name
    audit = dataloom / "runs/spider2-dbt/sm2/preparation_audits" / args.task_id / f"{run_name}.json"
    manifest = dataloom / "runs/spider2-dbt/sm2" / args.task_id / f"{args.condition}.manifest.json"
    evaluation = dataloom / "runs/spider2-dbt/sm2/evaluations" / args.task_id / f"{run_name}.json"
    if work.exists():
        raise RuntimeError(f"work directory already exists: {work}")

    run([
        sys.executable, str(dataloom / "runtime/prepare_spider_pilot.py"),
        "--source", str(source), "--destination", str(work), "--task-id", args.task_id,
        "--spider-root", str(spider), "--signalpilot-root", str(signalpilot),
        "--audit-output", str(audit),
    ])

    mounts = [
        f"type=bind,src={work},dst=/workspace/task",
        f"type=bind,src={manifest},dst=/experiment/manifest.json,readonly",
        f"type=bind,src={dataloom / 'runtime/run_spider_pilot_agent.py'},dst=/runner/run_spider_pilot_agent.py,readonly",
        f"type=bind,src={dataloom / 'runtime/spider_conditions.py'},dst=/runner/spider_conditions.py,readonly",
        f"type=bind,src={signalpilot / 'benchmark/agent/sdk_runner.py'},dst=/app/benchmark/agent/sdk_runner.py,readonly",
    ]
    if args.condition in {"S1", "S2"}:
        evidence = dataloom / "runs/spider2-dbt/sm1" / f"{args.task_id}.evidence.json"
        mounts.append(f"type=bind,src={evidence},dst=/experiment/evidence.json,readonly")
    if args.condition in {"S2", "S3"}:
        skills = signalpilot / "benchmark/signalpilot-plugin/skills"
        mounts.append(f"type=bind,src={skills},dst=/experiment/skills,readonly")

    docker = [
        "docker", "run", "--rm", "--name", f"dataloom-{args.task_id}-{args.condition.lower()}-{args.attempt}",
        "--label", "dataloom.spider=sm2", "--user", "agentuser", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "512",
        "--network", "signalpilot_default", "--entrypoint", "python",
    ]
    for mount in mounts:
        docker.extend(["--mount", mount])
    environment = {
        "SP_ORG_ID": f"dataloom-{args.task_id}-{args.condition.lower()}-{args.attempt}",
        "ANTHROPIC_BASE_URL": "http://host.docker.internal:15721",
        "ANTHROPIC_API_KEY": "local-vllm-placeholder",
        "ANTHROPIC_AUTH_TOKEN": "local-vllm-placeholder",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen3.8-27b",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "qwen3.8-27b",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen3.8-27b",
        "DATABASE_URL": "postgresql+asyncpg://signalpilot:changeme_dev_only@db:5432/signalpilot",
        "PYTHONPATH": "/app:/app/signalpilot/gateway:/runner",
    }
    for key, value in environment.items():
        docker.extend(["-e", f"{key}={value}"])
    docker.extend(["signalpilot-dbt-agent-clean:local", "/runner/run_spider_pilot_agent.py"])
    agent_process = subprocess.run(docker)
    if agent_process.returncode not in {0, 2}:
        raise RuntimeError(f"agent container infrastructure failure ({agent_process.returncode})")
    if not (work / "candidate.json").is_file() or not (work / "candidate.sha256").is_file():
        raise RuntimeError("agent container produced no frozen candidate")

    run([
        sys.executable, str(dataloom / "runtime/evaluate_spider_candidate.py"),
        "--work-dir", str(work), "--task-id", args.task_id,
        "--candidate", str(work / "candidate.json"),
        "--candidate-digest", str(work / "candidate.sha256"),
        "--spider-root", str(spider), "--signalpilot-root", str(signalpilot),
        "--output", str(evaluation),
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
