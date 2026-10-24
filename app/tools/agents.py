"""Tools the model can ask for, and the limits on using them.

    question -> model chooses a tool -> Tool.invoke checks the arguments -> Python runs it -> model answers

A Tool checks the model's arguments with Pydantic before anything runs, so
a wrong argument never reaches the database. A tool that needs a person's
OK first (requires_approval) refuses to run without it. The budget stops a
model that keeps calling tools in a loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    function: Callable[..., Any]
    requires_approval: bool = False

    def invoke(self, raw_args: dict[str, Any], *, approved: bool = False) -> Any:
        if self.requires_approval and not approved:
            raise PermissionError(f"Human approval required for {self.name}")
        args = self.args_model.model_validate(raw_args)
        return self.function(**args.model_dump())


@dataclass
class AgentState:
    messages: list[dict[str, str]] = field(default_factory=list)
    steps: int = 0
    tool_calls: int = 0
    cost_units: int = 0
    stopped_reason: str | None = None


def enforce_budget(state: AgentState, *, max_steps: int = 6, max_tool_calls: int = 4, max_cost_units: int = 100) -> None:
    if state.steps >= max_steps:
        raise RuntimeError("step budget exhausted")
    if state.tool_calls >= max_tool_calls:
        raise RuntimeError("tool-call budget exhausted")
    if state.cost_units >= max_cost_units:
        raise RuntimeError("cost budget exhausted")
