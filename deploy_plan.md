# 印章识别服务部署方案

## 一、目标

把 [seal_pipeline.py](file:///d:/tongxignzheng/yinzhang/seal_pipeline.py) 的印章识别能力封装为 HTTP API，支持：
- 单张/多张图片上传
- PDF 文件上传（逐页识别）
- 多客户端并发调用
- 返回印章位置 + 内容 + 可视化图

---

## 二、技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| Web 框架 | **FastAPI** | 异步原生、自动生成 OpenAPI 文档、生态成熟 |
| ASGI 服务器 | **uvicorn** | FastAPI 标配，单进程异步 |
| 多进程 | **gunicorn / uvicorn-workers** | 生产环境多 worker 进程并行 |
| 模型加载 | **进程级单例** | 每个 worker 加载一次产线，常驻内存 |
| 任务队列（可选） | **Celery + Redis** | 高并发下异步排队，避免请求超时 |

---

## 三、并发模型分析

### 3.1 PaddleOCR 产线的线程安全性

`seal_recognition` 产线基于 PaddlePaddle 静态图推理，**底层 C++ 引擎不是线程安全的**。多线程并发调用同一个产线实例会导致：
- 段错误（C++ 层竞争）
- 结果错乱（共享内存被覆盖）

**结论：单进程内不能多线程并发调用产线。**

### 3.2 支持并发的两种方案

#### 方案 A：多进程（推荐，简单）

```
客户端
   │
   ▼
┌─────────────────────────────────────┐
│  Nginx / 负载均衡（可选）          │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│  uvicorn (ASGI)                      │
│  ├─ worker 1 (独立进程，加载产线1)  │
│  ├─ worker 2 (独立进程，加载产线2)  │
│  ├─ worker 3 (独立进程，加载产线3)  │
│  └─ worker 4 (独立进程，加载产线4)  │
└─────────────────────────────────────┘
```

- 每个 worker 是独立进程，有自己的产线实例（内存隔离，无竞争）
- uvicorn 用 `--workers 4` 启动 4 个进程
- 并发度 = worker 数量
- **优点**：简单、稳定、易调试
- **缺点**：每个进程加载一份模型，内存占用高（约 2GB/worker）

#### 方案 B：任务队列（高并发场景）

```
客户端
   │
   ▼
┌─────────────────────────────────────┐
│  FastAPI (单进程，只接收请求)       │
│  └─ 提交任务到队列，立即返回 task_id │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│  Redis 队列                          │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│  Celery worker 池（多进程）          │
│  ├─ worker 1 (加载产线)             │
│  ├─ worker 2 (加载产线)             │
│  └─ ...                             │
└─────────────────────────────────────┘
   │
   ▼
客户端轮询 /task/{task_id} 获取结果
```

- 请求秒级响应（只入队），识别异步执行
- 客户端轮询结果
- **优点**：高并发不超时、可扩展 worker 数
- **缺点**：架构复杂，需要 Redis

### 3.3 推荐选择

| 场景 | 并发量 | 推荐方案 |
|------|--------|---------|
| 内部工具、低并发 | < 5 QPS | 方案 A（uvicorn 2 workers） |
| 部门级服务 | 5-20 QPS | 方案 A（uvicorn 4 workers） |
| 全公司/对外服务 | > 20 QPS | 方案 B（Celery + Redis） |

**当前阶段建议方案 A**，后续按需升级到方案 B。

---

## 四、API 设计

### 4.1 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/seal/recognize` | 上传图片/PDF，同步返回结果 |
| POST | `/seal/recognize_batch` | 批量上传多张图片 |
| POST | `/seal/recognize_async` | 异步识别（高并发场景） |
| GET | `/seal/task/{task_id}` | 查询异步任务结果 |
| GET | `/seal/vis/{task_id}.png` | 获取可视化图 |
| GET | `/health` | 健康检查 |

### 4.2 同步接口 `/seal/recognize`

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | 图片（jpg/png/webp）或 PDF |
| dpi | int | 否 | PDF 渲染 DPI，默认 200 |

**响应**：`application/json`

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "input_type": "image",
    "total_pages": 1,
    "total_seals": 1,
    "seals": [
      {
        "page": 1,
        "seal_idx": 0,
        "bbox": [39.47, 14.57, 507.73, 490.27],
        "texts": [
          {"text": "榆林市农业农村局", "score": 0.9997},
          {"text": "行政执法专用章", "score": 0.9996},
          {"text": "6108025193607", "score": 0.9985}
        ],
        "content": "榆林市农业农村局 行政执法专用章 6108025193607"
      }
    ],
    "vis_url": "/seal/vis/abc123.png"
  },
  "elapsed_ms": 1234
}
```

### 4.3 批量接口 `/seal/recognize_batch`

**请求**：`multipart/form-data`，`files` 字段传多个文件

```python
files: List[UploadFile] = File(...)
```

**响应**：数组，每个元素结构同同步接口

```json
{
  "code": 0,
  "data": {
    "results": [
      {"filename": "seal1.png", "seals": [...]},
      {"filename": "seal2.png", "seals": [...]}
    ]
  }
}
```

### 4.4 异步接口（可选，方案 B 时实现）

```json
// POST /seal/recognize_async
{
  "code": 0,
  "data": {"task_id": "abc123", "status": "queued"}
}

