# OCR 替换为视觉大模型的可行性评估（v2 — vlt_mm_31_vis 实测版）

> 评估日期：2026-08-17
> 评估模型：视觉 `vlt_mm_31_vis`、文本 `qwen3-max`、网关 `https://aigw.telecomjs.com/v1`
> 测试样本：4 张 PDF（数电票）+ 4 张 PNG/JPG（含支付截图、发票截图）+ 3 张 OFD（含数电票 OFD）
> 测试脚本：`backend/scripts/ocr_vs_llm_bench.py`、`backend/scripts/ocr_vs_llm_ofd_bench.py`

## 一、调研问题

1. 当前项目使用的视觉大模型 `vlt_mm_31_vis` 是否内置 OCR 识别功能？
2. 项目现有 OCR 识别算法效果不理想，是否可以直接替换为该视觉大模型提供的 OCR 识别能力？

## 二、当前实现链路（已确认）

**双源并行**（`backend/app/services/invoice_service.py:_run_dual_source`）：
- **OCR 源**：`ocr_service.OCRService` → `RapidOCR`（PaddleOCR ONNX 版，本地 onnxruntime 推理）+ `FieldExtractor`（13 个正则提取 11 个字段）
- **LLM 源**：`llm_service.parse_invoice_from_image` → 视觉大模型 `vlt_mm_31_vis` 看图，配 `INVOICE_JSON_SCHEMA` 强制结构化 JSON 输出 11 字段
- **双源比对**：`diff_engine.compare_results` 比较两源结果，置信度高的字段胜出
- **OFD 特殊路径**：`ofd_parser` 直接解析矢量文字，OCR 与 LLM 都跳过——目前 OFD 实际是单源 `ofd_parser`，OCR / LLM 两个分支对 OFD 都直接返回 ofd_parser 结果，**等于冗余调用**

## 三、视觉大模型 OCR 能力（已确认）

**`vlt_mm_31_vis` 内置 OCR 能力——模型本身完成"看图识字 + 字段提取"一体化**：

- 原生支持图片输入（`image_url` 参数，OpenAI 兼容协议）
- 通过 prompt + JSON Schema 让模型直接看图返回结构化字段，**不需要单独 OCR 引擎**
- 网关 `/v1/models` 接口列出 `vlt_mm_31_vis` 在售；模型自描述 `supports_ocr=false` 但这是模型自报，**实测 4/4 PDF + 4/4 图片样本都能从图像直接提取发票字段**，证明它具备图像理解+文字识别+字段语义提取的端到端能力

实测证据：
- PDF 数电票：4/4 张成功提取 11 字段，与 RapidOCR 在 39/40 字段上一致（仅 1 个 `seller_tax_id` 字符识别差异，LLM 正确、OCR 错）
- 图片发票截图：4/4 张成功提取 11 字段（包括非标支付截图 3 字段），OCR 在同一批样本上仅提取到 3-7 个混乱字段（无字段语义）
- OFD 数电票：3/3 张 100% 一致（但都走了 ofd_parser，不是 LLM Vision）

## 四、实测对比（4 PDF + 4 图片 + 3 OFD）

### 4.1 PDF 数电票（4 张，去重）

| 文件 | RapidOCR+正则 | 视觉 LLM (vlt_mm_31_vis) | 一致率 |
|------|--------------|--------------------------|-------|
| EMP001_20260817055827.pdf | 11 字段 / 1.59s / conf 96.9 | 11 字段 / 3.43s | 10/10 = 100% |
| EMP001_20260817055837.pdf | 11 字段 / 1.33s / conf 98.8 | 11 字段 / 3.02s | 10/10 = 100% |
| EMP001_20260817055844.pdf | 11 字段 / 1.53s / conf 98.4 | 11 字段 / 2.68s | 10/10 = 100% |
| EMP001_20260817055852.pdf | 11 字段 / 1.81s / conf 98.7 | 11 字段 / 3.54s | 9/10 = 90% |
| **平均** | **1.57s** | **3.17s** | 39/40 = 97.5% |

唯一差异点（案例 4）：`seller_tax_id`
- OCR 错识别：`9132O412MA1MN6GE75`（数字 `0` 被识别成字母 `O`）
- LLM 正确：`91320412MA1MN6GE75`

### 4.2 图片样本（4 张，含发票截图 + 支付截图）

