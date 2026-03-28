from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(Base):
	__tablename__ = "users"

	id = Column(Integer, primary_key=True, index=True)
	email = Column(String(255), unique=True, nullable=False, index=True)
	password_hash = Column(String(255), nullable=False)
	
	created_at = Column(DateTime, server_default=func.now())
	updated_at = Column(DateTime,  server_default=func.now(), onupdate=func.now())