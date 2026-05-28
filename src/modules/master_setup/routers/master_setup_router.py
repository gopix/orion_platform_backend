from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.response import build_response
from src.modules.master_setup.models.organization_model import Organization
from src.modules.master_setup.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["master_setup"])
organization_service = OrganizationService()


# ==================== CRUD Endpoints ====================
@router.post("", status_code=status.HTTP_201_CREATED)
def create_organization(name: str, db: Session = Depends(get_db)):
    """Create a new organization."""
    try:
        org = organization_service.create_organization(db=db, name=name)
        return build_response(
            response_code=201,
            message="Organization created successfully",
            data=org.to_dict()
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("")
def get_all_organizations(db: Session = Depends(get_db)):
    """Get all organizations."""
    orgs = organization_service.get_all_organizations(db=db)
    return build_response(
        response_code=200,
        message="Organizations retrieved successfully",
        data=[org.to_dict() for org in orgs]
    )


@router.get("/{organization_id}")
def get_organization(organization_id: int, db: Session = Depends(get_db)):
    """Get a specific organization by ID."""
    org = organization_service.get_organization_by_id(db=db, organization_id=organization_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return build_response(
        response_code=200,
        message="Organization retrieved successfully",
        data=org.to_dict()
    )


@router.put("/{organization_id}")
def update_organization(organization_id: int, name: str = None, db: Session = Depends(get_db)):
    """Update an organization."""
    org = organization_service.update_organization(db=db, organization_id=organization_id, name=name)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return build_response(
        response_code=200,
        message="Organization updated successfully",
        data=org.to_dict()
    )


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(organization_id: int, db: Session = Depends(get_db)):
    """Delete an organization."""
    success = organization_service.delete_organization(db=db, organization_id=organization_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return build_response(
        response_code=204,
        message="Organization deleted successfully"
    )