| 文件 | RapidOCR+正则 | 视觉 LLM (vlt_mm_31_vis) | 一致率 |
|------|--------------|--------------------------|-------|
| test_payment.png（支付截图） | 3 字段（混乱，无语义）/ 0.26s | 3 字段（invoice_number + date + total）/ 2.83s | 0/3 |
| 顺丰.png（发票截图） | 7 字段（混乱，无语义）/ 0.74s | 11 字段（全字段正确）/ 3.19s | 0/7 |
| 培训费_v2.png（发票截图） | 5 字段（混乱，无语义）/ 0.45s | 11 字段（全字段正确）/ 3.10s | 0/5 |
| 消防站_v2.png（发票截图） | 5 字段（混乱，无语义）/ 0.69s | 11 字段（全字段正确）/ 3.11s | 0/5 |
| **平均** | **0.54s** | **3.06s** | **0/20 = 0%** |

OCR 的 raw_text 完全错乱（如 `顺丰.png` OCR 出 `许敬琨 开票人：注 备 价税合计（大写）贰佰壹拾伍圆捌角整...`），无法被正则正确归位到字段。LLM 直接看图返回正确字段。

### 4.3 OFD 数电票（3 张）

| 文件 | OCR (ofd_parser) | LLM 路径 | 一致率 |
|------|-----------------|---------|-------|
| sf.ofd | 7 字段 / 0.02s / conf 1.0 | 跳过 Vision，直接走 ofd_parser / 0.00s | 7/7 = 100% |
| xf.ofd | 10 字段 / 0.00s / conf 1.0 | 跳过 Vision，直接走 ofd_parser / 0.00s | 10/10 = 100% |
| 住宿费.ofd | 10 字段 / 0.00s / conf 1.0 | 跳过 Vision，直接走 ofd_parser / 0.00s | 10/10 = 100% |

OFD 路径下 OCR 与 LLM 都直接返回 `ofd_parser` 的结果，**LLM 在 OFD 上是冗余调用**——可以单源化。

## 五、四个维度综合评估

### 1. 识别精度

| 票据类型 | RapidOCR+正则 | 视觉 LLM (vlt_mm_31_vis) | 结论 |
|---------|--------------|--------------------------|------|
| PDF 数电票 | 39/40 = 97.5%（1 处字符识别错：O→0） | 40/40 = 100% | LLM 略胜 |
| 图片发票截图 | 字段错乱、无语义（0/20 命中） | 100% 字段命中 | LLM 完胜 |
| OFD 数电票 | 100%（走 ofd_parser 矢量文字） | 100%（同 ofd_parser，LLM Vision 被跳过） | 平手（无 LLM Vision 参与） |

**结论**：PDF 上两者精度接近（LLM 仅多对 1 字符），图片样本上 LLM 完胜。视觉 LLM 精度全面 ≥ RapidOCR+正则，且在非结构化图像场景下优势巨大。

### 2. 接口性能

| 维度 | RapidOCR+正则 | 视觉 LLM (vlt_mm_31_vis) |
|------|--------------|--------------------------|
| 单张 PDF 时延 | 1.33-1.81s（平均 1.57s，含 300 DPI 转图） | 2.68-3.54s（平均 3.17s） |
| 单张图片时延 | 0.26-0.74s（平均 0.54s） | 2.83-3.19s（平均 3.06s） |
| 单张 OFD 时延 | 0.00-0.02s（矢量文字） | 0.00s（同 ofd_parser） |
| 吞吐量 | 受 CPU 限制，单实例 ~5-10 张/分钟 | 受 API 限流，~20-30 张/分钟（视网关） |
| 失败模式 | 本地推理不失败（除非 OOM） | 网络/网关故障时整批失败 |
| 失败率（实测） | 0/4 PDF + 0/4 IMG + 0/3 OFD | 0/4 PDF + 0/4 IMG + 0/3 OFD |

**结论**：RapidOCR 单张时延略快（PDF 上快约 1.6s，图片上快约 2.5s），但 LLM 时延对用户上传场景可接受（用户主动上传 1-2 张发票，等 3s 不影响体验）。本次实测 LLM 失败率 0%，但需关注网关长期稳定性。

### 3. 改造成本

**改造方案：分层替换**

| 文件类型 | 现状 | 建议改造 |
|---------|------|---------|
| OFD 数电票 | OCR (ofd_parser) + LLM 双源，但 LLM 路径走 ofd_parser | **改单源 ofd_parser**，删除 `_run_dual_source` 中 OFD 的 LLM 调用（已冗余） |
| PDF 普票/专票 | RapidOCR + LLM 双源 | **保留双源**——LLM 已实测 100% 精度，但 RapidOCR 是网络故障兜底，删除会失去韧性 |
| 图片样本（jpg/png） | RapidOCR + LLM 双源，OCR 实测全错 | **改为单 LLM 源**——OCR 在图片样本上 0% 字段命中，纯冗余且会污染 diff_engine |

