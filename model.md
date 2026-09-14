# 模型目录说明

本项目默认使用 GPU 版 PaddleX `seal_recognition` 产线。
建议将官方模型下载后放到当前目录下，保持目录名与官方模型名一致。

## 需要下载的 GPU 模型

项目运行时会依赖这些官方模型（对应 `seal_recognition` 产线的 GPU 版本）：

- `PP-DocLayout_plus-L` 或 `PP-DocLayout-L`
  - 版面检测：定位文档中的印章区域
- `PP-OCRv4_server_seal_det`
  - 印章文本检测：检测印章内弯曲/环形文字框
- `PP-OCRv4_server_rec`
  - 文本识别：识别印章中的字内容
- `PP-LCNet_x0_25_textline_ori`
  - 文字行方向分类：处理印章文字的方向/旋转

## 使用建议

下载后建议目录结构如下：

```text
models/
  PP-DocLayout_plus-L/
  PP-OCRv4_server_seal_det/
  PP-OCRv4_server_rec/
  PP-LCNet_x0_25_textline_ori/
```

如果你没有手动指定模型目录，PaddleX 默认也会将缓存下载到 `~/.paddlex/official_models/`。
本项目已经将默认缓存目录切到了 `./models`，这样后续下载会直接落到项目目录中。
