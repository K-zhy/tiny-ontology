"""Ontology Demo 的 FastAPI 应用入口。

启动: python server.py
前端页面: http://localhost:8000
Swagger 文档: http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import demo
from demo.api import router as demo_router
from ontology_engine.database import init_db


def create_app() -> FastAPI:
    """创建并装配 FastAPI 应用。"""
    demo.load()

    app = FastAPI(title="Ontology Demo", description="学生成绩管理系统 — Ontology 语义层 Demo")
    app.include_router(demo_router)
    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    @app.get("/")
    def index():
        return FileResponse("static/index.html")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
