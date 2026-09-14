# 印章识别 API 接口使用说明

## 1 接口定义

### 1.1 接口地址

服务默认监听地址为：

```text
http://{host}:8000
```

当前服务提供的主要接口如下：

| 接口名称 | 请求方式 | 接口路径 | 说明 |
|---|---|---|---|
| 单文件识别 | POST | `/seal/recognize` | 上传一张图片或一个 PDF 并同步返回识别结果 |
| 批量识别 | POST | `/seal/recognize_batch` | 一次上传多个图片或 PDF 并同步返回结果 |
| 可视化图片 | GET | `/seal/vis/{vis_id}.png` | 获取识别结果对应的标注图片 |
| 健康检查 | GET | `/health` | 检查服务状态 |

在线接口文档地址：

```text
http://{host}:8000/docs
```

### 1.2 支持单证类别

当前版本按上传文件类型识别，支持以下类别：

| 类别 | `input_type` | 支持格式 | 说明 |
|---|---|---|---|
| 普通图像 | `image` | JPG、JPEG、PNG、WEBP 等 Pillow 可读取的图像 | 按单页图像处理 |
| PDF 文件 | `pdf` | PDF | 先逐页渲染为图像，再逐页识别 |

当前接口没有单独的 `picType` 请求参数，文件类型通过上传文件名的 `.pdf` 后缀判断。非 PDF 文件按普通图像处理。

## 2 请求报文结构

### 2.1 识别请求参数说明

单文件识别接口使用 `multipart/form-data`，参数如下：

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|---|---|---:|---|---|
| `file` | File | 是 | 表单 | 待识别的图片或 PDF 文件 |
| `dpi` | Integer | 否 | Query 参数 | PDF 渲染分辨率，默认 `200`，取值范围 `72` 至 `600`；图片输入不使用该参数 |

限制说明：

- 单个上传文件大小不能超过 `10 MB`。
- PDF 会逐页识别，响应中的 `total_pages` 表示 PDF 总页数。
- `seals[].page` 表示印章所在页码，从 `1` 开始。
- 服务启动时会预加载印章识别产线，首次请求通常不需要再次加载模型。

批量接口 `/seal/recognize_batch` 使用同样的 `multipart/form-data`，但文件字段名为 `files`，可以重复传入多个文件；`dpi` 参数规则与单文件接口相同。

### 2.2 识别请求报文模板

本节中的“请求报文模板”是 HTTP `multipart/form-data` 请求的通用结构示意，便于理解客户端与服务端之间实际传输的内容，不是某一种编程语言专用的代码。

其中：

- `file` 是上传文件的表单字段名，不是服务器文件路径。
- `<文件二进制内容>` 表示图片或 PDF 的原始二进制内容，不是 Base64 字符串。
- `boundary` 是 multipart 请求的分隔符，通常由客户端库自动生成。
- `dpi` 是 URL 查询参数，当前接口应写在 `?dpi=200` 中。

客户端通常不需要手动拼接下面的原始 HTTP 报文，可以使用 curl、Python `requests` 或其他 HTTP 客户端库生成相同格式的请求。

#### 单文件识别

```http
POST /seal/recognize?dpi=200 HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: multipart/form-data; boundary=----Boundary

------Boundary
Content-Disposition: form-data; name="file"; filename="seal.png"
Content-Type: image/png

<文件二进制内容>
------Boundary--
```

使用 curl 调用：

```bash
curl -X POST "http://127.0.0.1:8000/seal/recognize?dpi=200" \
  -F "file=@seal.png"
```

使用 Python `requests` 调用：

```python
import requests


url = "http://127.0.0.1:8000/seal/recognize"

with open("seal.png", "rb") as image_file:
  response = requests.post(
    url,
    params={"dpi": 200},
    files={
      "file": ("seal.png", image_file, "image/png"),
    },
    timeout=120,
  )

response.raise_for_status()
result = response.json()
print(result)
```

上传 PDF 时，只需修改文件名、文件对象和 MIME 类型：

```python
import requests


with open("document.pdf", "rb") as pdf_file:
  response = requests.post(
    "http://127.0.0.1:8000/seal/recognize",
    params={"dpi": 200},
    files={
      "file": ("document.pdf", pdf_file, "application/pdf"),
    },
    timeout=300,
  )

response.raise_for_status()
result = response.json()
print(result)
```

#### 批量识别

```bash
curl -X POST "http://127.0.0.1:8000/seal/recognize_batch?dpi=200" \
  -F "files=@seal-1.png" \
  -F "files=@seal-2.pdf"
```

使用 Python `requests` 批量调用：

```python
import requests


url = "http://127.0.0.1:8000/seal/recognize_batch"

with open("seal-1.png", "rb") as image_file, open("seal-2.pdf", "rb") as pdf_file:
  response = requests.post(
    url,
    params={"dpi": 200},
    files=[
      ("files", ("seal-1.png", image_file, "image/png")),
      ("files", ("seal-2.pdf", pdf_file, "application/pdf")),
    ],
    timeout=300,
  )

response.raise_for_status()
result = response.json()
print(result)
```

## 3 调用返回

### 3.1 识别返回接口

单文件识别接口返回 `application/json`，外层结构为：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

批量识别接口的外层结构相同，文件级结果位于 `data.results` 中。

