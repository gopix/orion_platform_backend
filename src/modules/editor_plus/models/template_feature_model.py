from sqlalchemy import Column, ForeignKey, Integer, SmallInteger, UniqueConstraint, text
from sqlalchemy.orm import relationship

from src.core.database import Base
from src.modules.editor_plus.models.feature_model import MainFeature  # noqa: F401  (registers FK target)
from src.modules.editor_plus.models.template_model import Template  # noqa: F401  (registers FK target)


class TemplateFeature(Base):
    """Mapping: which main_features are enabled for a ce_template."""

    __tablename__ = "template_features"
    __table_args__ = (UniqueConstraint("template_id", "feature_id", name="uq_template_feature"),)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    template_id = Column(
        Integer,
        ForeignKey("ce_template.template_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_id = Column(
        Integer,
        ForeignKey("main_features.feature_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(SmallInteger, nullable=False, default=1, server_default=text("1"))  # 1 = enabled, 0 = disabled

    feature = relationship("MainFeature", lazy="joined", viewonly=True)
