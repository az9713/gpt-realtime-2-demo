"""HVAC tool implementations. Backed by fixture data via sandbox.py."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cockpit_core.agent.contract import (
    SessionContext,
    Tool,
    ToolCallRequest,
)

from . import sandbox  # type: ignore[attr-defined]
# When loaded by the vertical loader the module name is
# "verticals.hvac.tools"; the relative import works because sandbox.py
# is loaded into "verticals.hvac.sandbox" by the loader.


# ---------- read tools ----------


async def parts_lookup_handler(
    req: ToolCallRequest, _ctx: SessionContext
) -> dict[str, Any]:
    state = sandbox.load_state()
    model = str(req.args.get("model_number", "")).lower()
    desc = str(req.args.get("part_description", "")).lower()
    matches = [
        p
        for p in state.parts
        if (not model or model in p.get("model_number", "").lower())
        and (not desc or desc in p.get("description", "").lower())
    ]
    return {"matches": matches[:10], "total_matches": len(matches)}


async def truck_inventory_handler(
    req: ToolCallRequest, _ctx: SessionContext
) -> dict[str, Any]:
    state = sandbox.load_state()
    truck_id = str(req.args.get("truck_id", ""))
    part_number = str(req.args.get("part_number", ""))
    truck = next((t for t in state.trucks if t.get("id") == truck_id), None)
    if truck is None:
        return {"found": False, "error": f"unknown truck: {truck_id}"}
    if part_number:
        stock = next(
            (s for s in truck.get("stock", []) if s.get("part_number") == part_number),
            None,
        )
        return {"found": stock is not None, "stock": stock}
    return {"found": True, "truck": truck}


async def warranty_check_handler(
    req: ToolCallRequest, _ctx: SessionContext
) -> dict[str, Any]:
    state = sandbox.load_state()
    serial = str(req.args.get("unit_serial", ""))
    record = next((w for w in state.warranties if w.get("unit_serial") == serial), None)
    if record is None:
        return {"covered": False, "reason": "no warranty record on file"}
    return {"covered": record.get("status") == "active", "record": record}


async def schedule_lookup_handler(
    req: ToolCallRequest, _ctx: SessionContext
) -> dict[str, Any]:
    state = sandbox.load_state()
    start = req.args.get("start") or "0"
    end = req.args.get("end") or "9"
    tech = req.args.get("tech_id")
    jobs = [
        j
        for j in state.jobs
        if str(j.get("scheduled_at", ""))[:10] >= str(start)[:10]
        and str(j.get("scheduled_at", ""))[:10] <= str(end)[:10]
        and (tech is None or j.get("tech_id") == tech)
    ]
    return {"jobs": jobs[:25], "total": len(jobs)}


async def customer_lookup_handler(
    req: ToolCallRequest, _ctx: SessionContext
) -> dict[str, Any]:
    state = sandbox.load_state()
    phone = str(req.args.get("phone", ""))
    address = str(req.args.get("address", "")).lower()
    matches = [
        c
        for c in state.customers
        if (phone and phone in c.get("phone", ""))
        or (address and address in c.get("address", "").lower())
    ]
    return {"matches": matches[:10], "total": len(matches)}


# ---------- dangerous tools (approval-gated) ----------


async def schedule_move_handler(
    req: ToolCallRequest, _ctx: SessionContext
) -> dict[str, Any]:
    state = sandbox.load_state()
    job_id = str(req.args.get("job_id", ""))
    new_slot = str(req.args.get("new_slot", ""))
    job = next((j for j in state.jobs if j.get("id") == job_id), None)
    if job is None:
        return {"ok": False, "error": f"unknown job: {job_id}"}
    job["scheduled_at"] = new_slot
    job["last_modified"] = datetime.utcnow().isoformat() + "Z"
    sandbox.save_jobs(state.jobs)
    return {"ok": True, "job": job}


async def dispatch_truck_handler(
    req: ToolCallRequest, _ctx: SessionContext
) -> dict[str, Any]:
    state = sandbox.load_state()
    job_id = str(req.args.get("job_id", ""))
    truck_id = str(req.args.get("truck_id", ""))
    job = next((j for j in state.jobs if j.get("id") == job_id), None)
    truck = next((t for t in state.trucks if t.get("id") == truck_id), None)
    if job is None or truck is None:
        return {"ok": False, "error": "unknown job or truck"}
    job["assigned_truck"] = truck_id
    job["status"] = "dispatched"
    job["dispatched_at"] = datetime.utcnow().isoformat() + "Z"
    sandbox.save_jobs(state.jobs)
    return {"ok": True, "job": job, "truck": truck}


TOOLS: list[Tool] = [
    Tool(
        name="parts_lookup",
        description="Look up parts by model number and/or description.",
        schema={
            "type": "object",
            "properties": {
                "model_number": {"type": "string", "description": "HVAC unit model number"},
                "part_description": {"type": "string", "description": "free-text description"},
            },
            "required": [],
        },
        blast_radius="read",
        handler=parts_lookup_handler,
    ),
    Tool(
        name="truck_inventory",
        description="Check what stock a truck currently has.",
        schema={
            "type": "object",
            "properties": {
                "truck_id": {"type": "string"},
                "part_number": {"type": "string"},
            },
            "required": ["truck_id"],
        },
        blast_radius="read",
        handler=truck_inventory_handler,
    ),
    Tool(
        name="warranty_check",
        description="Check warranty status for a unit by serial number.",
        schema={
            "type": "object",
            "properties": {"unit_serial": {"type": "string"}},
            "required": ["unit_serial"],
        },
        blast_radius="read",
        handler=warranty_check_handler,
    ),
    Tool(
        name="schedule_lookup",
        description="List scheduled jobs in a date range, optionally for one tech.",
        schema={
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "end": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "tech_id": {"type": "string"},
            },
            "required": ["start", "end"],
        },
        blast_radius="read",
        handler=schedule_lookup_handler,
    ),
    Tool(
        name="customer_lookup",
        description="Look up a customer by phone or address.",
        schema={
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "address": {"type": "string"},
            },
            "required": [],
        },
        blast_radius="read",
        handler=customer_lookup_handler,
    ),
    Tool(
        name="schedule_move",
        description="Move a scheduled job to a new time slot. Dangerous; requires approval.",
        schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "new_slot": {"type": "string", "description": "ISO datetime"},
            },
            "required": ["job_id", "new_slot"],
        },
        blast_radius="dangerous",
        handler=schedule_move_handler,
    ),
    Tool(
        name="dispatch_truck",
        description="Dispatch a truck to a job. Dangerous; requires approval.",
        schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "truck_id": {"type": "string"},
            },
            "required": ["job_id", "truck_id"],
        },
        blast_radius="dangerous",
        handler=dispatch_truck_handler,
    ),
]
