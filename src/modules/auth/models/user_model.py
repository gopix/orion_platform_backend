from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(Base):
	__tablename__ = "users"

	id = Column(Integer, primary_key=True, index=True)
	user_name = Column(String(255), nullable=False)
	email = Column(String(255), unique=True, nullable=False, index=True)
	password_hash = Column(String(255), nullable=False)
	organization_id = Column(Integer, nullable=True)
	role_id = Column(Integer, nullable=True)
	created_at = Column(DateTime, server_default=func.now())
	updated_at = Column(DateTime,  server_default=func.now(), onupdate=func.now())

	def to_dict(self):
		return {
            "id": self.id,
            "user_name": self.user_name,
            "email": self.email,
            "organization_id": self.organization_id,
            "role_id": self.role_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }