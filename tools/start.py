"""Run the API and Vite frontend on Windows, macOS, or Linux."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def main() -> int:
    uv = shutil.which("uv")
    runner = shutil.which("bun") or shutil.which("npm")
    if not uv or not runner:
        print("Run `python tools/setup.py` first.", file=sys.stderr)
        return 1

    port = os.environ.get("IDS_PORT", "8766")
    frontend_port = os.environ.get("IDS_FRONTEND_PORT", "5199")
    api = subprocess.Popen(
        [uv, "run", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", port],
        cwd=ROOT,
    )
    frontend_command = [runner, "run", "dev", "--host", "127.0.0.1", "--port", frontend_port]
    frontend = subprocess.Popen(frontend_command, cwd=FRONTEND)
    children = (api, frontend)

    def stop(_signum: int, _frame: object) -> None:
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    print(f"API:      http://127.0.0.1:{port}")
    print(f"Frontend: http://127.0.0.1:{frontend_port}")
    try:
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
    finally:
        stop(signal.SIGTERM, None)
        for child in children:
            child.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
