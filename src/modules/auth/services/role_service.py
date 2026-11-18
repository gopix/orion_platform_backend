from typing import List, Optional

from sqlalchemy.orm import Session

from src.modules.auth.models.role_model import Roles
from src.modules.auth.schemas.auth_schema import RoleCreate, RoleUpdate


def create_role(db: Session, role_in: RoleCreate) -> Roles:
    """Create a new role."""
    role = Roles(
        role_name=role_in.role_name,
        role_description=role_in.role_description,
        is_Active=role_in.is_active,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def get_roles(db: Session) -> List[Roles]:
    """Return all roles, oldest first."""
    return db.query(Roles).order_by(Roles.role_id.asc()).all()


def get_role(db: Session, role_id: int) -> Optional[Roles]:
    """Return a single role by id, or None."""
    return db.query(Roles).filter(Roles.role_id == role_id).first()


def update_role(db: Session, role_id: int, role_in: RoleUpdate) -> Optional[Roles]:
    """Update the mutable fields of a role. Returns None if not found."""
    role = db.query(Roles).filter(Roles.role_id == role_id).first()
    if not role:
        return None

    if role_in.role_name is not None:
        role.role_name = role_in.role_name
    if role_in.role_description is not None:
        role.role_description = role_in.role_description
    if role_in.is_active is not None:
        role.is_Active = role_in.is_active

    db.commit()
    db.refresh(role)
    return role


def delete_role(db: Session, role_id: int) -> bool:
    """Delete a role. Returns False if not found."""
    role = db.query(Roles).filter(Roles.role_id == role_id).first()
    if not role:
        return False
    db.delete(role)
    db.commit()
    return True
