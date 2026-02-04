from fastapi import APIRouter

core_router = APIRouter(tags=["CORE"])


@core_router.get('/health')
async def health():
    return {'status': 'ok'}
