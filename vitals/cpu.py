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


def _read_cpu_name_from_powershell() -> Optional[str]:
    """Try to read the CPU model via PowerShell CIM."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    name = result.stdout.strip()
    return name or None


def get_cpu_model() -> str:
    """Return a best-effort CPU model string."""
    # Prefer richer Windows sources first to avoid generic "AMD64 Family..." strings.
    model = _read_cpu_name_from_powershell()
    if not model:
        model = _read_cpu_name_from_wmic()
    if not model:
        model = platform.uname().processor or platform.processor()
    return model or "unknown"


def get_cpu_usage(interval: float = 0.3) -> Optional[float]:
    """Sample CPU utilization percentage over the given interval."""
    try:
        # psutil returns a percentage across all cores.
        return psutil.cpu_percent(interval=interval)
    except Exception:
        return None


def _kelvin_tenths_to_celsius(raw: str) -> Optional[float]:
    """Convert tenths of Kelvin (used by some Windows ACPI sensors) to °C."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    celsius = value / 10.0 - 273.15
    if celsius < -20 or celsius > 120:
        return None
    return celsius


def _normalize_temperature_value(raw: str) -> Optional[float]:
    """Handle both tenths-of-Kelvin and Celsius numeric readings."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # Tenths of Kelvin are usually > 2000.
    if value > 200:
        c = value / 10.0 - 273.15
    else:
        c = value
    if c < -20 or c > 120:
        return None
    return c


def _query_wmic_temperature() -> Optional[float]:
    """Try reading CPU temperature via WMIC ACPI thermal sensors."""
    try:
        result = subprocess.run(
            [
                "wmic",
                "/namespace:\\\\root\\wmi",
                "path",
                "MSAcpi_ThermalZoneTemperature",
                "get",
                "CurrentTemperature",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    for line in lines:
        if line.lower().startswith("currenttemperature"):
            continue
        temp = _kelvin_tenths_to_celsius(line)
        if temp is not None:
            return temp
    return None


def _query_powershell_temperature() -> Optional[float]:
    """Fallback to PowerShell ACPI thermal sensors."""
    ps_script = (
        "$vals = @();"
        "$tz = Get-CimInstance -Namespace root/wmi -Class MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue;"
        "if ($tz) { $vals += ($tz | Select-Object -Expand CurrentTemperature) };"
        "$perf = Get-CimInstance -Class Win32_PerfFormattedData_Counters_ThermalZoneInformation -ErrorAction SilentlyContinue;"
        "if ($perf) { $vals += ($perf | Select-Object -Expand Temperature) };"
        "$probe = Get-CimInstance -Class Win32_TemperatureProbe -ErrorAction SilentlyContinue;"
        "if ($probe) { $vals += ($probe | Select-Object -Expand CurrentReading) };"
        "$vals | Where-Object { $_ -ne $null }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    for line in lines:
        temp = _normalize_temperature_value(line)
        if temp is not None:
            return temp
    return None


def get_cpu_temperature() -> Optional[float]:
    """Fetch CPU temperature if available on the current platform."""
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    if not temps:
        temp = _query_wmic_temperature()
        if temp is not None:
            return temp
        return _query_powershell_temperature()
    # On Windows this is often empty; on other platforms look for the first sensor.
    for readings in temps.values():
        if not readings:
            continue
        # Take the first available reading.
        if hasattr(readings[0], "current"):
            return readings[0].current
    # Fall back to Windows ACPI sensors if psutil did not find anything.
    temp = _query_wmic_temperature()
    if temp is not None:
        return temp
    return _query_powershell_temperature()


def get_cpu_info(interval: float = 0.3) -> CpuInfo:
    """Aggregate CPU details."""
    return CpuInfo(
        model=get_cpu_model(),
        usage_percent=get_cpu_usage(interval=interval),
        temperature_c=get_cpu_temperature(),
    )
