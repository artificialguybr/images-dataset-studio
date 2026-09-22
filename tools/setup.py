"""Install the backend and frontend with the tools available on the host OS."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def run(command: list[str], cwd: Path = ROOT) -> None:
    print("$", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    uv = shutil.which("uv")
    if not uv:
        print("uv is required: https://docs.astral.sh/uv/getting-started/installation/", file=sys.stderr)
        return 1
    bun = shutil.which("bun")
    npm = shutil.which("npm")
    if not bun and not npm:
        print("Node.js/npm or Bun is required: https://nodejs.org/", file=sys.stderr)
        return 1

    run([uv, "sync"])
    run([bun or npm, "install"], FRONTEND)
    print("\nReady. Start the app with: python tools/start.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
