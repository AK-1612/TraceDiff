import json
from typing import Dict, Any, Tuple

# Pricing per 1,000,000 tokens (USD)
MODEL_PRICING = {
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00},
    "claude-3-5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
    "llama3": {"prompt": 0.00, "completion": 0.00},
    "mistral": {"prompt": 0.00, "completion": 0.00},
    "default": {"prompt": 0.50, "completion": 1.50}
}

def calculate_token_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculates estimated token cost in USD based on standard enterprise model rates."""
    model_key = model_name.lower() if model_name else "default"
    rates = MODEL_PRICING.get(model_key, MODEL_PRICING["default"])
    cost = (prompt_tokens / 1_000_000.0 * rates["prompt"]) + (completion_tokens / 1_000_000.0 * rates["completion"])
    return round(cost, 6)

def compute_state_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes a deterministic structural diff between state_before and state_after.
    Identifies additions, deletions, value mutations, and list deltas.
    """
    before = before or {}
    after = after or {}
    
    before_keys = set(before.keys())
    after_keys = set(after.keys())
    
    added_keys = after_keys - before_keys
    removed_keys = before_keys - after_keys
    common_keys = before_keys & after_keys
    
    added = {k: after[k] for k in added_keys}
    removed = {k: before[k] for k in removed_keys}
    modified = {}
    unchanged = []
    
    for k in common_keys:
        val_before = before[k]
        val_after = after[k]
        
        if val_before != val_after:
            # Check if this is a list append (common in multi-agent message histories)
            if isinstance(val_before, list) and isinstance(val_after, list):
                if len(val_after) > len(val_before) and val_after[:len(val_before)] == val_before:
                    appended_items = val_after[len(val_before):]
                    modified[k] = {
                        "type": "list_append",
                        "before_len": len(val_before),
                        "after_len": len(val_after),
                        "appended": appended_items
                    }
                    continue
            modified[k] = {
                "type": "value_change",
                "before": val_before,
                "after": val_after
            }
        else:
            unchanged.append(k)
            
    stats = {
        "additions": len(added),
        "deletions": len(removed),
        "modifications": len(modified),
        "total_changes": len(added) + len(removed) + len(modified)
    }
    
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
        "stats": stats
    }

def format_val_for_diff(val: Any, max_len: int = 160) -> str:
    """Formats a value compactly for inline diff display."""
    if isinstance(val, (dict, list)):
        s = json.dumps(val, ensure_ascii=False)
    else:
        s = str(val)
    if len(s) > max_len:
        return s[:max_len] + " ... [truncated]"
    return s

def render_diff_html(diff: Dict[str, Any]) -> str:
    """Generates a rich Git-style visual diff block with red/green syntax styling."""
    stats = diff.get("stats", {})
    additions = stats.get("additions", 0)
    deletions = stats.get("deletions", 0)
    modifications = stats.get("modifications", 0)
    
    if stats.get("total_changes", 0) == 0:
        return """
        <div style="padding: 10px 14px; background: #161b22; border: 1px dashed #30363d; border-radius: 4px; font-size: 0.8rem; color: #8b949e; font-family: monospace;">
            ⚖️ No state mutations detected (idempotent node hop)
        </div>
        """
        
    diff_lines = []
    
    # Render Removed
    for k, v in diff.get("removed", {}).items():
        val_str = format_val_for_diff(v)
        diff_lines.append(
            f'<div style="background: rgba(248, 81, 73, 0.15); color: #f85149; padding: 2px 8px; border-left: 3px solid #f85149; margin-bottom: 2px;">'
            f'- <strong>{k}</strong>: {val_str}'
            f'</div>'
        )
        
    # Render Added
    for k, v in diff.get("added", {}).items():
        val_str = format_val_for_diff(v)
        diff_lines.append(
            f'<div style="background: rgba(63, 185, 80, 0.15); color: #3fb950; padding: 2px 8px; border-left: 3px solid #3fb950; margin-bottom: 2px;">'
            f'+ <strong>{k}</strong>: {val_str}'
            f'</div>'
        )
        
    # Render Modified
    for k, mod in diff.get("modified", {}).items():
        if mod.get("type") == "list_append":
            diff_lines.append(
                f'<div style="background: rgba(56, 139, 253, 0.15); color: #58a6ff; padding: 2px 8px; border-left: 3px solid #58a6ff; margin-bottom: 2px;">'
                f'~ <strong>{k}</strong>: list grew from {mod["before_len"]} -> {mod["after_len"]} items (+{len(mod["appended"])} appended)'
                f'</div>'
            )
        else:
            before_str = format_val_for_diff(mod.get("before"))
            after_str = format_val_for_diff(mod.get("after"))
            diff_lines.append(
                f'<div style="background: rgba(210, 153, 34, 0.12); padding: 4px 8px; border-left: 3px solid #d29922; margin-bottom: 4px;">'
                f'<div style="color: #f85149; font-size: 0.8rem;">- <strong>{k}</strong>: {before_str}</div>'
                f'<div style="color: #3fb950; font-size: 0.8rem;">+ <strong>{k}</strong>: {after_str}</div>'
                f'</div>'
            )
            
    header_badge = f"""
    <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px; font-size: 0.75rem; font-family: monospace;">
        <span style="background: #238636; color: #fff; padding: 1px 6px; border-radius: 3px;">+{additions} added</span>
        <span style="background: #da3633; color: #fff; padding: 1px 6px; border-radius: 3px;">-{deletions} removed</span>
        <span style="background: #9e6a03; color: #fff; padding: 1px 6px; border-radius: 3px;">~{modifications} modified</span>
    </div>
    """
    
    return f"""
    <div style="background: #0d1117; border: 1px solid #30363d; border-radius: 4px; padding: 10px; font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; overflow-x: auto;">
        {header_badge}
        {''.join(diff_lines)}
    </div>
    """

