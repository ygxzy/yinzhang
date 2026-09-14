# -*- coding: utf-8 -*-
"""产线单例管理：每个 worker 进程只加载一次产线实例。"""
import os
import yaml
from functools import lru_cache
from typing import Optional

# 延迟导入 paddlex（避免在模块加载时引入大型本地依赖，如 OpenCV）


@lru_cache(maxsize=1)
def get_seal_pipeline():
    """获取 seal_recognition 产线单例。
    
    PaddleOCR 产线底层 C++ 引擎不是线程安全的，必须进程级单例。
    uvicorn 多 worker 部署时，每个 worker 各加载一份。
    """
    # 延迟导入，只有在实际需要加载产线时才导入 paddlex
    from paddlex import create_pipeline

    device = os.environ.get("SEAL_DEVICE", "gpu").lower()
    print(f"[pipeline] 加载 seal_recognition 产线 (device={device}) ...")
    try:
        pipeline = create_pipeline("seal_recognition", device=device)
    except Exception as exc:
        if device == "gpu":
            print(f"[pipeline] GPU 初始化失败，回退到 CPU：{exc}")
            pipeline = create_pipeline("seal_recognition", device="cpu")
        else:
            raise
    print("[pipeline] 产线加载完成")
    return pipeline


def get_pipeline_params() -> dict:
    """从 config.yaml 读取产线参数。"""
    config_path = os.environ.get("SEAL_CONFIG_PATH", "config.yaml")
    if not os.path.exists(config_path):
        # 默认参数
        return {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "seal_det_unclip_ratio": 0.5,
            "seal_det_box_thresh": 0.6,
            "seal_det_thresh": 0.2,
            "seal_det_limit_side_len": 736,
            "seal_det_limit_type": "min",
            "seal_rec_score_thresh": 0,
        }

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    seal_cfg = cfg.get("seal_detection", {})
    return {
        "use_doc_orientation_classify": seal_cfg.get("use_doc_orientation_classify", False),
        "use_doc_unwarping": seal_cfg.get("use_doc_unwarping", False),
        "seal_det_unclip_ratio": seal_cfg.get("seal_det_unclip_ratio", 0.5),
        "seal_det_box_thresh": seal_cfg.get("seal_det_box_thresh", 0.6),
        "seal_det_thresh": seal_cfg.get("seal_det_thresh", 0.2),
        "seal_det_limit_side_len": seal_cfg.get("seal_det_limit_side_len", 736),
        "seal_det_limit_type": seal_cfg.get("seal_det_limit_type", "min"),
        "seal_rec_score_thresh": seal_cfg.get("seal_rec_score_thresh", 0),
    }