### 3.1.1 识别返回信息说明

#### 外层字段

| 字段名 | 类型 | 说明 |
|---|---|---|
| `code` | Integer | 业务状态码，`0` 表示成功 |
| `message` | String | 返回信息，成功时为 `success` |
| `data` | Object | 识别结果数据 |

#### 单文件 `data` 字段

| 字段名 | 类型 | 说明 |
|---|---|---|
| `filename` | String | 上传文件名 |
| `input_type` | String | 输入类型：`image` 或 `pdf` |
| `total_pages` | Integer | 文件总页数；普通图像固定为 `1` |
| `total_seals` | Integer | 检测到的印章总数 |
| `seals` | Array | 印章识别结果列表 |
| `vis_paths` | Array | 服务端生成的可视化图片临时路径 |
| `elapsed_ms` | Integer | 本次识别耗时，单位为毫秒 |

#### `seals` 数组元素字段

| 字段名 | 类型 | 说明 |
|---|---|---|
| `page` | Integer | 印章所在页码，从 `1` 开始，图片默认为1，pdf为印章所在页数 |
| `seal_idx` | Integer | 当前页内的印章索引，从 `0` 开始 |
| `bbox` | Array / null | 印章整体边界框坐标 |
| `texts` | Array | 印章内识别出的文字列表 |
| `content` | String | 将识别文字拼接后的结果 |

#### `texts` 数组元素字段

| 字段名 | 类型 | 说明 |
|---|---|---|
| `text` | String | 识别出的文字 |
| `score` | Float | 文字识别置信度 |

#### `resultMsg` 备注

当前实现使用字段名 `message`，没有返回 `resultMsg` 字段。若对接方的统一报文规范要求使用 `resultMsg`，可按以下方式映射：

```text
resultMsg = message
```

例如当前成功返回中的 `message: "success"`，对应统一报文中的 `resultMsg: "success"`。在未修改服务代码前，请以实际返回的 `message` 字段为准。

### 3.1.2 报文正常返回样例

#### 普通图像识别成功

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "filename": "seal.png",
    "input_type": "image",
    "total_pages": 1,
    "total_seals": 1,
    "seals": [
      {
        "page": 1,
        "seal_idx": 0,
        "bbox": [39.47, 14.57, 507.73, 490.27],
        "texts": [
          {
            "text": "某某市市场监督管理局",
            "score": 0.9997
          },
          {
            "text": "行政执法专用章",
            "score": 0.9996
          }
        ],
        "content": "某某市市场监督管理局 行政执法专用章"
      }
    ],
    "vis_paths": [
      "C:\\Users\\user\\AppData\\Local\\Temp\\seal_vis_a1b2c3d4.png"
    ],
    "elapsed_ms": 1234
  }
}
```

#### PDF 识别成功

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "filename": "document.pdf",
    "input_type": "pdf",
    "total_pages": 3,
    "total_seals": 2,
    "seals": [
      {
        "page": 1,
        "seal_idx": 0,
        "bbox": [100, 120, 500, 400],
        "texts": [],
        "content": ""
      },
      {
        "page": 3,
        "seal_idx": 0,
        "bbox": [80, 90, 460, 380],
        "texts": [],
        "content": ""
      }
    ],
    "vis_paths": [],
    "elapsed_ms": 2450
  }
}
```

#### 批量识别成功

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "total_files": 2,
    "results": [
      {
        "filename": "seal-1.png",
        "input_type": "image",
        "total_pages": 1,
        "total_seals": 1,
        "seals": [],
        "vis_paths": []
      },
      {
        "filename": "seal-2.pdf",
        "input_type": "pdf",
        "total_pages": 2,
        "total_seals": 0,
        "seals": [],
        "vis_paths": []
      }
    ],
    "elapsed_ms": 3200
  }
}
```

### 3.1.3 报文异常返回样例

#### 文件超过 10 MB

HTTP 状态码为 `413`：

```json
{
  "detail": "文件大小超过 10MB 限制"
}
```

#### 识别处理失败

HTTP 状态码为 `500`：

```json
{
  "detail": "识别失败: 具体错误信息"
}
```

#### 批量接口中的单文件失败

批量接口整体仍返回 HTTP `200`，失败文件在 `data.results` 中以 `error` 字段表示：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "total_files": 1,
    "results": [
      {
        "filename": "bad.pdf",
        "error": "处理 PDF 需要安装 pypdfium2：pip install pypdfium2"
      }
    ],
    "elapsed_ms": 18
  }
}
```

### 3.2 单证类别（picType）对照表

当前版本尚未实现 `picType` 请求字段，实际通过文件扩展名判断输入类型。为便于后续对接，可按以下逻辑对照：

| `picType` 建议值 | 单证类别 | 当前实现对应值 | 说明 |
|---|---|---|---|
| `IMAGE` | 普通图像 | `input_type = "image"` | JPG、JPEG、PNG、WEBP 等 |
| `PDF` | PDF 文件 | `input_type = "pdf"` | 文件名以 `.pdf` 结尾 |

以上 `picType` 仅为接口规范预留说明，当前调用时无需传入，也不会在当前响应中返回。若后续需要按业务单证类型（例如营业执照、合同、发票等）扩展，应先在服务端增加参数校验和对应枚举，再同步更新本表。
