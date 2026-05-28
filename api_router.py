from fastapi import APIRouter

# Import routers from each module
from src.modules.auth.routers.auth_router import router as auth_router
from src.modules.editor_plus.routers.editor_router import router as editor_router
from src.modules.publish_plus.routers.publish_router import router as publish_router
from src.modules.submit_plus.routers.submit_router import router as submit_router
from src.modules.accessibility_plus.routers.accessibility_router import router as accessibility_router
from src.modules.master_setup.routers.master_setup_router import router as master_setup_router

api_router = APIRouter(prefix="/api/v1")

# Include each module's router
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(editor_router, prefix="/editor", tags=["editor"])
api_router.include_router(publish_router, prefix="/publish", tags=["publish"])
api_router.include_router(submit_router, prefix="/submit", tags=["submit"])
api_router.include_router(accessibility_router, prefix="/accessibility", tags=["accessibility & remediation"])
api_router.include_router(master_setup_router, prefix="/master-setup", tags=["master_setup"])
