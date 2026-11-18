from fastapi import APIRouter

from src.modules.book_forge.routers.project_router import router as project_router
from src.modules.book_forge.routers.document_router import router as document_router
from src.modules.book_forge.routers.export_router import router as export_router
from src.modules.book_forge.routers.prompt_router import router as prompt_router
from src.modules.book_forge.routers.category_router import router as category_router
from src.modules.book_forge.routers.audit_sheet_router import (
    router as audit_sheet_router,
)

router = APIRouter()

router.include_router(project_router)
router.include_router(document_router)
router.include_router(export_router)
router.include_router(prompt_router)
router.include_router(category_router)
router.include_router(audit_sheet_router)
