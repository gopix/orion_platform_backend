from sqlalchemy import Column, Integer, String
from src.core.database import Base

class Manuscript(Base):
    __tablename__ = "manuscripts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    author = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="Submitted")
    organization_id = Column(Integer, nullable=False)
    file_path = Column(String(512), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)