from fastapi import APIRouter

router = APIRouter()

@router.get("/test")
async def test_submit():
    return {"message": "Submit Plus router is working"}
