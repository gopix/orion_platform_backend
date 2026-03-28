from fastapi import APIRouter

router = APIRouter()

@router.get("/test")
async def test_publish():
    return {"message": "Publish Plus router is working"}
