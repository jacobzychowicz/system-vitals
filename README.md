# System Vitals

Windows-focused CLI that surfaces host, CPU, memory, disk, and GPU metrics.
The code is simple to serve as a foundation for learning
DevOps, observability, and infrastructure tooling.

## Current Features
- Hostname, OS version, and uptime
- CPU model, real-time usage, and (when available) temperature
- Memory usage
- Disk usage for the chosen drive (defaults to the system drive)
- GPU detection (any vendor) and NVIDIA metrics via `nvidia-smi` when present
- handling of missing or unsupported metrics

## Setup
1) Install Python 3.10+ on Windows 10/11.
2) Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage
Run the CLI:
```
python main.py
```

Optional flags:
- `--drive <LETTER>`: Drive letter for disk usage (e.g., `--drive D`).
- `--interval <seconds>`: Sampling window for CPU utilization (default 0.3s).

## Notes
- NVIDIA metrics are collected via `nvidia-smi` when available, otherwise GPU
  info falls back to model detection only.
- CPU temperature on Windows is often unavailable; the CLI will show
  `unavailable` when the OS does not expose it.