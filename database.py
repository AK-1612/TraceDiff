import sqlite3
import json
from typing import Dict, Any, List, Optional
from schemas import StateTransitionEvent, SecurityLogEvent
from diff_engine import compute_state_diff, calculate_token_cost

DB_NAME = "tracediff.db"

def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Transitions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            node_name TEXT,
            parent_node TEXT,
            step_index INTEGER DEFAULT 0,
            state_before TEXT,
            state_after TEXT,
            tool_calls TEXT,
            token_count INTEGER,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            model_name TEXT DEFAULT 'default',
            estimated_cost_usd REAL DEFAULT 0.0,
            latency_ms REAL DEFAULT 0.0,
            diff_summary TEXT,
            timestamp TEXT
        )
    """)
    
    # Run migrations for existing columns if needed
    columns_to_add = [
        ("parent_node", "TEXT"),
        ("step_index", "INTEGER DEFAULT 0"),
        ("prompt_tokens", "INTEGER DEFAULT 0"),
        ("completion_tokens", "INTEGER DEFAULT 0"),
        ("model_name", "TEXT DEFAULT 'default'"),
        ("estimated_cost_usd", "REAL DEFAULT 0.0"),
        ("latency_ms", "REAL DEFAULT 0.0"),
        ("diff_summary", "TEXT")
    ]
    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE transitions ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass # Already exists
            
    # 2. Security Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS security_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            node_name TEXT,
            threat_level TEXT,
            category TEXT DEFAULT 'ADVERSARIAL_INPUT',
            details TEXT,
            raw_payload_snippet TEXT,
            timestamp TEXT
        )
    """)
    sec_cols = [
        ("category", "TEXT DEFAULT 'ADVERSARIAL_INPUT'"),
        ("raw_payload_snippet", "TEXT")
    ]
    for col_name, col_type in sec_cols:
        try:
            cursor.execute(f"ALTER TABLE security_logs ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass

    # 3. Settings Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Default settings if empty
    defaults = {
        "data_retention_days": "30",
        "ollama_gateway_url": "http://localhost:11434/api/generate",
        "auto_security_scan": "true",
        "token_budget_alert_threshold": "4000",
        "default_pricing_model": "gpt-4o-mini"
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

def init_security_db():
    # Kept for backward compatibility; calls init_db()
    init_db()

def log_transition(event: StateTransitionEvent) -> int:
    # Auto-calculate tokens if breakdown is provided
    if event.token_count == 0 and (event.prompt_tokens + event.completion_tokens > 0):
        event.token_count = event.prompt_tokens + event.completion_tokens
    elif event.token_count > 0 and (event.prompt_tokens + event.completion_tokens == 0):
        event.prompt_tokens = int(event.token_count * 0.7)
        event.completion_tokens = event.token_count - event.prompt_tokens
        
    # Auto-calculate cost if not provided
    if event.estimated_cost_usd == 0.0 and event.token_count > 0:
        event.estimated_cost_usd = calculate_token_cost(event.model_name, event.prompt_tokens, event.completion_tokens)
        
    # Auto-calculate structural state diff if not provided
    diff_data = event.diff_summary
    if not diff_data:
        diff_data = compute_state_diff(event.state_before, event.state_after)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transitions (
            run_id, node_name, parent_node, step_index,
            state_before, state_after, tool_calls,
            token_count, prompt_tokens, completion_tokens,
            model_name, estimated_cost_usd, latency_ms,
            diff_summary, timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event.run_id,
        event.node_name,
        event.parent_node,
        event.step_index,
        json.dumps(event.state_before),
        json.dumps(event.state_after),
        json.dumps(event.tool_calls or []),
        event.token_count,
        event.prompt_tokens,
        event.completion_tokens,
        event.model_name,
        event.estimated_cost_usd,
        event.latency_ms,
        json.dumps(diff_data),
        event.timestamp
    ))
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id

def log_security_event(event: SecurityLogEvent) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO security_logs (run_id, node_name, threat_level, category, details, raw_payload_snippet, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        event.run_id,
        event.node_name,
        event.threat_level,
        event.category,
        event.details,
        event.raw_payload_snippet,
        event.timestamp
    ))
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id

def get_run_transitions(run_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transitions WHERE run_id = ? ORDER BY id ASC", (run_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_run_summary(run_id: str) -> Dict[str, Any]:
    transitions = get_run_transitions(run_id)
    if not transitions:
        return {}
    
    total_tokens = sum(t.get("token_count", 0) for t in transitions)
    total_prompt_tokens = sum(t.get("prompt_tokens", 0) for t in transitions)
    total_completion_tokens = sum(t.get("completion_tokens", 0) for t in transitions)
    total_cost = sum(t.get("estimated_cost_usd", 0.0) for t in transitions)
    total_latency = sum(t.get("latency_ms", 0.0) for t in transitions)
    
    error_count = 0
    for t in transitions:
        tools = json.loads(t.get("tool_calls") or "[]")
        if any(call.get("error") or call.get("status") == "error" for call in tools):
            error_count += 1
            
    return {
        "run_id": run_id,
        "total_nodes": len(transitions),
        "total_tokens": total_tokens,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "estimated_cost_usd": round(total_cost, 6),
        "total_latency_ms": round(total_latency, 2),
        "error_count": error_count,
        "first_timestamp": transitions[0].get("timestamp") if transitions else "",
        "last_timestamp": transitions[-1].get("timestamp") if transitions else ""
    }

def get_all_runs() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            run_id, 
            COUNT(*) as node_count, 
            SUM(token_count) as total_tokens, 
            SUM(estimated_cost_usd) as total_cost,
            MIN(timestamp) as started_at,
            MAX(timestamp) as last_updated
        FROM transitions 
        GROUP BY run_id 
        ORDER BY MAX(id) DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    runs = []
    for r in rows:
        run_data = dict(r)
        run_id = run_data["run_id"]
        # Check if run had errors
        conn2 = get_connection()
        c2 = conn2.cursor()
        c2.execute("SELECT tool_calls FROM transitions WHERE run_id = ?", (run_id,))
        tool_rows = c2.fetchall()
        conn2.close()
        
        has_error = False
        for trow in tool_rows:
            try:
                tools = json.loads(trow[0] or "[]")
                if any(tool.get("error") or tool.get("status") == "error" for tool in tools):
                    has_error = True
                    break
            except Exception:
                pass
                
        run_data["has_error"] = has_error
        runs.append(run_data)
        
    return runs

def get_latest_run_id() -> str:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT run_id FROM transitions ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else ""
    except Exception:
        return ""

def get_all_security_logs(limit: int = 100, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    if run_id:
        cursor.execute("SELECT * FROM security_logs WHERE run_id = ? ORDER BY id DESC LIMIT ?", (run_id, limit))
    else:
        cursor.execute("SELECT * FROM security_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_settings() -> Dict[str, str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def save_setting(key: str, value: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()
