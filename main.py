import importlib
import subprocess
import sys
from pathlib import Path


def ensure_dependencies() -> None:
    """Install requirements if missing (best effort, silent on failure)."""
    missing = []
    for mod in ("psutil", "clr"):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return
    req_file = Path(__file__).with_name("requirements.txt")
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
    try:
        subprocess.run(cmd, check=False, capture_output=True, timeout=120)
    except Exception:
        # Do not block app launch if install fails; downstream imports may still error.
        pass


def main() -> None:
    ensure_dependencies()
    from cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
