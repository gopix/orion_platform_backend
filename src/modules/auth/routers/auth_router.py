from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.modules.auth.schemas.auth_schema import UserCreate, UserResponse, UserLogin
from src.modules.auth.services.auth_service import create_user, authenticate_user
from src.modules.auth.models.user_model import User
from src.core.database import get_db

router = APIRouter()

@router.post("/register", response_model=UserResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
	user = create_user(db, user_in)
	return user

@router.post("/login", response_model=UserResponse)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
	user = authenticate_user(db, user_in.email, user_in.password)
	if not user:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
	return user
