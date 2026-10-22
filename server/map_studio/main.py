"""Single-origin editor/API runtime; database and artwork remain external."""
from pathlib import Path
import json
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import assets, auth, router
from .config import settings

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / settings.frontend_dir
app = FastAPI(title="Neighborhood Map Studio", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth.router)
app.include_router(router.router)
app.include_router(assets.router)
app.include_router(router.public_router)


@app.middleware("http")
async def response_policy(request: Request, call_next):
    started = time.monotonic()
    limit = assets.MAX_BODY if request.url.path.endswith("/assets") else 2 * 1024 * 1024
    if request.method in {"POST", "PUT", "PATCH"}:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > limit:
                return JSONResponse({"detail": "request_too_large"}, status_code=413)
            body.extend(chunk)
        request._body = bytes(body)
    response = await call_next(request)
    route = request.scope.get("route")
    if request.url.path.startswith("/api/") and route:
        logging.getLogger("uvicorn.error").info(json.dumps({
            "event": "studio_request", "route": getattr(route, "path", "unknown"),
            "method": request.method, "status": response.status_code,
            "durationMs": round((time.monotonic() - started) * 1000),
        }))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    if not request.url.path.startswith("/api/public/"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True, "service": "neighborhood-map-studio"}


@app.get("/api/runtime-info", include_in_schema=False)
async def runtime_info(request: Request):
    await auth.actor(request)
    return {"ready": not settings.missing()}


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/map-studio/", status_code=307)


# The login shell has no private content. Every data/asset route authenticates.
if DIST.is_dir():
    app.mount("/map-studio", StaticFiles(directory=DIST, html=True), name="editor")
else:
    @app.get("/map-studio/", include_in_schema=False)
    async def missing_frontend():
        return JSONResponse({"detail": "frontend_not_built"}, status_code=503)
