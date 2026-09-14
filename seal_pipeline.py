# -*- coding: utf-8 -*-
"""
印章识别服务（产线模式 + PDF 支持）
====================================
基于 PaddleOCR 的 seal_recognition 产线，内置：
- 版面分析（定位印章区域）
- 印章文本检测（多点弯曲框）
- 弯曲矫正（AutoRectifier，相机标定 + 透视变换）
- 文本识别

支持输入：
- 图片（jpg/png/webp 等）
- PDF（逐页渲染后识别）

用法：
    python seal_pipeline.py                           # 默认配置 config.yaml
    python seal_pipeline.py --input data/seal.png     # 临时指定输入
    python seal_pipeline.py --input doc.pdf           # PDF 逐页识别
    python seal_pipeline.py --tier server             # 临时切到 server 档（高精度）

依赖：
    pip install paddlex[ocr]          # 产线 + 印章识别
    pip install pypdfium2             # PDF 渲染
"""
import os
import json
import argparse
from pathlib import Path

import yaml
from PIL import Image

# 产线
from paddlex import create_pipeline

# PDF 渲染（可选，处理 PDF 时才需要）
try:
    import pypdfium2 as pdfium
    HAS_PDF_SUPPORT = True
except ImportError:
    HAS_PDF_SUPPORT = False


def load_config(config_path, tier_override=None):
    """加载 YAML 配置，可命令行覆盖档位。"""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if tier_override:
        cfg["model_tier"] = tier_override
    return cfg


def load_input_as_images(input_path, pdf_dpi=150):
    """把输入（图片或 PDF）加载成 PIL Image 列表。
    - 图片：直接返回 [Image]
    - PDF：逐页渲染成 Image，dpi 控制清晰度（默认 150，印章建议 200+）
    """
    ext = Path(input_path).suffix.lower()

    if ext == ".pdf":
        if not HAS_PDF_SUPPORT:
            raise RuntimeError("处理 PDF 需要安装 pypdfium2：pip install pypdfium2")
        print(f"[PDF] 渲染 {input_path} (dpi={pdf_dpi})")
        pdf = pdfium.PdfDocument(input_path)
        images = []
        scale = pdf_dpi / 72  # PDF 默认 72 DPI
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            images.append(pil_image)
            print(f"  第 {i+1} 页: {pil_image.size}")
        return images, "pdf"
    else:
        # 图片
        img = Image.open(input_path)
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = bg
        else:
            img = img.convert("RGB")
        return [img], "image"


def clean_output_dir(out_dir):
    """运行前清理输出目录，避免新旧结果混杂。"""
    import glob
    patterns = [
        "_input_page_*.png",           # 临时输入图
        "*_layout_det_res.png",        # 版面分析可视化
        "*_seal_res_region*.png",      # 印章区域可视化
        "*_res.png",                   # 其他结果图
        "pipeline_res.json",           # 产线原始 JSON
        "pipeline_results.json",       # 产线结果 JSON
        "seal_results.json",           # 最终结果 JSON
        "layout_res.json",             # 版面分析 JSON
    ]
    removed = 0
    for pattern in patterns:
        for f in glob.glob(os.path.join(out_dir, pattern)):
            try:
                os.remove(f)
                removed += 1
            except Exception:
                pass
    if removed:
        print(f"[清理] 删除 {removed} 个旧文件")


