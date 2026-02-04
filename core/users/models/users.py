from database import Base
from sqlalchemy import Column, String, Integer, JSON, ForeignKey
from sqlalchemy.orm import relationship

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    role = Column(String, nullable=False, unique=True, index=True)
    permissions = Column(JSON, nullable=True)  # Optional, may be null

    users = relationship("User", back_populates="role")

    def __repr__(self):
        return f"<Role(role='{self.role}')>"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    additional_data = Column(JSON, nullable=True)

    role = relationship("Role", back_populates="users")

    def __str__(self):
        return self.username

    def __repr__(self):
        return f"<User(username='{self.username}')>"
