import pytest

from cockpit_core.agent.contract import SessionContext, Tool, ToolCallRequest
from cockpit_core.guardrails.middleware import GuardrailDecision, GuardrailRunner


@pytest.fixture
def ctx():
    return SessionContext(
        conversation_id="c1",
        vertical="hvac",
        surface="browser",
        mode="realtime2",
        persona="Aria",
    )


@pytest.fixture
def tool():
    async def _h(_req, _ctx):
        return {"ok": True}

    return Tool(
        name="x",
        description="x",
        schema={"type": "object", "properties": {}, "required": []},
        blast_radius="read",
        handler=_h,
    )


@pytest.mark.asyncio
async def test_post_call_redacts_pii(ctx, monkeypatch):
    monkeypatch.setattr("cockpit_core.guardrails.middleware.emit", lambda **_: None)
    g = GuardrailRunner()
    out = await g.after_agent_output(ctx, "email me at jane@x.com")
    assert "[email]" in out


@pytest.mark.asyncio
async def test_tool_hook_can_block(ctx, tool, monkeypatch):
    monkeypatch.setattr("cockpit_core.guardrails.middleware.emit", lambda **_: None)

    async def deny(_ctx, _tool, _req):
        return GuardrailDecision(blocked=True, reason="policy")

    g = GuardrailRunner(tool_hooks=[deny])
    req = ToolCallRequest(
        conversation_id="c1",
        turn_id="t1",
        tool_name="x",
        args={},
        surface="browser",
        vertical="hvac",
    )
    decision = await g.before_tool_call(ctx, tool, req)
    assert decision.blocked
    assert decision.reason == "policy"


@pytest.mark.asyncio
async def test_pre_hooks_compose(ctx, monkeypatch):
    monkeypatch.setattr("cockpit_core.guardrails.middleware.emit", lambda **_: None)

    async def upper(_ctx, text):
        return text.upper()

    async def trim(_ctx, text):
        return text.strip()

    g = GuardrailRunner(pre_hooks=[trim, upper])
    out = await g.before_user_input(ctx, "  hi  ")
    assert out == "HI"
