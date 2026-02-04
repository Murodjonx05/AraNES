from fastapi import FastAPI
from core.api import CORE
from core.plugin.loader import include_plugins
from core.plugin.api.routes import router as PLUGIN
from core.users import init_permissions_sync
from database import init_db

import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("middlewares.local_route_middleware").setLevel(logging.INFO)

# Initialize main application
APP = FastAPI(
    title="AraNES Core API",
    description="Core API for AraNES. brand: AraNES. slogan: Arachne Core & Services.",
    version="0.1.0"
)

# Include main API router
APP.include_router(CORE)
# Loader management API
APP.include_router(PLUGIN)

# Sync role permissions on permission registry changes
@APP.on_event("startup")
async def _startup() -> None:
    await init_db()
    await init_permissions_sync()

# Auto-load plugins from services/
include_plugins(APP)
