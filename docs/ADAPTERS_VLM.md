# VLM 适配层（代码任务 C）

统一在 `adapters/base.py` 的 `BaseEngine` 接口下实现 4 类 VLM 引擎：

| 配置里的 `type` | 类 | 后端 | `device` 语义 |
|---|---|---|---|
| `vlm.openai_compat` | `OpenAICompatVLM` | 任意 OpenAI 兼容 `/chat/completions` | `remote`（不占用本地算力） |
| `vlm.gemini` | `GeminiVLM` | Google Gemini `generateContent` REST | `remote` |
| `vlm.local` | `LocalVLMEngine` | `params.backend` = `ollama` / `openai_compat` / `transformers` | `auto` 按 **cuda -> mps -> cpu** 探测 |

三者都声明 `modalities=("image",)`、`capabilities=("recognize","vqa","extract")`，
runner 仍按既有契约跳过不匹配的任务/模态。

## 1. 新增文件

| 文件 | 作用 |
|---|---|
| `adapters/_http.py` | 私有 HTTP 层：线程内复用 `requests.Session`（缺 requests 时回退 `urllib`）、API Key 解析、状态码中文提示、密钥脱敏、响应片段截断 |
| `adapters/_vlm_util.py` | 私有共享层：图片读取/MIME 嗅探/base64、prompt 优先级、OpenAI/Gemini 响应与 usage 解析、JSON 字段抽取、**device 探测**、`run_openai_compat()` 唯一实现 |
| `adapters/vlm_openai_compat.py` | 注册 `vlm.openai_compat` |
| `adapters/vlm_gemini.py` | 注册 `vlm.gemini` |
| `adapters/vlm_local.py` | 注册 `vlm.local`，内含 `_TransformersBackend` |
| `tests/test_vlm_http_stub.py` | 本地假 HTTP 端点（`127.0.0.1` 随机端口，`ThreadingHTTPServer`），不发任何外部请求 |
| `tests/test_vlm_openai_compat.py` | 13 个用例：请求构造、prompt 优先级、usage/成本、content parts、401、缺 key、缺图、截断、extract |
| `tests/test_vlm_gemini.py` | 9 个用例：endpoint、`x-goog-api-key`、inline_data、usage、安全拦截、缺 key/model |
| `tests/test_vlm_local.py` | 14 个用例：ollama/openai_compat/transformers、device 探测、错误提示 |
| `tests/test_vlm_registry.py` | 5 个用例：`configs/full.yaml` 中全部 VLM 引擎零 key 可构造、类型已注册 |

`_http.py` / `_vlm_util.py` 以下划线开头，`load_builtin_adapters()` 会自动跳过，
不会被当成引擎模块注册。

## 2. `vlm.openai_compat`

请求体（图片走 base64 data URI）：

```json
{
  "model": "qwen-vl-max",
  "messages": [
    {"role": "user", "content": [
      {"type": "text", "text": "<prompt>"},
      {"type": "image_url",
       "image_url": {"url": "data:image/png;base64,...", "detail": "high"}}
    ]}
  ],
  "temperature": 0,
  "stream": false,
  "max_tokens": 4096
}
```

- 端点：`params.endpoint`，否则 `base_url.rstrip('/') + '/chat/completions'`；
  `base_url` 若已写成完整 `.../chat/completions` 也不会重复拼接。
- 文本：`choices[0].message.content`，字符串或 `[{type:text,text}]` 数组都支持。
- usage：`prompt_tokens` / `completion_tokens` / `total_tokens`，
  兼容 `input_tokens` / `output_tokens` 别名；同时写 `images=1, calls=1`。
- `max_tokens` 可改字段名：`params.max_tokens_field: max_completion_tokens`。
- 额外厂商参数放 `params.extra_body`（顶层 merge）或 `params.headers`。

## 3. `vlm.gemini`

- 端点：`params.endpoint`，否则
  `{base_url}/models/{model}:generateContent`；`base_url` 默认
  `https://generativelanguage.googleapis.com/v1beta`。
