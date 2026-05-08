"""Loads a vertical pack from disk into runtime objects."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from cockpit_core.agent.contract import Tool
from cockpit_core.agent.registry import ToolRegistry
from cockpit_core.guardrails.middleware import GuardrailRunner
from cockpit_core.settings import get_settings


class PackLoadError(ValueError):
    """Raised when a vertical pack on disk does not match the schema."""


@dataclass
class VerticalPack:
    name: str
    version: str
    persona: str
    modes: list[str]
    surfaces: list[str]
    languages: list[str]
    auto_translate_non_english: bool
    prompt: str
    tools: list[Tool]
    registry: ToolRegistry
    guardrails: GuardrailRunner
    approvals_config: dict[str, Any]
    preambles: dict[str, str]
    post_call: Callable[[Any], Awaitable[None]] | None = None
    raw_pack_yaml: dict[str, Any] = field(default_factory=dict)
    raw_policy_yaml: dict[str, Any] = field(default_factory=dict)

    def approval_phrase(self, tool_name: str) -> str | None:
        entry = self.approvals_config.get(tool_name)
        if not entry:
            return None
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            phrase = entry.get("phrase")
            return str(phrase) if phrase else None
        return None

    def approval_timeout(self, tool_name: str, default: int = 60) -> int:
        entry = self.approvals_config.get(tool_name)
        if isinstance(entry, dict):
            timeout = entry.get("timeout_seconds")
            if isinstance(timeout, int):
                return timeout
        return default


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PackLoadError(f"missing required file: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PackLoadError(f"{path} must be a YAML mapping at the top level")
    return raw


def _load_module(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PackLoadError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_pack_namespace(pack_dir: Path, name: str) -> None:
    """Register `verticals` and `verticals.<name>` as namespace packages so
    that relative imports inside the pack (e.g. ``from . import sandbox``)
    resolve against the real on-disk files.
    """
    parent_name = "verticals"
    if parent_name not in sys.modules:
        parent = ModuleType(parent_name)
        parent.__path__ = [str(pack_dir.parent)]  # type: ignore[attr-defined]
        sys.modules[parent_name] = parent

    pkg_name = f"{parent_name}.{name}"
    if pkg_name not in sys.modules:
        pkg = ModuleType(pkg_name)
        pkg.__path__ = [str(pack_dir)]  # type: ignore[attr-defined]
        sys.modules[pkg_name] = pkg

    sandbox_path = pack_dir / "sandbox.py"
    if sandbox_path.exists():
        _load_module(f"{pkg_name}.sandbox", sandbox_path)


def _require_field(data: dict[str, Any], key: str, where: Path) -> Any:
    if key not in data:
        raise PackLoadError(f"missing required field {key!r} in {where}")
    return data[key]


def load_vertical_from_path(pack_dir: Path) -> VerticalPack:
    if not pack_dir.is_dir():
        raise PackLoadError(f"vertical directory not found: {pack_dir}")

    pack_yaml = _load_yaml(pack_dir / "pack.yaml")
    name = str(_require_field(pack_yaml, "name", pack_dir / "pack.yaml"))
    version = str(pack_yaml.get("version", "0.0.0"))
    persona = str(pack_yaml.get("persona", name))
    modes = list(pack_yaml.get("modes", ["realtime2"]))
    surfaces = list(pack_yaml.get("surfaces", ["browser", "phone"]))
    languages = list(pack_yaml.get("languages", ["en"]))
    auto_translate = bool(pack_yaml.get("auto_translate_non_english", False))

    prompt_path = pack_dir / "prompt.md"
    if not prompt_path.exists():
        raise PackLoadError(f"missing required prompt.md in {pack_dir}")
    prompt = prompt_path.read_text(encoding="utf-8")

    policy = _load_yaml(pack_dir / "policy.yaml")
    approvals_yaml = _load_yaml(pack_dir / "approvals.yaml")
    approvals_config: dict[str, Any] = approvals_yaml.get("tools", {}) or {}

    preambles_yaml = _load_yaml(pack_dir / "preambles.yaml")
    preambles: dict[str, str] = {
        k: str(v) for k, v in (preambles_yaml.get("preambles", {}) or {}).items()
    }

    _ensure_pack_namespace(pack_dir, name)
    tools_module = _load_module(f"verticals.{name}.tools", pack_dir / "tools.py")
    if not hasattr(tools_module, "TOOLS"):
        raise PackLoadError(
            f"{pack_dir / 'tools.py'} must export a TOOLS list of Tool dataclasses"
        )
    tools_obj = tools_module.TOOLS
    if not isinstance(tools_obj, list) or not all(isinstance(t, Tool) for t in tools_obj):
        raise PackLoadError(
            f"{pack_dir / 'tools.py'}: TOOLS must be list[Tool]"
        )

    for tool in tools_obj:
        if tool.preamble is None and tool.name in preambles:
            tool.preamble = preambles[tool.name]
        if tool.blast_radius == "dangerous":
            phrase = approvals_config.get(tool.name)
            if isinstance(phrase, dict):
                phrase = phrase.get("phrase")
            if phrase:
                tool.preamble = str(phrase)

    registry = ToolRegistry(tools_obj)
    guardrails = GuardrailRunner()  # vertical-specific hooks layered later

    post_call_fn: Callable[[Any], Awaitable[None]] | None = None
    post_call_path = pack_dir / "post_call.py"
    if post_call_path.exists():
        mod = _load_module(f"verticals.{name}.post_call", post_call_path)
        post_call_fn = getattr(mod, "post_call", None)

    return VerticalPack(
        name=name,
        version=version,
        persona=persona,
        modes=modes,
        surfaces=surfaces,
        languages=languages,
        auto_translate_non_english=auto_translate,
        prompt=prompt,
        tools=tools_obj,
        registry=registry,
        guardrails=guardrails,
        approvals_config=approvals_config,
        preambles=preambles,
        post_call=post_call_fn,
        raw_pack_yaml=pack_yaml,
        raw_policy_yaml=policy,
    )


def load_vertical(name: str) -> VerticalPack:
    settings = get_settings()
    return load_vertical_from_path(Path(settings.verticals_dir) / name)
