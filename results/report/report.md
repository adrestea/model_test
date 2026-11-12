# hard 识别引擎评测报告

- 数据集：**hard**（语言 zh） · 样本 12 个（有标注 12 个） · 引擎 5 个 · 预测 60 条
- 结果文件：`results/hard/run.json`
- 运行时间：2026-11-12T14:29:21+00:00 · 报告生成：2026-11-12 22:30:15
- 准确率口径：**完整率** · 总榜排序：**CER** · 汇率：1 USD = 7.2 CNY

## 选型结论

- 完整率最高：rapidocr（99.89%），每千张成本 $0.0000 / ¥0.0000。
- 最省钱：rapidocr（$0.0000 / ¥0.0000/千张），完整率 99.89%。
- 帕累托前沿（没有更便宜且更准的引擎）：rapidocr。
- 本次运行的引擎成本均为 0（本地部署），成本列只用于说明口径。

## 引擎总榜

| 排名 | 引擎 | 类型 | 样本(失败) | CER↓ | 错认率↓ | 漏提率↓ | 多提率↓ | 完整率↑ | 行级F1↑ | 定位IoU↑ | 完全匹配↑ | 漏/多/错字数 | 平均延迟↓ | P90↓ | 吞吐 | 每千张成本↓ |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | rapidocr ✅帕累托 | ocr.rapidocr | 12(0) | 0.28% | 0.00% | 0.11% | 0.17% | 99.89% | 0.95 | 0.89 | 83.33% | 1/1/0 | 1,531.4 ms | 2,008.4 ms | 39.2 张/分钟 | $0.0000 / ¥0.0000 |
| 2 | local-qwen25vl-3b | vlm.local | 12(12) | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 3 | paddleocr | ocr.paddleocr | 12(12) | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 4 | qwen-vl-max | vlm.openai_compat | 12(12) | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 5 | tesseract | ocr.tesseract | 12(12) | — | — | — | — | — | — | — | — | — | — | — | — | — |

## 分场景分组

### 场景：合成

| 引擎 | 样本 | CER↓ | 完整率↑ | 漏提率↓ | 多提率↓ | 行级F1↑ | 平均延迟↓ | 每千张成本↓ |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 12/12 | 0.28% | 99.89% | 0.11% | 0.17% | 0.95 | 1,531.4 ms | $0.0000 / ¥0.0000 |
| local-qwen25vl-3b | 0/12 | — | — | — | — | — | — | — |
| paddleocr | 0/12 | — | — | — | — | — | — | — |
| qwen-vl-max | 0/12 | — | — | — | — | — | — | — |
| tesseract | 0/12 | — | — | — | — | — | — | — |

## 延迟分布

| 引擎 | 有效样本 | 平均↓ | P50↓ | P90↓ | P99↓ | 最大 | 吞吐 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 12 | 1,531.4 ms | 1,468.3 ms | 2,008.4 ms | 2,191.5 ms | 2,213.0 ms | 39.2 张/分钟 |
| local-qwen25vl-3b | 0 | — | — | — | — | — | — |
| paddleocr | 0 | — | — | — | — | — | — |
| qwen-vl-max | 0 | — | — | — | — | — | — |
| tesseract | 0 | — | — | — | — | — | — |

> 缓存命中样本不计入延迟/成本；样本数 < 100 时 P99 仅供参考。

## 成本核算

| 引擎 | 单张成本 | 每千张(USD) | 每千张(CNY) | 每千分钟(USD) | 每千分钟(CNY) | 完整率↑ | 每提升1pp成本(USD/千张) | 选型 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | $0.000000 | $0.0000 | $0.0000 | $0.0000 | $0.0000 | 99.89% | — | 帕累托 |
| local-qwen25vl-3b | — | — | — | — | — | — | — | — |
| paddleocr | — | — | — | — | — | — | — | — |
| qwen-vl-max | — | — | — | — | — | — | — | — |
| tesseract | — | — | — | — | — | — | — | — |

> 每千分钟成本 = 单张成本 ÷ 单张机时(分钟) × 1000；「每提升 1pp 成本」以最便宜引擎为基线（Δ成本 ÷ Δ完整率百分点）。

