from sqlalchemy import Column, Integer, String, TIMESTAMP, func

from src.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    customer_name = Column(String(255), nullable=False, index=True)
    customer_address = Column(String(500), nullable=True)
    phone_no = Column(String(20), nullable=True)
    email_id = Column(String(255), nullable=True, unique=True, index=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "customer_name": self.customer_name,
            "customer_address": self.customer_address,
            "phone_no": self.phone_no,
            "email_id": self.email_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
