from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    String,
    TIMESTAMP,
    func,
)

from src.core.database import Base

class WebAccessibilityRulesModel(Base):

    __tablename__ = "web_accessibility_rules"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    rule_code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    wcag_criterion = Column(String(20), nullable=False)
    wcag_level = Column(String(10), nullable=False)
    category = Column(String(100), nullable=True)
    severity = Column(String(50), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
            onupdate=func.current_timestamp())

    def to_dict(self, include_payload: bool = False):
        data = {
            "id": self.id,
            "rule_code": self.rule_code,
            "name": self.name,
            "wcag_criterion": self.wcag_criterion,
            "wcag_level": self.wcag_level,
            "category": self.category,
            "severity": self.severity,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
        return data