- 密钥放 **请求头** `x-goog-api-key`，不拼 query，避免日志泄漏。
- 图片：`contents[0].parts[1].inline_data = {mime_type, data}`。
- usage：`usageMetadata.promptTokenCount` / `candidatesTokenCount` /
  `totalTokenCount`（含 `thoughtsTokenCount` 时记为 `reasoning_tokens`）。
- 无 candidates 且 `promptFeedback.blockReason` 存在 -> 中文错误提示被安全策略拒绝；
  `finishReason=MAX_TOKENS` -> 提示调大 `max_tokens`。
- 可选：`system`、`safety_settings`（list，原样透传）、
  `response_mime_type`、`stop_sequences`、`top_p`、`top_k`。

## 4. `vlm.local`

`params.backend` 三选一：

| backend | 端点 | 依赖 | 鉴权 |
|---|---|---|---|
| `ollama` | 默认 `http://localhost:11434/api/chat` | 本机 ollama 服务 + 已 pull 的多模态模型 | 无 |
| `openai_compat` | 默认 `http://localhost:8000/v1/chat/completions` | vLLM / LM Studio / llama.cpp server 等 | 有 `api_key_env` 才加 `Authorization` |
| `transformers` | 进程内加载 | `torch` + `transformers` + `accelerate` + `pillow` | 无 |

### ollama

```json
{
  "model": "qwen2.5vl:3b",
  "messages": [{"role": "user", "content": "<prompt>", "images": ["<base64>"]}],
  "stream": false,
  "options": {"temperature": 0, "num_predict": 2048}
}
```

`base_url` 自动补 `/api/chat`（写成 `.../api` 或 `.../api/chat` 均可）。
usage 取 `prompt_eval_count` / `eval_count`；`total_duration` 等纳秒字段换算成
`*_ms` 放进 `meta`。HTTP 200 但带 `{"error": ...}` 也会抛中文错误。

### openai_compat

复用 `run_openai_compat()`，与在线版请求形状完全一致，但 `require_key=False`：
没有 `api_key_env` / 环境变量时**不**加 `Authorization` 头，适配本地不校验 key 的服务。
`max_new_tokens` 会映射成请求里的 `max_tokens`。

### transformers

- 惰性 import：构造引擎时不 import torch/transformers；缺依赖只在 `predict` 时报错。
- 模型类按 `AutoModelForImageTextToText` -> `AutoModelForVision2Seq` ->
  `AutoModelForCausalLM` 顺序取第一个存在的。
- 优先 `processor.apply_chat_template(...)`，失败则回退 `processor(text=prompt, images=image)`。
- `dtype=auto`：cuda/mps 用 `float16`，cpu 用 `float32`；可显式
  `float16|bfloat16|float32`。
- 单模型 + 锁串行 `generate`，`torch.inference_mode()`，默认 greedy。
- 迁移到 cuda/mps 失败会自动回落 CPU，并把原因写入 `meta.device_probe.reason`。
- `warmup()` 可预加载权重；加载失败不会中断 run，留给 `predict` 记录错误。

### 通用参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `backend` | `ollama` | 仅 `vlm.local`，非法值给出中文可选值列表 |
| `model` | —（必填） | 模型名 / 本地路径 |
| `base_url` | 见上 | 在线必填；本地有默认值 |
| `endpoint` | 空 | 完整 URL，优先级最高 |
| `api_key_env` | 见各引擎 | 只读环境变量名，不硬编码密钥 |
| `prompt` | `DEFAULT_PROMPT` | 直接指定 prompt |
| `prompt_file` | 空 | UTF-8 文本文件；文件不存在报中文错误 |
| `image_detail` | 空 | 仅 OpenAI 兼容：`auto/low/high` |
| `max_tokens` / `max_new_tokens` | 在线 4096，本地 2048 | 两者都认，`max_tokens` 优先 |
| `temperature` | `0` | 默认确定性输出 |
| `timeout_s` | 在线 120，本地 600 | 本地 CPU 推理建议调大 |
| `system` | 空 | 可选 system prompt / systemInstruction |
| `extra_body` / `headers` / `options` | 空 | 厂商/本地服务透传 |
| `device` | `auto` | 仅 `vlm.local`：`auto/cpu/cuda/cuda:N/mps` |
| `dtype` | `auto` | 仅 transformers |
| `trust_remote_code` | `false` | 仅 transformers |
| `local_files_only` | `false` | 仅 transformers，离线加载 |
| `generation_kwargs` | 空 | 仅 transformers，透传 `generate()` |

