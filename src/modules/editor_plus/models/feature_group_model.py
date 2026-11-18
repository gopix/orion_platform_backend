from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, func

from src.core.database import Base


class FeatureGroup(Base):
    __tablename__ = "feature_groups"

    feature_group_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    group_name = Column(String(255), nullable=False)
    group_code = Column(Integer, nullable=False, unique=True, index=True)
    group_description = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