def run_seal_pipeline(cfg, input_path):
    """跑 seal_recognition 产线，返回每页/每图的印章识别结果。"""
    out_dir = cfg["paths"]["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    # 运行前清理输出目录
    clean_output_dir(out_dir)

    # 加载输入
    pdf_cfg = cfg.get("pdf", {})
    pdf_dpi = pdf_cfg.get("render_dpi", 200)
    images, input_type = load_input_as_images(input_path, pdf_dpi=pdf_dpi)
    print(f"[输入] {input_path}, 类型={input_type}, 共 {len(images)} 页/张")

    # 创建产线
    print("\n[产线] 加载 seal_recognition ...")
    pipeline = create_pipeline("seal_recognition")

    # 产线参数（官方标准配置）
    seal_cfg = cfg.get("seal_detection", {})
    pipeline_params = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "seal_det_unclip_ratio": seal_cfg.get("seal_det_unclip_ratio", 0.5),
        "seal_det_box_thresh": seal_cfg.get("seal_det_box_thresh", 0.6),
        "seal_det_thresh": seal_cfg.get("seal_det_thresh", 0.2),
        "seal_det_limit_side_len": seal_cfg.get("seal_det_limit_side_len", 736),
        "seal_det_limit_type": seal_cfg.get("seal_det_limit_type", "min"),
        "seal_rec_score_thresh": seal_cfg.get("seal_rec_score_thresh", 0),
    }

    # 对每页/每张图跑产线
    all_results = []
    temp_paths = []

    for page_idx, img in enumerate(images):
        # 产线 predict 需要文件路径，先存临时图（用唯一前缀避免冲突）
        temp_path = os.path.join(out_dir, f"_input_page_{page_idx}.png")
        img.save(temp_path)
        temp_paths.append(temp_path)

        print(f"\n{'='*50}")
        print(f"[处理 第 {page_idx+1} 页/张] 尺寸: {img.size}")

        output = pipeline.predict(temp_path, **pipeline_params)

        for res in output:
            # 先解析结果，判断是否有印章
            res_data = res.json if hasattr(res, "json") else {}
            if isinstance(res_data, dict) and "res" in res_data:
                inner = res_data["res"]
            else:
                inner = res_data if isinstance(res_data, dict) else {}

            seal_res_list = inner.get("seal_res_list", [])
            layout_res = inner.get("layout_det_res", {})
            layout_seals = [b for b in layout_res.get("boxes", []) if b.get("label") == "seal"]

            print(f"  版面分析: 检测到 {len(layout_seals)} 个印章区域")
            print(f"  印章识别: {len(seal_res_list)} 个结果")

            # 只有检测到印章时才保存可视化
            if seal_res_list:
                try:
                    res.save_to_img(save_path=out_dir)
                except Exception:
                    pass

            for si, seal_res in enumerate(seal_res_list):
                rec_texts = seal_res.get("rec_texts", [])
                rec_scores = seal_res.get("rec_scores", [])

                seal_texts = []
                for i, text in enumerate(rec_texts):
                    score = rec_scores[i] if i < len(rec_scores) else 0
                    seal_texts.append({"text": text, "score": float(score)})

                content = " ".join(t["text"] for t in seal_texts if t["text"])
                print(f"  印章 {si}: {content!r}")

                bbox = layout_seals[si]["coordinate"] if si < len(layout_seals) else None
                all_results.append({
                    "page": page_idx + 1,
                    "seal_idx": si,
                    "bbox": bbox,
                    "texts": seal_texts,
                    "content": content,
                })

    # 清理临时文件
    for p in temp_paths:
        try:
            os.remove(p)
        except Exception:
            pass

    # 保存最终结果
    out_json = os.path.join(out_dir, "seal_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "input": input_path,
            "input_type": input_type,
            "total_pages": len(images),
            "total_seals": len(all_results),
            "seals": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[完成] 共识别 {len(all_results)} 个印章，结果保存到 {out_json}")


def main():
    parser = argparse.ArgumentParser(description="印章识别服务（产线模式 + PDF 支持）")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--input", default=None, help="输入文件（图片或 PDF），覆盖 config.yaml 里的 paths.image")
    parser.add_argument("--tier", default=None, choices=["mobile", "server"],
                        help="临时覆盖档位（mobile/server）")
    args = parser.parse_args()

    cfg = load_config(args.config, args.tier)
    input_path = args.input or cfg["paths"]["image"]
    run_seal_pipeline(cfg, input_path)


if __name__ == "__main__":
    main()
