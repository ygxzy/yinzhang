# 印章识别服务方案

## 一、整体方案

基于 **PaddleOCR 3.x 官方 seal_recognition 产线**，零训练开箱即用。
输入：图片 / PDF / Word → 输出：印章位置（bbox/polygon）+ 印章内容文本。

### 1.1 技术栈（全部官方现成）

| 模块 | 官方模型 | 作用 |
|------|---------|------|
| 版面区域检测 | PP-DocLayout-L | 在文档/图里定位"印章区域"整体 bbox |
| 印章文本检测 | **PP-OCRv4_server_seal_det**（Hmean 98.4%） | 在印章区域内检测弯曲文本框 |
| 文本识别 | PP-OCRv4_server_rec | 识别每个弯曲文本框的内容 |
| 文本行方向分类 | PP-LCNet_x0_25_textline_ori | 印章文字多为环形，需角度分类 |

调用方式：
```python
from paddlex import create_pipeline
pipeline = create_pipeline(pipeline="seal_recognition")
output = pipeline.predict(page_img, **SEAL_KWARGS)
```

### 1.2 模块对比（为何不用通用 OCR）

- 通用 `PaddleOCR()` 产线**不带印章检测模块**，只能识别普通横排文本
- 印章文字多为**环形/弧形排列**，通用 OCR 识别率低
- `seal_recognition` 产线内置印章专用检测+识别，对圆形公章/财务章/合同章识别率高

---

## 二、系统架构

```
客户端（图片/Word/PDF）
        │
        ▼
┌──────────────────────────────┐
│  FastAPI 服务（接口层）        │
│  POST /seal  接收 multipart   │
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  文档预处理层                 │
│  - 图片：直传                 │
│  - PDF：pdf2image → 逐页渲染  │
│  - Word(docx)：libreoffice 转 PDF → 渲染 │
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  seal_recognition 产线        │
│  pipeline.predict(page_imgs,  │
│    use_doc_orientation_classify=False, │
│    use_doc_unwarping=False,   │
│    seal_det_unclip_ratio=0.5, │
│    seal_det_box_thresh=0.6,   │
│    seal_det_thresh=0.2,       │
│    seal_det_limit_side_len=736,│
│    seal_det_limit_type="min", │
│    seal_rec_score_thresh=0)   │
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  结果聚合层                   │
│  每页 → [{seal_bbox, content, conf}] │
│  多页合并为文档级结果         │
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  JSON 响应 + 可视化图         │
└──────────────────────────────┘
```

---

## 三、文档输入处理

三种格式统一转成图片列表后送产线。

| 格式 | 方案 | 依赖库 |
|------|------|--------|
| 图片 (jpg/png/bmp) | 直传 PIL | pillow |
| PDF | 逐页渲染成 PIL | `pdf2image`（需装 poppler） |
| Word (.docx/.doc) | LibreOffice headless 转 PDF → 再走 PDF 路径 | `libreoffice`（系统级） |

**注意**：Word 里印章可能在正文图片、页眉页脚图片里。转 PDF 渲染整页最稳，能覆盖所有位置。

---

## 四、印章检测参数（官方在线体验标准配置）

```python
SEAL_KWARGS = dict(
    use_doc_orientation_classify=False,  # 印章不能矫正，会异位
    use_doc_unwarping=False,              # 同上
    seal_det_unclip_ratio=0.5,            # 文本框扩张系数
    seal_det_box_thresh=0.6,              # 框内平均分阈值
    seal_det_thresh=0.2,                  # 像素阈值
    seal_det_limit_side_len=736,          # 边长限制
    seal_det_limit_type="min",            # 短边限制
    seal_rec_score_thresh=0,              # 识别分数阈值，全保留业务侧再过滤
)
```

> 这些阈值是官方在线体验调过的标准值，改了识别率会掉，勿随意修改。

---

## 五、输出结构

```json
{
  "seals": [
    {
      "page": 1,
      "seal_bbox": [x1, y1, x2, y2],
      "seal_polygon": [[x,y], ...],
      "texts": [
        {"text": "某某有限公司", "bbox": [...], "conf": 0.97},
        {"text": "财务专用章", "bbox": [...], "conf": 0.95}
      ],
      "content": "某某有限公司 财务专用章"
    }
  ],
  "vis_path": "/data/vis/abc123.png"
}
```

- `seal_bbox`：印章整体区域（版面检测给）
- `seal_polygon`：印章多边形（印章文本检测给）
- `texts`：印章内的文字行列表
- `content`：拼接后的印章全文
- `vis_path`：可视化图（红框标印章位置）

---

## 六、部署形态

| 部署 | 模型档 | 速度 | 适用 |
|------|--------|------|------|
| CPU | `PP-OCRv4_mobile_seal_det`（4.6MB） | 单页 ~50ms 检测 | 内部小流量 |
| GPU | `PP-OCRv4_server_seal_det`（109MB） | 单页 ~90ms 检测 | 生产高并发 |

- **CPU 部署**：`pip install paddlepaddle paddlex`，无 GPU 依赖
- **GPU 部署**：`pip install paddlepaddle-gpu`，可叠加 TensorRT 加速
- **服务化**：推荐自己包 FastAPI（更可控），或用 PaddleX 自带 `paddlex --serve`

---

## 七、引擎选择（关键）

### 7.1 支持的引擎

| 引擎 | 说明 | 推荐场景 |
|------|------|---------|
| `paddle_static` | 飞桨静态图推理（默认） | 通用，CPU/GPU 都行 |
| `hpi` | 飞桨高性能推理 | GPU 加速 |
| `onnxruntime` | ONNX Runtime | CPU 部署加速、跨平台 |

