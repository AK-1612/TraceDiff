import json
import sqlite3
from typing import List, Dict, Any, Optional
from database import get_connection, get_all_runs, get_latest_run_id, get_run_summary, get_settings
from diff_engine import render_diff_html, compute_state_diff

def generate_mermaid_graph(transitions: List[Dict[str, Any]]) -> str:
    """
    Generates a Mermaid.js flowchart string mapping out complex agent state hops,
    supporting DAG branches, parent references, failure states, and cyclic retry loops.
    """
    if not transitions:
        return 'graph TD\n    empty["No transitions recorded"]'

    mermaid_lines = ["graph TD"]
    seen_nodes = set()
    
    for i, t in enumerate(transitions):
        node = t.get("node_name", f"Node_{i}")
        tokens = t.get("token_count", 0)
        cost = t.get("estimated_cost_usd", 0.0)
        latency = t.get("latency_ms", 0.0)
        
        try:
            tool_calls = json.loads(t.get("tool_calls") or "[]")
        except Exception:
            tool_calls = []
            
        has_error = any(call.get("error") or call.get("status") == "error" for call in tool_calls)
        
        fill_color = "#1f242c"
        stroke_color = "#FFE600" # EY Yellow
        text_color = "#FFFFFF"
        
        if has_error:
            fill_color = "#3b1a1a"
            stroke_color = "#f85149" # Alert red
        elif "security" in node.lower() or "guard" in node.lower():
            fill_color = "#241f31"
            stroke_color = "#a371f7" # Guard purple
            
        latency_str = f"{latency:.0f}ms" if latency > 0 else "<1ms"
        cost_str = f"{cost:.4f} USD" if cost > 0 else "Free"
        
        label = f"{node}<br/>{tokens} tok | {cost_str} | {latency_str}"
        mermaid_lines.append(f'    node_{i}["{label}"]')
        mermaid_lines.append(f'    style node_{i} fill:{fill_color},stroke:{stroke_color},stroke-width:2px,color:{text_color}')
        
        # Determine edges (parent vs sequential vs cyclic)
        parent_node = t.get("parent_node")
        
        connected = False
        if parent_node:
            for prev_idx in reversed(range(i)):
                if transitions[prev_idx].get("node_name") == parent_node:
                    is_loop = node in seen_nodes
                    if is_loop:
                        mermaid_lines.append(f'    node_{prev_idx} -. "Retry Loop" .-> node_{i}')
                    else:
                        mermaid_lines.append(f'    node_{prev_idx} -->|Branch| node_{i}')
                    connected = True
                    break
                    
        # Default sequential connection
        if not connected and i > 0:
            if node in seen_nodes:
                mermaid_lines.append(f'    node_{i-1} -. "Retry Loop" .-> node_{i}')
            else:
                mermaid_lines.append(f'    node_{i-1} -->|Next| node_{i}')
                
        seen_nodes.add(node)
        
    return "\n".join(mermaid_lines)

