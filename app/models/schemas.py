# -*- coding: utf-8 -*-
"""Pydantic 请求/响应模型。"""
from typing import List, Optional, Any
from pydantic import BaseModel, Field


class SealText(BaseModel):
    """单个文本框识别结果。"""
    text: str = Field(..., description="文本内容")
    score: float = Field(..., description="置信度")


class SealInfo(BaseModel):
    """单个印章识别结果。"""
    page: int = Field(..., description="页码（从 1 开始）")
    seal_idx: int = Field(..., description="印章索引")
    bbox: Optional[List[Any]] = Field(None, description="印章整体 bbox")
    texts: List[SealText] = Field(default_factory=list, description="文本框列表")
    content: str = Field("", description="拼接后的印章全文")


class RecognizeResponse(BaseModel):
    """识别响应。"""
    code: int = Field(0, description="0=成功，非0=失败")
    message: str = Field("success", description="提示信息")
    data: dict = Field(default_factory=dict, description="识别结果")


class BatchRecognizeResponse(BaseModel):
    """批量识别响应。"""
    code: int = Field(0)
    message: str = Field("success")
    data: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """健康检查响应。"""
    status: str = Field("ok")
    pipeline_loaded: bool = Field(False)
    version: str = Field("1.0.0")
