from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.modules.auth.schemas.auth_schema import (
    UserCreate,
    UserResponse,
    UserLogin,
    UserUpdate,
    RoleCreate,
    RoleUpdate,
)
from src.modules.auth.services.auth_service import (
    create_user,
    authenticate_user,
    build_user_response,
    get_users,
    get_user,
    update_user,
    delete_user,
)
from src.modules.auth.services import role_service
from src.core.database import get_db
from src.core.response import build_response

router = APIRouter()


@router.post("/register", response_model=UserResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
	user = create_user(db, user_in)
	return build_user_response(db, user)

@router.post("/login", response_model=UserResponse)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
	user = authenticate_user(db, user_in.email, user_in.password)
	if not user:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
	return build_user_response(db, user)



# ==================== User CRUD ====================
# Note: user creation is handled by POST /register above.
@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    """List all users."""
    users = get_users(db)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Users retrieved successfully",
        data=[build_user_response(db, user) for user in users],
    )


@router.get("/users/{user_id}")
def read_user(user_id: int, db: Session = Depends(get_db)):
    """Get a single user by id."""
    user = get_user(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="User retrieved successfully",
        data=build_user_response(db, user),
    )


@router.put("/users/{user_id}")
def edit_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    """Update an existing user."""
    user = update_user(db, user_id, payload)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="User updated successfully",
        data=build_user_response(db, user),
    )


@router.delete("/users/{user_id}")
def remove_user(user_id: int, db: Session = Depends(get_db)):
    """Delete a user."""
    success = delete_user(db, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="User deleted successfully",
        data={"id": user_id},
    )


# ==================== Role CRUD ====================
@router.post("/roles", status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreate, db: Session = Depends(get_db)):
    """Create a new role."""
    role = role_service.create_role(db, payload)
    return build_response(
        response_code=status.HTTP_201_CREATED,
        message="Role created successfully",
        data=role.to_dict(),
    )


@router.get("/roles")
def list_roles(db: Session = Depends(get_db)):
    """List all roles."""
    roles = role_service.get_roles(db)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Roles retrieved successfully",
        data=[role.to_dict() for role in roles],
    )


@router.get("/roles/{role_id}")
def read_role(role_id: int, db: Session = Depends(get_db)):
    """Get a single role by id."""
    role = role_service.get_role(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Role retrieved successfully",
        data=role.to_dict(),
    )


@router.put("/roles/{role_id}")
def edit_role(role_id: int, payload: RoleUpdate, db: Session = Depends(get_db)):
    """Update an existing role."""
    role = role_service.update_role(db, role_id, payload)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Role updated successfully",
        data=role.to_dict(),
    )


@router.delete("/roles/{role_id}")
def remove_role(role_id: int, db: Session = Depends(get_db)):
    """Delete a role."""
    success = role_service.delete_role(db, role_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Role deleted successfully",
        data={"id": role_id},
    )