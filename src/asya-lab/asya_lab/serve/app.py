"""asya serve: local FastAPI backend for @asya/ui."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from asya_lab.config.project import AsyaProject
from asya_lab.serve.routes import create_router


def create_app(project: AsyaProject) -> FastAPI:
    app = FastAPI(title="asya serve", version="0.1.0")

    api_router = create_router(project)
    app.include_router(api_router, prefix="/api")

    # Serve bundled @asya/ui SPA: prefer installed static/ (wheel), fall back to ui/dist/ (dev)
    static_dir = Path(__file__).parent.parent / "static"
    ui_dist = Path(__file__).parent.parent.parent / "ui" / "dist"
    spa_dir = static_dir if static_dir.is_dir() and any(static_dir.glob("*.js")) else ui_dist
    if spa_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(spa_dir), html=True), name="ui")

    return app
