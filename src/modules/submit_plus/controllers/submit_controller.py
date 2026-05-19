# submit_controller.py
import json
from src.modules.submit_plus.services.submit_service import process_manuscript_submission, define_structure_template_service

def manuscript_submission(payload):
    """
    Handle manuscript submission.
    Calls service layer to process the submission.
    """
    return process_manuscript_submission(payload)


def structure_template_submission(payload):
    """
    Handle structure template submission.
    Parses structure and calls service layer.
    """
    # Parse structure if it's a JSON string
    if isinstance(payload.structure, str):
        try:
            structure_list = json.loads(payload.structure) if payload.structure.startswith('[') else payload.structure.split(',')
            structure_list = [s.strip() for s in structure_list]
        except (json.JSONDecodeError, AttributeError):
            structure_list = [s.strip() for s in payload.structure.split(',')]
    else:
        structure_list = payload.structure
    
    # Update payload with parsed structure
    payload.structure = structure_list
    
    # Call service to create template
    template = define_structure_template_service(payload)
    
    # Return template data
    return {
        "id": template.id,
        "organization_id": template.organization_id,
        "book_id": template.book_id,
        "template_name": template.template_name,
        "structure": json.loads(template.structure_json) if template.structure_json else []
    }