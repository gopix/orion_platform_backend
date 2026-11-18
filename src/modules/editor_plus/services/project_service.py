from sqlalchemy.orm import Session

from src.modules.editor_plus.models.customer_model import Customer
from src.modules.editor_plus.models.project_model import Project
from src.modules.editor_plus.models.template_model import Template
from src.modules.editor_plus.schemas.project_schema import (
    ProjectCreate,
    ProjectListData,
    ProjectResponse,
    ProjectUpdate,
)


class ProjectNotFoundError(Exception):
    pass


class InvalidCustomerError(Exception):
    pass


class ProjectHasTemplatesError(Exception):
    pass


class ProjectService:
    """Service layer for ce_projects CRUD operations.

    Takes Pydantic input schemas and returns Pydantic output schemas,
    so ORM objects never leak out of this layer.
    """

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    def _get(self, db: Session, project_id: int) -> Project | None:
        return db.query(Project).filter(Project.project_id == project_id).first()

    def _ensure_customer_exists(self, db: Session, customer_id: int) -> None:
        if not db.query(Customer.id).filter(Customer.id == customer_id).first():
            raise InvalidCustomerError(f"Customer with id {customer_id} does not exist")

    def create_project(self, db: Session, payload: ProjectCreate) -> ProjectResponse:
        """Create a new project"""
        name = self._clean(payload.project_name)
        if not name:
            raise ValueError("Project name is required")

        self._ensure_customer_exists(db, payload.customer_id)

        project = Project(
            project_name=name,
            customer_id=payload.customer_id,
            project_description=self._clean(payload.project_description),
            project_manager=self._clean(payload.project_manager),
            created_by=payload.created_by,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return ProjectResponse.model_validate(project)

    def get_all_projects(
        self,
        db: Session,
        customer_id: int | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> ProjectListData:
        """Get projects, optionally filtered by customer and name/manager search"""
        query = db.query(Project)
        if customer_id is not None:
            query = query.filter(Project.customer_id == customer_id)
        search = self._clean(search)
        if search:
            like = f"%{search}%"
            query = query.filter(
                Project.project_name.ilike(like) | Project.project_manager.ilike(like)
            )
        total = query.count()
        projects = query.order_by(Project.project_id.asc()).offset(skip).limit(limit).all()
        return ProjectListData(
            total=total,
            skip=skip,
            limit=limit,
            items=[ProjectResponse.model_validate(p) for p in projects],
        )

    def get_project_by_id(self, db: Session, project_id: int) -> ProjectResponse | None:
        """Get project by ID"""
        project = self._get(db, project_id)
        return ProjectResponse.model_validate(project) if project else None

    def update_project(self, db: Session, project_id: int, payload: ProjectUpdate) -> ProjectResponse:
        """Partially update a project (only fields sent in the request)"""
        project = self._get(db, project_id)
        if not project:
            raise ProjectNotFoundError("Project not found")

        data = payload.model_dump(exclude_unset=True)

        if "project_name" in data:
            name = self._clean(data["project_name"])
            if not name:
                raise ValueError("Project name cannot be empty")
            project.project_name = name

        if "customer_id" in data:
            if data["customer_id"] is None:
                raise ValueError("customer_id cannot be null")
            self._ensure_customer_exists(db, data["customer_id"])
            project.customer_id = data["customer_id"]

        if "project_description" in data:
            project.project_description = self._clean(data["project_description"])

        if "project_manager" in data:
            project.project_manager = self._clean(data["project_manager"])

        db.commit()
        db.expire(project, ["customer"])  # reload customer if customer_id changed
        db.refresh(project)
        return ProjectResponse.model_validate(project)

    def delete_project(self, db: Session, project_id: int) -> bool:
        """Delete a project. Refuses if any ce_template row still references it."""
        project = self._get(db, project_id)
        if not project:
            return False
        template_count = db.query(Template).filter(Template.project_id == project_id).count()
        if template_count:
            raise ProjectHasTemplatesError(
                f"Project has {template_count} template(s); delete or reassign them first"
            )
        db.delete(project)
        db.commit()
        return True
