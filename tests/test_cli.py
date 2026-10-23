"""Tests for the command-line interface."""

from __future__ import annotations

import json

import pytest

from agent_orchestrator import cli


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _echo_workflow(tmp_path, name="demo"):
    return _write(
        tmp_path / f"{name}.json",
        {"name": name, "steps": [{"id": "a", "tool": "echo", "inputs": {"text": "hi"}}]},
    )


def test_build_parser():
    parser = cli.build_parser()
    assert parser.prog == "agent_orchestrator"


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_run_success(tmp_path, capsys):
    db = tmp_path / "o.db"
    wf = _echo_workflow(tmp_path)
    rc = cli.main(["--db", str(db), "run", wf])
    out = capsys.readouterr().out
    assert rc == 0
    assert "succeeded" in out
    assert "a" in out


def test_run_json_output(tmp_path, capsys):
    db = tmp_path / "o.db"
    wf = _echo_workflow(tmp_path)
    rc = cli.main(["--db", str(db), "--json", "run", wf])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["status"] == "succeeded"


def test_run_failure_returns_one(tmp_path, capsys):
    db = tmp_path / "o.db"
    wf = _write(
        tmp_path / "fail.json",
        {
            "name": "failwf",
            "steps": [{"id": "a", "tool": "fail", "retry": {"max_attempts": 1}}],
        },
    )
    rc = cli.main(["--db", str(db), "run", wf])
    assert rc == 1
    assert "failed" in capsys.readouterr().out


def test_status_and_list(tmp_path, capsys):
    db = tmp_path / "o.db"
    wf = _echo_workflow(tmp_path)
    cli.main(["--db", str(db), "run", wf, "--run-id", "run-1"])
    capsys.readouterr()

    rc = cli.main(["--db", str(db), "status", "run-1"])
    assert rc == 0
    assert "run-1" in capsys.readouterr().out

    rc = cli.main(["--db", str(db), "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "run-1" in out
    assert "demo" in out


def test_status_missing_returns_one(tmp_path, capsys):
    db = tmp_path / "o.db"
    rc = cli.main(["--db", str(db), "status", "nope"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_list_json_empty(tmp_path, capsys):
    db = tmp_path / "o.db"
    rc = cli.main(["--db", str(db), "--json", "list"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_resume_failed_run(tmp_path, capsys):
    db = tmp_path / "o.db"
    wf = _write(
        tmp_path / "fail.json",
        {
            "name": "failwf",
            "steps": [{"id": "a", "tool": "fail", "retry": {"max_attempts": 1}}],
        },
    )
    cli.main(["--db", str(db), "run", wf, "--run-id", "run-x"])
    capsys.readouterr()
    rc = cli.main(["--db", str(db), "resume", "run-x"])
    assert rc == 1
    assert "run-x" in capsys.readouterr().out