### 7.2 不支持的引擎

- `transformers`：仅 PaddleOCR-VL 大模型可用，传统 CV 模型（检测/识别/版面/印章）**不支持**，指定会触发重新下载 HF 格式模型。

### 7.3 本地验证示例

```python
# 印章检测
from paddleocr import SealTextDetection
model = SealTextDetection(engine="paddle_static", model_name="PP-OCRv4_mobile_seal_det")
output = model.predict("seal.png", batch_size=1)

# 版面检测
from paddleocr import LayoutDetection
model = LayoutDetection(model_name="PP-DocLayout_plus-L", engine="paddle_static")
output = model.predict("image.jpg", batch_size=1, layout_nms=True)
```

---

## 八、ONNX 模型转换

### 8.1 模型格式说明

PaddleOCR 3.x 官方模型有**两种并存格式**：

| 格式 | 目录内文件 | 说明 |
|------|-----------|------|
| 传统静态图 | `inference.pdmodel` + `inference.pdiparams` | Paddle 2.x 格式 |
| PIR 新格式 | `inference.json` + `inference.pdiparams` + `.yml` | Paddle 3.0 新IR |

本地缓存路径：`C:\Users\xuzeyu-dhq\.paddlex\official_models\<模型名>\`

### 8.2 转换命令（飞桨 AI Studio / Python 3.8-3.12 环境）

```bash
# 方案 A：paddlex CLI（推荐，PIR 格式适配最好）
paddlex --paddle2onnx \
  --paddle_model_dir ~/.paddlex/official_models/PP-OCRv4_mobile_seal_det \
  --onnx_model_dir ~/work/onnx_models/seal_det \
  --opset_version 14

# 方案 B：paddle2onnx（需 >=1.1 版本支持 PIR）
pip install -U "paddle2onnx>=1.1"
paddle2onnx \
  --model_dir ~/.paddlex/official_models/PP-OCRv4_mobile_seal_det \
  --model_filename inference.json \
  --params_filename inference.pdiparams \
  --save_file ~/work/seal_det.onnx \
  --opset_version 14
```

### 8.3 ONNX 加载

```python
model = SealTextDetection(
    engine="onnxruntime",
    model_dir="./onnx_models/seal_det"  # 指向含 .onnx 的目录
)
```

---

## 九、本地环境配置

### 9.1 Python 版本要求

- paddlepaddle / paddleocr 支持 **Python 3.8 ~ 3.12（64位）**
- 不支持 Python 3.13+、32 位 Python

### 9.2 虚拟环境搭建

```powershell
# 查看已安装版本
py --list

# 用 3.10 创建虚拟环境（64位）
py -3.10 -m venv d:\tongxignzheng\.venv

# 激活
d:\tongxignzheng\.venv\Scripts\Activate.ps1

# 安装依赖（清华镜像加速）
pip install paddleocr onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 9.3 模型缓存

- 缓存路径：`C:\Users\xuzeyu-dhq\.paddlex\official_models\`
- 用户级全局目录，**虚拟环境不影响**，切换 Python 版本后直接复用
- 已缓存模型：
  - `PP-DocLayout_plus-L`（版面检测）
  - `PP-OCRv4_mobile_seal_det`（印章检测-移动端）
  - `PP-OCRv4_server_seal_det`（印章检测-服务端）
  - `PP-OCRv5_server_det_safetensors`（文本检测）

### 9.4 跳过模型源检查（避免重复下载）

```powershell
# 临时
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True"

# 永久
setx PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK True
```

---

## 十、落地步骤

### 阶段 1：产线验证（半天）

1. 在飞桨 AI Studio 跑 `seal_recognition` 产线，喂 3-5 张真实印章图/PDF
2. 看默认模型识别率，必要时调参数
3. 在线体验地址：https://aistudio.baidu.com/community/app/387977/webUI

### 阶段 2：FastAPI 服务（1-2 天）

1. 文档预处理层（图片/PDF/Word 转图片）
2. 产线调用 + 结果聚合 + 可视化输出
3. JSON 响应封装

### 阶段 3：压测 & 调档

- CPU 慢 → 换 mobile 档 / 转 ONNX
- GPU 够 → server 档 + hpi 引擎
- 必要时上 TensorRT 加速

### 阶段 4：二次开发（可选）

- 默认模型对圆形公章/财务章/合同章识别率已经很高，大概率不用训
- 如方形章、少数民族文字章识别不好，标 50-200 张微调 `PP-OCRv4_server_seal_det`

---

## 十一、当前进度

- [x] 方案规划
- [x] 本地 Python 3.10 虚拟环境搭建
- [x] paddleocr 安装 + 模型缓存确认
- [x] SealTextDetection 模块验证脚本（test.py）
- [x] LayoutDetection 模块验证脚本（banmian.py）
- [ ] seal_recognition 产线验证（飞桨 AI Studio）
- [ ] ONNX 模型转换
- [ ] FastAPI 服务开发
- [ ] 压测与调优

---

## 十二、相关文件

- [test.py](file:///d:/tongxignzheng/yinzhang/test.py) — 印章检测验证脚本
- [banmian.py](file:///d:/tongxignzheng/yinzhang/banmian.py) — 版面检测验证脚本
- [seal_recognition_demo.py](file:///d:/tongxignzheng/seal_recognition_demo.py) — seal_recognition 产线完整 demo（含 PDF/Word 预处理）
- 模型缓存：`C:\Users\xuzeyu-dhq\.paddlex\official_models\`
