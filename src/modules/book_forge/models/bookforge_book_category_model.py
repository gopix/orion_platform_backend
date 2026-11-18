from sqlalchemy import BigInteger, Column, String, TIMESTAMP, func

from src.core.database import Base


class BookForgeBookCategoryModel(Base):
    """Master list of book categories (book types).

    Single source of truth for the categories a project can belong to and that
    blueprint prompts are authored for. ``category_name`` is the normalized key
    (lowercase, underscores) that prompt templates key off
    (``blueprint_generation_<category_name>``); projects reference this table by
    ``id``.
    """

    __tablename__ = "book_forge_category"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    category_name = Column(String(100), nullable=False, unique=True, index=True)
    category_description = Column(String(500), nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    def to_dict(self):
        return {
            "category_id": self.id,
            "category_name": self.category_name,
            "category_description": self.category_description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
