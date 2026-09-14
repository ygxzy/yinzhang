# -*- coding: utf-8 -*-
"""
印章识别完整流程（配置驱动版）
=================================
完整流程：版面分析 → 提取 seal bbox → 裁剪 → 尺寸规范化 → 印章文本检测 → 文本识别

读取 config.yaml 配置，自动选择 mobile/server 档位的模型。
修改 config.yaml 即可切换档位，无需改代码。

用法：
    python seal_pipeline.py
    python seal_pipeline.py --config config.yaml
    python seal_pipeline.py --tier server  # 临时切到 server 档
"""
import os
import json
import math
import argparse
from pathlib import Path

import yaml
import numpy as np
from PIL import Image
from PIL import Image as PILImage

from paddleocr import LayoutDetection, SealTextDetection, TextRecognition

# 产线模式可选导入（paddlex）
try:
    from paddlex import create_pipeline
    HAS_PADDLEX_PIPELINE = True
except ImportError:
    HAS_PADDLEX_PIPELINE = False


def load_config(config_path, tier_override=None):
    """加载 YAML 配置，可命令行覆盖档位。"""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if tier_override:
        cfg["model_tier"] = tier_override
    # 把当前档位的模型配置提升到顶层方便访问
    tier = cfg["model_tier"]
    models = cfg["models"][tier]
    cfg["active_models"] = models
    return cfg


def build_layout_model(cfg):
    """构建版面检测模型。"""
    m = cfg["active_models"]
    device = cfg.get("device", "cpu")
    print(f"[模型] layout={m['layout']}, device={device}")
    try:
        model = LayoutDetection(model_name=m["layout"], device=device)
    except TypeError:
        model = LayoutDetection(model_name=m["layout"])
    return model


def build_seal_models(cfg):
    """构建印章检测 + 文本识别模型。
    注意：engine 参数在某些 paddleocr/paddlex 版本组合下不被 BasePredictor 接受，
    所以这里不传 engine，让它默认用 paddle_static。用 device 参数控制 CPU/GPU。
    """
    m = cfg["active_models"]
    engine = cfg["engine"]
    device = cfg.get("device", "cpu")
    print(f"[配置] 档位={cfg['model_tier']}, 引擎={engine}, device={device}")
    print(f"[模型] seal_det={m['seal_det']}, rec={m['rec']}")

    # 构建模型：传 device，不传 engine（避免版本兼容问题）
    try:
        seal_det = SealTextDetection(
            model_name=m["seal_det"],
            device=device,
        )
    except TypeError:
        seal_det = SealTextDetection(model_name=m["seal_det"])

    try:
        rec = TextRecognition(
            model_name=m["rec"],
            device=device,
        )
    except TypeError:
        rec = TextRecognition(model_name=m["rec"])

    return seal_det, rec


def run_layout_detection(layout_model, image_path, layout_cfg, out_dir):
    """跑版面检测，返回 seal 类别的 bbox 列表。
    如果检测不到 seal，返回整图作为 fallback。
    """
    print("\n[步骤1] 版面分析...")
    # LayoutDetection.predict() 模块级支持的参数有限，这里只传它确实支持的
    # 实测 paddlex 3.7 下 layout_score_thresh / layout_nms_thresh 都不被接受
    # 只传 layout_nms（如果配置了）
    params = {}
    if "layout_nms" in layout_cfg:
        params["layout_nms"] = layout_cfg["layout_nms"]

    output = layout_model.predict(image_path, batch_size=1, **params)

    seal_boxes = []
    all_boxes = []
    for res in output:
        # 保存版面分析可视化结果
        try:
            res.save_to_img(save_path=out_dir)
        except Exception:
            pass
        try:
            res.save_to_json(save_path=os.path.join(out_dir, "layout_res.json"))
        except Exception:
            pass

        # 解析结果，提取 seal 类别
        res_data = res.json if hasattr(res, "json") else {}
        if isinstance(res_data, dict):
            inner = res_data.get("res", res_data)
            boxes = inner.get("boxes", []) or []
        else:
            boxes = []

        for b in boxes:
            all_boxes.append(b)
            if b.get("label") == "seal":
                seal_boxes.append(b)

    print(f"  版面分析共检测到 {len(all_boxes)} 个区域")
    print(f"  其中 seal 类别: {len(seal_boxes)} 个")
    for i, s in enumerate(seal_boxes):
        print(f"    印章 {i}: bbox={s.get('coordinate')}, score={s.get('score', 0):.3f}")

    return seal_boxes


