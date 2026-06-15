#!/usr/bin/env python
"""Insert TREE_STRUCTURE_AGENT checks into database"""
from src.modules.accessibility_plus.engines.validator.tree_structure_agent import TreeStructureAgent
from src.core.database import SessionLocal
from src.modules.accessibility_plus.models.master_accessibility_model import MasterAccessibilityModel
from src.modules.accessibility_plus.models.org_project_accessibility_model import OrgProjectAccessibilityCheckModel
from datetime import datetime

agent = TreeStructureAgent()

checks_config = [
    {
        'check_code': 'TREE-001',
        'check_name': 'Full Document Structure Tree',
        'description': 'Extracts complete hierarchical PDF structure with all elements',
        'category': 'Document Structure',
        'default_priority': 'HIGH',
        'wcag_reference': None,
        'pdfua_reference': 'ISO 32000-2',
        'remediation_guidance': 'Review structure tree for missing or incorrect element types',
        'agent_code': 'TREE_STRUCTURE_AGENT',
    },
    {
        'check_code': 'TREE-002',
        'check_name': 'Structure Tree Statistics',
        'description': 'Counts elements by type and analyzes document depth and nesting',
        'category': 'Document Structure',
        'default_priority': 'MEDIUM',
        'wcag_reference': None,
        'pdfua_reference': 'ISO 32000-2',
        'remediation_guidance': 'Analyze statistics to identify structural issues',
        'agent_code': 'TREE_STRUCTURE_AGENT',
    },
    {
        'check_code': 'TREE-003',
        'check_name': 'Elements by Type',
        'description': 'Searchable flat list of all elements organized by type',
        'category': 'Document Structure',
        'default_priority': 'MEDIUM',
        'wcag_reference': None,
        'pdfua_reference': 'ISO 32000-2',
        'remediation_guidance': 'Filter and review elements by type for correctness',
        'agent_code': 'TREE_STRUCTURE_AGENT',
    },
]

session = SessionLocal()

# Insert into master table
for cfg in checks_config:
    existing = session.query(MasterAccessibilityModel).filter(
        MasterAccessibilityModel.check_code == cfg['check_code']
    ).first()
    
    if not existing:
        new_check = MasterAccessibilityModel(**cfg, is_active=True, created_at=datetime.now())
        session.add(new_check)
        print(f'✓ Created {cfg["check_code"]} in master table')
    else:
        print(f'~ {cfg["check_code"]} already exists')

session.commit()

# Enable for organization 1
for cfg in checks_config:
    existing = session.query(OrgProjectAccessibilityCheckModel).filter(
        OrgProjectAccessibilityCheckModel.organization_id == 1,
        OrgProjectAccessibilityCheckModel.project_id.is_(None),
        OrgProjectAccessibilityCheckModel.check_code == cfg['check_code'],
    ).first()
    
    if not existing:
        org_check = OrgProjectAccessibilityCheckModel(
            organization_id=1,
            project_id=None,
            check_code=cfg['check_code'],
            check_name=cfg['check_name'],
            category=cfg['category'],
            default_priority=cfg['default_priority'],
            agent_code=cfg['agent_code'],
            is_active=True,
            created_at=datetime.now(),
        )
        session.add(org_check)
        print(f'✓ Enabled {cfg["check_code"]} for org 1')
    else:
        print(f'~ {cfg["check_code"]} already enabled')

# Get master check IDs and enable for org 1
for cfg in checks_config:
    master_check = session.query(MasterAccessibilityModel).filter(
        MasterAccessibilityModel.check_code == cfg['check_code']
    ).first()
    
    if not master_check:
        print(f'ERROR: Master check {cfg["check_code"]} not found')
        continue
    
    existing = session.query(OrgProjectAccessibilityCheckModel).filter(
        OrgProjectAccessibilityCheckModel.organization_id == 1,
        OrgProjectAccessibilityCheckModel.project_id.is_(None),
        OrgProjectAccessibilityCheckModel.check_code == cfg['check_code'],
    ).first()
    
    if not existing:
        org_check = OrgProjectAccessibilityCheckModel(
            organization_id=1,
            project_id=None,
            master_check_id=master_check.check_id,
            check_code=cfg['check_code'],
            check_name=cfg['check_name'],
            category=cfg['category'],
            default_priority=cfg['default_priority'],
            agent_code=cfg['agent_code'],
            is_active=True,
            created_at=datetime.now(),
        )
        session.add(org_check)
        print(f'✓ Enabled {cfg["check_code"]} for org 1')
    else:
        print(f'~ {cfg["check_code"]} already enabled')

session.commit()
session.close()
print('\n✅ Database updated! TREE_STRUCTURE_AGENT checks are now enabled.')
