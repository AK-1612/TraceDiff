import sqlite3
from datetime import datetime

def insert_test_security_log():
    conn = sqlite3.connect("tracediff.db")
    cursor = conn.cursor()
    
    # Insert a simulated critical prompt injection / jailbreak event
    cursor.execute("""
        INSERT INTO security_logs (run_id, node_name, threat_level, details, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (
        "ollama_agent_1793599972",
        "AgentGuardVectorScanner",
        "CRITICAL",
        "Adversarial intent detected: Prompt injection bypass payload matching /etc/passwd exfiltration.",
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    
    conn.commit()
    conn.close()
    print("Test security log inserted successfully!")

if __name__ == "__main__":
    insert_test_security_log()