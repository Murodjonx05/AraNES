import shutil
import sys
import textwrap
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.auth as auth_module
from core.plugin.loader import PluginRegistry, include_plugins
from core.plugin.api import routes as loader_routes


def _write_plugin(plugin_dir: Path, body: str) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "app.py").write_text(textwrap.dedent(body), encoding="utf-8")


def test_include_all_routes_guarded(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "services"
    state_file = plugins_dir / "plugins_registry.json"
    plugin_name = f"demo_{tmp_path.name}"
    _write_plugin(
        plugins_dir / plugin_name,
        """
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/ping")
        async def ping():
            return {"ok": True}
        """,
    )

    registry = PluginRegistry(plugins_dir=plugins_dir, state_file=state_file)
    app = FastAPI()
    include_plugins(app, registry=registry)
    client = TestClient(app)

    resp = client.get(f"/plugins/{plugin_name}/ping")
    assert resp.status_code == 503

    registry.enable(plugin_name)
    resp = client.get(f"/plugins/{plugin_name}/ping")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_load_plugins_cache_mtime(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "services"
    state_file = plugins_dir / "plugins_registry.json"
    plugin_name = f"cache_{tmp_path.name}"
    plugin_dir = plugins_dir / plugin_name
    _write_plugin(
        plugin_dir,
        """
        from fastapi import APIRouter

        router = APIRouter()
        VALUE = 1
        """,
    )

    registry = PluginRegistry(plugins_dir=plugins_dir, state_file=state_file)
    records = registry.load_plugins()
    record = records[0]
    module_before = sys.modules[record.module_name]

    registry.load_plugins()
    record_after = registry.get(plugin_name)
    module_after = sys.modules[record_after.module_name]
    assert module_after is module_before

    time.sleep(1.1)
    _write_plugin(
        plugin_dir,
        """
        from fastapi import APIRouter

        router = APIRouter()
        VALUE = 2
        """,
    )

    registry.load_plugins()
    record_reload = registry.get(plugin_name)
    module_reload = sys.modules[record_reload.module_name]
    assert module_reload is not module_before
    assert getattr(module_reload, "VALUE") == 2


def test_removed_plugin_cleanup(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "services"
    state_file = plugins_dir / "plugins_registry.json"
    plugin_name = f"removed_{tmp_path.name}"
    plugin_dir = plugins_dir / plugin_name
    _write_plugin(
        plugin_dir,
        """
        from fastapi import APIRouter

        router = APIRouter()
        """,
    )

    registry = PluginRegistry(plugins_dir=plugins_dir, state_file=state_file)
    registry.load_plugins()
    assert registry.get(plugin_name) is not None

    shutil.rmtree(plugin_dir)

    registry.load_plugins()
    assert registry.get(plugin_name) is None


def test_switch_unknown_plugin_404(tmp_path: Path, monkeypatch) -> None:
    plugins_dir = tmp_path / "services"
    state_file = plugins_dir / "plugins_registry.json"
    registry = PluginRegistry(plugins_dir=plugins_dir, state_file=state_file)
    monkeypatch.setattr(loader_routes, "PLUGIN_REGISTRY", registry)

    app = FastAPI()
    app.include_router(loader_routes.router)
    app.dependency_overrides[auth_module.require_auth] = lambda: None
    client = TestClient(app)

    resp = client.post("/api/loader/plugins/unknown/switch?enabled=true")
    assert resp.status_code == 404