// GET /seal/task/abc123
{
  "code": 0,
  "data": {
    "task_id": "abc123",
    "status": "done",
    "seals": [...]
  }
}
```

---

## 五、服务架构

### 5.1 目录结构

```
yinzhang/
├── app/                        # FastAPI 应用
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── routes/
│   │   ├── seal.py             # 印章识别路由
│   │   └── health.py           # 健康检查
│   ├── services/
│   │   ├── seal_service.py     # 印章识别服务（封装产线）
│   │   └── pdf_service.py      # PDF 渲染服务
│   ├── models/
│   │   └── schemas.py          # Pydantic 请求/响应模型
│   └── core/
│       ├── config.py           # 配置加载
│       └── pipeline.py         # 产线单例管理
├── config.yaml                 # 配置文件
├── seal_pipeline.py            # 命令行版（保留）
├── requirements.txt
└── Dockerfile                  # 容器化部署
```

### 5.2 核心代码骨架

#### `app/core/pipeline.py`（产线单例）

```python
from paddlex import create_pipeline
from functools import lru_cache

@lru_cache(maxsize=1)
def get_seal_pipeline():
    """进程级单例，只加载一次。"""
    return create_pipeline("seal_recognition")
```

#### `app/services/seal_service.py`

```python
from app.core.pipeline import get_seal_pipeline
from app.services.pdf_service import render_pdf_to_images

def recognize_seal(file_bytes: bytes, filename: str, dpi: int = 200):
    """识别印章，返回结构化结果。"""
    pipeline = get_seal_pipeline()

    # 判断类型
    if filename.lower().endswith(".pdf"):
        images = render_pdf_to_images(file_bytes, dpi)
    else:
        from PIL import Image
        import io
        images = [Image.open(io.BytesIO(file_bytes)).convert("RGB")]

    # 逐页识别
    all_seals = []
    for page_idx, img in enumerate(images):
        # 产线需要文件路径，存临时文件
        temp_path = f"/tmp/_seal_{page_idx}.png"
        img.save(temp_path)

        output = pipeline.predict(temp_path, ...)
        # 解析结果...
        all_seals.extend(...)

    return all_seals
```

#### `app/routes/seal.py`

```python
from fastapi import APIRouter, UploadFile, File
from app.services.seal_service import recognize_seal

router = APIRouter(prefix="/seal", tags=["印章识别"])

@router.post("/recognize")
async def recognize(file: UploadFile = File(...), dpi: int = 200):
    file_bytes = await file.read()
    seals = recognize_seal(file_bytes, file.filename, dpi)
    return {"code": 0, "data": {"seals": seals}}
```

#### `app/main.py`

```python
from fastapi import FastAPI
from app.routes import seal, health

app = FastAPI(title="印章识别服务", version="1.0.0")
app.include_router(seal.router)
app.include_router(health.router)
```

### 5.3 启动方式

#### 开发环境

```bash
uvicorn app.main:app --reload --port 8000
```

#### 生产环境（多进程）

```bash
# 方案 A：uvicorn 多 worker
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# 或用 gunicorn（Linux）
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

