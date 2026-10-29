"""Runtime configuration, read from environment variables (see `.env.example`)."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


def data_dir() -> Path:
    """Folder holding the editable reference data (YAML). Override with MOBIMIX_DATA_DIR."""
    return Path(os.environ.get("MOBIMIX_DATA_DIR", DEFAULT_DATA_DIR))


def static_dir() -> Path | None:
    """Folder with the built web app (frontend/dist). Set MOBIMIX_STATIC_DIR to have the server
    serve the web app too, from the same address as the API (how it runs when published); by
    default the server is the API alone and the web app comes from the Vite dev server. A path
    that is not a folder is a mistake, and the server does not start."""
    raw = os.environ.get("MOBIMIX_STATIC_DIR")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_dir():
        raise RuntimeError(f"MOBIMIX_STATIC_DIR={raw!r} is not a folder")
    return path


def cors_origins() -> list[str]:
    """Origins allowed to call the API from a browser (the Vite dev server by default)."""
    raw = os.environ.get("MOBIMIX_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
