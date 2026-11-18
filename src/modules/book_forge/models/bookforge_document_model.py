from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    String,
    TIMESTAMP,
    func,
)

from src.core.database import Base


class BookForgeDocumentModel(Base):
    __tablename__ = "book_forge_documents"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        BigInteger,
        ForeignKey("book_forge_projects.id"),
        nullable=False,
        index=True,
    )
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_extension = Column(String(20))
    mime_type = Column(String(150))
    file_size = Column(BigInteger)  # bytes
    document_type = Column(String(50))
    created_by = Column(BigInteger, nullable=False)
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
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "file_path": self.file_path,
            "file_extension": self.file_extension,
            "mime_type": self.mime_type,
            "file_size": self.file_size,
            "document_type": self.document_type,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_deleted": self.is_deleted,
        }
