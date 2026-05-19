from fastapi import APIRouter

router = APIRouter()

@router.get("/outstanding")
async def get_outstanding_payments():
    return {"message": "Get outstanding payments"}  

@router.get("/ageing")
async def get_ageing_report():      
    return {"message": "Get ageing report"} 

@router.post("/reminders/send")
async def send_payment_reminders():
    return {"message": "Send payment reminders"}    
