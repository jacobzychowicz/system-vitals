# System Vitals

CLI that surfaces host, CPU, memory, disk, and GPU metrics.

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
