import json
import asyncio
from typing import Dict, Set, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from schemas import StateTransitionEvent, SecurityLogEvent, SystemSettingsModel
from database import (
    init_db,
    log_transition,
    log_security_event,
    get_run_transitions,
    get_all_security_logs,
    get_all_runs,
    get_latest_run_id,
    get_settings,
    save_setting
)
from security_scanner import agent_guard
from visualizer import (
    render_debugger_html,
    render_vector_scanning_html,
    render_settings_html,
    render_run_explorer_html
)

app = FastAPI(
    title="TraceDiff Enterprise Observability Sidecar",
    description="Enterprise Multi-Agent Tracing, State Delta Diffing, and Security Guardrail Sidecar",
    version="2.1.0"
)

# In-memory pub/sub queues for Real-Time Server-Sent Events (SSE)
RUN_SUBSCRIBERS: Dict[str, Set[asyncio.Queue]] = {}

def broadcast_to_run(run_id: str, message: dict):
    """Pushes a message to all active SSE subscribers listening to run_id."""
    if run_id in RUN_SUBSCRIBERS:
        for q in list(RUN_SUBSCRIBERS[run_id]):
            try:
                q.put_nowait(message)
            except Exception:
                pass

@app.on_event("startup")
def startup_event():
    init_db()

# --- Telemetry & Ingestion APIs ---

@app.post("/api/v1/log-transition")
def api_log_transition(event: StateTransitionEvent):
    # 1. Log transition and calculate diffs/costs in database
    row_id = log_transition(event)
    
    # 2. Check settings for automated real-time AgentGuard security scanning
    settings = get_settings()
    if settings.get("auto_security_scan", "true") == "true":
        threats = agent_guard.scan_transition(
            run_id=event.run_id,
            node_name=event.node_name,
            state_before=event.state_before,
            state_after=event.state_after,
            tool_calls=event.tool_calls
        )
        for threat in threats:
            log_security_event(threat)

    # 3. Broadcast to real-time live listeners
    broadcast_to_run(event.run_id, {
        "type": "new_transition",
        "node_name": event.node_name,
        "token_count": event.token_count,
        "step_index": event.step_index
    })
    
    return {"status": "logged", "row_id": row_id, "run_id": event.run_id}

@app.post("/api/v1/log-security")
def api_log_security(event: SecurityLogEvent):
    row_id = log_security_event(event)
    return {"status": "logged", "security_event_id": row_id, "threat_level": event.threat_level}

@app.get("/api/v1/stream/{run_id}")
async def stream_run_events(run_id: str):
    """Server-Sent Events (SSE) stream for real-time live debugger updates."""
    async def event_generator():
        queue = asyncio.Queue()
        if run_id not in RUN_SUBSCRIBERS:
            RUN_SUBSCRIBERS[run_id] = set()
        RUN_SUBSCRIBERS[run_id].add(queue)
        
        yield f"data: {json.dumps({'type': 'connected', 'run_id': run_id})}\n\n"
        
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield f": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if run_id in RUN_SUBSCRIBERS:
                RUN_SUBSCRIBERS[run_id].discard(queue)
                if not RUN_SUBSCRIBERS[run_id]:
                    del RUN_SUBSCRIBERS[run_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.get("/api/v1/runs")
def api_get_runs():
    return get_all_runs()

@app.get("/api/v1/settings")
def api_get_settings():
    return get_settings()

@app.post("/api/v1/settings")
def api_save_settings(settings: SystemSettingsModel):
    save_setting("data_retention_days", str(settings.data_retention_days))
    save_setting("ollama_gateway_url", settings.ollama_gateway_url)
    save_setting("auto_security_scan", "true" if settings.auto_security_scan else "false")
    save_setting("token_budget_alert_threshold", str(settings.token_budget_alert_threshold))
    save_setting("default_pricing_model", settings.default_pricing_model)
    return {"status": "success", "message": "Settings updated"}

# --- Web UI Pages ---

@app.get("/", response_class=HTMLResponse)
def root_view():
    latest = get_latest_run_id()
    if latest:
        return RedirectResponse(url=f"/debug/{latest}")
    return RedirectResponse(url="/runs")

@app.get("/debug", response_class=HTMLResponse)
def debug_default_view():
    latest = get_latest_run_id()
    if latest:
        return RedirectResponse(url=f"/debug/{latest}")
    return RedirectResponse(url="/runs")

@app.get("/debug/{run_id}", response_class=HTMLResponse)
def get_debug_view(run_id: str):
    transitions = get_run_transitions(run_id)
    if not transitions:
        raise HTTPException(status_code=404, detail="Run ID not found")
    return render_debugger_html(run_id, transitions)

@app.get("/runs", response_class=HTMLResponse)
def get_runs_view():
    return render_run_explorer_html()

@app.get("/vector-scanning", response_class=HTMLResponse)
def get_vector_scanning_view():
    logs = get_all_security_logs(limit=100)
    return render_vector_scanning_html(logs)

@app.get("/settings", response_class=HTMLResponse)
def get_settings_view():
    return render_settings_html()
