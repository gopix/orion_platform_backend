from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    String,
    TIMESTAMP,
    func,
)

from src.core.database import Base

class WebAccessibilityWebsiteModel(Base):

    __tablename__ = "web_accessibility_websites"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=True)
    base_url = Column(String(2048), nullable=True)
    description = Column(String(255), nullable=True)
    accessibility_status = Column(String(50), nullable=True, default="UNKNOWN")
    environment = Column(String(50), nullable=False, default="PRODUCTION")
    crawl_enabled = Column(Boolean, nullable=False, default=False)
    crawl_frequency = Column(String(50), nullable=True)
    authentication_required = Column(Boolean, nullable=False, default=False)
    authentication_type = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
            onupdate=func.current_timestamp())
    last_scan_at = Column(TIMESTAMP, nullable=True)

    def to_dict(self, include_payload: bool = False):
        data = {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "description": self.description,
            "accessibility_status": self.accessibility_status,
            "environment": self.environment,
            "crawl_enabled": self.crawl_enabled,
            "crawl_frequency": self.crawl_frequency,
            "authentication_required": self.authentication_required,
            "authentication_type": self.authentication_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_scan_at": self.last_scan_at
        }
        return data
