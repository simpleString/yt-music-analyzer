"""Repairs the essentia vs essentia-tensorflow wheel collision.

Both wheels ship the same file paths (essentia/_essentia*.so,
essentia/standard.py, ...). On a fresh venv the install order is not
defined: if the plain essentia wheel lands last, TensorflowPredict*
algorithms disappear from essentia.standard. This script reinstalls
essentia-tensorflow so its files overwrite the plain wheel, then
re-checks in a fresh interpreter.

Usage: uv run --no-sync python tools/ensure_essentia.py  (exit 0 = ok)
"""

import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

CHECK = (
    "from essentia.standard import "
    "TensorflowPredict2D, TensorflowPredictTempoCNN"
)

REINSTALL = [
    "uv", "pip", "install",
    "--reinstall-package", "essentia-tensorflow",
    "essentia-tensorflow",
]
REINSTALL_PIP = [
    sys.executable, "-m", "pip", "install",
    "--force-reinstall", "--no-deps", "essentia-tensorflow",
]


def ok() -> bool:
    probe = subprocess.run(
        [sys.executable, "-c", CHECK], capture_output=True
    )
    return probe.returncode == 0


def repair() -> None:
    cmd = REINSTALL if shutil.which("uv") else REINSTALL_PIP
    subprocess.run(
        cmd, cwd=BACKEND_DIR, check=True, capture_output=True
    )


if __name__ == "__main__":
    if ok():
        sys.exit(0)
    print(
        "essentia-tensorflow is shadowed by the plain essentia wheel "
        "— reinstalling…",
        flush=True,
    )
    repair()
    if ok():
        print("essentia-tensorflow repaired")
        sys.exit(0)
    print(
        "repair failed; run manually:\n"
        "  cd backend && uv pip install --reinstall-package "
        "essentia-tensorflow essentia-tensorflow",
        file=sys.stderr,
    )
    sys.exit(1)
