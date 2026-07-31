# ── Frontend build stage ─────────────────────────────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend ./
# Vite is configured to output to ../app/webdist
RUN mkdir -p /app/webdist && npm run build

# ── Python runtime ───────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schema.sql .
COPY app ./app
# Bring in the built SPA from the frontend stage
COPY --from=frontend /app/webdist ./app/webdist

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
