from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import SECRET_KEY
from core.users.models.users import User
from database import SessionLocal


ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

_bearer = HTTPBearer(auto_error=False)


async def _get_db() -> AsyncSession:
    async with SessionLocal() as db:
        yield db


def create_access_token(
    user_id: int,
    username: Optional[str] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    expires = timedelta(minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + expires}
    if username:
        payload["username"] = username
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if user is None:
        return None
    if user.password != password:
        return None
    return user


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(_get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    user_id: Optional[int] = None
    if isinstance(subject, int):
        user_id = subject
    else:
        try:
            user_id = int(subject)
        except (TypeError, ValueError):
            user_id = None

    if user_id is not None:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
    else:
        username = subject
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalars().first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user
