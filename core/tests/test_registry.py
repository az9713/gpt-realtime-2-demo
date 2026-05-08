import pytest

from cockpit_core.agent.contract import Tool
from cockpit_core.agent.registry import ToolRegistry, UnknownToolError


async def _noop(_req, _ctx):
    return {"ok": True}


def _tool(name: str, blast: str = "read") -> Tool:
    return Tool(
        name=name,
        description="t",
        schema={"type": "object", "properties": {}, "required": []},
        blast_radius=blast,  # type: ignore[arg-type]
        handler=_noop,
    )


def test_register_and_get():
    r = ToolRegistry([_tool("a")])
    r.register(_tool("b"))
    assert r.has("a") and r.has("b")
    assert r.get("a").name == "a"


def test_duplicate_register_rejected():
    r = ToolRegistry([_tool("a")])
    with pytest.raises(ValueError):
        r.register(_tool("a"))


def test_unknown_tool_raises():
    r = ToolRegistry()
    with pytest.raises(UnknownToolError):
        r.get("missing")


def test_schemas_shape_for_realtime():
    r = ToolRegistry([_tool("a")])
    schemas = r.schemas()
    assert schemas[0]["type"] == "function"
    assert schemas[0]["name"] == "a"
    assert "parameters" in schemas[0]