def get_base_html(title: str, active_tab: str, content: str, extra_head: str = "", active_run_id: str = "") -> str:
    all_runs = get_all_runs()
    latest_run = get_latest_run_id()
    current_run = active_run_id or latest_run
    trace_link = f"/debug/{current_run}" if current_run else "#"
    
    # Build run selector options
    run_options_html = ""
    for r in all_runs[:15]:
        r_id = r["run_id"]
        tok = r.get("total_tokens", 0)
        selected = 'selected' if r_id == current_run else ''
        run_options_html += f'<option value="{r_id}" {selected}>{r_id} ({tok:,} tok)</option>'
        
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} | TraceDiff Enterprise Observability</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        {extra_head}
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
            :root {{
                --bg-dark: #0d1117;
                --panel-bg: #161b22;
                --card-bg: #21262d;
                --border-color: #30363d;
                --text-main: #f0f6fc;
                --text-muted: #8b949e;
                --accent: #FFE600; /* EY Yellow */
                --accent-dim: #cca800;
                --success: #3fb950;
                --danger: #f85149;
                --warning: #d29922;
                --info: #58a6ff;
            }}
            * {{ box-sizing: border-box; }}
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background-color: var(--bg-dark);
                color: var(--text-main);
                margin: 0;
                display: flex;
                height: 100vh;
                overflow: hidden;
            }}
            .sidebar {{
                width: 280px;
                background-color: var(--panel-bg);
                border-right: 1px solid var(--border-color);
                display: flex;
                flex-direction: column;
                padding: 24px 18px;
                flex-shrink: 0;
            }}
            .brand {{
                font-size: 1.25rem;
                font-weight: 700;
                letter-spacing: -0.02em;
                color: var(--text-main);
                margin-bottom: 24px;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .brand span {{ color: var(--accent); }}
            .brand .badge {{
                font-size: 0.65rem;
                background: #30363d;
                color: var(--accent);
                padding: 2px 6px;
                border-radius: 4px;
                font-weight: 600;
                letter-spacing: 0.05em;
            }}
            .run-selector-container {{
                margin-bottom: 24px;
                padding-bottom: 16px;
                border-bottom: 1px solid var(--border-color);
            }}
            .run-selector-container label {{
                font-size: 0.72rem;
                text-transform: uppercase;
                color: var(--text-muted);
                letter-spacing: 0.06em;
                font-weight: 600;
                display: block;
                margin-bottom: 6px;
            }}
            .run-select {{
                width: 100%;
                background: #0d1117;
                border: 1px solid var(--border-color);
                color: var(--text-main);
                padding: 8px 10px;
                border-radius: 6px;
                font-size: 0.8rem;
                font-family: 'JetBrains Mono', monospace;
                cursor: pointer;
            }}
            .run-select:focus {{
                border-color: var(--accent);
                outline: none;
            }}
            .nav-section {{
                font-size: 0.72rem;
                color: var(--text-muted);
                text-transform: uppercase;
                letter-spacing: 0.06em;
                font-weight: 600;
                margin-bottom: 12px;
                margin-top: 8px;
            }}
            .sidebar-link {{
                display: flex;
                align-items: center;
                gap: 10px;
                color: var(--text-muted);
                font-size: 0.88rem;
                text-decoration: none;
                padding: 8px 12px;
                border-radius: 6px;
                margin-bottom: 4px;
                transition: all 0.15s ease-in-out;
            }}
            .sidebar-link:hover {{
                color: var(--text-main);
                background-color: rgba(255, 255, 255, 0.05);
            }}
            .sidebar-link.active {{
                color: #000;
                background-color: var(--accent);
                font-weight: 600;
            }}
            .sidebar-footer {{
                margin-top: auto;
                font-size: 0.75rem;
                color: var(--text-muted);
                border-top: 1px solid var(--border-color);
                padding-top: 16px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .main-content {{
                flex: 1;
                display: flex;
                flex-direction: column;
                padding: 24px 32px;
                overflow-y: auto;
            }}
            .kpi-bar {{
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 16px;
                margin-bottom: 24px;
            }}
            .kpi-card {{
                background-color: var(--panel-bg);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                padding: 14px 18px;
                display: flex;
                flex-direction: column;
            }}
            .kpi-title {{
                font-size: 0.72rem;
                text-transform: uppercase;
                color: var(--text-muted);
                font-weight: 600;
                letter-spacing: 0.05em;
                margin-bottom: 6px;
            }}
            .kpi-value {{
                font-size: 1.35rem;
                font-weight: 700;
                color: var(--text-main);
                font-family: 'JetBrains Mono', monospace;
            }}
            .kpi-subtext {{
                font-size: 0.75rem;
                color: var(--text-muted);
                margin-top: 4px;
            }}
            .dashboard-grid {{
                display: grid;
                grid-template-columns: 1fr 1.15fr;
                gap: 20px;
                min-height: 550px;
            }}
            .card {{
                background-color: var(--panel-bg);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }}
            .card-header {{
                padding: 14px 18px;
                border-bottom: 1px solid var(--border-color);
                font-size: 0.82rem;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: var(--text-muted);
                font-weight: 600;
                background-color: #12161c;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .card-body {{
                padding: 18px;
                flex: 1;
                overflow-y: auto;
            }}
            ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
            ::-webkit-scrollbar-track {{ background: var(--bg-dark); }}
            ::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 3px; }}
        </style>
        <script>
            function switchRun(runId) {{
                if (runId) {{
                    window.location.href = '/debug/' + runId;
                }}
            }}
        </script>
    </head>
    <body>
        <div class="sidebar">
            <div class="brand">
                <i class="fa-solid fa-microchip" style="color: var(--accent);"></i>
                Trace<span>Diff</span>
                <span class="badge">SIDECAR</span>
            </div>
            
            <div class="run-selector-container">
                <label><i class="fa-solid fa-list-check"></i> Active Run</label>
                <select class="run-select" onchange="switchRun(this.value)">
                    {run_options_html if run_options_html else '<option value="">No runs logged</option>'}
                </select>
            </div>

            <div class="nav-section">Observability Suite</div>
            <a href="{trace_link}" class="sidebar-link {'active' if active_tab == 'traces' else ''}">
                <i class="fa-solid fa-diagram-project"></i> Agent Traces
            </a>
            <a href="/runs" class="sidebar-link {'active' if active_tab == 'runs' else ''}">
                <i class="fa-solid fa-clock-rotate-left"></i> Run Explorer
            </a>
            <a href="/vector-scanning" class="sidebar-link {'active' if active_tab == 'vector' else ''}">
                <i class="fa-solid fa-shield-halved"></i> Vector Scanning
            </a>
            <a href="/settings" class="sidebar-link {'active' if active_tab == 'settings' else ''}">
                <i class="fa-solid fa-sliders"></i> Settings
            </a>

            <div class="sidebar-footer">
                <span>Sidecar Active</span>
                <span>v2.1 Enterprise</span>
            </div>
        </div>
        <div class="main-content">
            {content}
        </div>
    </body>
    </html>
    """

def render_debugger_html(run_id: str, transitions: List[Dict[str, Any]]) -> str:
    summary = get_run_summary(run_id)
    mermaid_code = generate_mermaid_graph(transitions)
    
    total_tokens = summary.get("total_tokens", 0)
    prompt_tokens = summary.get("prompt_tokens", 0)
    completion_tokens = summary.get("completion_tokens", 0)
    total_cost = summary.get("estimated_cost_usd", 0.0)
    total_latency = summary.get("total_latency_ms", 0.0)
    error_count = summary.get("error_count", 0)
    total_nodes = summary.get("total_nodes", len(transitions))
    
    status_badge = '<span style="color: var(--success); font-weight: 600;">SUCCESS</span>' if error_count == 0 else f'<span style="color: var(--danger); font-weight: 600;">{error_count} FAILED</span>'

    # Build KPI Bar
    kpi_bar_html = f"""
    <div class="kpi-bar">
        <div class="kpi-card">
            <div class="kpi-title">Total Tokens</div>
            <div class="kpi-value">{total_tokens:,}</div>
            <div class="kpi-subtext">{prompt_tokens:,} in / {completion_tokens:,} out</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Estimated Cost</div>
            <div class="kpi-value">${total_cost:.4f}</div>
            <div class="kpi-subtext">Aggregated USD</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Execution Latency</div>
            <div class="kpi-value">{total_latency:.0f} ms</div>
            <div class="kpi-subtext">{total_latency/1000.0:.2f}s total runtime</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Total Hops</div>
            <div class="kpi-value">{total_nodes}</div>
            <div class="kpi-subtext">Nodes evaluated</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Audit Status</div>
            <div class="kpi-value" style="font-size: 1.15rem;">{status_badge}</div>
            <div class="kpi-subtext">{error_count} tool errors</div>
        </div>
    </div>
    """

    steps_html = ""
    for idx, t in enumerate(transitions):
        tools = json.loads(t.get("tool_calls") or "[]")
        state_before = json.loads(t.get("state_before") or "{}")
        state_after = json.loads(t.get("state_after") or "{}")
        diff_raw = t.get("diff_summary")
        diff_data = json.loads(diff_raw) if diff_raw else compute_state_diff(state_before, state_after)
        
        diff_html = render_diff_html(diff_data)
        
        # Tools representation
        tools_html = ""
        if tools:
            for tool in tools:
                status = tool.get("status", "unknown")
                status_color = "#3fb950" if status == "success" else "#f85149"
                err_msg = f"<div style='color: #f85149; margin-top: 4px; font-size: 0.8rem;'>Error: {tool.get('error')}</div>" if tool.get("error") else ""
                out_msg = f"<div style='color: #8b949e; margin-top: 4px; font-size: 0.8rem;'>Output: {str(tool.get('output'))[:250]}</div>" if tool.get("output") else ""
                tools_html += f"""
                <div style="background: #111418; border: 1px solid #30363d; border-radius: 4px; padding: 8px 12px; margin-top: 6px; font-family: monospace;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem;">
                        <span style="font-weight: 600; color: #58a6ff;">🔧 {tool.get('tool', 'tool')}</span>
                        <span style="color: {status_color}; font-weight: 600;">{status.upper()}</span>
                    </div>
                    {out_msg}
                    {err_msg}
                </div>
                """
        else:
            tools_html = "<div style='color: #8b949e; font-size: 0.8rem; font-style: italic;'>No tool calls in this hop</div>"

        # Content extract
        raw_content = state_after.get("extracted_data") or state_after.get("response") or state_after.get("context") or state_after.get("code") or json.dumps(state_after, indent=2)
        if isinstance(raw_content, (dict, list)):
            raw_content = json.dumps(raw_content, indent=2)

        node_name = t.get('node_name', f'Node_{idx}')
        tokens = t.get('token_count', 0)
        cost = t.get('estimated_cost_usd', 0.0)
        latency = t.get('latency_ms', 0.0)
        parent_info = f"<span style='color: #8b949e; font-size: 0.75rem;'>from: {t.get('parent_node')}</span>" if t.get('parent_node') else ""

        steps_html += f"""
        <div class="step-card" id="step-{idx}" style="background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <div>
                    <span style="font-weight: 700; color: var(--accent); font-size: 1rem;">{node_name}</span>
                    {parent_info}
                </div>
                <div style="display: flex; gap: 8px; font-size: 0.75rem; font-family: monospace;">
                    <span style="background: #21262d; border: 1px solid #30363d; padding: 2px 8px; border-radius: 4px; color: #8b949e;">{tokens} tok</span>
                    <span style="background: #21262d; border: 1px solid #30363d; padding: 2px 8px; border-radius: 4px; color: #8b949e;">${cost:.4f}</span>
                    <span style="background: #21262d; border: 1px solid #30363d; padding: 2px 8px; border-radius: 4px; color: #8b949e;">{latency:.0f}ms</span>
                </div>
            </div>
            
            <div style="font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; margin-bottom: 4px;">State Mutation (Delta Diff)</div>
            {diff_html}
            
            <div style="font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; margin-top: 12px; margin-bottom: 4px;">Tool Invocations</div>
            {tools_html}

            <details style="margin-top: 12px;">
                <summary style="font-size: 0.75rem; color: #58a6ff; cursor: pointer; text-transform: uppercase; font-weight: 600;">View Raw Output State</summary>
                <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #c9d1d9; background: #0d1117; border: 1px solid #30363d; padding: 10px; border-radius: 4px; white-space: pre-wrap; line-height: 1.4; max-height: 200px; overflow-y: auto; margin-top: 6px;">{raw_content}</div>
            </details>
        </div>
        """

    extra_head = f"""
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ 
            startOnLoad: true, 
            securityLevel: 'loose',
            theme: 'base',
            themeVariables: {{
                primaryColor: '#1f242c',
                primaryTextColor: '#FFFFFF',
                primaryBorderColor: '#FFE600',
                lineColor: '#58a6ff',
                fontFamily: 'Inter, sans-serif'
            }}
        }});

        // Real-Time Server-Sent Events (SSE) Live Feed
        const runId = "{run_id}";
        if (runId) {{
            const eventSource = new EventSource('/api/v1/stream/' + runId);
            eventSource.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    if (data.type === 'new_transition') {{
                        console.log('[TraceDiff SSE] New transition received, refreshing stream...');
                        // Smoothly reload page to display newly arrived graph nodes and metrics
                        window.location.reload();
                    }}
                }} catch (e) {{
                    console.error('[TraceDiff SSE Error]', e);
                }}
            }};
        }}
    </script>
    <style>
        .graph-container {{
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 24px;
            overflow-x: auto;
        }}
    </style>
    """

    content = f"""
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: flex-end;">
        <div>
            <h1 style="margin: 0; font-size: 1.5rem; font-weight: 700;">Agent Execution Trace</h1>
            <p style="margin: 4px 0 0 0; color: var(--text-muted); font-size: 0.88rem; font-family: 'JetBrains Mono', monospace;">
                Run ID: <span style="color: var(--accent);">{run_id}</span>
            </p>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-muted); display: flex; gap: 12px; align-items: center;">
            <button onclick="window.location.reload()" style="background: #21262d; border: 1px solid #30363d; color: var(--text-main); padding: 6px 12px; border-radius: 6px; cursor: pointer;">
                <i class="fa-solid fa-arrows-rotate"></i> Refresh
            </button>
        </div>
    </div>
    
    {kpi_bar_html}

    <div class="dashboard-grid">
        <div class="card">
            <div class="card-header">
                <span><i class="fa-solid fa-diagram-project"></i> Multi-Agent Topology Graph</span>
                <span style="font-size: 0.72rem; color: var(--text-muted);">Mermaid.js DAG</span>
            </div>
            <div class="card-body graph-container">
                <div class="mermaid">
                    {mermaid_code}
                </div>
            </div>
        </div>
        <div class="card">
            <div class="card-header">
                <span><i class="fa-solid fa-code-compare"></i> State Transition & Diff Stream</span>
                <span style="font-size: 0.72rem; color: var(--text-muted);">{len(transitions)} Transitions</span>
            </div>
            <div class="card-body">
                {steps_html}
            </div>
        </div>
    </div>
    """

    return get_base_html("Trace Visualizer", "traces", content, extra_head, active_run_id=run_id)

def render_run_explorer_html() -> str:
    runs = get_all_runs()
    rows_html = ""
    
    if not runs:
        rows_html = "<tr><td colspan='6' style='text-align: center; color: var(--text-muted); padding: 40px;'>No runs recorded in database yet.</td></tr>"
    else:
        for r in runs:
            r_id = r["run_id"]
            nodes = r["node_count"]
            tokens = r["total_tokens"] or 0
            cost = r["total_cost"] or 0.0
            last_seen = r.get("last_updated") or ""
            has_error = r.get("has_error", False)
            
            status_badge = '<span style="background: rgba(248, 81, 73, 0.15); color: #f85149; border: 1px solid #f85149; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">FAILED</span>' if has_error else '<span style="background: rgba(63, 185, 80, 0.15); color: #3fb950; border: 1px solid #3fb950; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">SUCCESS</span>'
            
            rows_html += f"""
            <tr style="border-bottom: 1px solid var(--border-color); transition: background 0.15s ease;" onmouseover="this.style.background='#161b22'" onmouseout="this.style.background='transparent'">
                <td style="padding: 12px 16px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">
                    <a href="/debug/{r_id}" style="color: var(--accent); text-decoration: none; font-weight: 600;">{r_id}</a>
                </td>
                <td style="padding: 12px 16px;">{status_badge}</td>
                <td style="padding: 12px 16px; font-family: monospace;">{nodes} hops</td>
                <td style="padding: 12px 16px; font-family: monospace;">{tokens:,}</td>
                <td style="padding: 12px 16px; font-family: monospace;">${cost:.4f}</td>
                <td style="padding: 12px 16px; color: var(--text-muted); font-size: 0.82rem;">{last_seen}</td>
            </tr>
            """

    content = f"""
    <div style="margin-bottom: 24px;">
        <h1 style="margin: 0; font-size: 1.5rem; font-weight: 700;">Run Explorer & Audit History</h1>
        <p style="margin: 4px 0 0 0; color: var(--text-muted); font-size: 0.88rem;">
            Comprehensive audit log of all autonomous agent executions, token consumption, and status outcomes.
        </p>
    </div>
    <div class="card" style="height: calc(100% - 80px);">
        <div class="card-header">
            <span>Historical Executions</span>
            <span style="font-size: 0.75rem; color: var(--text-muted);">{len(runs)} Total Runs</span>
        </div>
        <div class="card-body" style="padding: 0; overflow-y: auto;">
            <table style="width: 100%; border-collapse: collapse; text-align: left;">
                <thead>
                    <tr style="background: #12161c; border-bottom: 1px solid var(--border-color); font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted);">
                        <th style="padding: 12px 16px;">Run ID</th>
                        <th style="padding: 12px 16px;">Status</th>
                        <th style="padding: 12px 16px;">Depth</th>
                        <th style="padding: 12px 16px;">Total Tokens</th>
                        <th style="padding: 12px 16px;">Est. Cost</th>
                        <th style="padding: 12px 16px;">Timestamp</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
    """
    return get_base_html("Run Explorer", "runs", content)

def render_vector_scanning_html(security_logs: List[Dict[str, Any]]) -> str:
    rows_html = ""
    if not security_logs:
        rows_html = "<tr><td colspan='5' style='text-align: center; color: var(--text-muted); padding: 40px;'>No security threats or anomalies detected. System secure.</td></tr>"
    else:
        for log in security_logs:
            lvl = log.get('threat_level', 'MEDIUM')
            badge_color = "#f85149" if lvl == "CRITICAL" else ("#d29922" if lvl == "HIGH" else "#FFE600")
            cat = log.get('category', 'ADVERSARIAL_INPUT')
            snippet = log.get('raw_payload_snippet') or ""
            snippet_html = f"<div style='font-family: monospace; font-size: 0.75rem; color: #ff7b72; background: #0d1117; padding: 4px 6px; border-radius: 3px; margin-top: 4px;'>{snippet}</div>" if snippet else ""

            rows_html += f"""
            <tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding: 12px 16px; font-family: monospace; font-size: 0.8rem; color: var(--text-muted);">{log.get('timestamp')}</td>
                <td style="padding: 12px 16px; font-family: monospace; font-size: 0.82rem;">
                    <a href="/debug/{log.get('run_id')}" style="color: #58a6ff; text-decoration: none;">{log.get('run_id')}</a>
                    <div style="color: var(--text-muted); font-size: 0.75rem;">{log.get('node_name')}</div>
                </td>
                <td style="padding: 12px 16px;">
                    <span style="background: {badge_color}22; color: {badge_color}; border: 1px solid {badge_color}; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; font-weight: 700;">{lvl}</span>
                    <div style="color: var(--text-muted); font-size: 0.72rem; margin-top: 4px; font-family: monospace;">{cat}</div>
                </td>
                <td style="padding: 12px 16px; color: var(--text-main); font-size: 0.85rem;">
                    {log.get('details')}
                    {snippet_html}
                </td>
            </tr>
            """

    content = f"""
    <div style="margin-bottom: 24px;">
        <h1 style="margin: 0; font-size: 1.5rem; font-weight: 700;">AgentGuard Security & Vector Scanning</h1>
        <p style="margin: 4px 0 0 0; color: var(--text-muted); font-size: 0.88rem;">
            Real-time semantic interception, prompt injection defense, credential leak prevention, and adversarial payload telemetry.
        </p>
    </div>
    <div class="card" style="height: calc(100% - 80px);">
        <div class="card-header">
            <span>Live Security Audit Stream</span>
            <span style="font-size: 0.75rem; color: var(--text-muted);">{len(security_logs)} Threat Telemetry Records</span>
        </div>
        <div class="card-body" style="padding: 0; overflow-y: auto;">
            <table style="width: 100%; border-collapse: collapse; text-align: left;">
                <thead>
                    <tr style="background: #12161c; border-bottom: 1px solid var(--border-color); font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted);">
                        <th style="padding: 12px 16px;">Timestamp</th>
                        <th style="padding: 12px 16px;">Run / Node Source</th>
                        <th style="padding: 12px 16px;">Threat & Category</th>
                        <th style="padding: 12px 16px;">Telemetry Findings</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
    """
    return get_base_html("Vector Scanning", "vector", content)

def render_settings_html() -> str:
    settings = get_settings()
    retention = settings.get("data_retention_days", "30")
    ollama_url = settings.get("ollama_gateway_url", "http://localhost:11434/api/generate")
    auto_scan = settings.get("auto_security_scan", "true") == "true"
    budget = settings.get("token_budget_alert_threshold", "4000")
    pricing_model = settings.get("default_pricing_model", "gpt-4o-mini")

    content = f"""
    <div style="margin-bottom: 24px;">
        <h1 style="margin: 0; font-size: 1.5rem; font-weight: 700;">System Settings & Governance</h1>
        <p style="margin: 4px 0 0 0; color: var(--text-muted); font-size: 0.88rem;">
            Configure TraceDiff Observability engine, AgentGuard security thresholds, and billing governance.
        </p>
    </div>
    <div class="card" style="max-width: 750px;">
        <div class="card-header">Sidecar Configuration</div>
        <div class="card-body">
            <form id="settings-form" onsubmit="saveSettings(event)">
                <div style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-size: 0.85rem; font-weight: 600;">Data Retention Policy (Audit Compliance)</label>
                    <select id="retention" style="width: 100%; padding: 10px; background: #0d1117; border: 1px solid var(--border-color); color: #fff; border-radius: 6px;">
                        <option value="7" {'selected' if retention == '7' else ''}>7 Days (Ephemeral Dev)</option>
                        <option value="30" {'selected' if retention == '30' else ''}>30 Days (Standard Compliance)</option>
                        <option value="90" {'selected' if retention == '90' else ''}>90 Days (Enterprise Audit)</option>
                        <option value="365" {'selected' if retention == '365' else ''}>1 Year (Statutory Requirement)</option>
                    </select>
                </div>

                <div style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-size: 0.85rem; font-weight: 600;">Ollama / LLM Gateway API URL</label>
                    <input type="text" id="ollama_url" value="{ollama_url}" style="width: 100%; padding: 10px; background: #0d1117; border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-family: monospace;">
                </div>

                <div style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-size: 0.85rem; font-weight: 600;">Default Model Rate for Cost Estimation</label>
                    <select id="pricing_model" style="width: 100%; padding: 10px; background: #0d1117; border: 1px solid var(--border-color); color: #fff; border-radius: 6px;">
                        <option value="gpt-4o-mini" {'selected' if pricing_model == 'gpt-4o-mini' else ''}>GPT-4o Mini ($0.15 / $0.60 per 1M)</option>
                        <option value="gpt-4o" {'selected' if pricing_model == 'gpt-4o' else ''}>GPT-4o ($2.50 / $10.00 per 1M)</option>
                        <option value="claude-3-5-sonnet" {'selected' if pricing_model == 'claude-3-5-sonnet' else ''}>Claude 3.5 Sonnet ($3.00 / $15.00 per 1M)</option>
                        <option value="llama3" {'selected' if pricing_model == 'llama3' else ''}>Llama 3 Local ($0.00 - Self-Hosted)</option>
                    </select>
                </div>

                <div style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-size: 0.85rem; font-weight: 600;">Token Budget Alert Threshold per Node</label>
                    <input type="number" id="budget" value="{budget}" style="width: 100%; padding: 10px; background: #0d1117; border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-family: monospace;">
                </div>

                <div style="margin-bottom: 24px;">
                    <label style="display: flex; align-items: center; gap: 8px; font-size: 0.88rem; cursor: pointer;">
                        <input type="checkbox" id="auto_scan" {'checked' if auto_scan else ''} style="width: 16px; height: 16px; accent-color: var(--accent);">
                        Enable AgentGuard Real-Time In-Flight Security Scanning
                    </label>
                </div>

                <div style="display: flex; gap: 12px; align-items: center;">
                    <button type="submit" style="background: var(--accent); color: #000; font-weight: 700; border: none; padding: 10px 24px; border-radius: 6px; cursor: pointer; font-size: 0.9rem;">
                        Save Configuration
                    </button>
                    <span id="save-msg" style="color: var(--success); font-size: 0.85rem; display: none;">Configuration updated successfully!</span>
                </div>
            </form>
        </div>
    </div>

    <script>
        async function saveSettings(e) {{
            e.preventDefault();
            const payload = {{
                data_retention_days: parseInt(document.getElementById('retention').value),
                ollama_gateway_url: document.getElementById('ollama_url').value,
                default_pricing_model: document.getElementById('pricing_model').value,
                token_budget_alert_threshold: parseInt(document.getElementById('budget').value),
                auto_security_scan: document.getElementById('auto_scan').checked
            }};
            try {{
                const res = await fetch('/api/v1/settings', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                if (res.ok) {{
                    const msg = document.getElementById('save-msg');
                    msg.style.display = 'inline';
                    setTimeout(() => {{ msg.style.display = 'none'; }}, 3000);
                }}
            }} catch (err) {{
                alert('Failed to save settings: ' + err);
            }}
        }}
    </script>
    """
    return get_base_html("Settings", "settings", content)
