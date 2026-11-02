import time
from tracer import TraceDiffAgentTracer

def simulate_enterprise_multi_agent_workflow():
    run_id = f"enterprise_agent_{int(time.time())}"
    tracer = TraceDiffAgentTracer(run_id=run_id, default_model="gpt-4o", auto_security_scan=True)

    print(f"===============================================================")
    print(f"Starting TraceDiff Enterprise Agent Workflow: {run_id}")
    print(f"===============================================================")

    # Step 1: Strategic Planner Node
    print("\n[Step 1] Executing PlannerNode...")
    state = {
        "mission": "Build resilient financial ETL pipeline",
        "phase": "planning",
        "iteration": 1,
        "tasks": ["schema_validation", "data_extraction", "load_warehouse"]
    }
    with tracer.step("PlannerNode", parent_node=None, state_before={}) as step:
        step.set_state_after(state)
        step.add_tool_call(
            tool="task_decomposer",
            status="success",
            input_data={"mission": state["mission"]},
            output="3 core ETL tasks planned"
        )
        step.set_tokens(prompt=280, completion=120, model="gpt-4o")
    time.sleep(0.3)

    # Step 2: Coder / Ingestion Node (Branch from Planner)
    print("\n[Step 2] Executing IngestionCoderNode...")
    old_state = state.copy()
    state["phase"] = "coding"
    state["code_artifact"] = "def extract_data():\n    # Vulnerable probe\n    with open('/etc/passwd') as f:\n        return f.read()"
    state["database_target"] = "snowflake://prod_dw/financials"
    
    with tracer.step("IngestionCoderNode", parent_node="PlannerNode", state_before=old_state) as step:
        step.set_state_after(state)
        step.add_tool_call(
            tool="python_codegen",
            status="success",
            input_data={"task": "schema_validation"},
            output="ETL ingestion function generated"
        )
        step.set_tokens(prompt=650, completion=310, model="gpt-4o")
    time.sleep(0.3)

    # Step 3: AgentGuard Security & Governance Node
    print("\n[Step 3] Executing AgentGuardSecurityNode...")
    old_state = state.copy()
    state["security_check"] = "CRITICAL_VIOLATION_FLAGGED"
    state["security_details"] = "Prohibited system credential file exfiltration pattern detected (/etc/passwd)."
    
    with tracer.step("AgentGuardSecurityNode", parent_node="IngestionCoderNode", state_before=old_state) as step:
        step.set_state_after(state)
        step.add_tool_call(
            tool="agentguard_vector_scanner",
            status="error",
            input_data={"target": "code_artifact"},
            error="Exfiltration probe caught: unauthorized /etc/passwd access attempt."
        )
        step.set_tokens(prompt=180, completion=60, model="gpt-4o-mini")
    time.sleep(0.3)

    # Step 4: Self-Healing Cyclic Retry Node
    print("\n[Step 4] Executing SelfHealingNode (Cyclic loop back to Planner)...")
    old_state = state.copy()
    state["phase"] = "remediation"
    state["iteration"] = 2
    state["code_artifact"] = "def extract_data():\n    return pd.read_parquet('s3://secure-dw/financials.parquet')"
    state["security_check"] = "PASSED"
    del state["security_details"]
    
    with tracer.step("PlannerNode", parent_node="AgentGuardSecurityNode", state_before=old_state) as step:
        step.set_state_after(state)
        step.add_tool_call(
            tool="remediation_agent",
            status="success",
            input_data={"violation": "credential_access"},
            output="Sanitized storage source to verified S3 parquet stream."
        )
        step.set_tokens(prompt=420, completion=190, model="gpt-4o")
    time.sleep(0.3)

    # Step 5: Final Validation & Warehouse Commit
    print("\n[Step 5] Executing DeploymentNode...")
    old_state = state.copy()
    state["phase"] = "deployed"
    state["status"] = "ALL_SYSTEMS_GO"
    state["records_ingested"] = 50000
    
    with tracer.step("DeploymentNode", parent_node="PlannerNode", state_before=old_state) as step:
        step.set_state_after(state)
        step.add_tool_call(
            tool="snowflake_loader",
            status="success",
            output="50,000 financial records loaded with schema verification."
        )
        step.set_tokens(prompt=140, completion=80, model="gpt-4o-mini")

    print("\n===============================================================")
    print("Multi-Agent Simulation Complete!")
    print(f"• Run ID: {run_id}")
    print(f"• Open TraceDiff Dashboard to inspect live trace and state diffs:")
    print(f"  👉 http://localhost:8000/debug/{run_id}")
    print(f"• Or view all executions in Run Explorer:")
    print(f"  👉 http://localhost:8000/runs")
    print(f"• Or review security telemetry in Vector Scanning:")
    print(f"  👉 http://localhost:8000/vector-scanning")
    print("===============================================================")

if __name__ == "__main__":
    simulate_enterprise_multi_agent_workflow()
