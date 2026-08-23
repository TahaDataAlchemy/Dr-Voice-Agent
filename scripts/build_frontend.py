"""Build the Next.js dashboard and copy the static export into ./static (served by FastAPI).

Usage:  uv run python scripts/build_frontend.py [--skip-install]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
STATIC = ROOT / "static"


def main() -> int:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    if "--skip-install" not in sys.argv and not (FRONTEND / "node_modules").exists():
        subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)
    out = FRONTEND / "out"
    if STATIC.exists():
        shutil.rmtree(STATIC)
    shutil.copytree(out, STATIC)
    print(f"copied {out} -> {STATIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
