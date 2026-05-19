from fastapi import APIRouter, UploadFile, File, Form, status
from typing import Optional

from src.modules.submit_plus.controllers.submit_controller import manuscript_submission, structure_template_submission
from src.core.response import build_response, APIResponse
from src.modules.submit_plus.schema.submit_schema import SubmitPayload, StructureTemplatePayload

router = APIRouter()

@router.get("/test")
async def test_submit():
    return {"message": "Submit Plus router is working"}

@router.post("/manuscripts",status_code=status.HTTP_201_CREATED,response_model=APIResponse)
def create_manuscript_endpoint(
    title: str = Form(...),
    author: str = Form(...),
    organization_id: int = Form(...),
    file: UploadFile = File(...)
):
    payload = SubmitPayload(
        title=title,
        author=author,
        organization_id=organization_id,
        file=file
    )

    result = manuscript_submission(payload)
    return build_response(status_code=201, message="Manuscript submitted successfully", data=result)

@router.post("/structure-templates", status_code=status.HTTP_201_CREATED, response_model=APIResponse)
def create_structure_template(
    organization_id: int = Form(...),
    template_name: str = Form(...),
    structure: str = Form(...),
    book_id: Optional[int] = Form(None)
):
    payload = StructureTemplatePayload(
        organization_id=organization_id,
        book_id=book_id,
        template_name=template_name,
        structure=structure
    )
    
    result = structure_template_submission(payload)
    return build_response(status_code=201, message="Structure template created successfully", data=result)