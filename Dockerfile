# Build the already-owned frontend once, then ship only its production output.
FROM node:22-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
COPY shared/ /src/shared/
RUN npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=3000
WORKDIR /opt/map-studio

# Keep this image independent from the BFF's Poetry/FastAPI dependency set.
RUN apt-get update && apt-get install -y --no-install-recommends libcairo2 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
COPY shared/ ./shared/
COPY --from=frontend-build /src/frontend/dist ./frontend/dist
COPY start.sh ./start.sh
RUN chmod 0555 ./start.sh
RUN useradd --system --uid 10001 --home /opt/map-studio studio
USER studio

EXPOSE 3000
ENTRYPOINT ["/opt/map-studio/start.sh"]
