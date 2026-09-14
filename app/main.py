# -*- coding: utf-8 -*-
"""FastAPI 应用入口。"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import seal, health

app = FastAPI(
    title="印章识别服务",
    description="基于 PaddleOCR seal_recognition 产线的印章识别 API",
    version="1.0.0",
)

# CORS（开发环境允许所有来源，生产环境按需配置）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router)
app.include_router(seal.router)


@app.on_event("startup")
async def startup_event():
    """启动时预加载产线（避免首次请求超时）。"""
    # 支持通过环境变量跳过产线预加载，便于本地快速 smoke test
    # 设置 SEAL_SKIP_PRELOAD=1 将跳过加载重模型依赖（例如 PaddleX）
    if os.environ.get("SEAL_SKIP_PRELOAD", "0") in ("1", "true", "True"):
        print("[startup] 跳过产线预加载（SEAL_SKIP_PRELOAD=1）")
        return

    from app.core.pipeline import get_seal_pipeline
    get_seal_pipeline()


@app.get("/")
async def root():
    """根路径，返回 API 信息。"""
    return {
        "name": "印章识别服务",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "识别单张": "POST /seal/recognize",
            "批量识别": "POST /seal/recognize_batch",
            "可视化图": "GET /seal/vis/{vis_id}.png",
            "健康检查": "GET /health",
        },
    }
