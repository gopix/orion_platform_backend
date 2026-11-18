from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.modules.auth.models.user_model import User
from src.modules.auth.schemas.auth_schema import UserCreate, UserResponse, UserUpdate
from src.modules.auth.utils.password_utils import hash_password, verify_password


def build_user_response(db: Session, user: User) -> UserResponse:
    organization_name = None
    role_name = None

    if user.organization_id is not None:
        organization_name = db.execute(
            text("SELECT organization_name FROM organizations WHERE id = :organization_id"),
            {"organization_id": user.organization_id},
        ).scalar_one_or_none()

    if user.role_id is not None:
        role_name = db.execute(
            text("SELECT role_name FROM roles WHERE role_id = :role_id"),
            {"role_id": user.role_id},
        ).scalar_one_or_none()

    return UserResponse(
        id=user.id,
        user_name=user.user_name,
        email=user.email,
        role_name=role_name,
        organization_name=organization_name,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def create_user(db: Session, user_in: UserCreate):
    # Check duplicate user
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        user_name=user_in.user_name,
        email=user_in.email,
        password_hash=hash_password(user_in.password),
        organization_id=user_in.organization_id,
        role_id=1
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


# ==================== User CRUD ====================
def get_users(db: Session) -> List[User]:
    """Return all users, oldest first."""
    return db.query(User).order_by(User.id.asc()).all()


def get_user(db: Session, user_id: int) -> Optional[User]:
    """Return a single user by id, or None."""
    return db.query(User).filter(User.id == user_id).first()


def update_user(db: Session, user_id: int, user_in: UserUpdate) -> Optional[User]:
    """Update the mutable fields of a user. Returns None if not found."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    if user_in.email is not None and user_in.email != user.email:
        clash = (
            db.query(User)
            .filter(User.email == user_in.email, User.id != user_id)
            .first()
        )
        if clash:
            raise HTTPException(status_code=400, detail="Email already registered")
        user.email = user_in.email

    if user_in.user_name is not None:
        user.user_name = user_in.user_name
    if user_in.organization_id is not None:
        user.organization_id = user_in.organization_id
    if user_in.role_id is not None:
        user.role_id = user_in.role_id
    if user_in.password:
        user.password_hash = hash_password(user_in.password)

    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    """Delete a user. Returns False if not found."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    db.delete(user)
    db.commit()
    return True