from sqlalchemy import Boolean, Column, Integer, String, Text, TIMESTAMP, func
from src.core.database import Base


class OrgProjectAccessibilityCheckModel(Base):
    __tablename__ = "org_project_accessibility_check"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    organization_id = Column(Integer, nullable=False, index=True)
    project_id = Column(String(100), nullable=True, index=True)
    master_check_id = Column(Integer, nullable=False, index=True)
    check_code = Column(String(100), nullable=False, index=True)
    check_name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    category = Column(String(50), nullable=False, index=True)
    default_priority = Column(String(10), nullable=False, index=True)
    wcag_reference = Column(String(50))
    pdfua_reference = Column(String(50))
    remediation_guidance = Column(Text)
    agent_code = Column(String(100))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    def to_dict(self):
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "master_check_id": self.master_check_id,
            "check_code": self.check_code,
            "check_name": self.check_name,
            "description": self.description,
            "category": self.category,
            "default_priority": self.default_priority,
            "wcag_reference": self.wcag_reference,
            "pdfua_reference": self.pdfua_reference,
            "remediation_guidance": self.remediation_guidance,
            "agent_code": self.agent_code,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