## 逐样本对照

配色：<span style="background:#fde2e1;color:#b91c1c">漏提</span> · <span style="background:#dbe7ff;color:#1d4ed8">多提</span> · <span style="background:#fdf0c8;color:#92400e">错认</span>

### 样本 `synth_0001`（场景：合成）

原图：`datasets/hard/images/synth_0001.jpg`

**GT**：结算方式:月结30天银行账号:6222020200112233纳税人识别号:91110108MA01B2C34D检验员:钱七

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 2,017.2 ms | $0.000000 | 结算方式:月结30天银行账号:6222020200112233纳税人识别号:91110108MA01B2C34D检验员:钱七 |
| local-qwen25vl-3b | — | — | — | — | — | 3.4 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.2 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0002`（场景：合成）

原图：`datasets/hard/images/synth_0002.jpg`

**GT**：银行账号:6222020200112233备注:货到验收合格后付款邮政编码:100080序号:0042

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,778.7 ms | $0.000000 | 银行账号:6222020200112233备注:货到验收合格后付款邮政编码:100080序号:0042 |
| local-qwen25vl-3b | — | — | — | — | — | 2.6 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.7 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0003`（场景：合成）

原图：`datasets/hard/images/synth_0003.jpg`

**GT**：数量:120件联系电话:138-0000-1111合同编号:HT-2024-0091金额小写:¥38<span style="background:#fde2e1;color:#b91c1c;text-decoration:line-through">,</span>400.00检验员:钱七发票号码:12345678

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 1.32% | 98.68% | 1.32% | 0.00% | 0.00% | 1,135.3 ms | $0.000000 | 数量:120件联系电话:138-0000-1111合同编号:HT-2024-0091金额小写:¥38400.00检验员:钱七发票号码:12345678 |
| local-qwen25vl-3b | — | — | — | — | — | 3.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.4 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.2 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0004`（场景：合成）

原图：`datasets/hard/images/synth_0004.jpg`

**GT**：产品名称:智能语音识别模块运输方式:公路运输产品名称:智能语音识别模块乙方:上海示例信息技术有限公司

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,713.6 ms | $0.000000 | 产品名称:智能语音识别模块运输方式:公路运输产品名称:智能语音识别模块乙方:上海示例信息技术有限公司 |
| local-qwen25vl-3b | — | — | — | — | — | 2.7 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.6 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0005`（场景：合成）

原图：`datasets/hard/images/synth_0005.jpg`

**GT**：开户银行:中国工商银行北京分行运输方式:公路运输交货日期:2024年6月30日规格型号:VLM-OCR-3000开票日期:2024年05月01日

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,276.9 ms | $0.000000 | 开户银行:中国工商银行北京分行运输方式:公路运输交货日期:2024年6月30日规格型号:VLM-OCR-3000开票日期:2024年05月01日 |
| local-qwen25vl-3b | — | — | — | — | — | 2.6 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.6 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0006`（场景：合成）

原图：`datasets/hard/images/synth_0006.jpg`

**GT**：大写金额:叁万捌仟肆佰元整审核人:王五签发日期:2024年3月15日

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,405.2 ms | $0.000000 | 大写金额:叁万捌仟肆佰元整审核人:王五签发日期:2024年3月15日 |
| local-qwen25vl-3b | — | — | — | — | — | 2.7 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.2 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0007`（场景：合成）

原图：`datasets/hard/images/synth_0007.jpg`

**GT**：电子邮箱:support@example.com提货地点:上海市浦东新区世纪大道100号批准人:赵六

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 2.00% | 100.00% | 0.00% | 2.00% | 0.00% | 2,213.0 ms | $0.000000 | 电子邮箱:<span style="background:#dbe7ff;color:#1d4ed8">s</span>support@example.com提货地点:上海市浦东新区世纪大道100号批准人:赵六 |
| local-qwen25vl-3b | — | — | — | — | — | 3.8 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0008`（场景：合成）

原图：`datasets/hard/images/synth_0008.jpg`

**GT**：乙方:上海示例信息技术有限公司批准人:赵六邮政编码:100080备注:货到验收合格后付款合同编号:HT-2024-0091

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,474.9 ms | $0.000000 | 乙方:上海示例信息技术有限公司批准人:赵六邮政编码:100080备注:货到验收合格后付款合同编号:HT-2024-0091 |
| local-qwen25vl-3b | — | — | — | — | — | 0.9 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0009`（场景：合成）

