from fastapi import APIRouter, Depends

from core.auth import require_auth

# Open/closed routers
CORE_OPEN = APIRouter(prefix="/api")
CORE_CLOSE = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

# Aggregator router
CORE = APIRouter()

# Import modules to register their routes
from . import v1  # noqa: F401

CORE.include_router(CORE_OPEN)
CORE.include_router(CORE_CLOSE)
