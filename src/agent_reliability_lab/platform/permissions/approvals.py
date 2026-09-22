"""Explicit in-memory approval state for high-risk actions."""

from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from agent_reliability_lab.domain.models import ApprovalRequest, ApprovalStatus


class InMemoryApprovalStore:
    """Store approval decisions without allowing implicit approval."""

    def __init__(self) -> None:
        self._requests: dict[UUID, ApprovalRequest] = {}
        self._lock = RLock()

    def request(self, run_id: UUID, tool_name: str, reason: str) -> ApprovalRequest:
        approval = ApprovalRequest(run_id=run_id, tool_name=tool_name, reason=reason)
        with self._lock:
            self._requests[approval.approval_id] = approval
        return approval

    def get(self, approval_id: UUID) -> ApprovalRequest | None:
        with self._lock:
            return self._requests.get(approval_id)

    def approve(self, approval_id: UUID) -> ApprovalRequest:
        return self._resolve(approval_id, ApprovalStatus.APPROVED)

    def reject(self, approval_id: UUID) -> ApprovalRequest:
        return self._resolve(approval_id, ApprovalStatus.REJECTED)

    def _resolve(self, approval_id: UUID, status: ApprovalStatus) -> ApprovalRequest:
        with self._lock:
            return self._resolve_locked(approval_id, status)

    def _resolve_locked(self, approval_id: UUID, status: ApprovalStatus) -> ApprovalRequest:
        approval = self._requests.get(approval_id)
        if approval is None:
            raise KeyError(f"approval not found: {approval_id}")
        if approval.status is not ApprovalStatus.PENDING:
            raise ValueError(f"approval is already {approval.status.value}")
        resolved = approval.model_copy(update={"status": status, "resolved_at": datetime.now(UTC)})
        self._requests[approval_id] = resolved
        return resolved
