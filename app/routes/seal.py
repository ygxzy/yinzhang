# -*- coding: utf-8 -*-
"""印章识别路由。"""
import os
import time
import shutil
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse

from app.services.seal_service import recognize_seal
from app.models.schemas import RecognizeResponse, BatchRecognizeResponse

router = APIRouter(prefix="/seal", tags=["印章识别"])


@router.post("/recognize", response_model=RecognizeResponse)
async def recognize(
    file: UploadFile = File(..., description="图片或 PDF 文件"),
    dpi: int = Query(200, ge=72, le=600, description="PDF 渲染 DPI"),
):
    """同步识别单张图片或 PDF 中的印章。
    
    - 支持 jpg/png/webp 图片
    - 支持 PDF（逐页渲染后识别）
    - 返回每个印章的 bbox + 文本 + 可视化图
    """
    start = time.time()
    file_bytes = await file.read()

    # 文件大小限制 10MB
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件大小超过 10MB 限制")

    try:
        result = recognize_seal(file_bytes, file.filename, dpi)
        elapsed_ms = int((time.time() - start) * 1000)
        return RecognizeResponse(
            code=0,
            message="success",
            data={
                "filename": file.filename,
                **result,
                "elapsed_ms": elapsed_ms,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"识别失败: {str(e)}")


@router.post("/recognize_batch", response_model=BatchRecognizeResponse)
async def recognize_batch(
    files: List[UploadFile] = File(..., description="多个图片或 PDF 文件"),
    dpi: int = Query(200, ge=72, le=600, description="PDF 渲染 DPI"),
):
    """批量识别多张图片/PDF。
    
    串行处理（产线内部已批处理，并行会内存爆炸）。
    """
    start = time.time()
    results = []

    for file in files:
        file_bytes = await file.read()
        if len(file_bytes) > 10 * 1024 * 1024:
            results.append({
                "filename": file.filename,
                "error": "文件大小超过 10MB 限制",
            })
            continue

        try:
            result = recognize_seal(file_bytes, file.filename, dpi)
            results.append({
                "filename": file.filename,
                **result,
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "error": str(e),
            })

    elapsed_ms = int((time.time() - start) * 1000)
    return BatchRecognizeResponse(
        code=0,
        message="success",
        data={
            "total_files": len(files),
            "results": results,
            "elapsed_ms": elapsed_ms,
        },
    )


@router.get("/vis/{vis_id}.png")
async def get_visualization(vis_id: str):
    """获取可视化图（红框标注印章位置）。"""
    import tempfile
    vis_path = os.path.join(tempfile.gettempdir(), f"seal_vis_{vis_id}.png")
    if not os.path.exists(vis_path):
        raise HTTPException(status_code=404, detail="可视化图不存在或已过期")
    return FileResponse(vis_path, media_type="image/png")
