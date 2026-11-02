import time
import requests
from typing import Dict, Any, Optional, List, Callable
from contextlib import contextmanager
from schemas import StateTransitionEvent, SecurityLogEvent
from security_scanner import agent_guard
from diff_engine import compute_state_diff, calculate_token_cost

class StepContext:
    """Helper context object to capture state, tools, and token metrics during a node execution."""
    def __init__(self, tracer: 'TraceDiffAgentTracer', node_name: str, parent_node: Optional[str] = None, state_before: Optional[Dict[str, Any]] = None):
        self.tracer = tracer
        self.node_name = node_name
        self.parent_node = parent_node
        self.state_before = state_before or {}
        self.state_after = {}
        self.tool_calls: List[Dict[str, Any]] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.token_count = 0
        self.model_name = "default"
        self.start_time = time.time()
        
    def set_state_after(self, state: Dict[str, Any]):
        self.state_after = state
        
    def add_tool_call(self, tool: str, status: str = "success", input_data: Any = None, output: Any = None, error: Optional[str] = None):
        self.tool_calls.append({
            "tool": tool,
            "status": status,
            "input": input_data,
            "output": output,
            "error": error
        })
        
    def set_tokens(self, prompt: int = 0, completion: int = 0, total: Optional[int] = None, model: str = "default"):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.token_count = total if total is not None else (prompt + completion)
        self.model_name = model

class TraceDiffAgentTracer:
    """
    Enterprise Observability Sidecar Client.
    Provides automated interception, step-wise tracing, context managers,
    and integrated security telemetry scanning for multi-agent loops.
    """
    def __init__(
        self,
        run_id: str,
        endpoint: str = "http://localhost:8000/api/v1/log-transition",
        security_endpoint: str = "http://localhost:8000/api/v1/log-security",
        auto_security_scan: bool = True,
        default_model: str = "default"
    ):
        self.run_id = run_id
        self.endpoint = endpoint
        self.security_endpoint = security_endpoint
        self.auto_security_scan = auto_security_scan
        self.default_model = default_model
        self.step_counter = 0
        self.last_node_name: Optional[str] = None

    def log_step(
        self,
        node_name: str,
        state_before: Dict[str, Any],
        state_after: Dict[str, Any],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        token_count: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        model_name: Optional[str] = None,
        parent_node: Optional[str] = None,
        latency_ms: float = 0.0
    ):
        """Logs a single state transition hop and dispatches telemetry."""
        self.step_counter += 1
        model = model_name or self.default_model
        resolved_parent = parent_node if parent_node is not None else self.last_node_name
        self.last_node_name = node_name

        total_tok = token_count or (prompt_tokens + completion_tokens)
        cost = calculate_token_cost(model, prompt_tokens, completion_tokens)
        diff_data = compute_state_diff(state_before, state_after)

        payload = {
            "run_id": self.run_id,
            "node_name": node_name,
            "parent_node": resolved_parent,
            "step_index": self.step_counter,
            "state_before": state_before,
            "state_after": state_after,
            "tool_calls": tool_calls or [],
            "token_count": total_tok,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "model_name": model,
            "estimated_cost_usd": cost,
            "latency_ms": latency_ms,
            "diff_summary": diff_data
        }

        # 1. Automatic Real-Time Security Telemetry Scan
        if self.auto_security_scan:
            findings = agent_guard.scan_transition(
                run_id=self.run_id,
                node_name=node_name,
                state_before=state_before,
                state_after=state_after,
                tool_calls=tool_calls
            )
            for finding in findings:
                self.log_security(finding)

        # 2. Dispatch State Transition
        try:
            response = requests.post(self.endpoint, json=payload, timeout=4)
            if response.status_code >= 400:
                raise Exception(f"Sidecar HTTP {response.status_code}")
            return response.json()
        except Exception as e:
            # Fallback to local DB logging if sidecar server is unavailable
            try:
                from database import log_transition
                ev = StateTransitionEvent(**payload)
                log_transition(ev)
                return {"status": "logged_local_fallback", "run_id": self.run_id}
            except Exception as inner_e:
                print(f"[TraceDiff Warning] Failed to log transition for node {node_name}: {e} (Fallback failed: {inner_e})")
                return None

    def log_security(self, event: SecurityLogEvent):
        """Transmits security telemetry to the sidecar."""
        payload = event.model_dump()
        try:
            resp = requests.post(self.security_endpoint, json=payload, timeout=2)
            if resp.status_code >= 400:
                raise Exception(f"Sidecar HTTP {resp.status_code}")
        except Exception:
            # Fallback direct insertion
            try:
                from database import log_security_event
                log_security_event(event)
            except Exception:
                pass

    @contextmanager
    def step(self, node_name: str, parent_node: Optional[str] = None, state_before: Optional[Dict[str, Any]] = None):
        """Context manager for seamless block-level agent node interception."""
        ctx = StepContext(self, node_name, parent_node, state_before)
        try:
            yield ctx
        finally:
            latency = (time.time() - ctx.start_time) * 1000.0
            self.log_step(
                node_name=ctx.node_name,
                state_before=ctx.state_before,
                state_after=ctx.state_after,
                tool_calls=ctx.tool_calls,
                token_count=ctx.token_count,
                prompt_tokens=ctx.prompt_tokens,
                completion_tokens=ctx.completion_tokens,
                model_name=ctx.model_name,
                parent_node=ctx.parent_node,
                latency_ms=latency
            )

    def trace(self, node_name: Optional[str] = None):
        """Decorator for autonomous agent node functions."""
        def decorator(func: Callable):
            def wrapper(*args, **kwargs):
                name = node_name or func.__name__
                # Inspect first dict argument as state
                state_arg = next((arg for arg in args if isinstance(arg, dict)), {})
                state_before = dict(state_arg) if state_arg else {}
                start_time = time.time()
                result = func(*args, **kwargs)
                latency = (time.time() - start_time) * 1000.0
                
                state_after = result if isinstance(result, dict) else (state_arg or {})
                self.log_step(
                    node_name=name,
                    state_before=state_before,
                    state_after=state_after,
                    latency_ms=latency
                )
                return result
            return wrapper
        return decorator