prompt 优先级：`EngineRequest.prompt` > `params.prompt` > `params.prompt_file` >
`core.config.DEFAULT_PROMPT`。`task="extract"` 且带 `req.schema` 时自动追加
“只输出 JSON”的 Schema 说明，并尝试从返回文本里解析 `fields`。

## 5. device 探测（真实返回）

```python
from adapters._vlm_util import detect_device
detect_device("auto")
```

本机（无 GPU、venv 内无 torch、无 nvidia-smi）实测：

```
auto -> cpu
{"requested": "auto", "torch_available": false, "cuda_available": false,
 "mps_available": false,
 "reason": "torch 不可用（ModuleNotFoundError: No module named 'torch'），无法探测 GPU，回落 CPU"}
cpu -> cpu
{"requested": "cpu", ..., "reason": "显式指定 device，跳过自动探测"}
cuda:0 -> cuda:0
{"requested": "cuda:0", ..., "reason": "显式指定 device，跳过自动探测"}
```

逻辑：
1. 显式 `cpu/cuda/cuda:N/mps` 原样返回（是否真的可用由后端在加载时暴露错误）；
2. `auto` 先 `torch.cuda.is_available()`，再 `torch.backends.mps.is_available()`；
3. 都不可用或 torch 未安装 -> `cpu`，原因写入 `device_probe.reason`；
4. 结果同时进 `Prediction.meta.device / device_requested / device_probe`。

## 6. 上线所需环境变量与安装命令

### 在线

| 引擎 | 环境变量（默认名） | 额外安装 |
|---|---|---|
| `vlm.openai_compat`（通义 qwen-vl-max） | `export DASHSCOPE_API_KEY=...` | `pip install requests`（项目已依赖） |
| `vlm.openai_compat`（OpenAI） | `export OPENAI_API_KEY=...` | 同上 |
| `vlm.openai_compat`（智谱 glm-4v） | `export ZHIPU_API_KEY=...` | 同上 |
| `vlm.gemini` | `export GEMINI_API_KEY=...` | 同上 |

环境变量名以 `configs/full.yaml` 的 `params.api_key_env` 为准；换网关时只改
`base_url` + `model` + `api_key_env`，不用改代码。

### 本地

```bash
# ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
ollama pull qwen2.5vl:3b          # 模型名必须与 params.model 一致
# 无需 Python 额外依赖（走 HTTP）

# OpenAI 兼容本地服务（任选其一）
pip install vllm                  # vLLM
# 或 LM Studio / llama.cpp server / SGLang，把 base_url 指到 .../v1

# transformers
pip install torch transformers accelerate pillow
# GPU 按 CUDA 版本装 torch；Qwen2.5-VL 老版本 transformers 可能还需要：
pip install qwen-vl-utils timm
# 国内网络可先设 HF_ENDPOINT=https://hf-mirror.com
```

本机验证用 venv：`.venv/bin/python`（系统 `python3` 无 pip）。当前 venv 已装
`pytest/requests/pyyaml/pillow` 用于单测；torch/transformers/ollama **未安装**。

## 7. 错误处理：单引擎失败不拖垮 run

`BaseEngine.predict()` 会捕获 `_predict()` 的一切异常写入 `Prediction.error`，
因此本层所有错误都按“抛异常 + 中文原因”实现，构造阶段（`build_engine`）不校验
key、不加载模型。缺 key / 缺依赖 / 服务未启动时实测：

