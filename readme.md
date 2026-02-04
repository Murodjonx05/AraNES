# AraNES

brand: AraNES  
slogan: Arachne Core & Services

AraNES — модульное ядро на FastAPI для LMS‑платформ и образовательных сервисов. Проект строится вокруг плагинов, единого контракта прав доступа и быстрых внутренних вызовов без сетевого оверхеда.

## Ключевые возможности

- Plugin Loader: подключение, переключение и hot‑reload плагинов из `services/`.
- Permissions Registry: динамическая Pydantic‑схема прав, расширяемая плагинами.
- In‑process HTTP: вызовы внутри приложения через `httpx.ASGITransport`.
- Async DB: единый async‑слой на `AsyncSession`.
- JWT‑доступ: разделение на `CORE_OPEN` и `CORE_CLOSE`.
- Roles/Users API: базовый слой управления пользователями и ролями.

## Быстрый старт

1. Установка зависимостей:

```bash
pip install -r requirements.txt
```

2. Запуск сервера:

```bash
uvicorn main:APP --reload
```

3. Проверка:

```
GET /api/health
```

## Архитектурные блоки

- `main.py` — инициализация FastAPI, подключение API и плагинов.
- `core/inprocess_http.py` — in‑process HTTP вызовы.
- `core/permission.py` — реестр прав и сборка динамической схемы.
- `core/plugin/` — загрузчик плагинов и API управления.
- `core/api/v1/` — роли, пользователи, health, auth.
- `services/` — каталог плагинов.

## Аутентификация и доступ

- `CORE_OPEN` — публичные endpoints.
- `CORE_CLOSE` — защищенные endpoints (JWT).

JWT выдается по `POST /api/auth/token` на основе `username` и `password`.

Пример:

```bash
curl -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"hash"}'
```

Использование:

```bash
curl http://localhost:8000/api/roles \
  -H "Authorization: Bearer <token>"
```

## Plugin Loader (MVP)

**Состояние:** `services/plugins_registry.json`  
**Плагины:** `services/<plugin>/app.py`  
**Роутеры:** любые `APIRouter` в `app.py`  
**Префикс:** `/plugins/<plugin_name>`

### API управления (JWT)

- `GET /api/loader/plugins`
- `GET /api/loader/plugins/{name}`
- `POST /api/loader/plugins/{name}/switch?enabled=true|false`
- `POST /api/loader/plugins/refresh`

## Реестр прав доступа

Поля именуются по шаблону:

```
[prefix:]ClassName:field
```

`prefix` нормализуется через `:` (пример: `plugins/quiz` -> `plugins:quiz`). Все ключи приводятся к нижнему регистру.

Пример регистрации:

```python
from pydantic import BaseModel
from core.permission import PERMISSIONS

class QuizSettings(BaseModel):
    timer: int = 60
    attempts: int = 3

PERMISSIONS.register(QuizSettings, prefix="plugins/quiz")
```

## In‑process HTTP

```python
from fastapi import Request, Response
from core.inprocess_http import inprocess_get

@CORE_OPEN.get("/get_health")
async def get_health(request: Request):
    response = await inprocess_get(request, "/api/health")
    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "application/json"),
    )
```

## Основные эндпоинты

Открытые:
- `GET /api/health`
- `POST /api/auth/token`
- `POST /api/roles`
- `POST /api/users`

Закрытые (JWT):
- `GET /api/roles`
- `PATCH /api/roles/{name}/permissions`
- `GET /api/roles/{name}/permissions`
- `PATCH /api/users/{user_id}`
- `PATCH /api/users/{user_id}/role`
- все `/api/loader/*`

## Конфигурация окружения

Переменные читаются из окружения. Файл `.env` подхватывается автоматически через `python-dotenv`. Пример — `.env.example`.

- `ARANES_SECRET_KEY` — секретный ключ (длина 32+)
- `DATABASE_URL_ASYNC` — async URL (по умолчанию `sqlite+aiosqlite:///./app.db`)
- `SQLALCHEMY_ECHO` — логирование SQL (`true/false`)
- `ACCESS_TOKEN_EXPIRE_MINUTES` — срок жизни токена

## Тесты

```bash
pytest
```