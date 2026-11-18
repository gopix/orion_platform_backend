from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional


class UserCreate(BaseModel):
    user_name: str
    email: EmailStr
    password: str
    organization_id: int


class UserResponse(BaseModel):
    id: int
    user_name: str
    email: EmailStr
    role_name: Optional[str]
    organization_name: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    user_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    organization_id: Optional[int] = None
    role_id: Optional[int] = None


class RoleCreate(BaseModel):
    role_name: str
    role_description: Optional[str] = None
    is_active: int = 1


class RoleUpdate(BaseModel):
    role_name: Optional[str] = None
    role_description: Optional[str] = None
    is_active: Optional[int] = None


class RoleResponse(BaseModel):
    id: int
    role_name: str
    role_description: Optional[str] = None
    is_Active: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}