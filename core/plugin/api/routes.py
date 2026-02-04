from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import require_auth
from core import BASE_DIR
from core.plugin.loader import PLUGIN_REGISTRY, include_plugins
from core.plugin.models import PluginRecord

router: APIRouter = APIRouter(
    prefix="/api/loader",
    tags=["Plugin"],
    dependencies=[Depends(require_auth)],
)

def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except Exception:
        return str(path)

class PluginInfo(BaseModel):
    name: str
    enabled: bool
    path: str
    routers: int
    error: Optional[str] = None

class PluginListResponse(BaseModel):
    plugins: List[PluginInfo]

class PluginStatusResponse(BaseModel):
    name: str
    enabled: bool

def _record_to_plugininfo(record: PluginRecord) -> PluginInfo:
    return PluginInfo(
        name=record.name,
        enabled=record.enabled,
        path=_relative_path(record.path),
        routers=len(record.routers),
        error=record.error,
    )

@router.get("/plugins", response_model=PluginListResponse)
def list_plugins() -> PluginListResponse:
    records = PLUGIN_REGISTRY.load_plugins()
    return PluginListResponse(plugins=[_record_to_plugininfo(r) for r in records])

@router.get("/plugins/{name}", response_model=PluginInfo)
def get_plugin(name: str) -> PluginInfo:
    PLUGIN_REGISTRY.load_plugins()
    record = PLUGIN_REGISTRY.get(name)
    if record is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return _record_to_plugininfo(record)

@router.post("/plugins/{name}/switch", response_model=PluginInfo)
def switch_plugin(name: str, enabled: bool, request: Request) -> PluginInfo:
    PLUGIN_REGISTRY.load_plugins()
    record = PLUGIN_REGISTRY.get(name)
    if record is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    if enabled:
        PLUGIN_REGISTRY.enable(name)
    else:
        PLUGIN_REGISTRY.disable(name)
    include_plugins(request.app, registry=PLUGIN_REGISTRY)
    request.app.openapi_schema = None
    record = PLUGIN_REGISTRY.get(name)
    if record is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return _record_to_plugininfo(record)


@router.post("/plugins/refresh", response_model=PluginListResponse)
def refresh_plugins(request: Request) -> PluginListResponse:
    records = PLUGIN_REGISTRY.load_plugins()
    include_plugins(request.app, registry=PLUGIN_REGISTRY)
    request.app.openapi_schema = None
    return PluginListResponse(plugins=[_record_to_plugininfo(r) for r in records])
