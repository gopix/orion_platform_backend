from sqlalchemy import Column, Integer, String, ForeignKey
from src.core.database import Base

class StrctureTemplate(Base):
    __tablename__ = "book_structure_templates"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False)
    book_id = Column(Integer, nullable=True)
    template_name = Column(String(255), nullable=True)
    structure_json = Column(String(4000), nullable=True)
    is_active = Column(Integer, default=1)  # Using Integer for boolean (1 for True, 0 for False)
    created_at = Column(String(255), nullable=True)


class TemplateSection(Base):
    __tablename__ = "template_sections"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("book_structure_templates.id"), nullable=False)
    section_name = Column(String(255), nullable=False)
    parent_id = Column(Integer, nullable=True)  # For hierarchical sections
    order_index = Column(Integer, nullable=False)
    is_mandatory = Column(Integer, default=1)  # 1 for True, 0 for False
    created_at = Column(String(255), nullable=True)