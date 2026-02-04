import hashlib
import importlib.util
import json
import logging
import re
import sys
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from core import PLUGINS_DIR
from core.plugin.models import PluginRecord
from core.permission import PERMISSIONS

logger = logging.getLogger(__name__)


def get_state_file() -> Path:
    """Plugin state is stored in services/plugins_registry.json."""
    return PLUGINS_DIR / "plugins_registry.json"


def _iter_plugin_dirs(plugins_dir: Path) -> Iterable[Path]:
    """
    Yield plugin subdirectories that don't start with '.' or '__'.
    """
    if not plugins_dir.exists() or not plugins_dir.is_dir():
        return
    for item in plugins_dir.iterdir():
        if item.is_dir() and not (item.name.startswith(".") or item.name.startswith("__")):
            yield item


def _find_router_objects(module) -> List[APIRouter]:
    """
    Extract all APIRouter instances from the module globals.
    """
    return [obj for obj in vars(module).values() if isinstance(obj, APIRouter)]


def _is_plugin_route(route: APIRoute, plugin_name: str) -> bool:
    tag = f"plugin:{plugin_name}"
    tags = route.tags or []
    return any(isinstance(item, str) and item == tag for item in tags)


class PluginRegistry:
    def __init__(
        self, plugins_dir: Optional[Path] = None, state_file: Optional[Path] = None
    ):
        self.plugins_dir: Path = plugins_dir or PLUGINS_DIR
        self.state_file: Path = state_file or get_state_file()
        self._state: Dict[str, bool] = self._load_state()
        self._state_mtime: Optional[int] = self._state_file_mtime()
        self._module_mtimes: Dict[str, int] = {}
        self._records: Dict[str, PluginRecord] = {}
        self._lock = threading.RLock()

        # Ensure required files/directories exist
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._save_state()

    def _state_file_mtime(self) -> Optional[int]:
        try:
            return self.state_file.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _load_state(self) -> Dict[str, bool]:
        if not self.state_file.exists():
            return {}
        try:
            with self.state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Coerce keys to str and values to bool
                    return {str(k): bool(v) for k, v in data.items()}
        except Exception as exc:
            logger.warning("Failed to load plugin state from %s: %s", self.state_file, exc)
        return {}

    def _save_state(self) -> None:
        # Atomic update of the state file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._state, ensure_ascii=False, indent=2)
        tmp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        try:
            tmp.replace(self.state_file)
        except FileNotFoundError:
            tmp.rename(self.state_file)
        self._state_mtime = self._state_file_mtime()

    def _sync_records_enabled(self) -> None:
        for name, record in self._records.items():
            record.enabled = self._state.get(name, False)

    def _refresh_state_from_disk(self) -> None:
        current_mtime = self._state_file_mtime()
        if current_mtime is None:
            if self._state:
                self._state = {}
                self._sync_records_enabled()
            self._state_mtime = None
            return
        if self._state_mtime is None or current_mtime != self._state_mtime:
            self._state = self._load_state()
            self._state_mtime = current_mtime
            self._sync_records_enabled()

    def refresh_state(self) -> None:
        with self._lock:
            self._refresh_state_from_disk()

    def is_enabled(self, name: str) -> bool:
        with self._lock:
            self._refresh_state_from_disk()
            return self._state.get(name, False)

    def enable(self, name: str) -> None:
        with self._lock:
            self._refresh_state_from_disk()
            self._state[name] = True
            self._save_state()
            record = self._records.get(name)
            if record:
                record.enabled = True

    def disable(self, name: str) -> None:
        with self._lock:
            self._refresh_state_from_disk()
            self._state[name] = False
            self._save_state()
            record = self._records.get(name)
            if record:
                record.enabled = False

    def list(self) -> List[PluginRecord]:
        with self._lock:
            self._refresh_state_from_disk()
            self._sync_records_enabled()
            return list(self._records.values())

    def get(self, name: str) -> Optional[PluginRecord]:
        with self._lock:
            self._refresh_state_from_disk()
            record = self._records.get(name)
            if record:
                record.enabled = self._state.get(name, False)
            return record

    def load_plugins(self) -> List[PluginRecord]:
        """
        Loads all plugins in the `plugins_dir`, updating plugin records and plugin states.
        Returns a list of PluginRecord.
        """
        with self._lock:
            self._refresh_state_from_disk()
            records: List[PluginRecord] = []
            plugins_found: set[str] = set()

            for plugin_dir in _iter_plugin_dirs(self.plugins_dir):
                plugin_name = plugin_dir.name
                plugins_found.add(plugin_name)
                module_path = plugin_dir / "app.py"
                safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", plugin_name)
                module_id = hashlib.md5(str(module_path.resolve()).encode("utf-8")).hexdigest()[:8]
                module_name = f"plugin_{safe_name}_{module_id}"

                if not module_path.exists():
                    record = PluginRecord(
                        name=plugin_name,
                        path=plugin_dir,
                        module_name=module_name,
                        routers=[],
                        enabled=self._state.get(plugin_name, False),
                        error="app.py not found",
                        module_mtime_ns=None,
                    )
                    self._records[plugin_name] = record
                    self._module_mtimes.pop(plugin_name, None)
                    records.append(record)
                    continue

                module_mtime = self._module_mtime(module_path)
                cached_mtime = self._module_mtimes.get(plugin_name)
                record = self._records.get(plugin_name)
                if (
                    record is not None
                    and record.error is None
                    and record.module_name == module_name
                    and module_mtime is not None
                    and cached_mtime == module_mtime
                ):
                    record.enabled = self._state.get(plugin_name, False)
                    record.module_mtime_ns = module_mtime
                    records.append(record)
                    continue

                try:
                    if record:
                        sys.modules.pop(record.module_name, None)
                    spec = importlib.util.spec_from_file_location(module_name, module_path)
                    if not spec or not spec.loader:
                        raise ImportError("Unable to build module spec")
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    routers = _find_router_objects(module)
                    record = PluginRecord(
                        name=plugin_name,
                        path=plugin_dir,
                        module_name=module_name,
                        routers=routers,
                        enabled=self._state.get(plugin_name, False),
                        module_mtime_ns=module_mtime,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to load plugin '%s' from %s: %s",
                        plugin_name,
                        module_path,
                        exc,
                    )
                    record = PluginRecord(
                        name=plugin_name,
                        path=plugin_dir,
                        module_name=module_name,
                        routers=[],
                        enabled=self._state.get(plugin_name, False),
                        error=str(exc),
                        module_mtime_ns=module_mtime,
                    )
                self._records[plugin_name] = record
                if module_mtime is not None:
                    self._module_mtimes[plugin_name] = module_mtime
                records.append(record)

            stale_records = [name for name in list(self._records.keys()) if name not in plugins_found]
            for name in stale_records:
                record = self._records.pop(name, None)
                self._module_mtimes.pop(name, None)
                if record:
                    sys.modules.pop(record.module_name, None)

            self._sync_plugin_states(records)
            return records

    def _module_mtime(self, module_path: Path) -> Optional[int]:
        try:
            return module_path.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _sync_plugin_states(self, records: List[PluginRecord]) -> None:
        """
        Set default disabled state for new plugins, remove stale state files,
        and save state if modified or if state file missing.
        """
        updated = False

        # Set default disabled state for plugins not in state
        for record in records:
            if record.name not in self._state:
                self._state[record.name] = False
                updated = True

        # Remove plugins from state that no longer exist on disk
        plugins_found = set(r.name for r in records)
        stale_keys = [k for k in list(self._state.keys()) if k not in plugins_found]
        if stale_keys:
            for k in stale_keys:
                del self._state[k]
            updated = True

        if updated or not self.state_file.exists():
            self._save_state()