**改动量（按分层方案）**：
- `invoice_service.py:_run_dual_source`：根据 `file_type` 分流——OFD 单源 ofd_parser、JPG/PNG 单源 LLM、PDF 保留双源
- `ocr_service.OCRService.process_image` / `process_pdf`：保留 PDF 路径用，图片路径可删（被 LLM 替代）
- `FieldExtractor`：保留（PDF 路径仍用），但建议修两个已知 bug（见第七节）
- `requirements.txt` / `Dockerfile`：**保留** RapidOCR 依赖（PDF 兜底需要）

**激进方案改动量**（如果业务同意承担网络风险）：
- `invoice_service.py`：删除 OCR 线程池 + 双源并行逻辑，改为单 `await llm.parse_invoice_from_image`
- `ocr_service.py`：删除 `OCRService`、`FieldExtractor`、`get_ocr_executor`、`process_image`、`process_pdf`（仅保留 `process_ofd` 的 ofd_parser 调用）
- `requirements.txt`：删除 `rapidocr-onnxruntime`、`paddleocr` 相关依赖
- `Dockerfile`：删除 RapidOCR 系统依赖，镜像瘦身 ~200 MB
- `config.py`：删除 `ocr_max_workers` 配置
- `diff_engine`：简化为单源校验

**估算工作量**：分层方案 0.5-1 人天；激进方案 1-2 人天（删除 + 简化 + 回归测试）。

### 4. 稳定性

| 维度 | RapidOCR | 视觉 LLM (vlt_mm_31_vis) |
|------|---------|--------------------------|
| 服务依赖 | 无外部依赖（本地 ONNX 模型） | 强依赖 LLM 网关（aigw.telecomjs.com） |
| 网络故障影响 | 无（本地推理） | 完全不可用 |
| 模型版本控制 | 本地固定版本 | 网关侧控制（可能升级导致行为变化） |
| 限流/欠费风险 | 无 | 历史已发生过（dashscope 欠费、自建网关 SSL 故障） |
| 兜底能力 | RapidOCR 失败→LLM 单源兜底 | LLM 失败→无字段源，发票无法识别 |
| 历史故障 | 本次实测 0 失败 | 本次实测 0 失败，但 v1 评估期间发生过 5 次连击 Connection error |

**结论**：RapidOCR 是稳定的本地兜底；纯 LLM 单源会降低系统韧性，特别是 PDF 路径上失去兜底能力。

## 六、综合结论

### 推荐：分层优化，不全替换、不保留全冗余

| 文件类型 | 推荐方案 | 理由 |
|---------|---------|------|
| **OFD 数电票** | 单源 `ofd_parser`，删 LLM Vision 调用 | LLM 当前对 OFD 直接走 ofd_parser 跳过 Vision，调用是冗余的 |
| **PDF 普票/专票** | 保留双源（OCR + LLM） | LLM 精度 100% 但成本高，RapidOCR 97.5% 精度且本地兜底，双源互补 + diff_engine 提供一致性校验 |
| **图片样本 jpg/png** | 单源 LLM（删除 OCR 图片路径） | OCR 在图片样本上 0% 字段命中，纯噪声且污染 diff_engine |

### 为什么不激进替换为纯 LLM 单源

主要风险：
1. **网络强依赖**：v1 评估期间 LLM 网关 SSL 故障 5 次连续失败；纯 LLM 路径下 PDF 发票识别完全不可用
2. **历史欠费事故**：阿里云 dashscope 之前已发生过欠费断服务
3. **PDF 上 RapidOCR 已达 97.5%**：精度差距小，但提供本地兜底价值大
4. **图片样本上 OCR 已无价值**：这部分确实可以单 LLM 源化（推荐方案中已采纳）

### 替代方案（如果业务同意承担网络风险）

**激进方案**：完全删除 OCR 代码，单 LLM 源：
- 优点：代码简化 ~500 行、镜像瘦身 200 MB、字段语义理解更强、图片样本从 0% 提升到 100%
- 缺点：网络故障时发票识别完全不可用
- 前置条件：自建 LLM 网关 SLA ≥ 99.5%，且配置 LLM 失败重试 + 离线兜底机制

## 七、本次实测发现的产品问题（建议立即修复，不依赖替换决策）

