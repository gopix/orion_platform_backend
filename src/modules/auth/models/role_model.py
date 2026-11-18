from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Roles(Base):
	__tablename__ = "roles"

	role_id = Column(Integer, primary_key=True, index=True)
	role_name = Column(String(255), nullable=False)
	role_description = Column(String(255), nullable=True)
	is_Active = Column(Integer, nullable=False, default=1)
	created_at = Column(DateTime, server_default=func.now())
	
	def to_dict(self):
		return {
            "id": self.role_id,
            "role_name": self.role_name,
            "role_description": self.role_description,
            "is_Active": self.is_Active,
            "created_at": self.created_at,
        }