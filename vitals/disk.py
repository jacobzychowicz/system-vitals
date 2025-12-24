from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import psutil


@dataclass
class DiskInfo:
    drive: str
    used_bytes: Optional[int]
    total_bytes: Optional[int]


def _normalize_drive(drive_letter: Optional[str]) -> str:
    drive = drive_letter or os.environ.get("SystemDrive", "C:")
    drive = drive.rstrip("\\/")
    if not drive.endswith(":"):
        drive = f"{drive}:"
    return drive


def get_disk_info(drive_letter: Optional[str] = None) -> Optional[DiskInfo]:
    """Return disk usage for the specified (or system) drive."""
    drive = _normalize_drive(drive_letter)
    path = f"{drive}\\"
    try:
        usage = psutil.disk_usage(path)
        return DiskInfo(drive=drive, used_bytes=usage.used, total_bytes=usage.total)
    except Exception:
        return None
