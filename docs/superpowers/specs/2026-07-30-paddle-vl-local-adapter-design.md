# PaddleVlLocalAdapter 设计文档

**日期**: 2026-07-30  
**项目**: llm-construct-question  
**范围**: 实现 `service/ocr/paddle_vl_local.py`，通过本地 `paddleocr genai_server`（vLLM 后端）完成图片/PDF OCR。

---

## 1. 背景与目标

当前 `service/ocr/paddle_vl_local.py` 是占位实现，直接抛 `NotImplementedError`。生产环境已部署本地容器：

```bash
paddleocr genai_server \
  --model_name PaddleOCR-VL-1.5-0.9B \
  --host 0.0.0.0 \
  --port 8128 \
  --backend vllm
```

目标：

1. 实现 `PaddleVlLocalAdapter`，与 `PaddleCloudAdapter` 保持同一 `OcrAdapter` 接口。
2. 通过 PaddleOCR Python SDK 的 `PaddleOCRVL` 客户端连接本地 vLLM 服务。
3. 支持单图 OCR 与整本 PDF OCR，统一返回 markdown 文本。
4. 不引入 JSON 上传 OSS 等副作用，适配器仅负责 OCR 并返回文本。

---

## 2. 架构与组件

```
┌─────────────────────────────────────────┐
│           ParseWorker / HTTP API        │
│              parse_image / parse_pdf    │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│     PaddleVlLocalAdapter                │
│  (implements OcrAdapter)                │
│  - parse_image(image_path) -> str       │
│  - parse_pdf(pdf_path) -> str           │
└─────────────────┬───────────────────────┘
                  │ PaddleOCRVL SDK
┌─────────────────▼───────────────────────┐
│  paddleocr genai_server (vLLM backend)  │
│  http://<host>:8128/v1                  │
└─────────────────────────────────────────┘
```

- **入口不变**：`service/ocr/factory.py` 根据 `OCR__PROVIDER=paddle-vl-local` 创建适配器。
- **接口不变**：`parse_image` / `parse_pdf` 签名与 `PaddleCloudAdapter` 完全一致。
- **实现依赖**：`PaddleOCRVL(vl_rec_backend='vllm-server', vl_rec_server_url=cfg.server_url)`。

---

## 3. 数据流

### 3.1 `parse_image(image_path)`

1. 调用 `self._pipeline.predict(image_path)`。
2. 遍历返回结果，从每个结果对象的 `res.markdown` 中提取文本：
   - 若 `markdown` 为 dict，取 `markdown.get("text")`；
   - 若 `markdown` 为 str，直接使用；
   - 其他类型忽略。
3. 将多段 markdown 文本按 `\n\n` 拼接为单个字符串。
4. 返回 markdown 文本；无内容时返回空字符串。

### 3.2 `parse_pdf(pdf_path)`

1. 调用 `self._pipeline.predict(pdf_path)`。
2. 收集每一页结果对象的 `res.markdown`，按与 `parse_image` 相同的方式提取文本。
3. 使用 `self._pipeline.concatenate_markdown_pages(markdown_list)` 合并跨页 markdown，避免生成多个独立 `.md` 文件。
4. 返回合并后的 markdown 文本；无内容时返回空字符串。

> 注：若 `concatenate_markdown_pages` 在目标 SDK 版本不可用，则回退到手动按页拼接。

---

## 4. 配置与依赖

### 4.1 配置项

在 `libs/settings.py` 的 `PaddleVlLocalSettings` 中扩展：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `server_url` | `str` | `""` | 本地 vLLM 服务地址，例如 `http://127.0.0.1:8128/v1` |
| `device` | `str` | `"gpu:0"` | 保留字段，主要用于兼容性；实际推理在服务端 |
| `pipeline_version` | `str` | `"v1.5"` | PaddleOCRVL 管线版本 |
| `model_name` | `str` | `""` | 显式模型名；为空时由 SDK 自动推断 |

`conf/config.yaml` 同步更新示例值。

### 4.2 依赖

- `paddleocr>=3.4.0`（与容器镜像一致）。
- 宿主开发环境按需安装；生产容器已内置。

---

## 5. 错误处理

- SDK 调用异常统一捕获并包装为 `RuntimeError`，保留原始错误信息。
- `predict()` 返回空结果或所有页均无 markdown 文本时，返回空字符串，不抛错。
- 服务端不可达时由底层 requests 抛出连接异常，适配器原样上抛。

---

## 6. 测试策略

- 新增 `tests/service/ocr/test_paddle_vl_local.py`。
- 使用 `unittest.mock` 模拟 `PaddleOCRVL` 及其 `predict()` 返回的 result 对象。
- 覆盖场景：
  1. 单图 OCR 返回 markdown。
  2. 多页 PDF OCR 合并返回 markdown。
  3. 空结果返回空字符串。
  4. SDK 异常包装为 `RuntimeError`。
- 不修改现有 `tests/service/ocr/test_ocr.py` 中 paddle-cloud 相关用例。

---

## 7. 非目标

- 不将结构化 JSON 上传到 OSS；适配器仅返回 markdown 文本。
- 不扩展 `OcrAdapter` 接口签名；`parse_image` / `parse_pdf` 保持原样。
- 不修改 `parse_worker` 对 PDF 的处理流程；若后续需要直接调用 `parse_pdf`，在 worker 层另行调整。

---

## 8. 后续可扩展点

- 如需上传结构化 JSON，可在 `parse_worker` 层调用 SDK 的 `save_to_json()`，不侵入 `OcrAdapter`。
- 如需切换为 HTTP 直连 `/v1/chat/completions`，可新增独立适配器或重构当前实现。