def crop_seal(img, bbox, expand):
    """按 bbox 裁剪印章区域，外扩 expand 像素。"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1 = max(0, x1 - expand)
    y1 = max(0, y1 - expand)
    x2 = min(img.width, x2 + expand)
    y2 = min(img.height, y2 + expand)
    return img.crop((x1, y1, x2, y2)), (x1, y1, x2, y2)


def normalize_seal_size(img, min_side=320, min_area=40000):
    """规范化印章图尺寸，确保 OCR 模型能识别。
    OCR 模型对文字高度敏感，通常需要文字至少 20px 高。
    印章图太小会漏检/识别为空，这里按两条规则放大：
    1. 短边 < min_side：等比放大到 min_side
    2. 总面积 < min_area（约 200x200）：等比放大到满足面积
    用 LANCZOS 重采样保持质量。
    """
    w, h = img.size
    short_side = min(w, h)
    area = w * h

    scale = 1.0
    # 规则1：短边不足
    if short_side < min_side:
        scale = max(scale, min_side / short_side)
    # 规则2：面积不足（约 200x200=40000）
    if area < min_area:
        scale = max(scale, (min_area / area) ** 0.5)

    if scale > 1.0:
        new_w = int(w * scale)
        new_h = int(h * scale)
        # 用 LANCZOS 重采样（高质量）
        img = img.resize((new_w, new_h), Image.LANCZOS)
        print(f"  [尺寸规范化] {w}x{h} → {new_w}x{new_h} (放大 {scale:.2f}x)")
    else:
        print(f"  [尺寸规范化] {w}x{h} 无需放大")
    return img


def rectify_curved_text(seal_img, polygon, sample_points=64):
    """把弯曲文本框拉直成水平矩形图。
    印章顶部文字沿圆弧排列，SealTextDetection 输出多点 polygon（弯曲边界）。
    TextRecognition 模型只能识别水平文字，所以需要先把弧形文字"拉直"。

    算法（x 分箱 strip unwrapping，稳健版）：
    1. 取 polygon 的 x 范围 [xmin, xmax]
    2. 在 x 范围内等距取 W 个 x 位置（W = 输出宽度，由 polygon 宽度决定）
    3. 对每个 x 位置，找 polygon 上所有 x 接近该位置的点，
       y 最小的是 upper[x]，y 最大的是 lower[x]
    4. 输出图宽 = W，高 = upper-lower 平均距离
    5. 对每列 x_i，从 upper[x_i] 到 lower[x_i] 采样 H 个像素

    这种方法对点序不敏感，适用于水平/弯曲文本框。

    参数：
        seal_img: PIL Image，印章图
        polygon: [[x1,y1], ..., [xn,yn]] 多点弯曲框
        sample_points: 采样列数（已弃用，保留兼容）
    返回：
        PIL Image，拉直后的文本图（水平排列）
    """
    pts = np.array(polygon, dtype=np.float32)
    n = len(pts)

    if n < 4:
        # 点太少，退回矩形裁剪
        xs = pts[:, 0]
        ys = pts[:, 1]
        bx1, by1 = int(max(0, xs.min())), int(max(0, ys.min()))
        bx2, by2 = int(min(seal_img.width, xs.max())), int(min(seal_img.height, ys.max()))
        return seal_img.crop((bx1, by1, bx2, by2))

    xs = pts[:, 0]
    ys = pts[:, 1]
    xmin, xmax = float(xs.min()), float(xs.max())
    ymin, ymax = float(ys.min()), float(ys.max())

    # 输出图尺寸：宽度 = polygon 的 x 跨度，高度 = polygon 的 y 跨度
    out_w = int(max(2, xmax - xmin))
    out_h = int(max(2, ymax - ymin))

    if out_w < 2 or out_h < 2:
        bx1, by1 = int(max(0, xmin)), int(max(0, ymin))
        bx2, by2 = int(min(seal_img.width, xmax)), int(min(seal_img.height, ymax))
        return seal_img.crop((bx1, by1, bx2, by2))

    # 对每列 x_i，找 polygon 上接近 x_i 的点
    # 用滑动窗口：对 x_i 附近的点取 y 极值
    # 窗口宽度：polygon x 范围的 5%
    window = max(2.0, (xmax - xmin) * 0.05)

    # 预计算：对每个点，它的 x 落在哪个 x_i 附近
    # x_i = xmin + i / (out_w - 1) * (xmax - xmin)
    x_cols = xmin + np.arange(out_w) / max(out_w - 1, 1) * (xmax - xmin)

    upper_y = np.full(out_w, np.nan, dtype=np.float32)
    lower_y = np.full(out_w, np.nan, dtype=np.float32)

    for i, x_target in enumerate(x_cols):
        # 找窗口内的点
        mask = np.abs(xs - x_target) <= window
        if mask.sum() == 0:
            # 找最近的点
            dists = np.abs(xs - x_target)
            nearest_idx = np.argmin(dists)
            upper_y[i] = ys[nearest_idx]
            lower_y[i] = ys[nearest_idx]
        else:
            ys_in_window = ys[mask]
            upper_y[i] = ys_in_window.min()
            lower_y[i] = ys_in_window.max()

    # 对 upper_y / lower_y 做线性插值，填补 NaN
    valid = ~np.isnan(upper_y)
    if valid.sum() >= 2:
        xs_valid = x_cols[valid]
        upper_y = np.interp(x_cols, xs_valid, upper_y[valid])
        lower_y = np.interp(x_cols, xs_valid, lower_y[valid])
    else:
        # 退回矩形裁剪
        bx1, by1 = int(max(0, xmin)), int(max(0, ymin))
        bx2, by2 = int(min(seal_img.width, xmax)), int(min(seal_img.height, ymax))
        return seal_img.crop((bx1, by1, bx2, by2))

    # 采样：对每列 i，从 (x_i, upper_y[i]) 到 (x_i, lower_y[i]) 采样 out_h 个像素
    arr = np.array(seal_img)
    out_arr = np.zeros((out_h, out_w, arr.shape[2]), dtype=arr.dtype)

    for i in range(out_w):
        x = x_cols[i]
        y_top = upper_y[i]
        y_bot = lower_y[i]
        for j in range(out_h):
            s = j / max(out_h - 1, 1)
            y = y_top * (1 - s) + y_bot * s
            x_int = int(max(0, min(arr.shape[1] - 1, round(x))))
            y_int = int(max(0, min(arr.shape[0] - 1, round(y))))
            out_arr[j, i] = arr[y_int, x_int]

    return PILImage.fromarray(out_arr)


def rectify_text_boxes(seal_img, text_boxes, out_dir, seal_idx, rectify_enabled=True):
    """对每个文本框做弯曲矫正，返回 (拉直后的图列表, 文本框裁剪图路径列表)。
    rectify_enabled=False 时退回简单矩形裁剪（兼容旧行为）。
    """
    text_imgs = []
    for bi, poly in enumerate(text_boxes):
        if rectify_enabled and len(poly) >= 4:
            # 弯曲矫正（多点 polygon）
            text_img = rectify_curved_text(seal_img, poly, sample_points=64)
            method = "弯曲矫正"
        else:
            # 简单矩形裁剪（兼容 4 点框或关闭矫正时）
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            bx1, by1 = int(max(0, min(xs))), int(max(0, min(ys)))
            bx2, by2 = int(min(seal_img.width, max(xs))), int(min(seal_img.height, max(ys)))
            if bx2 <= bx1 or by2 <= by1:
                continue
            text_img = seal_img.crop((bx1, by1, bx2, by2))
            method = "矩形裁剪"

        text_path = os.path.join(out_dir, f"seal_{seal_idx}_text_{bi}.png")
        text_img.save(text_path)
        text_imgs.append((text_path, text_img, method))
        print(f"    文本框 {bi}: {method}, 输出尺寸 {text_img.size}")
    return text_imgs


def run_pipeline_mode(cfg):
    """产线模式：直接用 seal_recognition 产线（官方弯曲矫正已处理好）。
    适合对比验证，或不需要精细控制中间步骤的场景。
    """
    if not HAS_PADDLEX_PIPELINE:
        print("[错误] 未安装 paddlex，无法用产线模式。请 pip install paddlex")
        return

    paths = cfg["paths"]
    out_dir = paths["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    print("\n[产线模式] 使用 seal_recognition 产线（含官方弯曲矫正）")
    pipeline = create_pipeline("seal_recognition")

    # 产线级参数（官方标准配置）
    output = pipeline.predict(
        paths["image"],
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        seal_det_unclip_ratio=0.5,
        seal_det_box_thresh=0.6,
        seal_det_thresh=0.2,
        seal_det_limit_side_len=736,
        seal_det_limit_type="min",
        seal_rec_score_thresh=0,
    )

    results = []
    for idx, res in enumerate(output):
        print(f"\n{'='*50}")
        print(f"[处理图 {idx}]")
        # 保存可视化
        try:
            res.save_to_img(save_path=out_dir)
        except Exception:
            pass
        try:
            res.save_to_json(save_path=os.path.join(out_dir, "pipeline_res.json"))
        except Exception:
            pass

        # 解析结果
        # 产线 res.json 结构：{'res': {'seal_res_list': [...], 'layout_det_res': {...}}}
        res_data = res.json if hasattr(res, "json") else {}
        # 数据嵌套在 'res' key 下
        if isinstance(res_data, dict) and "res" in res_data:
            inner = res_data["res"]
        else:
            inner = res_data if isinstance(res_data, dict) else {}

        seal_res_list = inner.get("seal_res_list", [])
        layout_res = inner.get("layout_det_res", {})
        layout_seals = [b for b in layout_res.get("boxes", []) if b.get("label") == "seal"]

        print(f"  版面分析检测到 {len(layout_seals)} 个印章区域")
        print(f"  印章识别结果: {len(seal_res_list)} 个")

        for si, seal_res in enumerate(seal_res_list):
            rec_texts = seal_res.get("rec_texts", [])
            rec_scores = seal_res.get("rec_scores", [])
            rec_polys = seal_res.get("rec_polys", [])

            seal_texts = []
            for i, text in enumerate(rec_texts):
                score = rec_scores[i] if i < len(rec_scores) else 0
                seal_texts.append({"text": text, "score": float(score)})

            content = " ".join(t["text"] for t in seal_texts if t["text"])
            print(f"  印章 {si}: {content!r}")

            # 取对应的版面 bbox
            bbox = layout_seals[si]["coordinate"] if si < len(layout_seals) else None
            results.append({
                "seal_idx": si,
                "bbox": bbox,
                "texts": seal_texts,
                "content": content,
            })

    out_json = os.path.join(out_dir, "pipeline_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[完成] 产线模式结果保存到 {out_json}")


def run_pipeline(cfg):
    paths = cfg["paths"]
    out_dir = paths["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    # 0. 加载原图（处理 RGBA 透明通道，OCR 模型需要 RGB）
    img = Image.open(paths["image"])
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    else:
        img = img.convert("RGB")
    print(f"[原图] {paths['image']}, 尺寸: {img.size}, 模式: {img.mode}")

    # 1. 版面分析
    layout_model = build_layout_model(cfg)
    layout_cfg = cfg.get("layout_detection", {})
    seal_boxes = run_layout_detection(layout_model, paths["image"], layout_cfg, out_dir)

    # 如果版面分析没检测到 seal，用整图作为 fallback
    if not seal_boxes:
        print("[警告] 版面分析未检测到 seal 类别，用整图作为印章区域")
        seal_boxes = [{"coordinate": [0, 0, img.width, img.height], "score": 1.0}]

    # 2. 构建印章检测 + 文本识别模型
    seal_det, rec = build_seal_models(cfg)

    # 3. 印章检测参数（模块级，非产线级）
    # SealTextDetection.predict() 只接受：
    #   limit_side_len, limit_type, thresh, box_thresh, unclip_ratio, max_side_limit
    det_kw = cfg["seal_detection"]
    seal_det_params = {
        "limit_side_len": det_kw["seal_det_limit_side_len"],
        "limit_type": det_kw["seal_det_limit_type"],
        "thresh": det_kw["seal_det_thresh"],
        "box_thresh": det_kw["seal_det_box_thresh"],
        "unclip_ratio": det_kw["seal_det_unclip_ratio"],
    }

    expand = cfg["crop"]["seal_expand"]
    size_cfg = cfg.get("size_normalization", {})

    results = []
    for idx, seal in enumerate(seal_boxes):
        print(f"\n{'='*50}")
        print(f"[处理印章 {idx}]")

        # 4. 裁剪
        seal_img, (x1, y1, x2, y2) = crop_seal(img, seal["coordinate"], expand)
        print(f"  裁剪区域: [{x1}, {y1}, {x2}, {y2}], 尺寸: {seal_img.size}")

        # 5. 尺寸规范化
        seal_img = normalize_seal_size(
            seal_img,
            min_side=size_cfg.get("min_side", 320),
            min_area=size_cfg.get("min_area", 40000),
        )

        # 保存规范化后的印章图
        seal_path = os.path.join(out_dir, f"seal_{idx}.png")
        seal_img.save(seal_path)

        # 6. 印章文本检测
        print("  [印章文本检测]")
        det_output = seal_det.predict(seal_path, batch_size=1, **seal_det_params)
        text_boxes = []
        for res in det_output:
            # TextDetResult 结构：res.json = {'res': {'dt_polys': [...]}}
            res_data = res.json if hasattr(res, "json") else {}
            if isinstance(res_data, dict):
                inner = res_data.get("res", res_data)
                polys = inner.get("dt_polys", []) or []
            else:
                polys = []
            for poly in polys:
                if hasattr(poly, "tolist"):
                    poly = poly.tolist()
                text_boxes.append(poly)
        print(f"    检测到 {len(text_boxes)} 个文本框")

        # 7. 弯曲矫正 + 文本识别
        print("  [弯曲矫正 + 文本识别]")
        rectify_cfg = cfg.get("rectification", {})
        rectify_enabled = rectify_cfg.get("enabled", True)
        sample_points = rectify_cfg.get("sample_points", 64)

        # 先打印每个文本框的点数和形状，便于判断
        for bi, poly in enumerate(text_boxes):
            pts_arr = np.array(poly)
            xs = pts_arr[:, 0]
            ys = pts_arr[:, 1]
            w = xs.max() - xs.min()
            h = ys.max() - ys.min()
            print(f"    文本框 {bi}: {len(poly)} 点, 范围 w={w:.1f} h={h:.1f}")

        seal_texts = []
        for bi, poly in enumerate(text_boxes):
            # 判断是否为弯曲框：点数 >= 6 且高度较大（弧形文字）
            # 4 点框是矩形/仿射框，直接矩形裁剪
            is_curved = len(poly) >= 6

            if rectify_enabled and is_curved:
                text_img = rectify_curved_text(seal_img, poly, sample_points=sample_points)
                method = "弯曲矫正"
            else:
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                bx1, by1 = int(max(0, min(xs))), int(max(0, min(ys)))
                bx2, by2 = int(min(seal_img.width, max(xs))), int(min(seal_img.height, max(ys)))
                if bx2 <= bx1 or by2 <= by1:
                    continue
                text_img = seal_img.crop((bx1, by1, bx2, by2))
                method = "矩形裁剪"

            text_path = os.path.join(out_dir, f"seal_{idx}_text_{bi}.png")
            text_img.save(text_path)
            print(f"    文本框 {bi}: {method} ({len(poly)}点), 输出尺寸 {text_img.size}")

            rec_output = rec.predict(text_path, batch_size=1)
            for r in rec_output:
                # TextRecResult 结构：r.json = {'res': {'rec_text': ..., 'rec_score': ...}}
                r_data = r.json if hasattr(r, "json") else {}
                if isinstance(r_data, dict):
                    inner = r_data.get("res", r_data)
                    text = inner.get("rec_text", "") or ""
                    score = inner.get("rec_score", 0) or 0
                else:
                    text = ""
                    score = 0
                seal_texts.append({"text": text, "score": float(score)})
                print(f"      → {text!r} (置信度 {score:.3f})")

        # 8. 聚合结果
        content = " ".join(t["text"] for t in seal_texts if t["text"])
        result = {
            "seal_idx": idx,
            "bbox": [x1, y1, x2, y2],
            "score": seal.get("score", 1.0),
            "texts": seal_texts,
            "content": content,
        }
        results.append(result)
        print(f"\n  [印章 {idx} 全文] {content!r}")

    # 保存最终结果
    out_json = os.path.join(out_dir, "seal_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[完成] 结果保存到 {out_json}")


def main():
    parser = argparse.ArgumentParser(description="印章识别完整流程")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--tier", default=None, choices=["mobile", "server"],
                        help="临时覆盖档位（mobile/server）")
    parser.add_argument("--mode", default="manual", choices=["manual", "pipeline"],
                        help="manual=手动串联（版面分析+裁剪+检测+识别），"
                             "pipeline=seal_recognition 产线（官方弯曲矫正）")
    args = parser.parse_args()

    cfg = load_config(args.config, args.tier)
    if args.mode == "pipeline":
        run_pipeline_mode(cfg)
    else:
        run_pipeline(cfg)


if __name__ == "__main__":
    main()
