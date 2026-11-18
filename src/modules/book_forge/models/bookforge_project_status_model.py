from sqlalchemy import BigInteger, Column, Integer, String, TIMESTAMP, func

from src.core.database import Base


class BookForgeProjectStatusModel(Base):
    """Master list of workflow statuses a project moves through.

    ``status_name`` is the internal enum value (lower_snake_case, unique) that
    ``book_forge_projects.book_status`` foreign-keys to; ``status_label`` is the
    UI-facing label. New projects start at 'draft'; status only advances through
    the workflow (sources_added -> building_knowledge -> knowledge_ready ->
    generating_blueprint -> blueprint_ready, plus 'failed').
    """

    __tablename__ = "book_forge_project_status"

    status_id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    status_name = Column(String(50), nullable=False, unique=True, index=True)
    status_label = Column(String(100), nullable=False)
    status_description = Column(String(255), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_by = Column(BigInteger, nullable=True)
    updated_by = Column(BigInteger, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    def to_dict(self):
        return {
            "status_id": self.status_id,
            "status_name": self.status_name,
            "status_label": self.status_label,
            "status_description": self.status_description,
            "sort_order": self.sort_order,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
