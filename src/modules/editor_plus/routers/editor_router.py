from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.modules.editor_plus.schemas.customer_schema import (
    CustomerCreate,
    CustomerDeleteAPIResponse,
    CustomerDeleteData,
    CustomerListAPIResponse,
    CustomerSingleAPIResponse,
    CustomerUpdate,
)
from src.modules.editor_plus.schemas.project_schema import (
    ProjectCreate,
    ProjectDeleteAPIResponse,
    ProjectDeleteData,
    ProjectListAPIResponse,
    ProjectSingleAPIResponse,
    ProjectUpdate,
)
from src.modules.editor_plus.services.customer_service import (
    CustomerHasProjectsError,
    CustomerNotFoundError,
    CustomerService,
    DuplicateCustomerError,
)
from src.modules.editor_plus.services.project_service import (
    InvalidCustomerError,
    ProjectHasTemplatesError,
    ProjectNotFoundError,
    ProjectService,
)
from src.modules.editor_plus.schemas.template_schema import (
    TemplateCreate,
    TemplateDeleteAPIResponse,
    TemplateDeleteData,
    TemplateListAPIResponse,
    TemplateSingleAPIResponse,
    TemplateStatus,
    TemplateUpdate,
)
from src.modules.editor_plus.services.template_service import (
    InvalidProjectError,
    TemplateNotFoundError,
    TemplateService,
)

router = APIRouter()
customer_service = CustomerService()
project_service = ProjectService()
template_service = TemplateService()


@router.get("/test")
async def test_editor():
    return {"message": "Editor Plus router is working"}


# ==================== Customer CRUD Endpoints ====================
@router.post(
    "/customers",
    status_code=status.HTTP_201_CREATED,
    response_model=CustomerSingleAPIResponse,
)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)) -> CustomerSingleAPIResponse:
    """Create a new customer."""
    try:
        customer = customer_service.create_customer(db=db, payload=payload)
    except DuplicateCustomerError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return CustomerSingleAPIResponse(
        response_code=status.HTTP_201_CREATED,
        message="Customer created successfully",
        data=customer,
    )


@router.get("/customers", response_model=CustomerListAPIResponse)
def get_all_customers(
    search: Optional[str] = Query(None, description="Filter by name, email or phone"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> CustomerListAPIResponse:
    """List customers with optional search and pagination."""
    result = customer_service.get_all_customers(db=db, search=search, skip=skip, limit=limit)
    return CustomerListAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Customers retrieved successfully",
        data=result,
    )


@router.get("/customers/{customer_id}", response_model=CustomerSingleAPIResponse)
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> CustomerSingleAPIResponse:
    """Get a customer by ID."""
    customer = customer_service.get_customer_by_id(db=db, customer_id=customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return CustomerSingleAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Customer retrieved successfully",
        data=customer,
    )


@router.put("/customers/{customer_id}", response_model=CustomerSingleAPIResponse)
def update_customer(
    customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db)
) -> CustomerSingleAPIResponse:
    """Update a customer. Only fields sent in the body are changed."""
    try:
        customer = customer_service.update_customer(db=db, customer_id=customer_id, payload=payload)
    except CustomerNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DuplicateCustomerError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return CustomerSingleAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Customer updated successfully",
        data=customer,
    )


@router.delete("/customers/{customer_id}", response_model=CustomerDeleteAPIResponse)
def delete_customer(customer_id: int, db: Session = Depends(get_db)) -> CustomerDeleteAPIResponse:
    """Delete a customer. Blocked (409) if the customer still has projects."""
    try:
        deleted = customer_service.delete_customer(db=db, customer_id=customer_id)
    except CustomerHasProjectsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return CustomerDeleteAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Customer deleted successfully",
        data=CustomerDeleteData(id=customer_id),
    )


