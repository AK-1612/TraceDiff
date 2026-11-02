import re
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from schemas import SecurityLogEvent

# Regex Patterns for Jailbreaks, Adversarial Injections, and PII
PATTERNS = {
    "PROMPT_INJECTION": [
        (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|directives|rules)", re.IGNORECASE), "CRITICAL", "Direct override attempt targeting core system directives."),
        (re.compile(r"disregard\s+(earlier|preceding|all)\s+(guidelines|instructions|context)", re.IGNORECASE), "CRITICAL", "Instruction wipeout / prompt reset attempt."),
        (re.compile(r"you\s+are\s+now\s+(in\s+)?(dan\s+mode|unfiltered|jailbreak|developer\s+mode|godmode)", re.IGNORECASE), "CRITICAL", "Jailbreak persona assumption attempt (DAN / Unfiltered mode)."),
        (re.compile(r"system\s*override\s*:\s*disable\s*safety", re.IGNORECASE), "CRITICAL", "System safety override command sequence detected."),
        (re.compile(r"repeat\s+(everything|the\s+text)\s+(above|from\s+the\s+beginning)", re.IGNORECASE), "HIGH", "System prompt exfiltration probe."),
    ],
    "DATA_EXFILTRATION": [
        (re.compile(r"/etc/(passwd|shadow|hosts)", re.IGNORECASE), "CRITICAL", "Unix system credential file exfiltration payload."),
        (re.compile(r"/proc/self/environ", re.IGNORECASE), "CRITICAL", "Process environment variable leak probe."),
        (re.compile(r"(rm\s+-rf\s+/|chmod\s+777|chown\s+root)", re.IGNORECASE), "CRITICAL", "Destructive host filesystem command injected."),
        (re.compile(r"(curl|wget)\s+https?://(?!localhost|127\.0\.0\.1)[^\s]+", re.IGNORECASE), "HIGH", "Out-of-band network egress / webhook exfiltration detected."),
        (re.compile(r"UNION\s+SELECT\s+.*FROM", re.IGNORECASE), "HIGH", "SQL injection database reconnaissance signature."),
    ],
    "PII_LEAK": [
        (re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12})\b"), "HIGH", "Unmasked Credit Card number detected in agent memory."),
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "HIGH", "US Social Security Number (SSN) pattern detected."),
        (re.compile(r"(?i)(password|secret_key|client_secret)\s*[:=]\s*['\"][A-Za-z0-9_!@#$%^&*()\-+=]{6,}['\"]"), "HIGH", "Cleartext password or secret credential in payload."),
    ],
    "CREDENTIAL_LEAK": [
        (re.compile(r"sk-[a-zA-Z0-9_-]{20,}"), "CRITICAL", "Leaked OpenAI API Secret Key."),
        (re.compile(r"AKIA[0-9A-Z]{16}"), "CRITICAL", "Leaked AWS Access Key ID."),
        (re.compile(r"ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{40,}"), "CRITICAL", "Leaked GitHub Personal Access Token."),
        (re.compile(r"-----BEGIN (RSA|EC|OPENSSH|DSA|PGP|ENCRYPTED|PRIVATE) KEY-----"), "CRITICAL", "Leaked cryptographic private key block."),
    ]
}

class AgentGuardScanner:
    """
    Real-Time Vector & Telemetry Security Scanner for Agent Workflows.
    Intercepts and analyzes state objects, tool calls, and LLM text inputs/outputs
    for adversarial injection, jailbreaks, PII leakage, and exfiltration.
    """
    def __init__(self):
        pass

    def scan_text(self, text: str) -> List[Dict[str, Any]]:
        """Scans a raw string for security anomalies across all signature categories."""
        findings = []
        if not text or not isinstance(text, str):
            return findings

        for category, rules in PATTERNS.items():
            for regex, level, desc in rules:
                match = regex.search(text)
                if match:
                    snippet = match.group(0)
                    if len(snippet) > 80:
                        snippet = snippet[:80] + "..."
                    findings.append({
                        "category": category,
                        "threat_level": level,
                        "details": desc,
                        "snippet": snippet
                    })
        return findings

    def _extract_all_strings(self, obj: Any) -> List[str]:
        """Recursively extracts all string values from nested dicts, lists, or primitives."""
        strings = []
        if isinstance(obj, str):
            strings.append(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str):
                    strings.append(k)
                strings.extend(self._extract_all_strings(v))
        elif isinstance(obj, list):
            for item in obj:
                strings.extend(self._extract_all_strings(item))
        return strings

    def scan_transition(
        self,
        run_id: str,
        node_name: str,
        state_before: Dict[str, Any],
        state_after: Dict[str, Any],
        tool_calls: Optional[List[Dict[str, Any]]] = None
    ) -> List[SecurityLogEvent]:
        """
        Scans a complete state transition (before/after states and tool executions)
        and generates SecurityLogEvent telemetry objects for any detected threats.
        """
        security_events = []
        
        # Combine strings from states and tool calls
        all_text_chunks = (
            self._extract_all_strings(state_before) +
            self._extract_all_strings(state_after) +
            self._extract_all_strings(tool_calls or [])
        )
        
        aggregated_text = "\n".join(all_text_chunks)
        findings = self.scan_text(aggregated_text)
        
        # Deduplicate findings by (category, details)
        seen = set()
        for f in findings:
            key = (f["category"], f["details"])
            if key in seen:
                continue
            seen.add(key)
            
            event = SecurityLogEvent(
                run_id=run_id,
                node_name=node_name,
                threat_level=f["threat_level"],
                category=f["category"],
                details=f["details"],
                raw_payload_snippet=f["snippet"],
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            )
            security_events.append(event)
            
        return security_events

# Global singleton instance
agent_guard = AgentGuardScanner()
