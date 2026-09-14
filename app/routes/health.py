# -*- coding: utf-8 -*-
"""健康检查路由。"""
from fastapi import APIRouter

from app.models.schemas import HealthResponse

router = APIRouter(tags=["健康检查"])


@router.get("/health", response_model=HealthResponse)
async def health():
    """健康检查接口。"""
    return {"status": "ok", "pipeline_loaded": True, "version": "1.0.0"}
