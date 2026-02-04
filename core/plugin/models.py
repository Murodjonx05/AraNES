from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter


@dataclass
class PluginRecord:
    name: str
    path: Path
    module_name: str
    routers: List[APIRouter]
    enabled: bool
    error: Optional[str] = None
    module_mtime_ns: Optional[int] = None
