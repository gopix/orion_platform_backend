from sqlalchemy.orm import Session

from src.modules.editor_plus.models.project_model import Project
from src.modules.editor_plus.models.template_model import Template
from src.modules.editor_plus.schemas.template_schema import (
    TemplateCreate,
    TemplateListData,
    TemplateResponse,
    TemplateUpdate,
)


class TemplateNotFoundError(Exception):
    pass


class InvalidProjectError(Exception):
    pass


class TemplateService:
    """Service layer for ce_template CRUD operations.

    Takes Pydantic input schemas and returns Pydantic output schemas,
    so ORM objects never leak out of this layer.
    """

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    def _get(self, db: Session, template_id: int) -> Template | None:
        return db.query(Template).filter(Template.template_id == template_id).first()

    def _ensure_project_exists(self, db: Session, project_id: int) -> None:
        if not db.query(Project.project_id).filter(Project.project_id == project_id).first():
            raise InvalidProjectError(f"Project with id {project_id} does not exist")

    def create_template(self, db: Session, payload: TemplateCreate) -> TemplateResponse:
        """Create a new template"""
        name = self._clean(payload.template_name)
        if not name:
            raise ValueError("Template name is required")

        self._ensure_project_exists(db, payload.project_id)

        template = Template(
            template_name=name,
            project_id=payload.project_id,
            template_design=payload.template_design,  # stored as-is (no trimming)
            template_description=self._clean(payload.template_description),
            template_status=payload.template_status,
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return TemplateResponse.model_validate(template)

    def get_all_templates(
        self,
        db: Session,
        project_id: int | None = None,
        template_status: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> TemplateListData:
        """Get templates, optionally filtered by project, status and name search"""
        query = db.query(Template)
        if project_id is not None:
            query = query.filter(Template.project_id == project_id)
        if template_status:
            query = query.filter(Template.template_status == template_status)
        search = self._clean(search)
        if search:
            query = query.filter(Template.template_name.ilike(f"%{search}%"))
        total = query.count()
        templates = query.order_by(Template.template_id.asc()).offset(skip).limit(limit).all()
        return TemplateListData(
            total=total,
            skip=skip,
            limit=limit,
            items=[TemplateResponse.model_validate(t) for t in templates],
        )

    def get_template_by_id(self, db: Session, template_id: int) -> TemplateResponse | None:
        """Get template by ID"""
        template = self._get(db, template_id)
        return TemplateResponse.model_validate(template) if template else None

    def update_template(self, db: Session, template_id: int, payload: TemplateUpdate) -> TemplateResponse:
        """Partially update a template (only fields sent in the request)"""
        template = self._get(db, template_id)
        if not template:
            raise TemplateNotFoundError("Template not found")

        data = payload.model_dump(exclude_unset=True)

        if "template_name" in data:
            name = self._clean(data["template_name"])
            if not name:
                raise ValueError("Template name cannot be empty")
            template.template_name = name

        if "project_id" in data:
            if data["project_id"] is None:
                raise ValueError("project_id cannot be null")
            self._ensure_project_exists(db, data["project_id"])
            template.project_id = data["project_id"]

        if "template_design" in data:
            template.template_design = data["template_design"]

        if "template_description" in data:
            template.template_description = self._clean(data["template_description"])

        if "template_status" in data:
            if data["template_status"] is None:
                raise ValueError("template_status cannot be null")
            template.template_status = data["template_status"]

        db.commit()
        db.expire(template, ["project"])  # reload project if project_id changed
        db.refresh(template)
        return TemplateResponse.model_validate(template)

    def delete_template(self, db: Session, template_id: int) -> bool:
        """Delete a template"""
        template = self._get(db, template_id)
        if not template:
            return False
        db.delete(template)
        db.commit()
        return True
