#!/usr/bin/env python
"""Debug check fetching"""
from src.modules.accessibility_plus.engines.accesibility_engine_pipeline import AccessibilityEnginePipeline

pipeline = AccessibilityEnginePipeline()

# Simulate the _fetch_enabled_checks call
enabled = pipeline._fetch_enabled_checks(organization_id=1, project_id='1')
print(f'Enabled checks for org 1 project 1: {len(enabled)}')

by_agent = pipeline._group_by_agent(enabled)
print(f'Agents with checks: {list(by_agent.keys())}')

if 'TREE_STRUCTURE_AGENT' in by_agent:
    checks = by_agent['TREE_STRUCTURE_AGENT']
    print(f'TREE_STRUCTURE_AGENT checks: {[c.check_code for c in checks]}')
else:
    print('TREE_STRUCTURE_AGENT NOT found')
    
    # Check what's in the org checks table for all agents
    from src.core.database import SessionLocal
    from src.modules.accessibility_plus.models.org_project_accessibility_model import OrgProjectAccessibilityCheckModel
    
    session = SessionLocal()
    all_checks = session.query(OrgProjectAccessibilityCheckModel).filter(
        OrgProjectAccessibilityCheckModel.organization_id == 1,
        OrgProjectAccessibilityCheckModel.is_active.is_(True),
    ).all()
    
    agents = set()
    for check in all_checks:
        agents.add(check.agent_code)
        if check.agent_code == 'TREE_STRUCTURE_AGENT':
            print(f'Found TREE check: {check.check_code}')
    
    print(f'All active agents for org 1: {sorted(agents)}')
    session.close()