# Singleton registry instance
PLUGIN_REGISTRY = PluginRegistry()


def _require_plugin_enabled(registry: PluginRegistry, name: str):
    """
    FastAPI dependency to check if plugin is enabled.
    """
    def _dep():
        if not registry.is_enabled(name):
            raise HTTPException(status_code=503, detail=f"Plugin '{name}' is disabled")
    return _dep


def _install_openapi_filter(app: FastAPI, registry: PluginRegistry) -> None:
    if getattr(app.state, "_plugin_openapi_filter_installed", False):
        return

    def custom_openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema

        filtered_routes = []
        for route in app.routes:
            if isinstance(route, APIRoute):
                tags = route.tags or []
                plugin_tags = [
                    tag for tag in tags if isinstance(tag, str) and tag.startswith("plugin:")
                ]
                if plugin_tags:
                    plugin_name = plugin_tags[0].split(":", 1)[1]
                    if not registry.is_enabled(plugin_name):
                        continue
            filtered_routes.append(route)

        app.openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=filtered_routes,
        )
        _inject_permissions_schema(app.openapi_schema)
        return app.openapi_schema

    app.openapi = custom_openapi
    app.state._plugin_openapi_filter_installed = True


def _inject_permissions_schema(openapi_schema: dict) -> None:
    try:
        model = PERMISSIONS.schema()
    except Exception:
        return

    model_name = model.__name__
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    defs = schema.pop("$defs", {})

    components = openapi_schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})

    for name, value in defs.items():
        schemas.setdefault(name, value)
    schemas[model_name] = schema

    path_item = openapi_schema.get("paths", {}).get("/api/roles/{name}/permissions")
    if not path_item:
        return
    patch_item = path_item.get("patch")
    if not patch_item:
        return
    request_body = patch_item.get("requestBody", {})
    content = request_body.get("content", {}).get("application/json")
    if not content:
        return
    content["schema"] = {
        "type": "object",
        "properties": {
            "permissions": {"$ref": f"#/components/schemas/{model_name}"},
        },
        "required": ["permissions"],
    }


