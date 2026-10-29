# One image that serves both the API and the web app, for publishing (see README, "Publish on Render").
# Locally nothing needs Docker: backend and frontend run as described in the README.

# --- 1. build the web app -----------------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. the server --------------------------------------------------------------------------
FROM python:3.13-slim

# Where the server finds the reference data and the built web app (see app/config.py).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOBIMIX_DATA_DIR=/app/data \
    MOBIMIX_STATIC_DIR=/app/web

WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN pip install --no-cache-dir ./backend

COPY data data
COPY --from=web /build/frontend/dist web

RUN useradd --create-home --uid 10001 mobimix
USER mobimix

# Render tells the server which port to use in $PORT; 10000 is its default.
EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
