from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from typing import Optional

import psutil


@dataclass
class CpuInfo:
    model: str
    usage_percent: Optional[float]
    temperature_c: Optional[float]


def _read_cpu_name_from_wmic() -> Optional[str]:
    """Try to read the CPU model via WMIC (Windows)."""
    try:
        result = subprocess.run(
            ["wmic", "cpu", "get", "Name"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    for line in lines:
        if line.lower() == "name":
            continue
        return line
    return None


def get_cpu_model() -> str:
    """Return a best-effort CPU model string."""
    model = platform.processor() or platform.uname().processor
    if not model:
        model = _read_cpu_name_from_wmic()
    return model or "unknown"


def get_cpu_usage(interval: float = 0.3) -> Optional[float]:
    """Sample CPU utilization percentage over the given interval."""
    try:
        # psutil returns a percentage across all cores.
        return psutil.cpu_percent(interval=interval)
    except Exception:
        return None


def get_cpu_temperature() -> Optional[float]:
    """Fetch CPU temperature if available on the current platform."""
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    if not temps:
        return None
    # On Windows this is often empty; on other platforms look for the first sensor.
    for readings in temps.values():
        if not readings:
            continue
        # Take the first available reading.
        if hasattr(readings[0], "current"):
            return readings[0].current
    return None


def get_cpu_info(interval: float = 0.3) -> CpuInfo:
    """Aggregate CPU details."""
    return CpuInfo(
        model=get_cpu_model(),
        usage_percent=get_cpu_usage(interval=interval),
        temperature_c=get_cpu_temperature(),
    )
