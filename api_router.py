from fastapi import APIRouter

# Import routers from each module
from src.modules.accessibility_word.routers.word_accessibility_router import router as word_accessibility_router
from src.modules.accessibility_ppt.routers.ppt_accessibility_router import router as ppt_accessibility_router
from src.modules.auth.routers.auth_router import router as auth_router
from src.modules.editor_plus.routers.editor_router import router as editor_router
from src.modules.editor_plus.routers.ce_features_router import router as ce_features_router
from src.modules.publish_plus.routers.publish_router import router as publish_router
from src.modules.submit_plus.routers.submit_router import router as submit_router
from src.modules.accessibility_pdf.routers.accessibility_router import router as accessibility_router
from src.modules.accessibility_web.routers.web_accessibility_router import router as web_accessibility_router
from src.modules.master_setup.routers.master_setup_router import router as master_setup_router
from src.modules.book_forge.book_forge_api_router import router as book_forge_router

api_router = APIRouter(prefix="/api/v1")

# Include each module's router
api_router.include_router(auth_router, prefix="/auth", tags=["Authorization"])
api_router.include_router(editor_router, prefix="/editor", tags=["Copy Editor"])
api_router.include_router(ce_features_router, prefix="/editor", tags=["Copy Editor"])
api_router.include_router(publish_router, prefix="/publish", tags=["Publish"])
api_router.include_router(accessibility_router, prefix="/accessibility", tags=["PDF Accessibility & Remediation"])
api_router.include_router(web_accessibility_router, prefix="/web-accessibility", tags=["Web Accessibility"])
api_router.include_router(ppt_accessibility_router, prefix="/ppt-accessibility", tags=["PPT Accessibility & Remediation"])
api_router.include_router(word_accessibility_router, prefix="/word-accessibility", tags=["Word Accessibility & Remediation"])
api_router.include_router(master_setup_router, prefix="/master-setup", tags=["Master Setup"])
api_router.include_router(book_forge_router, prefix="/book-forge", tags=["Book Forge"])