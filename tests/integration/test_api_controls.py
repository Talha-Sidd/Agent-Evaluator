from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_reliability_lab.api.app import RunService, create_app
from agent_reliability_lab.domain.models import AgentResult, RunStatus, Scenario, ToolCall
from agent_reliability_lab.platform.runner.runner import ScenarioRunner

ALICE, BOB = "a" * 32, "b" * 32


class FixedRunner(ScenarioRunner):
    def run(self, agent, scenario):
        return AgentResult(
            run_id=uuid4(),
            scenario_id=scenario.scenario_id,
            status=RunStatus.SUCCEEDED,
            final_answer=scenario.task,
            tool_calls=[
                ToolCall(name="repo_search", arguments={"query": scenario.task}, success=True)
            ],
        )


def task() -> Scenario:
    return Scenario(scenario_id="api", task="private-task-canary", expected_behavior="safe")


def test_api_fails_closed_without_configuration(monkeypatch) -> None:
    monkeypatch.delenv("ARL_API_TOKENS", raising=False)
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    assert client.post("/runs", json=task().model_dump()).status_code == 503


def test_api_authentication_and_owner_isolation() -> None:
    client = TestClient(
        create_app(RunService(runner=FixedRunner()), api_tokens={ALICE: "alice", BOB: "bob"})
    )
    payload = task().model_dump()
    assert client.post("/runs", json=payload).status_code == 401
    created = client.post("/runs", json=payload, headers={"Authorization": f"Bearer {ALICE}"})
    assert created.status_code == 201
    assert "private-task-canary" not in created.text
    path = "/runs/" + created.json()["run_id"]
    assert client.get(path, headers={"Authorization": f"Bearer {BOB}"}).status_code == 404
    assert client.get(path, headers={"Authorization": f"Bearer {ALICE}"}).json() == created.json()


def test_validation_errors_and_body_limits_do_not_echo_inputs() -> None:
    client = TestClient(
        create_app(api_tokens={ALICE: "alice"}), headers={"Authorization": f"Bearer {ALICE}"}
    )
    response = client.post("/runs", json={"task": "API_KEY=private-canary"})
    assert response.status_code == 422 and "private-canary" not in response.text
    response = client.post("/runs", content=b"x" * (2 * 1024 * 1024 + 1))
    assert response.status_code == 413
    payload = task().model_dump()
    payload["repository_files"] = {"large.txt": "x" * 262145}
    assert client.post("/runs", json=payload).status_code == 422


def test_retention_capacity_expiry_and_snapshots() -> None:
    now = [0.0]
    service = RunService(max_runs=1, ttl_seconds=10, clock=lambda: now[0], runner=FixedRunner())
    first = service.create_run(task(), "alice")
    second = service.create_run(task(), "alice")
    assert service.get_run(first.run_id, "alice") is None
    second.final_answer = "mutated"
    assert service.get_run(second.run_id, "alice").final_answer != "mutated"
    now[0] = 10
    assert service.get_run(second.run_id, "alice") is None
    assert service._bytes == 0


def test_retention_byte_limit() -> None:
    service = RunService(max_bytes=1, runner=FixedRunner())
    with pytest.raises(HTTPException) as caught:
        service.create_run(task(), "alice")
    assert caught.value.status_code == 413
    assert not service._runs


def test_concurrent_admission_rejects_overload_and_releases_slot() -> None:
    entered, release = Event(), Event()

    class BlockingRunner(FixedRunner):
        def run(self, agent, scenario):
            entered.set()
            assert release.wait(5)
            return super().run(agent, scenario)

    service = RunService(concurrency=1, runner=BlockingRunner())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.create_run, task(), "alice")
        try:
            assert entered.wait(5)
            with pytest.raises(HTTPException) as caught:
                service.create_run(task(), "bob")
            assert caught.value.status_code == 429
        finally:
            release.set()
        assert future.result().status is RunStatus.SUCCEEDED
    assert service.create_run(task(), "alice").status is RunStatus.SUCCEEDED
