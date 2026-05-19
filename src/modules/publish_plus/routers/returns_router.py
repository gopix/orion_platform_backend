from fastapi import APIRouter

router = APIRouter()

@router.post("/log")
async def log_return():
    return {"message": "Log a return"}  

@router.get("/distributor/{id}")
async def get_distributor_returns(id: int):
    return {"message": f"Get returns for distributor with ID {id}"} 

@router.get("/returns")
async def get_returns_summary():
    return {"message": "Get returns summary"}   


@router.post("/returns")
async def create_return():
    return {"message": "Create a return"}   