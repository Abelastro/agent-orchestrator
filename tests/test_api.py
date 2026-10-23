"""Tests for the FastAPI surface using Starlette's TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_orchestrator.api.app import create_app
from agent_orchestrator.store import SQLiteStore


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store))


def _register(client, workflow):
    resp = client.post("/workflows", json=workflow)
    assert resp.status_code == 201
    return resp


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "0.1.0"}


def test_create_and_list_workflows(client):
    _register(
        client,
        {"name": "wf", "steps": [{"id": "a", "tool": "echo", "inputs": {"text": "hi"}}]},
    )
    resp = client.get("/workflows")
    assert resp.status_code == 200
    assert [w["name"] for w in resp.json()] == ["wf"]


def test_start_run_success(client):
    _register(
        client,
        {"name": "wf", "steps": [{"id": "a", "tool": "echo", "inputs": {"text": "hi"}}]},
    )
    resp = client.post("/runs", json={"workflow_name": "wf"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["records"]["a"]["output"] == "hi"


def test_start_run_unknown_workflow(client):
    resp = client.post("/runs", json={"workflow_name": "missing"})
    assert resp.status_code == 404


def test_get_run_and_list_runs(client):
    _register(client, {"name": "wf", "steps": [{"id": "a", "tool": "echo"}]})
    run_id = client.post("/runs", json={"workflow_name": "wf"}).json()["id"]

    assert client.get(f"/runs/{run_id}").status_code == 200
    listing = client.get("/runs").json()
    assert [r["id"] for r in listing] == [run_id]


def test_get_run_missing(client):
    assert client.get("/runs/nope").status_code == 404


def test_resume_run(client):
    _register(
        client,
        {
            "name": "failwf",
            "steps": [
                {"id": "a", "tool": "fail", "retry": {"max_attempts": 1}}
            ],
        },
    )
    run = client.post("/runs", json={"workflow_name": "failwf"}).json()
    assert run["status"] == "failed"

    resumed = client.post(f"/runs/{run['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "failed"


def test_resume_missing(client):
    assert client.post("/runs/nope/resume").status_code == 404


def test_approve_flow(client):
    _register(
        client,
        {
            "name": "gate",
            "steps": [
                {
                    "id": "gate",
                    "tool": "echo",
                    "requires_approval": True,
                },
                {"id": "after", "tool": "echo", "depends_on": ["gate"]},
            ],
        },
    )
    run = client.post("/runs", json={"workflow_name": "gate"}).json()
    assert run["status"] == "awaiting_approval"

    approved = client.post(f"/runs/{run['id']}/steps/gate/approve")
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "succeeded"
    assert body["records"]["after"]["state"] == "succeeded"


def test_reject_flow(client):
    _register(
        client,
        {
            "name": "gate",
            "steps": [
                {
                    "id": "gate",
                    "tool": "echo",
                    "requires_approval": True,
                },
                {"id": "after", "tool": "echo", "depends_on": ["gate"]},
            ],
        },
    )
    run = client.post("/runs", json={"workflow_name": "gate"}).json()
    rejected = client.post(f"/runs/{run['id']}/steps/gate/reject")
    assert rejected.status_code == 200
    body = rejected.json()
    assert body["records"]["gate"]["state"] == "skipped"
    assert body["records"]["after"]["state"] == "skipped"


def test_approve_non_awaiting_conflict(client):
    _register(client, {"name": "wf", "steps": [{"id": "a", "tool": "echo"}]})
    run = client.post("/runs", json={"workflow_name": "wf"}).json()
    resp = client.post(f"/runs/{run['id']}/steps/a/approve")
    assert resp.status_code == 409


def test_reject_missing_run_returns_404(client):
    resp = client.post("/runs/nope/steps/a/reject")
    assert resp.status_code == 404


def test_engine_bound_to_store(client, store):
    assert isinstance(client.app.state.store, SQLiteStore)
