from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import authenticate_user, create_access_token
from database import SessionLocal


auth_router = APIRouter(prefix="/auth", tags=["Auth"])


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


async def get_db() -> AsyncSession:
    async with SessionLocal() as db:
        yield db


@auth_router.post("/token", response_model=TokenResponse)
async def issue_token(
    payload: TokenRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    user = await authenticate_user(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = create_access_token(user_id=user.id, username=user.username)
    return TokenResponse(access_token=token)
