#!/usr/bin/env python
"""Quick test to check API response"""
import json
import requests

url = 'http://localhost:8000/api/v1/accessibility/orion-validate-pdf'

# Find an existing PDF
import glob
pdfs = glob.glob(r'src\modules\accessibility_plus\temp\remediat*')

if not pdfs:
    print("❌ No test PDF found")
    exit(1)

pdf_path = pdfs[0]
print(f"Using: {pdf_path}")

try:
    with open(pdf_path, 'rb') as f:
        files = {'file': (pdf_path.split('\\')[-1], f)}
        data = {'organization_id': '1', 'project_id': '1'}
        r = requests.post(url, files=files, data=data, timeout=30)
        result = r.json()
        
        agents = result.get('data', {}).get('agent_results', {})
        print(f"\n📊 Agents in response ({len(agents)}):")
        for agent_code in sorted(agents.keys()):
            print(f"   ✓ {agent_code}")
        
        if 'TREE_STRUCTURE_AGENT' in agents:
            print("\n✅ TREE_STRUCTURE_AGENT FOUND!")
            checks = agents['TREE_STRUCTURE_AGENT']
            print(f"   Checks: {list(checks.keys())}")
        else:
            print("\n❌ TREE_STRUCTURE_AGENT NOT FOUND")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
