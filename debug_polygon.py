# -*- coding: utf-8 -*-
"""调试脚本：输出文本框 2 的 polygon 点坐标，分析形状。"""
import os
import json
import numpy as np
from PIL import Image
from paddleocr import SealTextDetection

def main():
    seal_path = "output_seal/seal_0.png"
    print(f"加载印章图: {seal_path}")
    img = Image.open(seal_path)
    print(f"尺寸: {img.size}")

    # 印章文本检测
    model = SealTextDetection(model_name="PP-OCRv4_mobile_seal_det")
    output = model.predict(seal_path, batch_size=1,
                           limit_side_len=736, limit_type="min",
                           thresh=0.2, box_thresh=0.6, unclip_ratio=0.5)

    for res in output:
        res_data = res.json if hasattr(res, "json") else {}
        if isinstance(res_data, dict):
            inner = res_data.get("res", res_data)
            polys = inner.get("dt_polys", []) or []
        else:
            polys = []

        print(f"\n检测到 {len(polys)} 个文本框")
        for i, poly in enumerate(polys):
            poly_list = poly.tolist() if hasattr(poly, "tolist") else poly
            pts = np.array(poly_list)
            print(f"\n=== 文本框 {i}: {len(poly_list)} 点 ===")
            print(f"x 范围: {pts[:,0].min():.1f} ~ {pts[:,0].max():.1f} (w={pts[:,0].max()-pts[:,0].min():.1f})")
            print(f"y 范围: {pts[:,1].min():.1f} ~ {pts[:,1].max():.1f} (h={pts[:,1].max()-pts[:,1].min():.1f})")
            print(f"中心: ({pts[:,0].mean():.1f}, {pts[:,1].mean():.1f})")
            # 打印前 5 个点和后 5 个点
            print(f"前5点: {poly_list[:5]}")
            print(f"后5点: {poly_list[-5:]}")
            # 分析点序：按 x 排序看是否连续
            xs = pts[:, 0]
            order_x = np.argsort(xs)
            print(f"按x排序后y值变化: {pts[order_x[:5], 1]} ... {pts[order_x[-5:], 1]}")

if __name__ == "__main__":
    main()
