from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Integer,
    JSON,
    String,
    Text,
    TIMESTAMP,
    func,
)

from src.core.database import Base


class BookForgeBlueprintModel(Base):
    """A generated book blueprint, versioned per project.

    Each run of the blueprint workflow inserts a NEW row (incrementing
    ``version`` for that project) rather than overwriting, so the review/revision
    loop preserves history — you can tell which version was generated, reviewed,
    and approved. The chapter outline lives in ``blueprint_json`` (the flat
    chapter schema: chapter_number, title, summary, learning_objectives,
    covered_topics).
    """

    __tablename__ = "book_forge_blueprints"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    project_id = Column(BigInteger, nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)

    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    # Full blueprint payload: {title, description, target_audience,
    # estimated_length, chapters: [...]}. JSON column keeps the chapters together.
    blueprint_json = Column(JSON, nullable=False)

    # Lifecycle: generated -> reviewed -> approved (see blueprint_service).
    status = Column(String(30), nullable=False, default="generated", index=True)

    created_by = Column(BigInteger, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "blueprint_json": self.blueprint_json,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_deleted": self.is_deleted,
        }