def _remove_plugin_routes(app: FastAPI, plugin_name: str) -> bool:
    routes = app.router.routes
    remaining = [
        route
        for route in routes
        if not (isinstance(route, APIRoute) and _is_plugin_route(route, plugin_name))
    ]
    if len(remaining) == len(routes):
        return False
    app.router.routes = remaining
    return True


def include_plugins(app: FastAPI, registry: Optional[PluginRegistry] = None) -> List[PluginRecord]:
    """
    Include routers of all discovered plugins into the FastAPI app.
    Access is gated by the plugin enabled state.

    Returns:
        List[PluginRecord]: The list of detected PluginRecord objects.
    """
    reg = registry or PLUGIN_REGISTRY
    records = reg.load_plugins()
    _install_openapi_filter(app, reg)

    registered_plugins = getattr(app.state, "_plugin_routes_registry", None)
    if registered_plugins is None:
        registered_plugins = {}
        app.state._plugin_routes_registry = registered_plugins

    current_names = {record.name for record in records}
    routes_changed = False

    stale = [name for name in registered_plugins.keys() if name not in current_names]
    for name in stale:
        routes_changed |= _remove_plugin_routes(app, name)
        registered_plugins.pop(name, None)

    for record in records:
        if record.name in registered_plugins:
            entry = registered_plugins[record.name]
            if entry.get("module_mtime_ns") == record.module_mtime_ns:
                continue
            routes_changed |= _remove_plugin_routes(app, record.name)

        if not record.routers:
            registered_plugins.pop(record.name, None)
            continue

        for router in record.routers:
            app.include_router(
                router,
                prefix=f"/plugins/{record.name}",
                tags=[f"plugin:{record.name}"],
                dependencies=[Depends(_require_plugin_enabled(reg, record.name))],
            )
        registered_plugins[record.name] = {"module_mtime_ns": record.module_mtime_ns}
        routes_changed = True

    if routes_changed:
        app.openapi_schema = None

    app.state.plugins_registry = reg
    return records
