from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import relationship

from src.core.database import Base
from src.modules.editor_plus.models.project_model import Project  # noqa: F401  (registers FK target)

# LONGTEXT on MySQL (designs can exceed TEXT's 64 KB), plain TEXT elsewhere
DesignText = Text().with_variant(LONGTEXT(), "mysql")


class Template(Base):
    __tablename__ = "ce_template"

    template_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    template_name = Column(String(255), nullable=False, index=True)
    project_id = Column(
        Integer,
        ForeignKey("ce_projects.project_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    template_design = Column(DesignText, nullable=True)
    template_description = Column(Text, nullable=True)
    template_status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)

    project = relationship("Project", lazy="joined")

    @property
    def project_name(self) -> str | None:
        return self.project.project_name if self.project else None
