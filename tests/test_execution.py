"""Durable execution tests use real database transactions; remote doubles stay in tests."""

import importlib.util

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect


def test_execution_schema_and_strict_contracts(client_factory):
    assert importlib.util.find_spec("videotranslate.models.execution"), "Execution schema missing"
    from videotranslate.execution.contracts import RunCreate, RunRetry
    from videotranslate.models.execution import InputState, ProjectEvent, RunAttempt, StageRun

    client = client_factory()
    tables = inspect(client.app.state.engine).get_table_names()
    assert {
        StageRun.__tablename__,
        RunAttempt.__tablename__,
        InputState.__tablename__,
        ProjectEvent.__tablename__,
    } <= set(tables)
    assert "event_sequence" in {
        c["name"] for c in inspect(client.app.state.engine).get_columns("projects")
    }
    for body in ({"stage": ""}, {"stage": "x" * 41}, {"stage": "probe", "surprise": True}):
        with pytest.raises(ValidationError):
            RunCreate(**body)
    assert RunRetry().acknowledge_uncertain_submission is False
    with pytest.raises(ValidationError):
        RunRetry(acknowledge_uncertain_submission="yes")
