from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    role: str
    permissions: Dict[str, Any] = Field(default_factory=dict, json_schema_extra={"example": {}})


class RoleResponse(BaseModel):
    id: int
    role: str
    permissions: Dict[str, Any] = Field(default_factory=dict, json_schema_extra={"example": {}})


class RolePermissionsResponse(BaseModel):
    role: str
    permissions: Dict[str, Any] = Field(default_factory=dict, json_schema_extra={"example": {}})


class RolePermissionsUpdate(BaseModel):
    permissions: Dict[str, Any] = Field(default_factory=dict, json_schema_extra={"example": {}})


class UserCreate(BaseModel):
    username: str
    password: str
    role: str


class UserRoleUpdate(BaseModel):
    role: str


class UserPatch(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    permissions: Optional[Dict[str, Any]] = None
