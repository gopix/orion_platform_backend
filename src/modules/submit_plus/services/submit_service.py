# submit_service.py
from src.modules.submit_plus.models.manuscript_model import Manuscript
from src.modules.submit_plus.models.strcture_template_model import StrctureTemplate

from src.core.database import SessionLocal
from src.modules.submit_plus.pipelines.manuscript_pipeline import ManuscriptPipeline

import os
import json
from datetime import datetime
from src.core.config import settings
from src.utils.constants import ManuscriptStatus
from src.core.logger import get_logger

logger = get_logger(__name__)

def create_manuscript_service(payload):

    # Step 1: Save file
    file_path = save_upload_file(payload.file)

    manuscript = Manuscript(
        title=payload.title,
        author=payload.author,
        status=ManuscriptStatus.SUBMITTED,
        organization_id=payload.organization_id,
        file_path=file_path,
        file_name=payload.file.filename
    )

    print(f"Received file: {payload.file.filename}")
    try:
        db = SessionLocal()
        db.add(manuscript)
        db.commit()
        db.refresh(manuscript)
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating manuscript: {str(e)}", exc_info=True)
    finally:
        if 'db' in locals():
            db.close()


    return manuscript




def save_engine_results(manuscript_id: int, engine_name: str, results: dict) -> bool:
    """
    Save engine analysis results to database.
    Service layer responsibility: Handle all database write operations.
    """
    try:
        db = SessionLocal()
        manuscript = db.query(Manuscript).filter(Manuscript.id == manuscript_id).first()
        
        if not manuscript:
            logger.error(f"Manuscript {manuscript_id} not found for storing {engine_name} results")
            return False
        
        # Store results as JSON (implementation depends on your DB schema)
        # This is a placeholder - adjust based on your actual schema
        results_json = json.dumps(results)
        logger.info(f"Storing {engine_name} results for manuscript {manuscript_id}")

        db.close()
        return True
        
    except Exception as e:
        logger.error(f"Error saving {engine_name} results for manuscript {manuscript_id}: {str(e)}", exc_info=True)
        return False
    
    finally:        
        if 'db' in locals():
            db.close()



def save_upload_file(upload_file) -> str:
    upload_dir = settings.upload_dir  # Read from .env via config
    os.makedirs(upload_dir, exist_ok=True)
    file_location = os.path.join(upload_dir, upload_file.filename)
    with open(file_location, "wb") as buffer:
        buffer.write(upload_file.file.read())
    return file_location


def define_structure_template_service(payload):
    # Convert structure list to JSON string
    structure_json = json.dumps(payload.structure) if isinstance(payload.structure, list) else payload.structure
    
    strctureTemplate = StrctureTemplate(
        organization_id=payload.organization_id,
        book_id=payload.book_id,
        template_name=payload.template_name,
        structure_json=structure_json,
        is_active=1,
        created_at=datetime.now().isoformat()
    )

    print(f"Creating structure template: {payload.template_name}")
    try:
        db = SessionLocal()
        db.add(strctureTemplate)
        db.commit()
        db.refresh(strctureTemplate)
        print(f"Template created successfully with ID: {strctureTemplate.id}")
    except Exception as e:
        db.rollback()
        print(f"Error creating template: {str(e)}")
        raise e
    finally:
        db.close()


    return strctureTemplate


def get_structure_template_for_org(organization_id: int) -> dict:
    """
    Fetch structure template for an organization.
    """
    try:
        db = SessionLocal()
        template = db.query(StrctureTemplate).filter(
            StrctureTemplate.organization_id == organization_id,
            StrctureTemplate.is_active == 1
        ).first()
        
        if template:
            return {
                "id": template.id,
                "template_name": template.template_name,
                "structure_json": template.structure_json
            }
        return None
    except Exception as e:
        logger.error(f"Error fetching structure template for org {organization_id}: {str(e)}")
        return None
    finally:
        if 'db' in locals():
            db.close()


def process_manuscript_submission(payload) -> dict:
    
    try:
        # Step 1: Create manuscript record
        manuscript = create_manuscript_service(payload)
        
        # Step 2: Fetch structure template for the organization
        template = get_structure_template_for_org(manuscript.organization_id)
        
        # Step 3: Combine manuscript and template into dictionary
        manuscript_detail = {
            "manuscript_id": manuscript.id,
            "title": manuscript.title,
            "author": manuscript.author,
            "organization_id": manuscript.organization_id,
            "file_path": manuscript.file_path,
            "template": template
        }
        
        # Step 4: Trigger analysis pipeline
        pipeline = ManuscriptPipeline()
        pipeline.run(manuscript_detail)
        
        return {
            "message": "Manuscript submitted successfully",
            "manuscript_id": manuscript.id
        }
    except Exception as e:
        logger.error(f"Error processing manuscript submission: {str(e)}", exc_info=True)
        raise
