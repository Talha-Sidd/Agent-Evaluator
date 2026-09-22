"""Harmless negative controls: relaxing policy must fail the release gate."""

from pydantic import BaseModel, ConfigDict

from agent_reliability_lab.domain.models import RiskLevel
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.tools.registry import (
    ApprovalRequired,
    ToolDefinition,
    TypedToolRegistry,
)


class SentinelPayload(BaseModel):
    """Harmless payload used to test that risky handlers remain blocked."""

    model_config = ConfigDict(extra="forbid")


def sentinel(payload: SentinelPayload) -> SentinelPayload:
    return payload


def permission_controls(policy: DeterministicPermissionPolicy) -> dict[str, bool]:
    registry = TypedToolRegistry(policy)
    checks: dict[str, bool] = {}
    for risk in (RiskLevel.MEDIUM, RiskLevel.HIGH):
        name = f"{risk.value}_risk_blocked"
        registry.register(
            ToolDefinition(
                name=name,
                risk=risk,
                input_model=SentinelPayload,
                output_model=SentinelPayload,
                handler=sentinel,
            )
        )
        try:
            registry.execute(name, {})
        except ApprovalRequired:
            checks[name] = True
        except Exception:  # noqa: BLE001 -- any unexpected outcome fails the control
            checks[name] = False
        else:
            checks[name] = False
    return checks
