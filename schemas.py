from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

def utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def utc_str_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

class StateTransitionEvent(BaseModel):
    run_id: str
    node_name: str
    parent_node: Optional[str] = None
    step_index: Optional[int] = 0
    state_before: Dict[str, Any] = Field(default_factory=dict)
    state_after: Dict[str, Any] = Field(default_factory=dict)
    tool_calls: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    token_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_name: Optional[str] = "default"
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0
    diff_summary: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=utc_iso_now)

class SecurityLogEvent(BaseModel):
    run_id: str
    node_name: str
    threat_level: str = "MEDIUM"  # 'INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    category: str = "ADVERSARIAL_INPUT"  # 'PROMPT_INJECTION', 'JAILBREAK', 'PII_LEAK', 'DATA_EXFILTRATION', 'UNSAFE_TOOL_CALL'
    details: str
    raw_payload_snippet: Optional[str] = None
    timestamp: str = Field(default_factory=utc_str_now)

class SystemSettingsModel(BaseModel):
    data_retention_days: int = 30
    ollama_gateway_url: str = "http://localhost:11434/api/generate"
    auto_security_scan: bool = True
    token_budget_alert_threshold: int = 4000
    default_pricing_model: str = "gpt-4o-mini"
