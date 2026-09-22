"""Small deterministic permission policy for tool actions."""

from agent_reliability_lab.domain.models import PermissionDecision, RiskLevel, ToolAction


class DeterministicPermissionPolicy:
    """Pure policy that allows low-risk tools and blocks riskier tools pending approval."""

    def check(self, action: ToolAction) -> PermissionDecision:
        if action.risk is RiskLevel.LOW:
            return PermissionDecision(
                tool_name=action.tool_name,
                allowed=True,
                requires_approval=False,
                reason="low-risk action is allowed automatically",
            )
        return PermissionDecision(
            tool_name=action.tool_name,
            allowed=False,
            requires_approval=True,
            reason=f"{action.risk.value}-risk action requires explicit approval",
        )
