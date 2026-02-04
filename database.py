import os

from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Default declarative base for use in models
Base = declarative_base()

# Example (override with environment variables as needed)
DATABASE_URL_ASYNC = os.getenv("DATABASE_URL_ASYNC", "sqlite+aiosqlite:///./app.db")
SQLALCHEMY_ECHO = os.getenv("SQLALCHEMY_ECHO", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Async engine and async session
async_engine = create_async_engine(DATABASE_URL_ASYNC, echo=SQLALCHEMY_ECHO, future=True)
SessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    # Ensure models are imported so metadata is populated.
    import core.users.models.users  # noqa: F401

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
