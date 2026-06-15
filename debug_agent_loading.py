"""
Debug script to check what's happening with agent loading
"""
import sys
from pathlib import Path

# Clear any cached imports
for module_name in list(sys.modules.keys()):
    if 'accessibility' in module_name.lower():
        del sys.modules[module_name]

print("Attempting fresh import...")
try:
    from src.modules.accessibility_plus.engines.accesibility_engine_pipeline import AccessibilityEnginePipeline
    
    pipeline = AccessibilityEnginePipeline()
    
    print(f"\n✓ Pipeline loaded")
    print(f"EXECUTION_SEQUENCE: {pipeline.EXECUTION_SEQUENCE}")
    print(f"TREE_STRUCTURE_AGENT in EXECUTION_SEQUENCE: {'TREE_STRUCTURE_AGENT' in pipeline.EXECUTION_SEQUENCE}")
    print(f"\nAGENT_CLASS_MAP keys: {sorted(pipeline.AGENT_CLASS_MAP.keys())}")
    print(f"TREE_STRUCTURE_AGENT in AGENT_CLASS_MAP: {'TREE_STRUCTURE_AGENT' in pipeline.AGENT_CLASS_MAP}")
    
    if 'TREE_STRUCTURE_AGENT' in pipeline.AGENT_CLASS_MAP:
        agent = pipeline._resolve_agent('TREE_STRUCTURE_AGENT')
        print(f"\nAgent resolution:")
        print(f"  Agent resolved: {agent is not None}")
        if agent:
            print(f"  Agent name: {agent.agent_name}")
            print(f"  Agent checks: {agent.supported_checks}")
        else:
            print(f"  ERROR: Could not resolve agent")
    
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
