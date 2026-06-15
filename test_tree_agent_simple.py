#!/usr/bin/env python
"""Test TREE_STRUCTURE_AGENT by calling API with actual PDF file"""
import requests
import sys
import json

url = 'http://localhost:8000/api/v1/accessibility/orion-validate-pdf'

# Try to find a PDF file
import os
import glob

pdf_files = glob.glob(r'c:\Orion\codebase\orion_backend\src\modules\accessibility_plus\temp\remediat*', recursive=True)
if not pdf_files:
    # Create a minimal PDF using native bytes
    pdf_hex = b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj 4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 100 750 Td (Test) Tj ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\n0000000190 00000 n\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n284\n%%EOF'
    pdf_path = 'test_minimal.pdf'
    with open(pdf_path, 'wb') as f:
        f.write(pdf_hex)
else:
    pdf_path = pdf_files[0]

print(f"Using PDF: {pdf_path}")
print(f"File exists: {os.path.exists(pdf_path)}")

try:
    with open(pdf_path, 'rb') as f:
        files = {'file': (os.path.basename(pdf_path), f, 'application/pdf')}
        data = {'organization_id': '1', 'project_id': '1'}
        
        print("\nCalling API endpoint...")
        response = requests.post(url, files=files, data=data, timeout=30)
        result = response.json()
        
        agent_results = result.get('data', {}).get('agent_results', {})
        
        print(f'\nAgent Results Keys: {list(agent_results.keys())}')
        
        if 'TREE_STRUCTURE_AGENT' in agent_results:
            print('\n✅ SUCCESS! TREE_STRUCTURE_AGENT FOUND!')
            tree_agent = agent_results['TREE_STRUCTURE_AGENT']
            print(f'Check Codes: {list(tree_agent.keys())}')
            for check_code in tree_agent:
                print(f'  - {check_code}')
        else:
            print('\n❌ TREE_STRUCTURE_AGENT NOT FOUND')
            print(f'Available: {list(agent_results.keys())}')
            sys.exit(1)
            
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
