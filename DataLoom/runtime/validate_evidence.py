"""Validate one EvidencePackage against a frozen Code-aware repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codeaware_adapter import repository_root
from contracts import ContractError, validate_evidence_package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
        validate_evidence_package(evidence, repository_root(args.project))
    except (OSError, ValueError, ContractError) as exc:
        print(f"EvidencePackage validation: FAIL: {type(exc).__name__}: {exc}")
        return 1
    print("EvidencePackage validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

