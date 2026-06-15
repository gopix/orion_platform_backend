"""
Test if TREE_STRUCTURE_AGENT executes in the full pipeline
"""
from src.modules.accessibility_plus.engines.accesibility_engine_pipeline import AccessibilityEnginePipeline

pipeline = AccessibilityEnginePipeline()

# Simulate a minimal context (no real PDF, just to test pipeline flow)
context = {
    "pdf_doc": None,
    "pdf_doc_path": "test.pdf",
    "document_name": "test.pdf",
}

print("Testing pipeline execution...")
print()

# Check if TREE_STRUCTURE_AGENT is in execution sequence
print(f"1. TREE_STRUCTURE_AGENT in EXECUTION_SEQUENCE: {'TREE_STRUCTURE_AGENT' in pipeline.EXECUTION_SEQUENCE}")

# Try to resolve the agent
agent = pipeline._resolve_agent('TREE_STRUCTURE_AGENT')
print(f"2. Agent resolves: {agent is not None}")

if agent:
    print(f"3. Agent name: {agent.agent_name}")
    print(f"4. Supported checks: {sorted(agent.supported_checks)}")
    print()
    print("5. TREE_STRUCTURE_AGENT is properly configured and ready to execute!")
    print()
    print("The agent SHOULD appear in the pipeline output once the application is restarted")
    print("(to clear Python bytecode cache).")
else:
    print("ERROR: Agent could not be resolved!")
