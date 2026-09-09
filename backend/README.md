# yt-music-analyzer — backend

FastAPI backend. For the full setup guide see the [root README](../README.md).

Quick dev start from this directory:

```bash
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Runtime data (DB, audio cache, models) lives in `data/`, config in `.env`
(see `.env.example`). Serves the built frontend from `../frontend/dist`
(override with `FRONTEND_DIST`).
