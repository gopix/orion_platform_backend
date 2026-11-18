"""SQLAlchemy ORM models for the Prompt Engine tables.

Kept alongside the other Book Forge ORM models so all DB-mapped tables live in
one place. These are persistence models only — the repository layer maps them to
the pure domain models in ``ai/prompts/models`` and nothing outside the
repository works with these classes directly.
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TIMESTAMP,
    func,
)

from src.core.database import Base


class PromptTemplateORM(Base):
    __tablename__ = "book_forge_prompt_templates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text)
    active_version = Column(Integer)
    status = Column(String(30), nullable=False, default="draft")
    created_by = Column(BigInteger)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class PromptVersionORM(Base):
    __tablename__ = "book_forge_prompt_versions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    template_id = Column(
        BigInteger,
        ForeignKey("book_forge_prompt_templates.id"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    template_text = Column(Text, nullable=False)
    model = Column(String(100))
    temperature = Column(Float)
    max_tokens = Column(Integer)
    status = Column(String(30), nullable=False, default="draft")
    created_by = Column(BigInteger)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class PromptVariableORM(Base):
    __tablename__ = "book_forge_prompt_variables"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    template_id = Column(
        BigInteger,
        ForeignKey("book_forge_prompt_templates.id"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    type = Column(String(30), nullable=False, default="string")
    required = Column(Boolean, nullable=False, default=True)
    default_value = Column(Text)
    description = Column(Text)


class PromptExecutionORM(Base):
    __tablename__ = "book_forge_prompt_executions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    request_id = Column(String(64), index=True)
    prompt_id = Column(BigInteger, index=True)
    version = Column(Integer)
    provider = Column(String(50))
    model = Column(String(100))
    rendered_prompt = Column(Text)
    response = Column(Text)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    latency_ms = Column(Float)
    cost = Column(Float)
    status = Column(String(30))
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