---

## 六、多图片批量推理

### 6.1 串行 vs 并行

| 方式 | 说明 | 适用 |
|------|------|------|
| 串行 | 逐张调用产线 | 简单，低并发 |
| 多进程并行 | 用 `concurrent.futures.ProcessPoolExecutor` | 批量大 |

**推荐串行**：因为产线内部已有批处理能力，单进程串行调用已足够。并行反而会因进程间模型复制导致内存爆炸。

### 6.2 批量接口实现

```python
@router.post("/recognize_batch")
async def recognize_batch(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        file_bytes = await file.read()
        seals = recognize_seal(file_bytes, file.filename)
        results.append({"filename": file.filename, "seals": seals})
    return {"code": 0, "data": {"results": results}}
```

---

## 七、部署形态

### 7.1 CPU 部署（当前）

```yaml
# docker-compose.yml
services:
  seal-api:
    build: .
    ports: ["8000:8000"]
    environment:
      - WORKERS=2
      - DEVICE=cpu
    deploy:
      resources:
        limits:
          memory: 8G          # 每 worker 约 2GB，2 worker = 4GB + 缓冲
```

- 单机 CPU 推理，每张图约 1-3 秒
- 2 worker 并发，QPS 约 0.5-1
- 适合内部工具

### 7.2 GPU 部署（高并发）

```yaml
services:
  seal-api:
    build: .
    ports: ["8000:8000"]
    environment:
      - WORKERS=1             # GPU 只能 1 worker（显存共享）
      - DEVICE=gpu
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: ["gpu"]
```

- GPU 推理，每张图约 100-300ms
- 单 worker，QPS 约 3-10
- 适合生产服务

### 7.3 容器化 Dockerfile

```dockerfile
FROM python:3.10-slim

# 系统依赖（PDF 渲染需要）
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libsm6 libxext6 libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

---

## 八、性能与资源

### 8.1 资源占用估算

| 部署形态 | 内存/worker | 模型大小 | 推理速度 | QPS |
|---------|------------|---------|---------|-----|
| CPU mobile 档 | ~1GB | 5MB | 1-3s/张 | 0.3-1 |
| CPU server 档（当前） | ~2GB | 109MB | 2-5s/张 | 0.2-0.5 |
| GPU server 档 | ~2GB + 显存 | 109MB | 100-300ms/张 | 3-10 |

### 8.2 优化建议

1. **模型转 ONNX**：CPU 推理快 2-3x（参考 [plan.md](file:///d:/tongxignzheng/yinzhang/plan.md) 第八章）
2. **GPU 部署**：高并发首选
3. **缓存结果**：相同文件 hash 直接返回历史结果
4. **限制文件大小**：单文件 < 10MB，避免大 PDF 拖垮内存

---

## 九、落地步骤

| 阶段 | 内容 | 产出 |
|------|------|------|
| 1. 搭骨架 | FastAPI 项目结构 + 产线单例 + 同步接口 | 可调用的 API |
| 2. 加 PDF 支持 | PDF 上传 + 逐页识别 | 支持 PDF 输入 |
| 3. 加批量接口 | 多文件上传 + 串行处理 | 支持批量 |
| 4. 容器化 | Dockerfile + docker-compose | 一键部署 |
| 5. 压测 | locust/ab 压测，调 worker 数 | 性能报告 |
| 6.（可选）异步 | Celery + Redis | 高并发 |

---

## 十、相关文件

| 文件 | 说明 |
|------|------|
| [seal_pipeline.py](file:///d:/tongxignzheng/yinzhang/seal_pipeline.py) | 命令行版（产线模式 + PDF 支持） |
| [seal_pipeline_hybrid.py](file:///d:/tongxignzheng/yinzhang/seal_pipeline_hybrid.py) | 混合版备份（手动串联 + 产线） |
| [config.yaml](file:///d:/tongxignzheng/yinzhang/config.yaml) | 配置文件 |
| [plan.md](file:///d:/tongxignzheng/yinzhang/plan.md) | 印章识别整体规划 |
| [deploy_plan.md](file:///d:/tongxignzheng/yinzhang/deploy_plan.md) | 本部署方案 |
