from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.permission import PERMISSIONS
from core.users.models.users import Role, User
from database import SessionLocal

logger = logging.getLogger(__name__)


def _merge_permissions(current: Optional[Dict[str, Any]], defaults: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if current:
        merged.update(current)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
    return merged


async def sync_role_permissions(db: AsyncSession) -> int:
    """
    Ensure all roles contain defaults for all registered permissions.
    Returns number of updated roles.
    """
    defaults = PERMISSIONS.default_permissions()
    updated = 0
    result = await db.execute(select(Role))
    for role in result.scalars().all():
        merged = _merge_permissions(role.permissions or {}, defaults)
        if merged != (role.permissions or {}):
            role.permissions = merged
            updated += 1
    if updated:
        await db.commit()
    return updated


async def create_role(
    db: AsyncSession, name: str, permissions: Optional[Dict[str, Any]] = None
) -> Role:
    defaults = PERMISSIONS.default_permissions()
    merged = _merge_permissions(permissions or {}, defaults)
    role = Role(role=name, permissions=merged)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


async def get_role_by_name(db: AsyncSession, name: str) -> Optional[Role]:
    result = await db.execute(select(Role).where(Role.role == name))
    return result.scalars().first()


async def create_user(db: AsyncSession, username: str, password: str, role: Role) -> User:
    user = User(username=username, password=password, role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user, attribute_names=["role"])
    return user


async def assign_role(db: AsyncSession, user: User, role: Role) -> User:
    user.role = role
    db.add(user)
    await db.commit()
    await db.refresh(user, attribute_names=["role"])
    return user


async def update_role_permissions(db: AsyncSession, role: Role, updates: Dict[str, Any]) -> Role:
    defaults = PERMISSIONS.default_permissions()
    merged = _merge_permissions(role.permissions or {}, defaults)
    merged.update(updates)
    role.permissions = merged
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


def build_permissions_with_patch(
    current: Optional[Dict[str, Any]], updates: Dict[str, Any]
) -> Dict[str, Any]:
    defaults = PERMISSIONS.default_permissions()
    merged = _merge_permissions(current or {}, defaults)
    merged.update(updates)
    return merged


def validate_permissions_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate payload against the current permissions schema.
    Returns validated permissions (normalized types).
    """
    try:
        model = PERMISSIONS.schema()
    except RuntimeError:
        return payload
    instance = model(**payload)
    return instance.model_dump()


async def init_permissions_sync() -> None:
    """
    Register a change listener so new plugin permissions are applied to all roles.
    Runs an initial sync on startup.
    """
    async def _run_sync() -> None:
        try:
            async with SessionLocal() as db:
                await sync_role_permissions(db)
        except Exception as exc:
            logger.warning("Failed to sync role permissions: %s", exc)

    def _listener(_registry) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_run_sync())
        else:
            loop.create_task(_run_sync())

    PERMISSIONS.add_change_listener(_listener)

    try:
        await _run_sync()
    except Exception as exc:
        logger.warning("Failed to run initial role permission sync: %s", exc)