# ==================== Project (ce_projects) CRUD Endpoints ====================
@router.post(
    "/projects",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectSingleAPIResponse,
)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectSingleAPIResponse:
    """Create a new project for an existing customer."""
    try:
        project = project_service.create_project(db=db, payload=payload)
    except InvalidCustomerError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return ProjectSingleAPIResponse(
        response_code=status.HTTP_201_CREATED,
        message="Project created successfully",
        data=project,
    )


@router.get("/projects", response_model=ProjectListAPIResponse)
def get_all_projects(
    customer_id: Optional[int] = Query(None, gt=0, description="Filter by customer"),
    search: Optional[str] = Query(None, description="Filter by project name or manager"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ProjectListAPIResponse:
    """List projects with optional customer filter, search and pagination."""
    result = project_service.get_all_projects(
        db=db, customer_id=customer_id, search=search, skip=skip, limit=limit
    )
    return ProjectListAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Projects retrieved successfully",
        data=result,
    )


@router.get("/projects/{project_id}", response_model=ProjectSingleAPIResponse)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectSingleAPIResponse:
    """Get a project by ID."""
    project = project_service.get_project_by_id(db=db, project_id=project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectSingleAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Project retrieved successfully",
        data=project,
    )


@router.put("/projects/{project_id}", response_model=ProjectSingleAPIResponse)
def update_project(
    project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)
) -> ProjectSingleAPIResponse:
    """Update a project. Only fields sent in the body are changed."""
    try:
        project = project_service.update_project(db=db, project_id=project_id, payload=payload)
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidCustomerError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return ProjectSingleAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Project updated successfully",
        data=project,
    )


@router.delete("/projects/{project_id}", response_model=ProjectDeleteAPIResponse)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> ProjectDeleteAPIResponse:
    """Delete a project. Blocked (409) if the project still has templates."""
    try:
        deleted = project_service.delete_project(db=db, project_id=project_id)
    except ProjectHasTemplatesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectDeleteAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Project deleted successfully",
        data=ProjectDeleteData(project_id=project_id),
    )


# ==================== Template (ce_template) CRUD Endpoints ====================
@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateSingleAPIResponse,
)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)) -> TemplateSingleAPIResponse:
    """Create a new template for an existing project."""
    try:
        template = template_service.create_template(db=db, payload=payload)
    except InvalidProjectError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return TemplateSingleAPIResponse(
        response_code=status.HTTP_201_CREATED,
        message="Template created successfully",
        data=template,
    )


@router.get("/templates", response_model=TemplateListAPIResponse)
def get_all_templates(
    project_id: Optional[int] = Query(None, gt=0, description="Filter by project"),
    template_status: Optional[TemplateStatus] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Filter by template name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> TemplateListAPIResponse:
    """List templates with optional project/status filters, search and pagination."""
    result = template_service.get_all_templates(
        db=db,
        project_id=project_id,
        template_status=template_status,
        search=search,
        skip=skip,
        limit=limit,
    )
    return TemplateListAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Templates retrieved successfully",
        data=result,
    )


@router.get("/templates/{template_id}", response_model=TemplateSingleAPIResponse)
def get_template(template_id: int, db: Session = Depends(get_db)) -> TemplateSingleAPIResponse:
    """Get a template by ID."""
    template = template_service.get_template_by_id(db=db, template_id=template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return TemplateSingleAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Template retrieved successfully",
        data=template,
    )


@router.put("/templates/{template_id}", response_model=TemplateSingleAPIResponse)
def update_template(
    template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db)
) -> TemplateSingleAPIResponse:
    """Update a template. Only fields sent in the body are changed."""
    try:
        template = template_service.update_template(db=db, template_id=template_id, payload=payload)
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidProjectError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return TemplateSingleAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Template updated successfully",
        data=template,
    )


@router.delete("/templates/{template_id}", response_model=TemplateDeleteAPIResponse)
def delete_template(template_id: int, db: Session = Depends(get_db)) -> TemplateDeleteAPIResponse:
    """Delete a template."""
    if not template_service.delete_template(db=db, template_id=template_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return TemplateDeleteAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Template deleted successfully",
        data=TemplateDeleteData(template_id=template_id),
    )
