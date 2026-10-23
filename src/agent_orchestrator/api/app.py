"""FastAPI application factory and HTTP surface."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..config import Settings, get_settings
from ..engine import Engine, NotFoundError, OrchestratorError, WorkflowError
from ..models import RunRecord, WorkflowSpec
from ..registry import DEFAULT_REGISTRY, ToolRegistry
from ..store.sqlite_store import SQLiteStore


class StartRunRequest(BaseModel):
    """Request body for starting a run from a registered workflow."""

    workflow_name: str
    run_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str


def create_app(
    store: SQLiteStore | None = None,
    *,
    settings: Settings | None = None,
    registry: ToolRegistry | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    """Build a FastAPI app bound to a store and engine.

    ``store`` defaults to a :class:`SQLiteStore` using ``settings.db_path``;
    ``engine`` defaults to a new :class:`Engine` sharing the same store.
    """

    resolved_settings = settings or get_settings()
    resolved_store = store or SQLiteStore(resolved_settings.db_path)
    resolved_engine = engine or Engine(
        registry=registry or DEFAULT_REGISTRY,
        store=resolved_store,
        settings=resolved_settings,
    )

    app = FastAPI(
        title="Agent Orchestrator",
        version="0.1.0",
        description="Durable agentic workflow orchestrator API.",
    )
    app.state.store = resolved_store
    app.state.engine = resolved_engine

    def _engine() -> Engine:
        return app.state.engine

    def _load_run(run_id: str) -> RunRecord:
        try:
            return _engine().get_run(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version="0.1.0")

    @app.post("/workflows", response_model=WorkflowSpec, status_code=201)
    def create_workflow(workflow: WorkflowSpec) -> WorkflowSpec:
        try:
            app.state.store.save_workflow(workflow)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return workflow

    @app.get("/workflows", response_model=list[WorkflowSpec])
    def list_workflows() -> list[WorkflowSpec]:
        return app.state.store.list_workflows()

    @app.post("/runs", response_model=RunRecord, status_code=201)
    def start_run(request: StartRunRequest) -> RunRecord:
        workflow = app.state.store.load_workflow(request.workflow_name)
        if workflow is None:
            raise HTTPException(
                status_code=404,
                detail=f"workflow not found: {request.workflow_name}",
            )
        try:
            return _engine().run(workflow, run_id=request.run_id)
        except OrchestratorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/runs", response_model=list[RunRecord])
    def list_runs() -> list[RunRecord]:
        return app.state.store.list_runs()

    @app.get("/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: str) -> RunRecord:
        return _load_run(run_id)

    @app.post("/runs/{run_id}/resume", response_model=RunRecord)
    def resume_run(run_id: str) -> RunRecord:
        _load_run(run_id)
        try:
            return _engine().resume(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/steps/{step_id}/approve", response_model=RunRecord)
    def approve_step(run_id: str, step_id: str) -> RunRecord:
        _load_run(run_id)
        try:
            return _engine().approve(run_id, step_id)
        except WorkflowError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/steps/{step_id}/reject", response_model=RunRecord)
    def reject_step(run_id: str, step_id: str) -> RunRecord:
        _load_run(run_id)
        try:
            return _engine().reject(run_id, step_id)
        except WorkflowError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()
