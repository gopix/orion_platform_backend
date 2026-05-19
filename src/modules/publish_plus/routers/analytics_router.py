from fastapi import APIRouter

router = APIRouter()

@router.get("/heatmap")
async def get_sales_heatmap():
    return {"message": "Get sales heatmap"}     

@router.get("/trending")
async def get_trending_books():     
    return {"message": "Get trending books"}            


@router.get("/distributor-ranking")
async def get_distributor_ranking():                
    return {"message": "Get distributor ranking"}