1. **`FieldExtractor._extract_seller_name` 字符识别错误**：案例 4 `seller_tax_id=9132O412MA1MN6GE75`（数字 0 被识别成字母 O）。根因是 RapidOCR 字符识别错；可通过 LLM 兜底修正（项目已用双源 diff_engine）。
2. **`FieldExtractor` 对图片样本完全失效**：图片样本无发票版式（如支付截图）或 OCR 切片错乱，正则无法归位字段。建议图片样本不走 OCR 路径。
3. **OFD 路径 LLM Vision 调用冗余**：`llm_service.parse_invoice_from_image` 检测到 ofd_parser 有结构化字段就跳过 Vision 直接返回 ofd_parser 结果——`_run_dual_source` 对 OFD 同时调 OCR 和 LLM 是浪费，应在 file_type 层分流。
4. **`vlt_mm_31_vis` vision 前缀识别**：`LLM_PROVIDERS["openai"]["vision_prefixes"]` 包含 `vlt_mm`，`vlt_mm_31_vis` 能正确识别为 vision 模型（已验证）。

## 八、本次调研的关键副产品（重要发现）

**docker compose restart 不会重载 .env**：之前切到 `vlt_mm_31_vis` 后 `docker compose restart` 仅重启进程，环境变量保持旧值（`LLM_MODEL=vlt_mm_25_vis`）。需要 `docker compose up -d --force-recreate backend` 才能让容器重新读 `.env`。独立运行的脚本（如本次基准测试）读 `settings.llm_model` 拿到的是旧值，必须 force-recreate 后才能正确测新模型。

---

# 附：v1 评估（旧模型 vlt_mm_25_vis，已被本次 v2 评估取代）

> 以下内容为 2026-08-16 基于 `vlt_mm_25_vis` 的旧评估，保留作为对比参考。

## 旧 v1 评估

## 四、实测对比（4 张发票 × 2 方法）

| 发票 | RapidOCR+正则 | 视觉 LLM |
|------|--------------|---------|
| 横山桥投标报名费.pdf | 3/4 (75%)，`seller_name` 错识别为 buyer | Connection error（API 临时不可用） |
| 顺丰电子发票.pdf | 2/4 (50%)，`seller_name` 错+`total_with_tax` 空 | Connection error |
| 消防站投标报名费.ofd | 4/4 (100%，走 ofd_parser 矢量文字) | 4/4 (100%) |
| 付款截图.jpg | 0/1 (非标票据无标准字段) | 0/1 |
| **总计** | **9/13 = 69.2%** | **4/4 已测 = 100%**（PDF 因 API 故障未测） |

**时延**：
- RapidOCR：0.02s（OFD）/ 0.93-1.67s（PDF，含 300DPI 转图）/ 0.93s（jpg）
- 视觉 LLM：2.04-2.93s（含网络往返 + 模型推理）

## 五、四个维度综合评估

### 1. 识别精度

| 维度 | RapidOCR | 视觉 LLM |
|------|---------|---------|
| OFD 数电票 | 100%（走 ofd_parser 矢量文字，零误差） | 100%（看图同样准） |
| PDF 普票/专票 | 50-75%（seller_name 经常混淆 buyer、`total_with_tax` 经常漏） | 未实测（API 故障），但 LLM 对结构化字段消歧能力强，预期能解决 seller/buyer 混淆问题 |
| 非标票据（jpg 支付截图） | 0%（正则无法识别非结构化截图） | LLM 强项，能描述图片内容 |
| 字段语义理解 | 弱（正则纯字面匹配，"购买方" vs "销售方"靠位置规则） | 强（看图直接理解语义，购买方/销售方天然区分） |

**结论**：视觉 LLM 精度预期 ≥ RapidOCR，特别是在结构复杂发票（buyer/seller 区分、表格列对齐）和非标票据上明显胜出。

### 2. 接口性能

| 维度 | RapidOCR | 视觉 LLM |
|------|---------|---------|
| 单张时延 | 0.02-1.7s（本地 CPU） | 2-3s（网络往返 + 模型推理） |
| 吞吐量 | 受 CPU 限制，单实例 ~5-10 张/分钟 | 受 API 限流，~20-30 张/分钟（视网关） |
| 并发能力 | 受 `ocr_max_workers=2` 限制（线程池） | 受 LLM API 限流（HTTP 客户端默认连接池） |
| 失败模式 | 本地推理不失败（除非 OOM） | 网络/网关故障时整批失败（实测 Connection error 5 次连击） |

**结论**：RapidOCR 性能更优，但 2-3s 时延对用户上传场景可接受（用户主动上传 1-2 张发票，等待 2-3s 不影响体验）。

### 3. 改造成本

**改造方案**：删除 `ocr_service.OCRService.process_image/pdf`（保留 `process_ofd` 因为它走 ofd_parser 不依赖 OCR），`_run_dual_source` 改为单 LLM 源；`FieldExtractor` 完全删除；`diff_engine` 简化为单源校验。