class TraceDiffLangGraphCallbackHandler:
    """
    Standard Callback Handler for LangChain & LangGraph agent graphs.
    Allows zero-code interception of tool invocations, node chains, and LLM hops.
    """
    def __init__(self, tracer: TraceDiffAgentTracer):
        self.tracer = tracer
        self.current_state: Dict[str, Any] = {}
        self.pending_tools: List[Dict[str, Any]] = []

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs):
        self.current_state = dict(inputs) if isinstance(inputs, dict) else {"input": str(inputs)}

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs):
        node_name = kwargs.get("name") or "LangGraphNode"
        state_after = dict(outputs) if isinstance(outputs, dict) else {"output": str(outputs)}
        self.tracer.log_step(
            node_name=node_name,
            state_before=self.current_state,
            state_after=state_after,
            tool_calls=self.pending_tools
        )
        self.current_state = state_after
        self.pending_tools = []

    def on_tool_end(self, output: str, **kwargs):
        name = kwargs.get("name", "tool")
        self.pending_tools.append({"tool": name, "status": "success", "output": str(output)[:500]})

    def on_tool_error(self, error: Exception, **kwargs):
        name = kwargs.get("name", "tool")
        self.pending_tools.append({"tool": name, "status": "error", "error": str(error)})

    def on_llm_end(self, response: Any, **kwargs):
        llm_output = getattr(response, "llm_output", {}) or {}
        usage = llm_output.get("token_usage", {})
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", prompt + completion)
        # Store for the current node hop
        self.tracer.default_model = llm_output.get("model_name", self.tracer.default_model)