原图：`datasets/hard/images/synth_0009.jpg`

**GT**：联系电话:138-0000-1111批准人:赵六发票号码:12345678提货地点:上海市浦东新区世纪大道100号规格型号:VLM-OCR-3000发票号码:12345678

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,928.5 ms | $0.000000 | 联系电话:138-0000-1111批准人:赵六发票号码:12345678提货地点:上海市浦东新区世纪大道100号规格型号:VLM-OCR-3000发票号码:12345678 |
| local-qwen25vl-3b | — | — | — | — | — | 2.4 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.2 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0010`（场景：合成）

原图：`datasets/hard/images/synth_0010.jpg`

**GT**：地址:北京市海淀区中关村大街1号数量:120件开票日期:2024年05月01日发票号码:12345678收款人:张三

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,461.7 ms | $0.000000 | 地址:北京市海淀区中关村大街1号数量:120件开票日期:2024年05月01日发票号码:12345678收款人:张三 |
| local-qwen25vl-3b | — | — | — | — | — | 1.8 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0011`（场景：合成）

原图：`datasets/hard/images/synth_0011.jpg`

**GT**：生产批号:20240312A7数量:120件序号:0042经办人:李四

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 927.5 ms | $0.000000 | 生产批号:20240312A7数量:120件序号:0042经办人:李四 |
| local-qwen25vl-3b | — | — | — | — | — | 0.9 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

### 样本 `synth_0012`（场景：合成）

原图：`datasets/hard/images/synth_0012.jpg`

**GT**：银行账号:6222020200112233订购单号:PO-8839201甲方:北京某某科技有限公司产品名称:智能语音识别模块备注:货到验收合格后付款

| 引擎 | CER | 完整率 | 漏提 | 多提 | 错认 | 延迟 | 成本(USD) | 预测（diff 高亮） |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rapidocr | 0.00% | 100.00% | 0.00% | 0.00% | 0.00% | 1,044.7 ms | $0.000000 | 银行账号:6222020200112233订购单号:PO-8839201甲方:北京某某科技有限公司产品名称:智能语音识别模块备注:货到验收合格后付款 |
| local-qwen25vl-3b | — | — | — | — | — | 1.7 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.local[ollama:local-qwen25vl-3b]: 无法连接 http://localhost:11434/api/chat（ConnectionError: HTTPConnectionPool(host='localhost', port=11434): Max retries exceeded with url: /api/chat (Caused by NewConnectionError("HTTPConnection(host='localhost', port=11434): Failed to establish a new connection: [Errno 111] Connection refused"))）。请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。 |
| paddleocr | — | — | — | — | — | 0.2 ms | $0.000000 | ⚠️ 失败：RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。 PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。 请先安装：     uv pip install --python .venv/bin/python paddlepaddle paddleocr     # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：     # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1     # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/ |
| qwen-vl-max | — | — | — | — | — | 0.0 ms | $0.000000 | ⚠️ 失败：AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量 DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，或把 params.api_key_env 指向已存在的环境变量名。（adapter 不会读取硬编码密钥，也不会打印密钥内容） |
| tesseract | — | — | — | — | — | 0.1 ms | $0.000000 | ⚠️ 失败：RuntimeError: 找不到可执行文件 `tesseract`。 Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。 请先安装：     sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng     # macOS: brew install tesseract tesseract-lang     # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract |

## 指标口径

- **CER** = (错认 + 漏提 + 多提) / GT 字数，按字符级编辑距离拆解，越低越好。
- **完整率** = 1 − 漏提率 − 错认率，对应“文字尽可能提全”的业务目标。
- **漏提率** / **多提率** / **错认率** 分别对应 OCR 老毛病与大模型幻觉。
- **行级 F1** 按归一化行文本集合匹配，免疫行序差异；**定位 IoU** 只在有 box 时计算。
- 成本在 run.json 内为 USD，本文按 1 USD = 7.2 CNY 折算。