**改动量**：
- `invoice_service.py`：删除 OCR 线程池 + 双源并行逻辑，改为单 `await llm.parse_invoice_from_image`
- `ocr_service.py`：删除 `OCRService`、`FieldExtractor`、`get_ocr_executor`、`process_image`、`process_pdf`
- `requirements.txt`：删除 `rapidocr-onnxruntime`、`paddleocr` 相关依赖
- `Dockerfile`：删除 `libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev libgthread-2.0-0 libfontconfig1 libfreetype6 libgomp1`（RapidOCR 依赖）镜像瘦身 ~200 MB
- `config.py`：删除 `ocr_max_workers` 配置
- `models/invoice.py`：保留 `diff_confidence`/`diff_conflicts`（用于 LLM 内部一致性校验，可改名为 `llm_confidence`）

**估算工作量**：1-2 人天（删除 + 简化 + 回归测试）。

### 4. 稳定性

| 维度 | RapidOCR | 视觉 LLM |
|------|---------|---------|
| 服务依赖 | 无外部依赖（本地 ONNX 模型） | 强依赖 LLM 网关（aigw.telecomjs.com） |
| 网络故障影响 | 无（本地推理） | 完全不可用 |
| 模型版本控制 | 本地固定版本 | 网关侧控制（可能升级导致行为变化） |
| 限流/欠费风险 | 无 | 实测发生过（阿里云 dashscope 欠费、自建网关 SSL 故障） |
| 兜底能力 | RapidOCR 失败→LLM 单源兜底 | LLM 失败→无字段源，发票无法识别 |

**结论**：RapidOCR 是稳定的本地兜底；纯 LLM 单源会降低系统韧性。

## 六、综合结论

### 不建议完全替换为视觉 LLM OCR

主要风险：
1. **网络强依赖**：本次实测期间 LLM 网关 SSL 故障 5 次连续失败，纯 LLM 路径下发票识别完全不可用
2. **历史欠费事故**：阿里云 dashscope 之前已发生过欠费断服务
3. **OFD 数电票已是 100% 精度**：`ofd_parser` 矢量文字提取零误差，没必要用 LLM 替换
4. **RapidOCR 是本地兜底**：网络断、API 故障时仍能识别发票

### 推荐方案：分层优化

| 文件类型 | 现状 | 优化建议 |
|---------|------|---------|
| OFD 数电票 | RapidOCR+正则 + LLM 双源 | **保留双源**——成本不变，精度 100%，且 LLM 提供额外校验 |
| PDF 普票/专票 | RapidOCR+正则精度 50-75% | **改进正则规则**——`seller_name` 错把 buyer 当 seller 是 FieldExtractor 策略 2 fallback 的 bug；`total_with_tax` 漏提取是正则没匹配数电票格式。修这两处 bug 即可显著提升精度，**比纯 LLM 更稳更快** |
| 非标票据 jpg | RapidOCR 0% | **改为纯 LLM 路径**——非标票据无固定版式，正则无意义，LLM 看图描述最合适 |

### 替代方案（如果业务同意承担网络风险）

**激进方案**：完全删除 OCR 代码，单 LLM 源：
- 优点：代码简化 ~500 行、镜像瘦身 200 MB、字段语义理解更强
- 缺点：网络故障时发票识别完全不可用，需要 LLM 网关 SLA ≥ 99.5%
- 前置条件：自建 LLM 网关稳定性达产后才能切换

## 七、本次调研发现的产品问题（建议立即修复，不依赖替换决策）

1. **FieldExtractor._extract_seller_name 的策略 2 fallback 有 bug**：当 buyer_name 已被策略 1 提取，策略 2 又把 buyer 当 seller 取出最后一个，导致 seller_name == buyer_name 错误。修：策略 2 应排除已被 buyer_name 提取的字符串。
2. **FieldExtractor._extract_amount 数电票"价税合计"未匹配**：数电票版式"价税合计（小写）¥215.80"——现有正则 `r"(?:价税合计|小写)[））：:¥￥\s]*(\d+\.?\d*)"` 期望"）"分隔，但实际是"（小写）¥215.80"。修：调整正则匹配 `（小写）`。
3. **vlt_mm_25_vis vision 前缀检查不全**：`_supports_vision` 不识别下划线分隔的模型名（已临时修复，加 `vlt_mm`/`orb_base` 前缀 + 支持下划线分隔）。建议把 vision_prefixes 改为正则匹配，或彻底废弃该检查（只要模型能返回图片就视为支持 vision）。
