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


class BookForgeAuditSheetModel(Base):
    """One audit-sheet exchange with the SME / end user, versioned per project.

    The audit sheet is the structural review gate: the system proposes the
    unit -> chapter breakdown, the SME corrects it and sets weights, and only
    then is a blueprint generated. Both directions of that exchange are stored
    as rows here, never overwritten, so the whole review history is retrievable.

    ``version`` is a SINGLE monotonic sequence per project spanning both
    directions, so the rows read as one ordered conversation::

        v1  generated   (system proposes 113 chapters)
        v2  submitted   (SME corrects 4 titles, sets 113 weights)
        v3  generated   (regenerated after a syllabus re-upload)
        v4  submitted   ...

    ``sheet_type`` says which direction a row is, and ``source_version`` links a
    submission back to the generated sheet it answers — so a submission can
    always be reconciled against exactly what was sent out.
    """

    __tablename__ = "book_forge_audit_sheets"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    project_id = Column(BigInteger, nullable=False, index=True)

    # Monotonic per project, across both sheet types (see class docstring).
    version = Column(Integer, nullable=False, default=1)

    # 'generated' = produced by the system for review.
    # 'submitted' = uploaded back by the end user / SME.
    sheet_type = Column(String(20), nullable=False, index=True)

    # For a 'submitted' row: the 'generated' version it responds to.
    source_version = Column(Integer, nullable=True)

    # Stored on disk (uuid-named); original_filename is what the user uploaded.
    stored_filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=True)
    file_path = Column(Text, nullable=False)
    file_size = Column(BigInteger, nullable=True)
    # Lets us detect a re-upload of a byte-identical sheet.
    checksum_sha256 = Column(String(64), nullable=True)

    # The sheet's content as structured data, so downstream generation never has
    # to re-open the workbook: {"chapters": [...], "flags": [...], "matches": [...]}.
    payload_json = Column(JSON, nullable=True)

    # Cheap counters for listing without loading payload_json.
    row_count = Column(Integer, nullable=True)
    weighted_count = Column(Integer, nullable=True)

    # 'current' for the newest row of its sheet_type, 'superseded' for older ones.
    status = Column(String(30), nullable=False, default="current", index=True)
    notes = Column(Text, nullable=True)

    created_by = Column(BigInteger, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    def to_dict(self, include_payload: bool = False):
        data = {
            "id": self.id,
            "project_id": self.project_id,
            "version": self.version,
            "sheet_type": self.sheet_type,
            "source_version": self.source_version,
            "stored_filename": self.stored_filename,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "checksum_sha256": self.checksum_sha256,
            "row_count": self.row_count,
            "weighted_count": self.weighted_count,
            "status": self.status,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_deleted": self.is_deleted,
        }
        # payload_json can be large (113+ chapter rows); opt in explicitly.
        if include_payload:
            data["payload_json"] = self.payload_json
        return data
