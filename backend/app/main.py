"""
FastAPI application entry point.

Defines the app instance, configures CORS middleware, registers routers,
and exposes the /health endpoint used by Docker Compose to know when the
service is ready.

Why FastAPI: native async support (required for SSE streaming), automatic
Pydantic validation, and OpenAPI docs generated for free.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import chat

# --- App initialization ---

app = FastAPI(
    title="SQL Agent",
    description="Natural language to SQL agent over the Chinook music dataset.",
    version="1.0.0",
)

# --- CORS middleware ---
# Allows the React frontend (localhost:5173) to call the API.
# Why list origins explicitly: wildcard "*" blocks cookies and auth headers —
# good practice even without auth today, in case we add it later.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
# Each router groups related endpoints in its own file.
# The "/chat" prefix means routes become /chat and /chat/stream.
app.include_router(chat.router, prefix="/chat", tags=["chat"])


# --- Health check ---

@app.get("/health", tags=["infra"])
def health() -> dict:
    """
    Liveness probe used by the Docker Compose healthcheck.

    Why this matters: docker-compose.yml waits for /health to return 200
    before starting the frontend. This prevents 'backend unavailable' errors
    during the startup window.
    """
    return {"status": "ok", "model": settings.claude_model}


# --- Single-container SPA serving (Hugging Face Spaces) --------------------
# When deployed via the root Dockerfile, the React build lives at /app/dist.
# We mount its asset folder and add a catch-all route that returns index.html,
# so the same uvicorn process serves both the API (/chat, /health) and the
# React SPA from a single port (7860 on HF, 8000 locally).
#
# In local dev (docker-compose), dist/ does not exist — Vite's own dev
# server handles the frontend, and this block is silently skipped.
_DIST = Path(__file__).parent.parent / "dist"
if _DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_DIST / "assets")),
        name="static-assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        """
        Catch-all route: returns index.html so the browser can hydrate React.

        Why `full_path` and not `_`: FastAPI treats underscore-prefixed params
        as required query params, not path params. The variable name in the
        decorator and the function signature must match.
        """
        return FileResponse(str(_DIST / "index.html"))
