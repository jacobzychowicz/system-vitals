from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class GpuInfo:
    model: str
    temperature_c: Optional[float]
    utilization_percent: Optional[float]
    memory_used_mb: Optional[float]
    memory_total_mb: Optional[float]


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
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


def _query_lhm_clr() -> Optional[GpuInfo]:
    """Use LibreHardwareMonitorLib via pythonnet to read GPU metrics."""
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
        computer.IsGpuEnabled = True
        computer.Open()
        for hw in computer.Hardware:
            hw.Update()
            if hw.HardwareType not in (
                Hardware.HardwareType.GpuNvidia,
                Hardware.HardwareType.GpuAmd,
                Hardware.HardwareType.GpuIntel,
            ):
                continue
            model = hw.Name or "unknown GPU"
            temp = None
            util = None
            mem_used = None
            mem_total = None
            for sensor in hw.Sensors:
                stype = sensor.SensorType
                name = (sensor.Name or "").lower()
                value = sensor.Value
                if value is None:
                    continue
                if stype == Hardware.SensorType.Temperature:
                    # Prefer hotspot/core, otherwise first temp.
                    if temp is None or any(tag in name for tag in ("hotspot", "core", "edge", "gpu")):
                        temp = float(value)
                elif stype == Hardware.SensorType.Load:
                    if util is None or "core" in name or "gpu" in name:
                        util = float(value)
                elif stype == Hardware.SensorType.Data:
                    if "memory used" in name or "dedicated memory used" in name:
                        mem_used = float(value)
                    if "memory total" in name or "dedicated memory total" in name:
                        mem_total = float(value)
            return GpuInfo(
                model=model,
                temperature_c=temp,
                utilization_percent=util,
                memory_used_mb=mem_used,
                memory_total_mb=mem_total,
            )
    except Exception:
        return None
    finally:
        try:
            if computer is not None:
                computer.Close()
        except Exception:
            pass
    return None


def _extract_lhm_json_gpu(node: dict) -> Optional[GpuInfo]:
    """Walk LHM JSON to find first GPU with temp/util/memory."""
    if not isinstance(node, dict):
        return None
    text = (node.get("Text") or "").lower()
    sensor_type = (node.get("SensorType") or "").lower()
    value = node.get("Value")
    children = node.get("Children") or []

    def to_float(val):
        if val is None:
            return None
        try:
            return float(str(val).split()[0])
        except Exception:
            return None

    # Identify a GPU parent node
    if "gpu" in text and "adapter" not in text:
        temp = None
        util = None
        mem_used = None
        mem_total = None
        model = node.get("Text") or "GPU"
        # Search children for sensors
        stack = [node]
        while stack:
            cur = stack.pop()
            if not isinstance(cur, dict):
                continue
            st = (cur.get("SensorType") or "").lower()
            nm = (cur.get("Text") or "").lower()
            val = cur.get("Value")
            if st == "temperature":
                if temp is None or any(tag in nm for tag in ("hotspot", "core", "edge", "gpu")):
                    cand = to_float(val)
                    if cand is not None:
                        temp = cand
            elif st == "load":
                if util is None or "core" in nm or "gpu" in nm:
                    cand = to_float(val)
                    if cand is not None:
                        util = cand
            elif st == "data":
                if "memory used" in nm or "dedicated memory used" in nm:
                    cand = to_float(val)
                    if cand is not None:
                        mem_used = cand
                if "memory total" in nm or "dedicated memory total" in nm:
                    cand = to_float(val)
                    if cand is not None:
                        mem_total = cand
            for child in cur.get("Children") or []:
                stack.append(child)
        return GpuInfo(
            model=model,
            temperature_c=temp,
            utilization_percent=util,
            memory_used_mb=mem_used,
            memory_total_mb=mem_total,
        )

    for child in children:
        found = _extract_lhm_json_gpu(child)
        if found:
            return found
    return None


def _query_lhm_http(url: str = "http://localhost:8085/data.json") -> Optional[GpuInfo]:
    """Try reading GPU metrics from a running LibreHardwareMonitor HTTP server."""
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
    return _extract_lhm_json_gpu(data)


def _query_nvidia_smi() -> List[GpuInfo]:
    """Return GPU metrics via nvidia-smi if available."""
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=5
        )
    except FileNotFoundError:
        return []
    except Exception:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    gpus: List[GpuInfo] = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        gpus.append(
            GpuInfo(
                model=parts[0],
                temperature_c=_safe_float(parts[1]),
                utilization_percent=_safe_float(parts[2]),
                memory_used_mb=_safe_float(parts[3]),
                memory_total_mb=_safe_float(parts[4]),
            )
        )
    return gpus


def _query_wmic_models() -> List[str]:
    """Fallback to WMIC for GPU model detection."""
    try:
        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0 or not result.stdout:
        return []
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.lower() != "name"]


def _query_powershell_models() -> List[str]:
    """Fallback to PowerShell for GPU model detection on newer Windows builds."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0 or not result.stdout:
        return []
    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]


def _query_powershell_utilization() -> Optional[float]:
    """Approximate GPU utilization via Windows performance counters."""
    ps_script = (
        "$c = Get-Counter '\\GPU Engine(*)\\Utilization Percentage' "
        "-ErrorAction SilentlyContinue; "
        "if (-not $c) { exit 1 }; "
        "$samples = $c.CounterSamples | "
        "Where-Object { $_.InstanceName -match 'engtype_3D' }; "
        "if (-not $samples) { $samples = $c.CounterSamples }; "
        "$vals = $samples | Select-Object -ExpandProperty CookedValue; "
        "if (-not $vals) { exit 1 }; "
        "[Math]::Round(($vals | Measure-Object -Average).Average, 2)"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return _safe_float(result.stdout.strip())


def get_gpu_info() -> Optional[GpuInfo]:
    """Return the first detected GPU with metrics where available."""
    nvidia_gpus = _query_nvidia_smi()
    if nvidia_gpus:
        return nvidia_gpus[0]

    # Try LibreHardwareMonitor via embedded CLR (auto-download) and HTTP.
    lhm_gpu = _query_lhm_clr()
    if lhm_gpu:
        return lhm_gpu
    lhm_http_gpu = _query_lhm_http()
    if lhm_http_gpu:
        return lhm_http_gpu

    # Fall back to model-only detection.
    models = _query_wmic_models()
    if not models:
        models = _query_powershell_models()

    utilization = _query_powershell_utilization()

    if models:
        return GpuInfo(
            model=models[0],
            temperature_c=None,
            utilization_percent=utilization,
            memory_used_mb=None,
            memory_total_mb=None,
        )
    return None
