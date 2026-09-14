# -*- coding: utf-8 -*-
"""印章识别服务：封装产线调用，支持图片和 PDF 输入。"""
import os
import io
import uuid
import tempfile
from typing import List, Dict, Any
from PIL import Image

from app.core.pipeline import get_seal_pipeline, get_pipeline_params
from app.services.pdf_service import is_pdf, render_pdf_to_images


def _load_input_as_images(file_bytes: bytes, filename: str, dpi: int = 200) -> List[Image.Image]:
    """把输入（图片或 PDF）加载成 PIL Image 列表。"""
    if is_pdf(filename):
        return render_pdf_to_images(file_bytes, dpi)
    
    img = Image.open(io.BytesIO(file_bytes))
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    else:
        img = img.convert("RGB")
    return [img]


def _parse_pipeline_result(res) -> List[Dict[str, Any]]:
    """解析产线单页结果，返回印章列表。"""
    res_data = res.json if hasattr(res, "json") else {}
    if isinstance(res_data, dict) and "res" in res_data:
        inner = res_data["res"]
    else:
        inner = res_data if isinstance(res_data, dict) else {}

    seal_res_list = inner.get("seal_res_list", [])
    layout_res = inner.get("layout_det_res", {})
    layout_seals = [b for b in layout_res.get("boxes", []) if b.get("label") == "seal"]

    seals = []
    for si, seal_res in enumerate(seal_res_list):
        rec_texts = seal_res.get("rec_texts", [])
        rec_scores = seal_res.get("rec_scores", [])

        seal_texts = []
        for i, text in enumerate(rec_texts):
            score = rec_scores[i] if i < len(rec_scores) else 0
            seal_texts.append({"text": text, "score": float(score)})

        content = " ".join(t["text"] for t in seal_texts if t["text"])
        bbox = layout_seals[si]["coordinate"] if si < len(layout_seals) else None

        seals.append({
            "seal_idx": si,
            "bbox": bbox,
            "texts": seal_texts,
            "content": content,
        })

    return seals


def recognize_seal(file_bytes: bytes, filename: str, dpi: int = 200) -> Dict[str, Any]:
    """识别印章，返回结构化结果。
    
    Args:
        file_bytes: 文件字节（图片或 PDF）
        filename: 文件名（用于判断类型）
        dpi: PDF 渲染 DPI
    
    Returns:
        {
            "input_type": "image" | "pdf",
            "total_pages": 1,
            "total_seals": 1,
            "seals": [...]
        }
    """
    pipeline = get_seal_pipeline()
    pipeline_params = get_pipeline_params()

    images = _load_input_as_images(file_bytes, filename, dpi)
    input_type = "pdf" if is_pdf(filename) else "image"

    all_seals = []
    vis_paths = []

    for page_idx, img in enumerate(images):
        # 产线 predict 需要文件路径，存临时文件
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
            img.save(temp_path)

        try:
            output = pipeline.predict(temp_path, **pipeline_params)

            for res in output:
                # 保存可视化图
                vis_id = str(uuid.uuid4())[:8]
                vis_path = os.path.join(tempfile.gettempdir(), f"seal_vis_{vis_id}.png")
                try:
                    res.save_to_img(save_path=vis_path)
                    vis_paths.append(vis_path)
                except Exception:
                    pass

                # 解析结果
                seals = _parse_pipeline_result(res)
                for s in seals:
                    s["page"] = page_idx + 1
                    all_seals.append(s)
        finally:
            # 清理临时输入文件
            try:
                os.remove(temp_path)
            except Exception:
                pass

    return {
        "input_type": input_type,
        "total_pages": len(images),
        "total_seals": len(all_seals),
        "seals": all_seals,
        "vis_paths": vis_paths,
    }
