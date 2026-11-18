from sqlalchemy import Column, ForeignKey, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.orm import relationship

from src.core.database import Base
from src.modules.editor_plus.models.feature_group_model import FeatureGroup  # noqa: F401  (registers FK target)


class MainFeature(Base):
    __tablename__ = "main_features"

    feature_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    feature_name = Column(String(255), nullable=False)
    feature_code = Column(Integer, nullable=False, unique=True, index=True)
    group_code = Column(
        Integer,
        ForeignKey("feature_groups.group_code", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    feature_description = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Read-only join for group_name; deletes cascade at DB level (ON DELETE CASCADE)
    group = relationship("FeatureGroup", lazy="joined", viewonly=True)

    @property
    def group_name(self) -> str | None:
        return self.group.group_name if self.group else None
