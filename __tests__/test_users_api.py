from typing import Dict

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.api.v1.users as users_api
import core.auth as auth_module
import core.permission as permission_module
import core.users.models.users  # noqa: F401
import core.users.service as users_service
from core.api import CORE_CLOSE, CORE_OPEN
from core.api.v1 import auth as auth_api
from database import Base


def _setup_app_and_db(monkeypatch):
    async_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _init_models() -> None:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init_models())

    monkeypatch.setattr(users_api, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(users_service, "SessionLocal", TestingSessionLocal)

    registry = permission_module.PermissionsRegistry()
    monkeypatch.setattr(permission_module, "PERMISSIONS", registry)
    monkeypatch.setattr(users_service, "PERMISSIONS", registry)
    monkeypatch.setattr(users_api, "PERMISSIONS", registry)

    monkeypatch.setattr(auth_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(auth_api, "SessionLocal", TestingSessionLocal)

    app = FastAPI()
    app.include_router(CORE_OPEN)
    app.include_router(CORE_CLOSE)
    return app, registry


def _get_auth_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post(
        "/api/auth/token",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_role_permissions_defaults_and_patch(monkeypatch):
    app, registry = _setup_app_and_db(monkeypatch)

    class BlogPerm(BaseModel):
        allow_read: bool = True
        max_items: int = 10

    registry.register(BlogPerm, prefix="plugins/blog")
    defaults: Dict[str, object] = registry.default_permissions()

    client = TestClient(app)
    resp = client.post("/api/roles", json={"role": "admin"})
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["permissions"].keys()) >= set(defaults.keys())
    for key, value in defaults.items():
        assert data["permissions"][key] == value

    resp = client.post(
        "/api/users",
        json={"username": "owner", "password": "hash", "role": "admin"},
    )
    assert resp.status_code == 200
    headers = _get_auth_headers(client, "owner", "hash")

    resp = client.patch(
        "/api/roles/admin/permissions",
        json={"permissions": {"plugins:blog:blogperm:allow_read": False}},
        headers=headers,
    )
    assert resp.status_code == 200
    patched = resp.json()["permissions"]
    assert patched["plugins:blog:blogperm:allow_read"] is False
    assert patched["plugins:blog:blogperm:max_items"] == 10

    resp = client.get("/api/roles/admin/permissions", headers=headers)
    assert resp.status_code == 200
    permissions = resp.json()["permissions"]
    assert permissions["plugins:blog:blogperm:allow_read"] is False

    resp = client.patch(
        "/api/roles/admin/permissions",
        json={"permissions": {"unknown:perm": True}},
        headers=headers,
    )
    assert resp.status_code == 400


def test_user_create_and_patch(monkeypatch):
    app, registry = _setup_app_and_db(monkeypatch)

    class AccessPerm(BaseModel):
        enabled: bool = True

    registry.register(AccessPerm)

    client = TestClient(app)
    resp = client.post("/api/roles", json={"role": "admin"})
    assert resp.status_code == 200

    resp = client.post(
        "/api/users",
        json={"username": "alice", "password": "hash", "role": "admin"},
    )
    assert resp.status_code == 200
    user_id = resp.json()["id"]
    headers = _get_auth_headers(client, "alice", "hash")

    resp = client.post(
        "/api/users",
        json={"username": "alice", "password": "hash2", "role": "admin"},
    )
    assert resp.status_code == 409

    resp = client.patch(
        f"/api/users/{user_id}",
        json={"username": "bob"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "bob"

    resp = client.post(
        "/api/roles",
        json={"role": "editor"},
    )
    assert resp.status_code == 200

    resp = client.patch(
        f"/api/users/{user_id}/role",
        json={"role": "editor"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


def test_protected_endpoints_require_token(monkeypatch):
    app, registry = _setup_app_and_db(monkeypatch)

    class AccessPerm(BaseModel):
        enabled: bool = True

    registry.register(AccessPerm)

    client = TestClient(app)
    resp = client.post("/api/roles", json={"role": "admin"})
    assert resp.status_code == 200

    resp = client.post(
        "/api/users",
        json={"username": "alice", "password": "hash", "role": "admin"},
    )
    assert resp.status_code == 200
    user_id = resp.json()["id"]

    resp = client.get("/api/roles")
    assert resp.status_code == 401

    resp = client.patch(
        f"/api/users/{user_id}",
        json={"username": "bob"},
    )
    assert resp.status_code == 401


def test_token_expires(monkeypatch):
    app, registry = _setup_app_and_db(monkeypatch)

    class AccessPerm(BaseModel):
        enabled: bool = True

    registry.register(AccessPerm)

    client = TestClient(app)
    resp = client.post("/api/roles", json={"role": "admin"})
    assert resp.status_code == 200

    resp = client.post(
        "/api/users",
        json={"username": "alice", "password": "hash", "role": "admin"},
    )
    assert resp.status_code == 200
    user_id = resp.json()["id"]

    expired = auth_module.create_access_token(user_id=user_id, username="alice", expires_minutes=-1)
    headers = {"Authorization": f"Bearer {expired}"}

    resp = client.get("/api/roles", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token expired"


def test_token_survives_username_change(monkeypatch):
    app, registry = _setup_app_and_db(monkeypatch)

    class AccessPerm(BaseModel):
        enabled: bool = True

    registry.register(AccessPerm)

    client = TestClient(app)
    resp = client.post("/api/roles", json={"role": "admin"})
    assert resp.status_code == 200

    resp = client.post(
        "/api/users",
        json={"username": "alice", "password": "hash", "role": "admin"},
    )
    assert resp.status_code == 200
    user_id = resp.json()["id"]

    headers = _get_auth_headers(client, "alice", "hash")

    resp = client.patch(
        f"/api/users/{user_id}",
        json={"username": "bob"},
        headers=headers,
    )
    assert resp.status_code == 200

    resp = client.get("/api/roles", headers=headers)
    assert resp.status_code == 200