```
[qwen-vl-max] ok=False device=remote
  error: AdapterHTTPError: vlm.openai_compat[qwen-vl-max]: 缺少 API Key，未设置环境变量
         DASHSCOPE_API_KEY。请先执行 `export DASHSCOPE_API_KEY=<your-key>`，...
[gemini] ok=False device=remote
  error: AdapterHTTPError: vlm.gemini[gemini]: 缺少 API Key，未设置环境变量 GEMINI_API_KEY...
[local-qwen25vl-3b] ok=False device=cpu
  error: AdapterHTTPError: vlm.local[ollama:...]: 无法连接 http://localhost:11434/api/chat
         （ConnectionError: ... Connection refused）。请检查 base_url / 网络；
         本地 ollama 需先 `ollama serve`，本地 OpenAI 兼容服务需确认端口已启动。
```

覆盖的错误类型：缺 key、缺图/图片路径不存在/空文件、HTTP 400/401/403/404/413/
429/5xx、非 JSON 响应、超时、连接失败、空文本、输出截断、Gemini 安全拦截、
ollama `{"error": ...}`、非法 `backend`、缺 `model`、transformers 缺依赖/OOM。
异常文本会脱敏 URL 里的 `key=` / `token=`，且不会回显 `api_key`。

## 8. 成本核算

沿用 `BaseEngine.compute_cost()`：在线 usage 提供 `input_tokens/output_tokens`，
所有引擎提供 `images=1, calls=1`。`configs/full.yaml` 里的
`input_per_1m/output_per_1m/per_image` 直接生效，无需 adapter 额外处理。

## 9. 单元测试（真实 pytest 输出）

全部用本机 `http.server` 假端点 + `requests` 发真实本地 HTTP 请求，**不发外部 API 请求**：

```bash
$ .venv/bin/python -m pytest -q
........................................                                 [100%]
41 passed in 0.81s
```

分文件：

```bash
$ .venv/bin/python -m pytest tests/test_vlm_openai_compat.py -q
13 passed
$ .venv/bin/python -m pytest tests/test_vlm_gemini.py -q
9 passed
$ .venv/bin/python -m pytest tests/test_vlm_local.py -q
14 passed
$ .venv/bin/python -m pytest tests/test_vlm_registry.py -q
5 passed
```

覆盖点：请求路径/头/JSON 结构、base64 图片字节回解一致、prompt 优先级、
usage token 映射、成本公式、content parts 拼接、每个错误分支、device 探测、
`configs/full.yaml` 全部 VLM 引擎零 key 可构造。

## 10. 未验证项（明确标注）

- **没有真实调用任何在线 API**：本机无 `DASHSCOPE_API_KEY / OPENAI_API_KEY /
  ZHIPU_API_KEY / GEMINI_API_KEY`，在线路径只验证到“请求构造 + 本地假端点响应解析”。
  真实网关的字段差异（如某些厂商 `max_tokens` 上限、图片大小限制、限流策略）未验证。
- **没有真实 ollama 服务/模型**：本机无 ollama、未 pull 模型，只验证了 HTTP 协议层。
  `qwen2.5vl:3b` 实际输出质量、CPU 延迟、`num_predict` 行为未测。
- **没有真实 transformers 推理**：venv 无 torch/transformers/模型权重，仅验证了
  缺依赖错误提示与“构造不 import 重型依赖”。不同模型的 chat template、processor
  `images=` 参数、`trust_remote_code` 需求需在目标机实测。
- **CUDA / MPS 分支未在真机跑过**：本机无 GPU（`nvidia-smi` 不存在），`auto` 实测
  回落 `cpu`。cuda->mps->cpu 的探测顺序代码已实现，但 cuda/mps 真实可用性未验证。
- **Gemini 安全阈值 / `safety_settings`**：只验证了 mock 的 `blockReason` 分支，
  真实拒答行为未验证。
- 图片目前仅支持 image 模态；视频/音频未接入（`modalities` 只有 `image`）。
- 大图会整段 base64 进内存，未做压缩/分块；超大图可能触发 413，需要上游先缩放。

## 11. 扩展新后端

1. 在 `vlm_local.py` 里加一个 `_predict_xxx()` 或后端类；
2. 在 `SUPPORTED_BACKENDS` 注册名字；
3. 复用 `load_image / resolve_prompt / append_schema / maybe_parse_fields`
   保证 prompt、图片、字段抽取行为一致；
4. 补 `tests/test_vlm_local.py` 的假端点用例（不请求外部服务）。
