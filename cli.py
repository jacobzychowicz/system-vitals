from __future__ import annotations

import argparse
from typing import Optional

from vitals.cpu import get_cpu_info
from vitals.disk import get_disk_info
from vitals.gpu import get_gpu_info
from vitals.hostsys import get_host_info
from vitals.mem import get_memory_info


def format_uptime(seconds: float) -> str:
    total = int(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "0m"


def format_gb(value: Optional[int]) -> str:
    if value is None:
        return "unavailable"
    return f"{value / (1024 ** 3):.1f} GB"


def format_mb(value: Optional[float]) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.0f} MB"


def format_percent(value: Optional[float]) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.1f}%"


def format_temperature(value: Optional[float]) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.0f} °C"


def render(args) -> None:
    host = get_host_info()
    cpu = get_cpu_info(interval=args.interval)
    memory = get_memory_info()
    disk = get_disk_info(drive_letter=args.drive)
    gpu = get_gpu_info()

    print(f"Host: {host.hostname}")
    print(f"OS: {host.os}")
    print(f"Uptime: {format_uptime(host.uptime_seconds)}\n")

    print("CPU:")
    print(f"  Model: {cpu.model}")
    print(f"  Usage: {format_percent(cpu.usage_percent)}")
    print(f"  Temp: {format_temperature(cpu.temperature_c)}\n")

    print("Memory:")
    print(f"  Used: {format_gb(memory.used_bytes)} / {format_gb(memory.total_bytes)}\n")

    if disk:
        print(f"Disk ({disk.drive}):")
        print(
            f"  Used: {format_gb(disk.used_bytes)} / {format_gb(disk.total_bytes)}\n"
        )
    else:
        print("Disk: unavailable\n")

    print("GPU:")
    if gpu:
        print(f"  Model: {gpu.model}")
        print(f"  Temp: {format_temperature(gpu.temperature_c)}")
        print(f"  Usage: {format_percent(gpu.utilization_percent)}")
        if gpu.memory_used_mb is not None and gpu.memory_total_mb is not None:
            print(
                f"  VRAM: {format_mb(gpu.memory_used_mb)} / {format_mb(gpu.memory_total_mb)}"
            )
        else:
            print("  VRAM: unavailable")
    else:
        print("  Model: unavailable")
    print()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Display system vitals (host, CPU, memory, disk, GPU)."
    )
    parser.add_argument(
        "--drive",
        help="Drive letter for disk usage (e.g. C or D). Defaults to the system drive.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.3,
        help="Sampling window in seconds for CPU utilization (default: 0.3).",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    render(args)
