# degrade 识别引擎评测报告

- 数据集：**smoke**（语言 zh） · 样本 3 个（有标注 3 个） · 引擎 6 个 · 预测 27 条
- 结果文件：`results/degrade/run.json`
- 运行时间：2026-11-12T07:51:10+00:00 · 报告生成：2026-11-12 15:53:33
- 准确率口径：**完整率** · 总榜排序：**CER** · 汇率：1 USD = 7.2 CNY

## 选型结论

- 完整率最高：rapidocr（100.00%），每千张成本 $0.0000 / ¥0.0000。
- 最省钱：rapidocr（$0.0000 / ¥0.0000/千张），完整率 100.00%。
- 帕累托前沿（没有更便宜且更准的引擎）：rapidocr。
- 本次运行的引擎成本均为 0（本地部署），成本列只用于说明口径。

## 引擎总榜

| 排名 | 引擎 | 类型 | 样本(失败) | CER↓ | 错认率↓ | 漏提率↓ | 多提率↓ | 完整率↑ | 行级F1↑ | 定位IoU↑ | 完全匹配↑ | 漏/多/错字数 | 平均延迟↓ | P90↓ | 吞吐 | 每千张成本↓ |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | rapidocr ✅帕累托 | ocr.rapidocr | 3(0) | 0.00% | 0.00% | 0.00% | 0.00% | 100.00% | 1.00 | 0.95 | 100.00% | 0/0/0 | 1,710.5 ms | 1,821.1 ms | 35.1 张/分钟 | $0.0000 / ¥0.0000 |
| 2 | gemini | vlm.gemini | 3(3) | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 3 | local-qwen | vlm.local | 3(3) | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 4 | paddleocr | ocr.paddleocr | 3(3) | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 5 | qwen-vl-max | vlm.openai_compat | 3(3) | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 6 | tesseract | ocr.tesseract | 3(3) | — | — | — | — | — | — | — | — | — | — | — | — | — |

## 分场景分组

### 场景：smoke

| 引擎 | 样本 | CER↓ | 完整率↑ | 漏提率↓ | 多提率↓ | 行级F1↑ | 平均延迟↓ | 每千张成本↓ |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 3/3 | 0.00% | 100.00% | 0.00% | 0.00% | 1.00 | 1,710.5 ms | $0.0000 / ¥0.0000 |
| gemini | 0/3 | — | — | — | — | — | — | — |
| local-qwen | 0/3 | — | — | — | — | — | — | — |
| paddleocr | 0/3 | — | — | — | — | — | — | — |
| qwen-vl-max | 0/3 | — | — | — | — | — | — | — |
| tesseract | 0/3 | — | — | — | — | — | — | — |

## 延迟分布

| 引擎 | 有效样本 | 平均↓ | P50↓ | P90↓ | P99↓ | 最大 | 吞吐 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 3 | 1,710.5 ms | 1,793.0 ms | 1,821.1 ms | 1,827.4 ms | 1,828.1 ms | 35.1 张/分钟 |
| gemini | 0 | — | — | — | — | — | — |
| local-qwen | 0 | — | — | — | — | — | — |
| paddleocr | 0 | — | — | — | — | — | — |
| qwen-vl-max | 0 | — | — | — | — | — | — |
| tesseract | 0 | — | — | — | — | — | — |

> 缓存命中样本不计入延迟/成本；样本数 < 100 时 P99 仅供参考。

## 成本核算

| 引擎 | 单张成本 | 每千张(USD) | 每千张(CNY) | 每千分钟(USD) | 每千分钟(CNY) | 完整率↑ | 每提升1pp成本(USD/千张) | 选型 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | $0.000000 | $0.0000 | $0.0000 | $0.0000 | $0.0000 | 100.00% | — | 帕累托 |
| gemini | — | — | — | — | — | — | — | — |
| local-qwen | — | — | — | — | — | — | — | — |
| paddleocr | — | — | — | — | — | — | — | — |
| qwen-vl-max | — | — | — | — | — | — | — | — |
| tesseract | — | — | — | — | — | — | — | — |

> 每千分钟成本 = 单张成本 ÷ 单张机时(分钟) × 1000；「每提升 1pp 成本」以最便宜引擎为基线（Δ成本 ÷ Δ完整率百分点）。

## 逐样本对照

配色：<span style="background:#fde2e1;color:#b91c1c">漏提</span> · <span style="background:#dbe7ff;color:#1d4ed8">多提</span> · <span style="background:#fdf0c8;color:#92400e">错认</span>

### 样本 `s01`（场景：smoke）

原图：`datasets/smoke/images/s01.png`

**GT**：发票号码:12345678开票日期:2024年05月01日合计金额:¥1,234.00

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,793.0 ms | $0.000000 | 发票号码:12345678开票日期:2024年05月01日合计金额:¥1,234.00 |
| gemini | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.gemini[gemini]: 缺少 API Key，未设置环境变量 GEMINI_API_KEY。请先执行 `export GEMINI_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| local-qwen | — | — | — | — | — | 2.5 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.2 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `s02`（场景：smoke）

原图：`datasets/smoke/images/s02.png`

**GT**：合同编号HT-2024-0091甲方:北京某某科技有限公司乙方:上海示例信息技术有限公司

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,828.1 ms | $0.000000 | 合同编号HT-2024-0091甲方:北京某某科技有限公司乙方:上海示例信息技术有限公司 |
| gemini | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.gemini[gemini]: 缺少 API Key，未设置环境变量 GEMINI_API_KEY。请先执行 `export GEMINI_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| local-qwen | — | — | — | — | — | 1.2 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.8 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `s03`（场景：smoke）

原图：`datasets/smoke/images/s03.png`

**GT**：收货人:张三联系电话:138-0000-1111地址:北京市海淀区中关村大街1号

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,510.2 ms | $0.000000 | 收货人:张三联系电话:138-0000-1111地址:北京市海淀区中关村大街1号 |
| gemini | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.gemini[gemini]: 缺少 API Key，未设置环境变量 GEMINI_API_KEY。请先执行 `export GEMINI_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| local-qwen | — | — | — | — | — | 2.4 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.2 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

## 指标口径

- **CER** = (错认 + 漏提 + 多提) / GT 字数，按字符级编辑距离拆解，越低越好。
- **完整率** = 1 − 漏提率 − 错认率，对应“文字尽可能提全”的业务目标。
- **漏提率** / **多提率** / **错认率** 分别对应 OCR 老毛病与大模型幻觉。
- **行级 F1** 按归一化行文本集合匹配，免疫行序差异；**定位 IoU** 只在有 box 时计算。
- 成本在 run.json 内为 USD，本文按 1 USD = 7.2 CNY 折算。

