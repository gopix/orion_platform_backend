from sqlalchemy import BigInteger, Boolean, Column, Date, ForeignKey, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.orm import relationship
from src.core.database import Base

# Imported so the referenced table is registered in the SQLAlchemy metadata,
# which lets the book_status FK below resolve (avoids NoReferencedTableError).
from src.modules.book_forge.models.bookforge_project_status_model import (  # noqa: F401
    BookForgeProjectStatusModel,
)


class BookForgeProjectModel(Base):
    __tablename__ = "book_forge_projects"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    book_title = Column(String(255),  nullable=False, index=True)
    # FK to the master category list. NULL = uncategorized.
    category_id = Column(
        BigInteger,
        ForeignKey("book_forge_category.id"),
        nullable=True,
        index=True,
    )
    # Read-only link to the category, so we can expose its name (which the
    # generation pipeline resolves the prompt from) without an extra query.
    category_ref = relationship("BookForgeBookCategoryModel", lazy="joined")
    book_subject = Column(Text)
    target_audience = Column(String(255))
    language_code = Column(String(10))
    expected_pages = Column(Integer)
    chapter_count = Column(Integer)
    publisher_name = Column(String(255))
    edition = Column(String(50))
    primary_output_format = Column(String(50))
    book_description = Column(Text) 
    submission_deadline = Column(Date)
    # FK to book_forge_project_status.status_name (the internal enum value).
    # New projects always start at 'draft' (status_id=1); the value must be one
    # of the seeded status_name rows.
    book_status = Column(
        String(50),
        ForeignKey("book_forge_project_status.status_name"),
        nullable=False,
        default="draft",
        index=True,
    )
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    is_deleted = Column(Boolean, nullable=False, default=False)
    
    
    def to_dict(self):
        return {
            "id": self.id,
            "book_title": self.book_title,
            "category_id": self.category_id,
            # The category NAME (used by the generation pipeline to pick the prompt).
            "category": self.category_ref.category_name if self.category_ref else None,
            "book_subject": self.book_subject,
            "target_audience": self.target_audience,
            "language_code" : self.language_code,
            "expected_pages": self.expected_pages,
            "chapter_count": self.chapter_count,    
            "publisher_name": self.publisher_name,
            "edition": self.edition,    
            "primary_output_format": self.primary_output_format,
            "book_description": self.book_description,
            "submission_deadline": self.submission_deadline,
            "book_status": self.book_status,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_deleted": self.is_deleted
        }
