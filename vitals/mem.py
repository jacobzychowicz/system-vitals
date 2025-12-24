from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import psutil


@dataclass
class MemoryInfo:
    used_bytes: Optional[int]
    total_bytes: Optional[int]


def get_memory_info() -> MemoryInfo:
    """Return memory usage; gracefully handle errors."""
    try:
        mem = psutil.virtual_memory()
        return MemoryInfo(used_bytes=mem.used, total_bytes=mem.total)
    except Exception:
        return MemoryInfo(used_bytes=None, total_bytes=None)
