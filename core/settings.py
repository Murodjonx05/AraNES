import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CORE = {
    "name": "AraNES",
    "year": 2026,
    "version": "0.0.3.0",
    "description": "Arachne Core & Services",
}

# SECURITY: require a strong secret in production
ARANES_SECRET_KEY: str | None = os.getenv("ARANES_SECRET_KEY")
if not ARANES_SECRET_KEY:
    raise RuntimeError(
        "ARANES_SECRET_KEY is not set. Generate a secure random key (>=32 chars) "
        "and set it in the environment."
    )
if len(ARANES_SECRET_KEY) < 32:
    raise RuntimeError("ARANES_SECRET_KEY is too short: use at least 32 characters.")

SECRET_KEY = ARANES_SECRET_KEY

PLUGINS_DIR = BASE_DIR / "services"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)