"""Thin FastAPI boundary around the deterministic agent platform."""

from uuid import UUID

from fastapi import FastAPI, HTTPException, status

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import AgentResult, Scenario
from agent_reliability_lab.platform.runner.runner import ScenarioRunner


class RunService:
    """Application service that owns the in-memory run lifecycle for this milestone."""

    def __init__(self) -> None:
        self._runner = ScenarioRunner()
        self._agent = RepoPilotDemo()
        self._runs: dict[UUID, AgentResult] = {}

    def create_run(self, scenario: Scenario) -> AgentResult:
        result = self._runner.run(self._agent, scenario)
        self._runs[result.run_id] = result
        return result

    def get_run(self, run_id: UUID) -> AgentResult | None:
        return self._runs.get(run_id)


def create_app(service: RunService | None = None) -> FastAPI:
    """Build the API with an injectable run service for testing."""

    run_service = service or RunService()
    app = FastAPI(title="Agent Reliability Lab", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/runs", response_model=AgentResult, status_code=status.HTTP_201_CREATED)
    def create_run(scenario: Scenario) -> AgentResult:
        return run_service.create_run(scenario)

    @app.get("/runs/{run_id}", response_model=AgentResult)
    def get_run(run_id: UUID) -> AgentResult:
        result = run_service.get_run(run_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        return result

    return app


app = create_app()
