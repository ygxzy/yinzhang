# -*- coding: utf-8 -*-
"""
调试 SealTextDetection 输出结构
=================================
单独跑一次印章检测，打印所有属性和输出结构，找到正确的文本框字段名。
"""
from paddleocr import SealTextDetection

model = SealTextDetection(model_name="PP-OCRv4_mobile_seal_det")
output = model.predict("./output_seal/seal_0.png", batch_size=1)

for i, res in enumerate(output):
    print(f"\n{'='*60}")
    print(f"[结果 {i}] 类型: {type(res).__name__}")
    print(f"[结果 {i}] 所有属性和方法:")
    for name in sorted(dir(res)):
        if name.startswith("_"):
            continue
        try:
            val = getattr(res, name)
            if callable(val):
                continue
            # 截断长输出
            val_str = str(val)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            print(f"  {name}: {val_str}")
        except Exception as e:
            print(f"  {name}: <error {e}>")

    # 重点看这几个常见字段名
    print(f"\n[重点字段检查]")
    for key in ["dt_polys", "polys", "boxes", "det_polys", "text_boxes",
                "polygons", "bboxes", "dt_scores", "scores"]:
        val = getattr(res, key, None)
        if val is not None:
            if isinstance(val, list):
                print(f"  {key}: list, len={len(val)}")
                if val:
                    print(f"    第一个元素类型: {type(val[0]).__name__}")
                    if isinstance(val[0], (list, tuple)) and val[0]:
                        print(f"    第一个元素: {val[0]}")
            else:
                print(f"  {key}: {type(val).__name__} = {str(val)[:200]}")

    # 尝试转 dict / json
    print(f"\n[尝试序列化]")
    for method in ["to_dict", "to_json", "json"]:
        if hasattr(res, method):
            try:
                val = getattr(res, method)()
                if callable(val):
                    val = val()
                val_str = str(val)
                print(f"  {method}(): {val_str[:500]}")
            except Exception as e:
                print(f"  {method}() 失败: {e}")
