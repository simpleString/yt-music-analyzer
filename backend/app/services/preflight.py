"""Startup sanity checks for external tools the audio pipeline needs.

The app degrades gracefully without them (jobs report errors), but a
fresh machine gives a much better first-run experience when the missing
pieces are called out loudly in the server log at boot.
"""

import logging
import shutil
import sys

from app.config import settings

log = logging.getLogger("preflight")

POT_SERVER_JS = (
    settings.data_dir / "tools" / "bgutil-pot-server" / "build" / "main.js"
)


def run_preflight() -> list[str]:
    problems: list[str] = []

    if shutil.which("ffmpeg") is None:
        problems.append(
            "ffmpeg not found on PATH — audio analysis and whisper clips "
            "will fail. Install it (apt/dnf/pacman install ffmpeg, "
            "brew install ffmpeg, winget install Gyan.FFmpeg)."
        )

    if shutil.which("node") is None:
        problems.append(
            "Node.js not found on PATH — the bgutil POT token server "
            "cannot start, YouTube downloads may hit bot checks. "
            "Install Node.js >= 20 (https://nodejs.org or nvm)."
        )

    if not POT_SERVER_JS.exists():
        problems.append(
            "bgutil-pot-server not found at data/tools/bgutil-pot-server — "
            "run ./setup.sh to fetch and build it (on Windows use WSL), "
            "or see README.md."
        )

    try:
        import essentia  # noqa: F401
    except ImportError:
        problems.append(
            "essentia is not installed (no upstream wheels for this "
            "platform, e.g. Windows) — audio analysis will be "
            "unavailable; every other feature works."
        )

    for p in problems:
        log.warning(p)

    if problems:
        print(
            f"preflight: {len(problems)} setup issue(s) detected "
            "(see warnings above)",
            file=sys.stderr,
        )
    return problems
