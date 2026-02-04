import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

CORE = {
    'name': 'AraNES',
    'year': 2026,
    'version': '0.0.3.0',
    'description': 'Arachne Core & Services'
}

SECRET_KEY = os.getenv(
    "ARANES_SECRET_KEY",
    "change-me-change-me-change-me-change-me",
)


PLUGINS_DIR = BASE_DIR / 'services'
if not PLUGINS_DIR.exists():
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
