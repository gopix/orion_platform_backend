from fastapi import APIRouter

# Import child routers
from src.modules.publish_plus.routers.analytics_router import router as analytics_router
from src.modules.publish_plus.routers.finance_router import router as finance_router

router = APIRouter()

@router.get("/test")
async def test_publish():
    return {"message": "Publish Plus router is working"}


# ✅ Include Analytics routes under Publish+
router.include_router(
    analytics_router,
    prefix="/analytics",
    tags=["Publish Analytics"]
)

# ✅ Include Finance routes under Publish+
router.include_router(
    finance_router,
    prefix="/finance",
    tags=["Publish Finance"]
)