"""Revision-controlled handoff protocol for DataLoom roles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from contracts import ContractError, require_ready_for_handoff


class ProtocolError(ValueError):
    pass


@dataclass
class HandoffRecord:
    task_id: str
    state: str = "PROJECT_UNDERSTANDING"
    revision: int = 0
    evidence_sha256: str | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)

    def _event(self, event: str, details: Mapping[str, Any]) -> None:
        self.audit.append(
            {
                "event": event,
                "revision": self.revision,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": dict(details),
            }
        )

    def submit_evidence(self, package: Mapping[str, Any], *, expected_revision: int) -> None:
        self._expect_revision(expected_revision)
        if package.get("task_id") != self.task_id:
            raise ProtocolError("evidence task_id does not match protocol task")
        try:
            require_ready_for_handoff(dict(package))
        except ContractError as exc:
            self._event("HANDOFF_REJECTED", {"reason": str(exc)})
            raise ProtocolError(str(exc)) from exc
        digest = package.get("artifact_sha256")
        if not isinstance(digest, str) or not digest:
            raise ProtocolError("ready evidence requires artifact_sha256")
        self.revision += 1
        self.evidence_sha256 = digest
        self.state = "SQL_GENERATION"
        self._event("HANDOFF_ACCEPTED", {"evidence_sha256": digest})

    def complete_sql(self, *, evidence_sha256: str, expected_revision: int) -> None:
        self._expect_revision(expected_revision)
        if self.state != "SQL_GENERATION":
            raise ProtocolError(f"cannot complete SQL from state {self.state}")
        if evidence_sha256 != self.evidence_sha256:
            raise ProtocolError("SQL result was produced from a stale evidence revision")
        self.revision += 1
        self.state = "COMPLETE"
        self._event("SQL_COMPLETED", {"evidence_sha256": evidence_sha256})

    def _expect_revision(self, expected: int) -> None:
        if expected != self.revision:
            raise ProtocolError(f"revision conflict: expected {expected}, current {self.revision}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "revision": self.revision,
            "evidence_sha256": self.evidence_sha256,
            "audit": list(self.audit),
        }

