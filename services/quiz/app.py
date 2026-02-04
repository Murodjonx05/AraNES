from fastapi import APIRouter

quiz = APIRouter()

@quiz.get('/solve')
async def solve():
    return {'status': 'ok'}
