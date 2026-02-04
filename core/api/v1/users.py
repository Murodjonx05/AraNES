from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.permission import PERMISSIONS
from core.users.models.users import Role, User
from core.users.schemas import (
    RoleCreate,
    RolePermissionsUpdate,
    RolePermissionsResponse,
    RoleResponse,
    UserCreate,
    UserPatch,
    UserResponse,
    UserRoleUpdate,
)

from core.users.service import (
    assign_role,
    build_permissions_with_patch,
    create_role,
    create_user,
    get_role_by_name,
    sync_role_permissions,
    update_role_permissions,
    validate_permissions_payload,
)

from database import SessionLocal

roles_open_router = APIRouter(prefix="/roles", tags=["Roles"])
roles_router = APIRouter(prefix="/roles", tags=["Roles"])
users_open_router = APIRouter(prefix="/users", tags=["Users"])
users_router = APIRouter(prefix="/users", tags=["Users"])


async def get_db():
    async with SessionLocal() as db:
        yield db


def role_to_response(role: Role) -> RoleResponse:
    return RoleResponse(id=role.id, role=role.role, permissions=role.permissions)


def user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role.role,
        permissions=user.role.permissions,
    )


async def get_role_or_404(db: AsyncSession, name: str) -> Role:
    role = await get_role_by_name(db, name)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


async def get_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def validate_permission_keys(payload_permissions: dict) -> None:
    known_permissions = set(PERMISSIONS.fields().keys())
    unknown = set(payload_permissions.keys()) - known_permissions
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown permission keys: {sorted(unknown)}",
        )


@roles_open_router.post("", response_model=RoleResponse)
async def create_role_api(
    payload: RoleCreate, db: AsyncSession = Depends(get_db)
) -> RoleResponse:
    role = await get_role_by_name(db, payload.role)
    if role:
        raise HTTPException(status_code=409, detail="Role already exists")
    role = await create_role(db, payload.role, payload.permissions)
    return role_to_response(role)


@roles_router.get("", response_model=list[RoleResponse])
async def list_roles(db: AsyncSession = Depends(get_db)) -> list[RoleResponse]:
    await sync_role_permissions(db)
    result = await db.execute(select(Role))
    roles = result.scalars().all()
    return [role_to_response(r) for r in roles]


@roles_router.patch("/{name}/permissions", response_model=RoleResponse)
async def patch_role_permissions(
    name: str, payload: RolePermissionsUpdate, db: AsyncSession = Depends(get_db)
) -> RoleResponse:
    role = await get_role_or_404(db, name)
    validate_permission_keys(payload.permissions)
    await sync_role_permissions(db)
    merged = build_permissions_with_patch(role.permissions, payload.permissions)
    validated = validate_permissions_payload(merged)
    role = await update_role_permissions(db, role, validated)
    return role_to_response(role)


@roles_router.get("/{name}/permissions", response_model=RolePermissionsResponse)
async def get_role_permissions(
    name: str, db: AsyncSession = Depends(get_db)
) -> RolePermissionsResponse:
    role = await get_role_or_404(db, name)
    await sync_role_permissions(db)
    await db.refresh(role)
    return RolePermissionsResponse(role=role.role, permissions=role.permissions)


@users_open_router.post("", response_model=UserResponse)
async def create_user_api(
    payload: UserCreate, db: AsyncSession = Depends(get_db)
) -> UserResponse:
    existing_result = await db.execute(
        select(User).where(User.username == payload.username)
    )
    existing = existing_result.scalars().first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")
    role = await get_role_or_404(db, payload.role)
    user = await create_user(db, payload.username, payload.password, role)
    return user_to_response(user)


@users_router.patch("/{user_id}/role", response_model=UserResponse)
async def set_user_role(
    user_id: int, payload: UserRoleUpdate, db: AsyncSession = Depends(get_db)
) -> UserResponse:
    user = await get_user_or_404(db, user_id)
    role = await get_role_or_404(db, payload.role)
    user = await assign_role(db, user, role)
    return user_to_response(user)


@users_router.patch("/{user_id}", response_model=UserResponse)
async def patch_user(
    user_id: int, payload: UserPatch, db: AsyncSession = Depends(get_db)
) -> UserResponse:
    user = await get_user_or_404(db, user_id)

    if payload.username is not None:
        existing_result = await db.execute(
            select(User).where(User.username == payload.username, User.id != user_id)
        )
        existing = existing_result.scalars().first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username already exists")
        user.username = payload.username
    if payload.password is not None:
        user.password = payload.password
    if payload.role is not None:
        role = await get_role_or_404(db, payload.role)
        user.role = role

    db.add(user)
    await db.commit()
    await db.refresh(user, attribute_names=["role"])
    return user_to_response(user)
