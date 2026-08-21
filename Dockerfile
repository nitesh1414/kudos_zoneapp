# ---------- frontend build ----------
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend ./
RUN npm run build

# ---------- application ----------
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY scripts ./scripts
COPY backend/.env .env
# Compiled React single-page app served by FastAPI
COPY --from=ui /backend/app/static ./backend/app/static
ENV PYTHONPATH=/app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
