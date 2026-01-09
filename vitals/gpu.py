from __future__ import annotations

import subprocess
from dataclasses import dataclass
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
