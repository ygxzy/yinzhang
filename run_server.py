# -*- coding: utf-8 -*-
"""启动脚本：用 venv 的 python 直接启动 uvicorn，绕过 PowerShell 执行策略限制。"""
import os
import sys

# 把项目根目录加入 sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# 设置环境变量
os.environ.setdefault("SEAL_CONFIG_PATH", os.path.join(PROJECT_ROOT, "config.yaml"))
os.environ.setdefault("SEAL_DEVICE", "gpu")
os.environ.setdefault("PADDLE_PDX_CACHE_DIR", os.path.join(PROJECT_ROOT, "models"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # 关闭 reload，避免文件修改触发重启
        workers=1,
    )
