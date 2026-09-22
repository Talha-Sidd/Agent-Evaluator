"""Safe operational errors; messages never embed rejected payloads or exceptions."""

from agent_reliability_lab.domain.models import ErrorCode


class ToolExecutionError(RuntimeError):
    """Safe operational failure carrying a typed error code without raw payloads."""

    def __init__(self, code: ErrorCode = ErrorCode.TOOL_ERROR) -> None:
        self.code = code
        super().__init__(code.value)
