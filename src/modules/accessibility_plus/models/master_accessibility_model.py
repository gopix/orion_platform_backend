from sqlalchemy import Boolean, Column, Integer, String, Text, TIMESTAMP, func
from src.core.database import Base


class MasterAccessibilityModel(Base):
    __tablename__ = "master_accessibility_check"

    check_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    check_code = Column(String(100), unique=True, nullable=False, index=True)
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

    def to_dict(self):
        return {
            "check_id": self.check_id,
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
        }
