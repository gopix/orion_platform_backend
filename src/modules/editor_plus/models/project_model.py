from sqlalchemy import Column, ForeignKey, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.orm import relationship

from src.core.database import Base
from src.modules.editor_plus.models.customer_model import Customer  # noqa: F401  (registers FK target)


class Project(Base):
    __tablename__ = "ce_projects"

    project_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_name = Column(String(255), nullable=False, index=True)
    customer_id = Column(
        Integer,
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    project_description = Column(Text, nullable=True)
    project_manager = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    created_by = Column(Integer, nullable=True)

    customer = relationship("Customer", lazy="joined")

    @property
    def customer_name(self) -> str | None:
        return self.customer.customer_name if self.customer else None
