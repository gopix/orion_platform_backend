from src.modules.accessibility_plus.engines.accesibility_engine_pipeline import AccessibilityEnginePipeline

pipeline = AccessibilityEnginePipeline()
print('=== Pipeline Configuration ===')
print(f'EXECUTION_SEQUENCE length: {len(pipeline.EXECUTION_SEQUENCE)}')
print('Agents in sequence:')
for agent_code in pipeline.EXECUTION_SEQUENCE:
    print(f'  - {agent_code}')
print()
print(f'TREE_STRUCTURE_AGENT in EXECUTION_SEQUENCE: {"TREE_STRUCTURE_AGENT" in pipeline.EXECUTION_SEQUENCE}')
print()
print('=== Testing Agent Resolution ===')
tree_agent = pipeline._resolve_agent('TREE_STRUCTURE_AGENT')
print(f'Agent resolved: {tree_agent is not None}')
if tree_agent:
    print(f'Agent name: {tree_agent.agent_name}')
    print(f'Supported checks: {tree_agent.supported_checks}')
