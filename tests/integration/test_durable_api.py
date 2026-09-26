from uuid import uuid4

from fastapi.testclient import TestClient

from agent_reliability_lab.api.app import RunService, create_app
from agent_reliability_lab.domain.models import StoredRun
from agent_reliability_lab.platform.storage.postgres import StorageError

TOKEN = "a" * 32
OTHER = "b" * 32


class FakeRepository:
    def __init__(self) -> None:
        self.records: dict[object, StoredRun] = {}
        self.fail = False

    def save(self, record: StoredRun, *, max_runs: int, max_bytes: int) -> None:
        if self.fail:
            raise StorageError("private-db-detail")
        self.records[record.result.run_id] = record.model_copy(deep=True)

    def get(self, run_id, owner: str) -> StoredRun | None:
        if self.fail:
            raise StorageError("private-db-detail")
        record = self.records.get(run_id)
        return record.model_copy(deep=True) if record and record.owner == owner else None


def client(repository: FakeRepository) -> TestClient:
    return TestClient(create_app(
        RunService(repository=repository), api_tokens={TOKEN: "alice", OTHER: "bob"}
    ))


def payload() -> dict[str, object]:
    return {
        "scenario_id": "durable", "task": "find needle",
        "repository_files": {"file.txt": "needle secret-token=private-canary"},
        "expected_behavior": "find file", "expected_tools": ["repo_search"],
    }


def test_restart_owner_and_evaluation_retrieval() -> None:
    repository = FakeRepository()
    first = client(repository)
    created = first.post("/runs", json=payload(), headers={"Authorization": f"Bearer {TOKEN}"})
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    second = client(repository)
    path = f"/runs/{run_id}"
    assert second.get(path, headers={"Authorization": f"Bearer {OTHER}"}).status_code == 404
    assert second.get(path + "/evaluation", headers={
        "Authorization": f"Bearer {OTHER}"
    }).status_code == 404
    assert second.get(path, headers={"Authorization": f"Bearer {TOKEN}"}).json() == created.json()
    evaluation = second.get(path + "/evaluation", headers={
        "Authorization": f"Bearer {TOKEN}"
    })
    assert evaluation.status_code == 200
    assert evaluation.json()["scenario_id"] == "durable"
    assert repository.records[next(iter(repository.records))].evaluator_version == "starter-v1"
    assert "private-canary" not in str(repository.records)


def test_storage_failure_is_explicit_and_does_not_leak_details() -> None:
    repository = FakeRepository()
    repository.fail = True
    api = client(repository)
    response = api.post("/runs", json=payload(), headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503
    assert response.json() == {"detail": "run storage unavailable"}
    response = api.get(f"/runs/{uuid4()}", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503
    assert "private-db-detail" not in response.text
