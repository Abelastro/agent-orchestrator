"""Durable persistence of workflows and runs using the stdlib ``sqlite3``.

The store keeps three tables: ``workflows`` (registered specs), ``runs`` (run
metadata plus the full workflow snapshot) and ``step_records`` (per-step
checkpoints). Connections are created lazily and guarded by a re-entrant lock so
the store can be shared across the FastAPI threadpool.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from ..models import RunRecord, RunStatus, StepRecord, StepState, WorkflowSpec

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    name TEXT PRIMARY KEY,
    spec_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL,
    workflow_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS step_records (
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    state TEXT NOT NULL,
    output_json TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at REAL,
    finished_at REAL,
    approved INTEGER,
    PRIMARY KEY (run_id, step_id),
    FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs (workflow_name);
CREATE INDEX IF NOT EXISTS idx_step_records_run ON step_records (run_id);
"""


def _dump_output(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)


def _load_output(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


class SQLiteStore:
    """Durable, thread-safe store of workflows and runs."""

    def __init__(self, db_path: str = "orchestrator.db") -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        """Close the underlying connection, if open."""

        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- workflows ---------------------------------------------------------

    def save_workflow(self, workflow: WorkflowSpec) -> WorkflowSpec:
        """Upsert a workflow specification by name."""

        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO workflows (name, spec_json) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET spec_json = excluded.spec_json",
                (workflow.name, workflow.model_dump_json()),
            )
            conn.commit()
        return workflow

    def load_workflow(self, name: str) -> WorkflowSpec | None:
        """Load a workflow by name, or ``None`` if it does not exist."""

        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT spec_json FROM workflows WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            return None
        return WorkflowSpec.model_validate_json(row["spec_json"])

    def list_workflows(self) -> list[WorkflowSpec]:
        """Return all registered workflows ordered by name."""

        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT spec_json FROM workflows ORDER BY name"
            ).fetchall()
        return [WorkflowSpec.model_validate_json(r["spec_json"]) for r in rows]

    def delete_workflow(self, name: str) -> None:
        """Delete a workflow by name."""

        with self._lock:
            conn = self._connect()
            conn.execute("DELETE FROM workflows WHERE name = ?", (name,))
            conn.commit()

    # -- runs --------------------------------------------------------------

    def save_run(self, run: RunRecord) -> RunRecord:
        """Persist a run and all of its step records (upsert semantics)."""

        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO runs (id, workflow_name, status, created_at, "
                "updated_at, workflow_json) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status = excluded.status, "
                "updated_at = excluded.updated_at, workflow_json = excluded.workflow_json",
                (
                    run.id,
                    run.workflow.name,
                    run.status.value,
                    run.created_at,
                    run.updated_at,
                    run.workflow.model_dump_json(),
                ),
            )
            conn.executemany(
                "INSERT INTO step_records (run_id, step_id, state, output_json, "
                "error, attempts, started_at, finished_at, approved) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id, step_id) DO UPDATE SET state = excluded.state, "
                "output_json = excluded.output_json, error = excluded.error, "
                "attempts = excluded.attempts, started_at = excluded.started_at, "
                "finished_at = excluded.finished_at, approved = excluded.approved",
                [
                    (
                        run.id,
                        rec.step_id,
                        rec.state.value,
                        _dump_output(rec.output),
                        rec.error,
                        rec.attempts,
                        rec.started_at,
                        rec.finished_at,
                        None if rec.approved is None else int(rec.approved),
                    )
                    for rec in run.records.values()
                ],
            )
            conn.commit()
        return run

    def load_run(self, run_id: str) -> RunRecord | None:
        """Load a run (with its step records) by id, or ``None``."""

        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            step_rows = conn.execute(
                "SELECT * FROM step_records WHERE run_id = ? ORDER BY rowid",
                (run_id,),
            ).fetchall()

        workflow = WorkflowSpec.model_validate_json(row["workflow_json"])
        records: dict[str, StepRecord] = {}
        for sr in step_rows:
            records[sr["step_id"]] = StepRecord(
                step_id=sr["step_id"],
                state=StepState(sr["state"]),
                output=_load_output(sr["output_json"]),
                error=sr["error"],
                attempts=sr["attempts"],
                started_at=sr["started_at"],
                finished_at=sr["finished_at"],
                approved=None if sr["approved"] is None else bool(sr["approved"]),
            )

        return RunRecord(
            id=row["id"],
            workflow=workflow,
            status=RunStatus(row["status"]),
            records=records,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_runs(self) -> list[RunRecord]:
        """Return all runs ordered by creation time (oldest first)."""

        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id FROM runs ORDER BY created_at, id"
            ).fetchall()
        runs: list[RunRecord] = []
        for row in rows:
            loaded = self.load_run(row["id"])
            if loaded is not None:
                runs.append(loaded)
        return runs

    def list_run_ids(self) -> list[str]:
        """Return all run ids ordered by creation time."""

        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id FROM runs ORDER BY created_at, id"
            ).fetchall()
        return [row["id"] for row in rows]

    def delete_run(self, run_id: str) -> None:
        """Delete a run and its step records."""

        with self._lock:
            conn = self._connect()
            conn.execute("DELETE FROM step_records WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            conn.commit()
