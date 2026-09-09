#!/usr/bin/env bash
# One-shot setup for a fresh machine (Linux / macOS).
# Idempotent: safe to re-run any time.
#
# What it does:
#   1. ensures uv (Python manager)          — auto-installs, user-level
#   2. ensures Node.js >= 20                — offers install (brew/nvm)
#   3. ensures ffmpeg                       — offers install (package manager)
#   4. installs backend Python deps         — uv sync
#   5. fetches & builds bgutil-pot-server   — into backend/data/tools/
#   6. installs frontend deps and builds    — frontend/dist
#
# Usage: ./setup.sh [--yes]
#   --yes   do not ask for confirmation when installing system packages
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
POT_DIR="$BACKEND_DIR/data/tools/bgutil-pot-server"

# must match the bgutil-ytdlp-pot-provider version in backend/pyproject.toml
POT_REPO="https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"
POT_VERSION="1.3.1"
NODE_MIN_MAJOR=20

ASSUME_YES=0
[ "${1:-}" = "--yes" ] && ASSUME_YES=1

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m ok \033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33mwarn\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31mfail\033[0m %s\n' "$*" >&2; exit 1; }

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  local answer
  read -r -p "$1 [y/N] " answer
  [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

node_major() {
  command -v node >/dev/null 2>&1 || { echo 0; return; }
  local v
  v="$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)"
  echo "${v:-0}"
}

cd "$REPO_ROOT"
info "Setting up yt-music-analyzer in $REPO_ROOT"

# ---------------------------------------------------------------------------
# 1. uv
# ---------------------------------------------------------------------------
if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version | cut -d' ' -f2)"
else
  info "uv not found — installing (user-level, no sudo)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv installation failed"
  ok "uv installed"
fi

# ---------------------------------------------------------------------------
# 2. Node.js >= 20
# ---------------------------------------------------------------------------
NODE_MAJOR="$(node_major)"
if [ "$NODE_MAJOR" -ge "$NODE_MIN_MAJOR" ]; then
  ok "Node.js $(node -v)"
else
  [ "$NODE_MAJOR" -gt 0 ] && warn "Node.js is $(node -v), but >= v$NODE_MIN_MAJOR is required"
  if command -v brew >/dev/null 2>&1; then
    confirm "Install Node.js via Homebrew?" && brew install node || warn "Skipping Node.js install"
  else
    info "Node.js >= $NODE_MIN_MAJOR is required (frontend build + POT token server)"
    if confirm "Install Node.js LTS via nvm (user-level, no sudo)?"; then
      curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash
      export NVM_DIR="$HOME/.nvm"
      # shellcheck disable=SC1091
      [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
      nvm install --lts
    else
      die "Node.js >= $NODE_MIN_MAJOR is required. Install it (https://nodejs.org, nvm, or your package manager) and re-run ./setup.sh"
    fi
  fi
  NODE_MAJOR="$(node_major)"
  [ "$NODE_MAJOR" -ge "$NODE_MIN_MAJOR" ] || die "Node.js >= $NODE_MIN_MAJOR still missing"
  ok "Node.js $(node -v)"
fi

# ---------------------------------------------------------------------------
# 3. ffmpeg
# ---------------------------------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f3)"
else
  warn "ffmpeg not found — required for audio analysis"
  installed_ffmpeg=0
  if command -v brew >/dev/null 2>&1; then
    if confirm "Install ffmpeg via Homebrew?"; then brew install ffmpeg && installed_ffmpeg=1; fi
  elif command -v apt-get >/dev/null 2>&1; then
    if confirm "Install ffmpeg via apt (needs sudo)?"; then (sudo apt-get update && sudo apt-get install -y ffmpeg) && installed_ffmpeg=1; fi
  elif command -v dnf >/dev/null 2>&1; then
    if confirm "Install ffmpeg via dnf (needs sudo)?"; then (sudo dnf install -y ffmpeg) && installed_ffmpeg=1; fi
  elif command -v pacman >/dev/null 2>&1; then
    if confirm "Install ffmpeg via pacman (needs sudo)?"; then (sudo pacman -S --noconfirm ffmpeg) && installed_ffmpeg=1; fi
  elif command -v zypper >/dev/null 2>&1; then
    if confirm "Install ffmpeg via zypper (needs sudo)?"; then (sudo zypper install -y ffmpeg) && installed_ffmpeg=1; fi
  fi
  if [ "$installed_ffmpeg" = 1 ]; then
    ok "ffmpeg installed"
  else
    warn "Continuing without ffmpeg — audio analysis will not work until it is installed"
  fi
fi

command -v git >/dev/null 2>&1 || die "git is required (needed to fetch bgutil-pot-server)"

# ---------------------------------------------------------------------------
# 4. backend Python environment
# ---------------------------------------------------------------------------
info "Installing backend Python dependencies (uv sync)"
(cd "$BACKEND_DIR" && uv sync)
(cd "$BACKEND_DIR" && uv run --no-sync python tools/ensure_essentia.py)
ok "Backend Python environment ready"

# ---------------------------------------------------------------------------
# 5. bgutil-pot-server (PO tokens for yt-dlp / YouTube downloads)
# ---------------------------------------------------------------------------
if [ -f "$POT_DIR/build/main.js" ]; then
  ok "bgutil-pot-server already built"
elif [ -f "$POT_DIR/package.json" ]; then
  info "bgutil-pot-server present but not built — building"
  (cd "$POT_DIR" && npm ci && npx tsc)
  [ -f "$POT_DIR/build/main.js" ] || die "POT server build failed (no build/main.js)"
  ok "bgutil-pot-server built"
else
  info "Fetching bgutil-pot-server v$POT_VERSION"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  git clone --depth 1 --branch "$POT_VERSION" --single-branch "$POT_REPO" "$TMP/repo" \
    || die "Failed to clone $POT_REPO"
  mkdir -p "$POT_DIR"
  cp -r "$TMP/repo/server/." "$POT_DIR/"
  (cd "$POT_DIR" && npm ci && npx tsc) || die "POT server build failed"
  rm -rf "$TMP"
  trap - EXIT
  [ -f "$POT_DIR/build/main.js" ] || die "POT server build produced no build/main.js"
  ok "bgutil-pot-server v$POT_VERSION built into backend/data/tools/"
fi

# ---------------------------------------------------------------------------
# 6. frontend build
# ---------------------------------------------------------------------------
info "Installing frontend dependencies (npm ci)"
(cd "$FRONTEND_DIR" && npm ci)
info "Building frontend (tsc + vite build)"
(cd "$FRONTEND_DIR" && npm run build)
[ -f "$FRONTEND_DIR/dist/index.html" ] || die "Frontend build failed (no dist/index.html)"
ok "Frontend built into frontend/dist"

# ---------------------------------------------------------------------------
# done
# ---------------------------------------------------------------------------
echo
ok "Setup complete. Next steps:"
echo "     1. Log into YouTube in Chrome (cookies are used for downloads)."
echo "        WSL: not reachable — put a manual cookies.txt into backend/data/"
echo "        and clear 'Browser for cookies' in Settings (see README)."
echo "     2. Start the app:            ./start.sh"
echo "     3. Open                      http://127.0.0.1:8000"
echo "     4. Go to the Import page and upload your Google Takeout"
echo "        watch history, then run the pipeline steps in order."
echo
echo "     For development instead:     ./dev.sh"
