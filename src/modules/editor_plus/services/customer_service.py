from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.modules.editor_plus.models.customer_model import Customer
from src.modules.editor_plus.models.project_model import Project
from src.modules.editor_plus.schemas.customer_schema import (
    CustomerCreate,
    CustomerListData,
    CustomerResponse,
    CustomerUpdate,
)


class CustomerNotFoundError(Exception):
    pass


class DuplicateCustomerError(Exception):
    pass


class CustomerHasProjectsError(Exception):
    pass


class CustomerService:
    """Service layer for Customer CRUD operations.

    Takes Pydantic input schemas and returns Pydantic output schemas,
    so ORM objects never leak out of this layer.
    """

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    def _clean_email(self, value: str | None) -> str | None:
        value = self._clean(value)
        return value.lower() if value else None

    def _get(self, db: Session, customer_id: int) -> Customer | None:
        return db.query(Customer).filter(Customer.id == customer_id).first()

    def _ensure_email_unique(self, db: Session, email_id: str | None, exclude_id: int | None = None) -> None:
        if not email_id:
            return
        query = db.query(Customer).filter(Customer.email_id == email_id)
        if exclude_id is not None:
            query = query.filter(Customer.id != exclude_id)
        if query.first():
            raise DuplicateCustomerError(f"Customer with email '{email_id}' already exists")

    def create_customer(self, db: Session, payload: CustomerCreate) -> CustomerResponse:
        """Create a new customer"""
        name = self._clean(payload.customer_name)
        if not name:
            raise ValueError("Customer name is required")

        email_id = self._clean_email(payload.email_id)
        self._ensure_email_unique(db, email_id)

        customer = Customer(
            customer_name=name,
            customer_address=self._clean(payload.customer_address),
            phone_no=self._clean(payload.phone_no),
            email_id=email_id,
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
        return CustomerResponse.model_validate(customer)

    def get_all_customers(
        self, db: Session, search: str | None = None, skip: int = 0, limit: int = 100
    ) -> CustomerListData:
        """Get customers with optional search (name/email/phone) and pagination"""
        query = db.query(Customer)
        search = self._clean(search)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    Customer.customer_name.ilike(like),
                    Customer.email_id.ilike(like),
                    Customer.phone_no.ilike(like),
                )
            )
        total = query.count()
        customers = query.order_by(Customer.id.asc()).offset(skip).limit(limit).all()
        return CustomerListData(
            total=total,
            skip=skip,
            limit=limit,
            items=[CustomerResponse.model_validate(c) for c in customers],
        )

    def get_customer_by_id(self, db: Session, customer_id: int) -> CustomerResponse | None:
        """Get customer by ID"""
        customer = self._get(db, customer_id)
        return CustomerResponse.model_validate(customer) if customer else None

    def update_customer(self, db: Session, customer_id: int, payload: CustomerUpdate) -> CustomerResponse:
        """Partially update a customer (only fields sent in the request)"""
        customer = self._get(db, customer_id)
        if not customer:
            raise CustomerNotFoundError("Customer not found")

        data = payload.model_dump(exclude_unset=True)

        if "customer_name" in data:
            name = self._clean(data["customer_name"])
            if not name:
                raise ValueError("Customer name cannot be empty")
            customer.customer_name = name

        if "customer_address" in data:
            customer.customer_address = self._clean(data["customer_address"])

        if "phone_no" in data:
            customer.phone_no = self._clean(data["phone_no"])

        if "email_id" in data:
            email_id = self._clean_email(data["email_id"])
            self._ensure_email_unique(db, email_id, exclude_id=customer_id)
            customer.email_id = email_id

        db.commit()
        db.refresh(customer)
        return CustomerResponse.model_validate(customer)

    def delete_customer(self, db: Session, customer_id: int) -> bool:
        """Delete a customer. Refuses if any ce_projects row still references it."""
        customer = self._get(db, customer_id)
        if not customer:
            return False
        project_count = db.query(Project).filter(Project.customer_id == customer_id).count()
        if project_count:
            raise CustomerHasProjectsError(
                f"Customer has {project_count} project(s); delete or reassign them first"
            )
        db.delete(customer)
        db.commit()
        return True
