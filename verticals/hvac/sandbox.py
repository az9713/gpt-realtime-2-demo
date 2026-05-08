"""HVAC sandbox data store backed by JSON fixtures.

A real production deployment would swap this for a CRM/ServiceTitan/
ServiceM8 adapter. Reading from JSON keeps v1 dev-friendly and
deterministic for evals.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(os.environ.get("HVAC_FIXTURE_DIR", str(Path(__file__).parent / "fixtures")))


def _load(name: str) -> Any:
    path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save(name: str, data: Any) -> None:
    path = FIXTURE_DIR / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


@dataclass
class SandboxState:
    parts: list[dict[str, Any]] = field(default_factory=list)
    trucks: list[dict[str, Any]] = field(default_factory=list)
    customers: list[dict[str, Any]] = field(default_factory=list)
    warranties: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[dict[str, Any]] = field(default_factory=list)


def load_state() -> SandboxState:
    return SandboxState(
        parts=_load("parts"),
        trucks=_load("trucks"),
        customers=_load("customers"),
        warranties=_load("warranties"),
        jobs=_load("jobs"),
    )


def save_jobs(jobs: list[dict[str, Any]]) -> None:
    _save("jobs", jobs)


def save_trucks(trucks: list[dict[str, Any]]) -> None:
    _save("trucks", trucks)
