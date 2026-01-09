from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
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


def _extract_temp_value(raw: str) -> Optional[float]:
    """Parse a temperature string like '45.0 °C' or '45' into a float."""
    if raw is None:
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)", str(raw))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if value < -20 or value > 120:
        return None
    return value


def _extract_lhm_temp(node: dict) -> Optional[float]:
    """Recursively search LibreHardwareMonitor JSON for a CPU package/core temp."""
    if not isinstance(node, dict):
        return None
    text = (node.get("Text") or "").lower()
    value = node.get("Value")
    sensor_type = (node.get("SensorType") or "").lower()
    # Prefer explicit temperature sensors
    if sensor_type == "temperature":
        if any(key in text for key in ("cpu", "package", "tdie", "ccd", "tctl")):
            temp = _extract_temp_value(value or text)
            if temp is not None:
                return temp
    else:
        # Fallback: label matches CPU and value has a temp-like number.
        if "cpu" in text or "package" in text:
            temp = _extract_temp_value(value or text)
            if temp is not None:
                return temp
    children = node.get("Children") or []
    for child in children:
        temp = _extract_lhm_temp(child)
        if temp is not None:
            return temp
    return None


def _ensure_lhm_lib() -> Optional[Path]:
    """Download and extract LibreHardwareMonitor portable build; return DLL path."""
    cache_dir = Path.home() / ".system-vitals" / "lhm"
    dll_path = cache_dir / "LibreHardwareMonitorLib.dll"
    if dll_path.exists():
        return dll_path
    url = (
        "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/"
        "releases/latest/download/LibreHardwareMonitor.zip"
    )
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = cache_dir / "LibreHardwareMonitor.zip"
        with urllib.request.urlopen(url, timeout=8) as resp, open(
            zip_path, "wb"
        ) as fh:
            fh.write(resp.read())
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(cache_dir)
        if dll_path.exists():
            return dll_path
    except Exception:
        return None
    return None


def _ensure_pythonnet() -> bool:
    """Ensure pythonnet is importable; attempt a quick pip install if missing."""
    try:
        import clr  # type: ignore
        return True
    except Exception:
        pass
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pythonnet>=3.0"],
            capture_output=True,
            check=False,
            timeout=12,
        )
    except Exception:
        return False
    try:
        import clr  # type: ignore
        return True
    except Exception:
        return False


def _query_lhm_clr() -> Optional[float]:
    """
    Try reading CPU temp by loading LibreHardwareMonitorLib via pythonnet.
    This downloads the portable build if the DLL is not cached.
    """
    if not _ensure_pythonnet():
        return None
    import clr  # type: ignore

    dll_path = _ensure_lhm_lib()
    if not dll_path:
        return None

    try:
        clr.AddReference(str(dll_path))
        from LibreHardwareMonitor import Hardware  # type: ignore
    except Exception:
        return None

    computer = None
    try:
        computer = Hardware.Computer()
        computer.IsCpuEnabled = True
        computer.Open()
        temp: Optional[float] = None
        for hw in computer.Hardware:
            hw.Update()
            if hw.HardwareType != Hardware.HardwareType.Cpu:
                continue
            package_temp = None
            first_temp = None
            for sensor in hw.Sensors:
                if sensor.SensorType != Hardware.SensorType.Temperature:
                    continue
                value = sensor.Value
                if value is None:
                    continue
                if first_temp is None:
                    first_temp = float(value)
                if "package" in (sensor.Name or "").lower():
                    package_temp = float(value)
                    break
            if package_temp is not None:
                temp = package_temp
            elif first_temp is not None:
                temp = first_temp
            if temp is not None:
                break
        if temp is None:
            return None
        if temp < -20 or temp > 120:
            return None
        return temp
    except Exception:
        return None
    finally:
        try:
            if computer is not None:
                computer.Close()
        except Exception:
            pass


def _query_lhm_http(url: str = "http://localhost:8085/data.json") -> Optional[float]:
    """Try reading temperature from a running LibreHardwareMonitor HTTP server."""
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            content = resp.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None
    except Exception:
        return None
    try:
        data = json.loads(content.decode("utf-8", errors="ignore"))
    except Exception:
        return None
    return _extract_lhm_temp(data)


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
        # Try embedded LibreHardwareMonitor via pythonnet (auto-download), then HTTP endpoint, then Windows WMI fallbacks.
        temp = _query_lhm_clr()
        if temp is not None:
            return temp
        temp = _query_lhm_http()
        if temp is not None:
            return temp
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
    temp = _query_lhm_clr()
    if temp is not None:
        return temp
    temp = _query_lhm_http()
    if temp is not None:
        return temp
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
