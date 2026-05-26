# Single-container image for Hugging Face Spaces.
#
# Why single-container: HF Spaces accepts exactly one Dockerfile per Space.
# We solve this by building the React frontend in a Node stage, then copying
# the static output into the Python image. FastAPI detects the `dist/` folder
# at startup and serves it as static files, so the same port handles both
# the API (/chat, /health) and the SPA (/).
#
# Port: HF Spaces exposes 7860 by default.
#
# Local test before pushing:
#   docker build -t olist-chat-hf .
#   docker run -p 7860:7860 --env-file .env olist-chat-hf
#   open http://localhost:7860


# --- Stage 1: build the React frontend -------------------------------------
FROM node:20-alpine AS fe-builder

WORKDIR /frontend
COPY frontend/package*.json .
RUN npm ci
COPY frontend/ .

# Leaving VITE_BACKEND_URL empty makes useChat.ts call relative URLs
# (e.g. fetch("/chat/stream")) — same origin as the SPA, no CORS issues.
# This works because FastAPI serves both the SPA and the API on port 7860.
ARG VITE_BACKEND_URL=""
ENV VITE_BACKEND_URL=$VITE_BACKEND_URL
RUN npm run build


# --- Stage 2: Python backend + frontend static files -----------------------
FROM python:3.11-slim

WORKDIR /app

# Native build tools for Pandas / databricks-sql-connector wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer caches across code changes.
# The repo-root requirements.txt is the single source of truth; the dbt /
# ingestion deps come along too but stay unused at runtime (~30MB extra,
# acceptable for a portfolio Space).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend source code (FastAPI app, services, routers).
COPY backend/app ./app

# Frontend build output — main.py looks for /app/dist at startup and serves
# it as static files when found.
COPY --from=fe-builder /frontend/dist ./dist

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
