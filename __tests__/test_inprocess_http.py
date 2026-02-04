from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.inprocess_http import (
    inprocess_delete,
    inprocess_get,
    inprocess_patch,
    inprocess_post,
    inprocess_put,
)


def test_inprocess_get():
    app = FastAPI()

    @app.get("/target")
    async def target():
        return {"ok": True}

    @app.get("/caller")
    async def caller(request: Request):
        response = await inprocess_get(request, "/target")
        return response.json()

    client = TestClient(app)
    response = client.get("/caller")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_inprocess_post():
    app = FastAPI()

    @app.post("/target")
    async def target(payload: dict):
        return {"echo": payload}

    @app.post("/caller")
    async def caller(request: Request):
        response = await inprocess_post(request, "/target", json={"x": 1})
        return response.json()

    client = TestClient(app)
    response = client.post("/caller")
    assert response.status_code == 200
    assert response.json() == {"echo": {"x": 1}}


def test_inprocess_put():
    app = FastAPI()

    @app.put("/target")
    async def target(payload: dict):
        return {"echo": payload}

    @app.put("/caller")
    async def caller(request: Request):
        response = await inprocess_put(request, "/target", json={"y": 2})
        return response.json()

    client = TestClient(app)
    response = client.put("/caller")
    assert response.status_code == 200
    assert response.json() == {"echo": {"y": 2}}


def test_inprocess_patch():
    app = FastAPI()

    @app.patch("/target")
    async def target(payload: dict):
        return {"echo": payload}

    @app.patch("/caller")
    async def caller(request: Request):
        response = await inprocess_patch(request, "/target", json={"z": 3})
        return response.json()

    client = TestClient(app)
    response = client.patch("/caller")
    assert response.status_code == 200
    assert response.json() == {"echo": {"z": 3}}


def test_inprocess_delete():
    app = FastAPI()

    @app.delete("/target")
    async def target():
        return {"deleted": True}

    @app.delete("/caller")
    async def caller(request: Request):
        response = await inprocess_delete(request, "/target")
        return response.json()

    client = TestClient(app)
    response = client.delete("/caller")
    assert response.status_code == 200
    assert response.json() == {"deleted": True}
