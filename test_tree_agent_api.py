#!/usr/bin/env python
"""Test script to verify TREE_STRUCTURE_AGENT in API response"""
import requests
import sys
from reportlab.pdfgen import canvas
from io import BytesIO

url = 'http://localhost:8000/api/v1/accessibility/orion-validate-pdf'
headers = {'Authorization': 'Bearer test-token'}

# Create minimal test PDF
pdf_buffer = BytesIO()
c = canvas.Canvas(pdf_buffer)
c.drawString(100, 750, 'Test Document')
c.showPage()
c.save()
pdf_buffer.seek(0)

# Call API
files = {'file': ('test.pdf', pdf_buffer, 'application/pdf')}
data = {'organization_id': '1', 'project_id': '1'}

try:
    print("Calling API endpoint...")
    response = requests.post(url, files=files, data=data, headers=headers, timeout=30)
    result = response.json()
    
    configured = result.get('data', {}).get('configured_agent_codes', [])
    available = result.get('data', {}).get('available_agent_codes', [])
    agent_results = result.get('data', {}).get('agent_results', {})
    
    print(f'\nConfigured Agents ({len(configured)}): {configured}')
    print(f'Available Agents ({len(available)}): {available}')
    print(f'Agent Results: {list(agent_results.keys())}')
    
    if 'TREE_STRUCTURE_AGENT' in agent_results:
        print('\n✅ SUCCESS! TREE_STRUCTURE_AGENT FOUND IN RESPONSE!')
        tree_agent = agent_results['TREE_STRUCTURE_AGENT']
        print(f'   Check Codes: {list(tree_agent.keys())}')
        for check_code, check_data in tree_agent.items():
            print(f'   - {check_code}: {type(check_data)}')
    else:
        print('\n❌ TREE_STRUCTURE_AGENT NOT FOUND - Still missing from response')
        sys.exit(1)
        
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
