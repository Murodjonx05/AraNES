import asyncio

import httpx
from fastapi import Request

_CLIENT_KEY = "_inprocess_http_client"
_CLIENT_LOCK_KEY = "_inprocess_http_client_lock"
_SHUTDOWN_HOOK_KEY = "_inprocess_http_shutdown_hook"


async def _close_inprocess_client(app) -> None:
    client = getattr(app.state, _CLIENT_KEY, None)
    if client is not None:
        await client.aclose()
        setattr(app.state, _CLIENT_KEY, None)


async def _get_inprocess_client(request: Request) -> httpx.AsyncClient:
    app = request.app
    lock = getattr(app.state, _CLIENT_LOCK_KEY, None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(app.state, _CLIENT_LOCK_KEY, lock)

    async with lock:
        client = getattr(app.state, _CLIENT_KEY, None)
        if client is not None:
            return client

        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url="http://app")
        setattr(app.state, _CLIENT_KEY, client)

        if not getattr(app.state, _SHUTDOWN_HOOK_KEY, False):
            async def _shutdown() -> None:
                await _close_inprocess_client(app)

            app.add_event_handler("shutdown", _shutdown)
            setattr(app.state, _SHUTDOWN_HOOK_KEY, True)

        return client


async def inprocess_request(request: Request, method: str, path: str, **kwargs) -> httpx.Response:
    """
    Make an in-process HTTP request against the same FastAPI app (no network).
    Reuses a cached AsyncClient per app for lower overhead.
    """
    client = await _get_inprocess_client(request)
    return await client.request(method, path, **kwargs)


async def inprocess_get(request: Request, path: str, **kwargs) -> httpx.Response:
    return await inprocess_request(request, "GET", path, **kwargs)


async def inprocess_post(request: Request, path: str, **kwargs) -> httpx.Response:
    return await inprocess_request(request, "POST", path, **kwargs)


async def inprocess_put(request: Request, path: str, **kwargs) -> httpx.Response:
    return await inprocess_request(request, "PUT", path, **kwargs)


async def inprocess_delete(request: Request, path: str, **kwargs) -> httpx.Response:
    return await inprocess_request(request, "DELETE", path, **kwargs)


async def inprocess_patch(request: Request, path: str, **kwargs) -> httpx.Response:
    return await inprocess_request(request, "PATCH", path, **kwargs)
