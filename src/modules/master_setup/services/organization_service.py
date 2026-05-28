from sqlalchemy.orm import Session

from src.modules.master_setup.models.organization_model import Organization


class OrganizationService:
    """Service layer for Organization CRUD operations"""

    def create_organization(self, db: Session, name: str, created_by: int | None = None) -> Organization:
        """Create a new organization"""
        if not name or not name.strip():
            raise ValueError("Organization name is required")

        organization = Organization(name=name.strip(), created_by=created_by)
        db.add(organization)
        db.commit()
        db.refresh(organization)
        return organization

    def get_all_organizations(self, db: Session) -> list[Organization]:
        """Get all organizations"""
        return db.query(Organization).order_by(Organization.id.asc()).all()

    def get_organization_by_id(self, db: Session, organization_id: int) -> Organization | None:
        """Get organization by ID"""
        return db.query(Organization).filter(Organization.id == organization_id).first()

    def update_organization(
        self, db: Session, organization_id: int, name: str | None = None, updated_by: int | None = None
    ) -> Organization | None:
        """Update an organization"""
        organization = db.query(Organization).filter(Organization.id == organization_id).first()

        if not organization:
            return None

        if name and name.strip():
            organization.name = name.strip()

        if updated_by is not None:
            organization.updated_by = updated_by

        db.commit()
        db.refresh(organization)
        return organization

    def delete_organization(self, db: Session, organization_id: int) -> bool:
        """Delete an organization"""
        organization = db.query(Organization).filter(Organization.id == organization_id).first()

        if not organization:
            return False

        db.delete(organization)
        db.commit()
        return True
