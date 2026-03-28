from fastapi import APIRouter

router = APIRouter()

@router.get("/test")
async def test_editor():
    return {"message": "Editor Plus router is working"}
