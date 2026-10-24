"""Tools: argument checks, approval and the budget (no database, no model)."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ValidationError

from app.tools.agents import AgentState, Tool, enforce_budget


class CountArgs(BaseModel):
    band: Literal["No risk", "Low", "Moderate", "High"] | None = None


def count_tool(**options):
    return Tool("count_cases", "Count cases", CountArgs, lambda band=None: {"band": band, "count": 10}, **options)


def test_valid_arguments_run_the_function():
    assert count_tool().invoke({"band": "High"}) == {"band": "High", "count": 10}


def test_wrong_arguments_never_run():
    with pytest.raises(ValidationError):
        count_tool().invoke({"band": "Very high"})


def test_approval_needed_before_running():
    tool = count_tool(requires_approval=True)
    with pytest.raises(PermissionError):
        tool.invoke({"band": "High"})
    assert tool.invoke({"band": "High"}, approved=True)["count"] == 10


@pytest.mark.parametrize("state,message", [(AgentState(steps=6), "step budget"),
                                           (AgentState(tool_calls=4), "tool-call budget")])
def test_budget_stops_a_loop(state, message):
    with pytest.raises(RuntimeError, match=message):
        enforce_budget(state)
    enforce_budget(AgentState(steps=5, tool_calls=3))     # within the limits: no error
