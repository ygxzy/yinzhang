# -*- coding: utf-8 -*-
"""PDF 渲染服务：把 PDF 逐页渲染成 PIL Image。"""
import io
from typing import List
from PIL import Image

try:
    import pypdfium2 as pdfium
    HAS_PDF_SUPPORT = True
except ImportError:
    HAS_PDF_SUPPORT = False


def is_pdf(filename: str) -> bool:
    """判断文件名是否是 PDF。"""
    return filename.lower().endswith(".pdf")


def render_pdf_to_images(file_bytes: bytes, dpi: int = 200) -> List[Image.Image]:
    """把 PDF 字节流逐页渲染成 PIL Image 列表。
    
    Args:
        file_bytes: PDF 文件字节
        dpi: 渲染 DPI，印章建议 200+（默认 150 太小会漏字）
    
    Returns:
        PIL Image 列表（RGB 模式）
    
    Raises:
        RuntimeError: 未安装 pypdfium2
    """
    if not HAS_PDF_SUPPORT:
        raise RuntimeError("处理 PDF 需要安装 pypdfium2：pip install pypdfium2")
    
    pdf = pdfium.PdfDocument(io.BytesIO(file_bytes))
    images = []
    scale = dpi / 72  # PDF 默认 72 DPI
    
    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil().convert("RGB")
        images.append(pil_image)
    
    return images
