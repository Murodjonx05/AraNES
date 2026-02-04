from core.api import CORE_CLOSE, CORE_OPEN
from .auth import auth_router
from .heal import core_router
from .users import roles_open_router, roles_router, users_open_router, users_router

CORE_OPEN.include_router(core_router)
CORE_OPEN.include_router(auth_router)
CORE_OPEN.include_router(roles_open_router)
CORE_OPEN.include_router(users_open_router)

CORE_CLOSE.include_router(roles_router)
CORE_CLOSE.include_router(users_router)
