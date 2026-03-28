from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.modules.auth.models.user_model import User
from src.modules.auth.schemas.auth_schema import UserCreate
from src.modules.auth.utils.password_utils import hash_password, verify_password


def create_user(db: Session, user_in: UserCreate):
    # Check duplicate user
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=user_in.email,
        password_hash=hash_password(user_in.password)
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str):
    user = db.query(User).filter(User.email == email).first()

    if not user:
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user