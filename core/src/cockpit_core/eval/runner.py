"""Scenario YAML loader + replay runner.

A scenario describes a sequence of (transcripts_in, expected_tool_calls,
expected_approvals, …) — without requiring live OpenAI or Postgres.
The runner drives the tool handlers directly (with the scenario-defined
approvals automatically resolving the dangerous-tool gate) and asserts
each expected outcome.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from cockpit_core.agent.contract import (
    SessionContext,
    Tool,
    ToolCallRequest,
)
from cockpit_core.guardrails.middleware import GuardrailRunner
from cockpit_core.verticals.loader import VerticalPack, load_vertical_from_path


@dataclass
class ExpectedToolCall:
    name: str
    args_contains: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExpectedApproval:
    tool: str
    decision: str  # 'approved' | 'denied' | 'timeout'
    via: str  # 'voice' | 'cockpit' | 'auto'


@dataclass
class Scenario:
    id: str
    description: str
    vertical: str
    surface: str = "browser"
    language: str = "en"
    user_inputs: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    expected_tool_calls: list[ExpectedToolCall] = field(default_factory=list)
    expected_approvals: list[ExpectedApproval] = field(default_factory=list)
    expected_no_pii: bool = True
    expected_mode: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    scenario_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    invoked_tools: list[dict[str, Any]] = field(default_factory=list)
    approval_decisions: list[dict[str, Any]] = field(default_factory=list)


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: scenario must be a mapping")
    return Scenario(
        id=str(raw.get("id", path.stem)),
        description=str(raw.get("description", "")),
        vertical=str(raw["vertical"]),
        surface=str(raw.get("surface", "browser")),
        language=str(raw.get("language", "en")),
        user_inputs=list(raw.get("user_inputs", [])),
        actions=list(raw.get("actions", [])),
        expected_tool_calls=[
            ExpectedToolCall(name=str(t["name"]), args_contains=dict(t.get("args_contains", {})))
            for t in raw.get("expected_tool_calls", [])
        ],
        expected_approvals=[
            ExpectedApproval(
                tool=str(a["tool"]),
                decision=str(a.get("decision", "approved")),
                via=str(a.get("via", "auto")),
            )
            for a in raw.get("expected_approvals", [])
        ],
        expected_no_pii=bool(raw.get("expected_no_pii", True)),
        expected_mode=raw.get("expected_mode"),
        raw=raw,
    )


def _ctx_for(scenario: Scenario) -> SessionContext:
    return SessionContext(
        conversation_id=f"eval-{scenario.id}",
        vertical=scenario.vertical,
        surface=scenario.surface,  # type: ignore[arg-type]
        mode="realtime2",
        persona=scenario.id,
        language=scenario.language,
    )


async def _maybe_run_tool(
    tool: Tool,
    req: ToolCallRequest,
    ctx: SessionContext,
    *,
    decision_for_dangerous: str,
    guardrails: GuardrailRunner,
) -> tuple[str, Any | None, str | None]:
    guard = await guardrails.before_tool_call(ctx, tool, req)
    if guard.blocked:
        return "blocked", None, guard.reason
    if tool.blast_radius == "dangerous" and decision_for_dangerous != "approved":
        return decision_for_dangerous, None, None
    try:
        result = await tool.handler(req, ctx)
        return "executed", result, None
    except Exception as e:
        return "failed", None, str(e)


async def run_scenario(
    scenario_path: Path,
    *,
    verticals_dir: Path | None = None,
) -> ScenarioResult:
    scenario = load_scenario(scenario_path)
    # Conventional layout: <repo>/verticals/<name>/scenarios/<id>.yaml
    parent_dir = scenario_path.parent.parent  # → <repo>/verticals/<name>
    candidates = [
        parent_dir,
        scenario_path.parent.parent.parent / "verticals" / scenario.vertical,
    ]
    if verticals_dir is not None:
        candidates.insert(0, verticals_dir / scenario.vertical)
    vertical_dir = next(
        (c for c in candidates if c.exists() and (c / "pack.yaml").exists()),
        None,
    )
    if vertical_dir is None:
        raise FileNotFoundError(
            f"vertical {scenario.vertical} not found near {scenario_path}"
        )

    pack: VerticalPack = load_vertical_from_path(vertical_dir)
    expected_by_tool: dict[str, ExpectedApproval] = {
        a.tool: a for a in scenario.expected_approvals
    }
    guardrails = GuardrailRunner()

    invocations: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    failures: list[str] = []

    ctx = _ctx_for(scenario)
    for action in scenario.actions:
        kind = action.get("kind")
        if kind == "tool":
            tool = pack.registry.get(str(action["name"]))
            req = ToolCallRequest(
                conversation_id=ctx.conversation_id,
                turn_id=f"{scenario.id}-turn",
                tool_name=tool.name,
                args=dict(action.get("args", {})),
                surface=ctx.surface,
                vertical=ctx.vertical,
            )
            decision = (
                expected_by_tool[tool.name].decision
                if tool.name in expected_by_tool
                else "approved"
            )
            status, result, error = await _maybe_run_tool(
                tool,
                req,
                ctx,
                decision_for_dangerous=decision,
                guardrails=guardrails,
            )
            invocations.append(
                {
                    "name": tool.name,
                    "args": req.args,
                    "status": status,
                    "result": result,
                    "error": error,
                }
            )
            if tool.blast_radius == "dangerous":
                approvals.append({"tool": tool.name, "decision": decision})
        elif kind == "mode":
            ctx.mode = str(action["mode"])  # type: ignore[assignment]
        elif kind == "language":
            ctx.language = str(action["language"])
        else:
            failures.append(f"unknown action kind: {kind!r}")

    for expected in scenario.expected_tool_calls:
        match = next(
            (
                inv
                for inv in invocations
                if inv["name"] == expected.name
                and inv["status"] == "executed"
                and all(inv["args"].get(k) == v for k, v in expected.args_contains.items())
            ),
            None,
        )
        if match is None:
            failures.append(
                f"expected tool {expected.name!r} executed with args "
                f"containing {json.dumps(expected.args_contains)} not found"
            )

    for approval in scenario.expected_approvals:
        match = next(
            (
                a
                for a in approvals
                if a["tool"] == approval.tool and a["decision"] == approval.decision
            ),
            None,
        )
        if match is None:
            failures.append(
                f"expected approval for {approval.tool!r} as {approval.decision!r} not observed"
            )

    if scenario.expected_mode is not None and ctx.mode != scenario.expected_mode:
        failures.append(
            f"expected mode {scenario.expected_mode!r} at end, got {ctx.mode!r}"
        )

    return ScenarioResult(
        scenario_id=scenario.id,
        passed=len(failures) == 0,
        failures=failures,
        invoked_tools=invocations,
        approval_decisions=approvals,
    )
