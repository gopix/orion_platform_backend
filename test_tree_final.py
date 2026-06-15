#!/usr/bin/env python
"""Test if TREE_STRUCTURE_AGENT is now working"""
import requests

url = 'http://localhost:8000/api/v1/accessibility/orion-validate-pdf'
pdf_path = r'src\modules\accessibility_plus\temp\remediated\aaa.pdf.pdf'

with open(pdf_path, 'rb') as f:
    files = {'file': ('test.pdf', f)}
    data = {'organization_id': '1', 'project_id': '1'}
    r = requests.post(url, files=files, data=data, timeout=30)
    result = r.json()
    ae = result.get('data', {}).get('agent_execution', {})
    ar = result.get('data', {}).get('agent_results', [])
    
    executed = ae.get('executed_agent_codes', [])
    print(f'Executed agents ({len(executed)}):')
    for agent in sorted(executed):
        print(f'  ✓ {agent}')
    
    print()
    if 'TREE_STRUCTURE_AGENT' in executed:
        print('✅ SUCCESS! TREE_STRUCTURE_AGENT is executing!')
        
        # Find TREE agent results
        for agent_result in ar:
            if agent_result and agent_result.get('agent_name') == 'TREE_STRUCTURE_AGENT':
                print(f'  Issues: {agent_result.get("issue_count")}')
                print(f'  Success: {agent_result.get("success")}')
                if agent_result.get('issues'):
                    print(f'  Check results:')
                    for issue in agent_result.get('issues', [])[:3]:
                        print(f'    - {issue.get("rule_id")}')
    else:
        print('❌ TREE_STRUCTURE_AGENT still not executing')
