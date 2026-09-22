from fastapi.testclient import TestClient

from agent_reliability_lab.api.app import create_app

TOKEN = "a" * 32


def authenticated_client() -> TestClient:
    return TestClient(
        create_app(api_tokens={TOKEN: "alice"}), headers={"Authorization": f"Bearer {TOKEN}"}
    )


def test_health_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_run_endpoint_executes_and_returns_retrievable_result() -> None:
    client = authenticated_client()
    payload = {
        "scenario_id": "api-1",
        "task": "find timeout handling",
        "repository_files": {"client.py": "timeout handling"},
        "expected_behavior": "find the relevant file",
        "expected_tools": ["repo_search"],
    }

    create_response = client.post("/runs", json=payload)

    assert create_response.status_code == 201
    result = create_response.json()
    assert result["scenario_id"] == "api-1"
    assert result["status"] == "succeeded"
    assert result["tool_calls"][0]["name"] == "repo_search"

    get_response = client.get(f"/runs/{result['run_id']}")

    assert get_response.status_code == 200
    assert get_response.json() == result


def test_get_run_returns_not_found_for_unknown_run() -> None:
    client = authenticated_client()

    response = client.get("/runs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json() == {"detail": "run not found"}
