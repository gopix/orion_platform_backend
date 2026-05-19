# editor_analysis_model.py

from sqlalchemy import Column, Integer, ForeignKey, JSON, String, DECIMAL, TIMESTAMP
from sqlalchemy.sql import func
from src.core.database import Base

class EditorAnalysisResult(Base):
    __tablename__ = "editor_analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    manuscript_id = Column(Integer, ForeignKey("manuscripts.id"), nullable=False)
    analysis_json = Column(JSON, nullable=False)
    model_version = Column(String(50), nullable=True)
    processing_time_seconds = Column(DECIMAL(10, 2), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)