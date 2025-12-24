from __future__ import annotations

import platform
import socket
import time
from dataclasses import dataclass

import psutil


@dataclass
class HostInfo:
    hostname: str
    os: str
    uptime_seconds: float


def _format_os_string() -> str:
    """Return a readable OS string, tolerating missing fields."""
    try:
        uname = platform.uname()
        system = uname.system or "Unknown OS"
        release = uname.release or ""
        version = uname.version or ""
        return f"{system} {release} ({version})".strip()
    except Exception:
        return platform.platform()


def get_host_info() -> HostInfo:
    """Collect hostname, OS description, and uptime in seconds."""
    hostname = socket.gethostname()
    os_string = _format_os_string()
    try:
        uptime_seconds = time.time() - psutil.boot_time()
    except Exception:
        uptime_seconds = 0.0
    return HostInfo(hostname=hostname, os=os_string, uptime_seconds=uptime_seconds)
