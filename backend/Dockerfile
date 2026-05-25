# =============================================================================
# SQL Agent — backend Dockerfile
# =============================================================================
# Strategy: single-stage image because the backend is pure Python.
# Why python:3.11-slim: smaller than the full image, still has enough to
# compile DuckDB and Pandas native extensions.

FROM python:3.11-slim

WORKDIR /app

# System dependencies needed to build DuckDB and Pandas wheels.
# --no-install-recommends keeps the image small.
# rm -rf cleans the apt cache so it does not bloat the layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies BEFORE copying the source code.
# Why: Docker caches each layer. If only the code changes, pip install will
# not run again — much faster rebuilds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and the Chinook dataset.
COPY app ./app
COPY data ./data

EXPOSE 8000

# --host 0.0.0.0 is required inside Docker to accept external connections.
# Without it, the server only listens on the container's loopback interface.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
