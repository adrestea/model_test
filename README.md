# vlm-ocr-eval — OCR / VLM 图文识别评测与选型系统

一套**引擎无关**的多模态识别评测框架：把「引擎 × 数据集样本 × 任务」跑成矩阵，
统一算 **CER / SUB / DEL / INS / 完整率 / 行 F1 / 定位 IoU / 延迟 / 成本**，落盘可复现结果，
再渲染 HTML / Markdown / CSV 报告、支持基线冻结与对比。

> 仓库根没有 `veval` 可执行文件（未安装到系统），统一用
> `.venv/bin/python cli.py ...` 调用；装包用 `~/.local/bin/uv pip install --python .venv/bin/python <pkg>`。
> 下文所有命令都以此为前提。

---

## 1. 安装

本机已验证环境：Python 3.10 + `.venv`，已安装 `rapidocr-onnxruntime`（真跑通）。

```bash
# 建虚拟环境（如尚未有 .venv）
python3.10 -m venv .venv

# 装依赖（已配阿里云镜像，不要连 pypi.org，会超时）
~/.local/bin/uv pip install --python .venv/bin/python -e .
~/.local/bin/uv pip install --python .venv/bin/python pytest pytest-cov

# 传统 OCR：本地 CPU 可直接跑的引擎
~/.local/bin/uv pip install --python .venv/bin/python rapidocr-onnxruntime onnxruntime

# 本地 VLM（需要 GPU/大内存，可选）
~/.local/bin/uv pip install --python .venv/bin/python transformers torch accelerate pillow
```

各引擎依赖的完整安装命令与「本机是否验证过」见 [docs/OCR_ADAPTERS.md](docs/OCR_ADAPTERS.md)
与 [docs/ADAPTERS_VLM.md](docs/ADAPTERS_VLM.md) 的依赖表。缺依赖不会让 run 崩（见 §6）。

### 目录规范

```
datasets/<数据集名>/            # 一个场景一个子目录，按目录名识别数据集
  images/                       # 图片：jpg/jpeg/png/bmp/webp/tif/tiff/pdf
  labels/                       # 标注：<stem>.txt(L1全文) / <stem>.json(L2行级/L3字段级)
  meta.yaml                     # 可选：语言/场景/来源
configs/*.yaml                  # 评测配置（engine 矩阵 + run 参数）
results/<run>/run.json          # 每次 run 的完整结果（可重放/喂报告）
results/<run>/summary.json      # 聚合摘要
results/baselines/<name>.json   # 冻结基线
results/<run>/report/           # 渲染出的报告（html/md/csv）
```

样本 ID = 文件名去掉扩展名（`001.jpg` → `001`）。三级标注规范与 box 格式见
[datasets/README.md](datasets/README.md)。

---

## 2. 快速自检（真跑通）

```bash
.venv/bin/python cli.py run -c configs/smoke.yaml
```

`configs/smoke.yaml` 指向 `datasets/smoke`（3 张中文图）+ `ocr.rapidocr`（纯 CPU）。
**本机真实输出**：

```
运行完成：smoke｜样本 3 个｜预测 3 条
引擎      样本  成功  错误率    CER    SUB    DEL    INS  完整率   行F1  定位IoU  P50(ms)  P90(ms)  成本/千
rapidocr     3     3    0.0%  0.000  0.000  0.000  0.000   1.000  1.000    0.951   1343.8   1385.4   0.0000
结果已落盘：results/smoke/run.json
```

CER=0.000 / 完整率 1.000 / 定位 IoU 0.951，证明「读文本 → 跑模型 → 算指标 → 落盘」整链路可用。

---

## 3. 跑矩阵

矩阵 = `configs/*.yaml` 里的 `engines` × `dataset` 样本 × `tasks`。

```bash
# 全量选型矩阵（8 引擎；本机只有 rapidocr 可用，其余会优雅降级，见 §6）
.venv/bin/python cli.py run -c configs/full.yaml

# 只跑前 N 张（冒烟）
.venv/bin/python cli.py run -c configs/full.yaml --limit 10

# 只跑指定引擎（逗号分隔，必须是配置里已有 id）
.venv/bin/python cli.py run -c configs/full.yaml --engines rapidocr,tesseract

# 并发覆盖 / 关缓存 / 自定 run 名
.venv/bin/python cli.py run -c configs/smoke.yaml --concurrency 4 --no-cache
.venv/bin/python cli.py run -c configs/smoke.yaml --run-name my-run
```

配置字段（`run` 块）：`name / dataset / tasks / concurrency / retries / repeats / cache /
timeout_s / normalize / out_dir / strict`；`engines` 是 `[{id, type, params, cost}]` 列表。
完整示例见 `configs/full.yaml`（含注释）。

关键口径：
- **CER 拆成 SUB/DEL/INS**：漏提(DEL)高是 OCR 典型，幻觉多提(INS)高是大模型典型，只看总 CER 会误判选型。
- **完整率 = 1 − DEL − SUB**；**行 F1** 按行集合匹配、免疫行序差异；**定位 IoU** 区分「真读到」与「猜对内容但位置乱」。
- **延迟/成本**：`repeats>1` 才取中位延迟；成本按 `cost` 配置分项累加，本地引擎填 `per_image: 0`。

---

## 4. 出报告

报告渲染是 Python API（CLI 目前只有 `run` 与 `baseline` 两个子命令，没有 `report` 子命令）：

```bash
.venv/bin/python - <<'PY'
from report.render import render_all
render_all("results/smoke/run.json", "results/smoke/report")
PY
```

输出 6 个文件：`report.html`、`report.md`、`engines.csv`、`samples.csv`、`scenes.csv`、`costs.csv`。
**本机真实输出**（smoke-base）：

```
=== smoke-base ===
  costs.csv:  results/smoke-base/report/costs.csv
  engines.csv: results/smoke-base/report/engines.csv
  html:        results/smoke-base/report/report.html
  md:          results/smoke-base/report/report.md
  samples.csv: results/smoke-base/report/samples.csv
  scenes.csv:  results/smoke-base/report/scenes.csv
```

`render_all` 第二参是输出目录，第三参可传 `ReportOptions(title=..., sort="cer", rate=7.2, formats=("html","md","csv"))`。
报告只读 `RunResult`，不重新推理。

---

## 5. 基线冻结与对比

```bash
# 冻结一次 run 为基线
.venv/bin/python cli.py baseline freeze results/smoke-base/run.json
# 或按 run 名解析（自动找 results/<name>/run.json）
.venv/bin/python cli.py baseline freeze smoke-base

# 对比当前 run 与基线
.venv/bin/python cli.py baseline diff results/smoke-current/run.json results/baselines/smoke-base.json
```

**本机真实 freeze 输出**：

```
基线已冻结：results/baselines/smoke-base.json（来源 results/smoke-base/run.json，run=smoke-base）
```

**本机真实 diff 输出**（同配置再跑一次，CER 持平、延迟因 CPU 热身后变小被判「变好」）：

```
基线对比：当前 run=smoke-current（results/smoke-current/run.json）｜基线 run=smoke-base（results/baselines/smoke-base.json）
口径：指标为成功样本均值；CER/SUB/DEL/INS/错误率/延迟/成本 越小越好，完整率/行F1/定位IoU 越大越好。

引擎      指标                   基线       当前      变化    结论
rapidocr  CER                  0.0000     0.0000   +0.0000    持平
rapidocr  完整率               1.0000     1.0000   +0.0000    持平
rapidocr  定位 IoU             0.9511     0.9511   +0.0000    持平
rapidocr  延迟 P50(ms)      1343.7898  1284.2180  -59.5718  ↑ 变好
rapidocr  成本/千样本(USD)     0.0000     0.0000   +0.0000    持平

样本级变化（按 CER）：变好 0｜变坏 0｜持平 3｜缺失 0
```

样本集不一致时（例如用 `--limit 2` 跑当前 run 去比 3 样本基线），会显式警告并计「缺失」：

```
⚠ 样本集不一致（rapidocr 基线 3 条/当前 2 条）：均值涨跌含样本构成变化，请结合样本级变化判断。
样本级变化（按 CER）：变好 0｜变坏 0｜持平 2｜缺失 1
```

常用参数：`--json`（机器可读）、`--all`（展示全部指标）、`--top N`（每类样本变化展示条数）。

---

## 6. 多引擎矩阵的降级行为（真实验证）

单个引擎「构建失败 / 缺依赖 / 无在线 key / 服务不在线」**不会炸掉整个 run**：
它会记为 engine 构建错误或样本级 error，其余引擎照常出分。

验证配置 `configs/degrade-matrix.yaml`（rapidocr + tesseract + paddleocr + qwen-vl-max + gemini + 本地 ollama）：

```bash
.venv/bin/python cli.py run -c configs/degrade-matrix.yaml --run-name degrade
```

**本机真实报错文本**：

```
引擎构建失败（已跳过）:
  - tesseract: warmup 失败 RuntimeError: 找不到可执行文件 `tesseract`。
Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。
请先安装：
    sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng
    ...
  - paddleocr: warmup 失败 RuntimeError: 缺少依赖 paddleocr（ModuleNotFoundError: No module named 'paddleocr'）。
PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。
请先安装：
    uv pip install --python .venv/bin/python paddlepaddle paddleocr
    ...
```

各失败/在线引擎落在样本级 error（不中断）：`gemini` / `qwen-vl-max` → `AdapterHTTPError: 缺少 API Key…`；
`local-qwen` → `AdapterHTTPError: 无法连接 http://localhost:11434/api/chat（ConnectionError: …Connection refused…）`。

**被跳过的组合**（`tasks` 含 `vqa`，而三个 OCR 引擎能力只有 recognize/lines/boxes）：

```
跳过不支持的组合 3 个：
  - 任务不支持：engine capabilities=['recognize', 'lines', 'boxes']（3 个）
```

对应 run.json `env.skipped.examples` 里是 `rapidocr/tesseract/paddleocr` 三条的 `task=vqa` 跳过记录。
「模态不匹配」跳过逻辑同理（例如视频数据集配 image 引擎会记「模态不匹配」）。

> 结论：RapidOCR 3/3 成功（CER=0），tesseract/paddleocr 记 warmup 失败，3 个在线/VLM 引擎每样本记
> 缺 key/连接失败，整个 run 仍正常落盘并渲染报告。这就是「优雅降级」的真实表现。

---

## 7. 加新引擎

最少三步，`core/`、`runner/`、`metrics/`、`report/` 零改动：

1. 新建 `adapters/<你>.py`，继承 `BaseEngine` 并注册：

```python
from adapters.base import BaseEngine, register
from core.types import EngineOutput, EngineRequest

INSTALL_CMD = "~/.local/bin/uv pip install --python .venv/bin/python <你的依赖>"


@register("your.type")  # 配置里 type 用这个字符串
class YourEngine(BaseEngine):
    type_name = "your.type"
    capabilities = ("recognize", "lines", "boxes")   # 支持的任务
    modalities = ("image",)                          # 支持的输入模态

    def _predict(self, req: EngineRequest) -> EngineOutput:
        # 这里调你的模型；缺依赖用 require_module/require_binary 抛中文错误
        # 填 text（全文）/ lines（行级，带 box）/ fields（抽取）
        return EngineOutput(text="识别结果", lines=[...])

    def warmup(self):  # 可选：预加载模型，不计入样本延迟
        ...
```

2. 配置里加一条：

```yaml
engines:
  - { id: my-engine, type: your.type, params: { ... }, cost: { per_image: 0.001 } }
```

3. 写单测：`tests/test_your_engine.py`，用已有 fake engine 做模板，缺依赖场景断言报中文错误。

`load_builtin_adapters()` 会自动发现 `adapters/` 下所有非下划线模块；模块导入失败会静默跳过
（`VEVAL_DEBUG=1` 时打印），不会因此报「未注册类型」。

## 8. 加新模态（视频 / 音频）

模态已贯穿全链路，加新模态只增加文件、不改 core 既有接口：

1. `adapters/<video_asr>.py`：`modalities=("video",)`，抽帧/整段送模型，结果填
   `lines=[Line(text, start_ms, end_ms)]`。
2. 数据集建 `datasets/<name>/videos/`（或 `audios/`），`labels/<stem>.json` 带时间戳行。
3. `metrics/` 注册时间轴指标插件（如 `segment_f1`），报告自动带表头。
4. 配置里加一条引擎；runner 会按 `engine.modalities` 与样本模态自动跳过不匹配组合。

详细设计见 [docs/ARCH.md](docs/ARCH.md)「模态解耦」一节。

---

## 9. 缓存与 prompt_file 失效

预测缓存 key 覆盖：**媒体字节 + engine_id + 参数指纹 + task + 有效 prompt + 归一化口径**。
命中缓存不重复计延迟/成本（meta 里保留原始值），所以重跑不会把性能刷漂亮。

- 改参数、改归一化、改 prompt、**改 prompt 文件内容**（路径不变）都会让缓存失效。
- 之前 `param_fingerprint()` 只哈希 `params`（prompt_file 只算了路径字符串），改文件内容缓存不失效；
  **已在 `runner/cache.py` 修复**：缓存键里的 prompt 分量复用 `resolve_prompt()`，按
  `req.prompt > params.prompt > params.prompt_file 内容 > 默认 prompt` 取实际生效的 prompt 摘要。
- 缓存目录默认 `.cache/predictions`，配置里 `run.cache_dir` 可覆盖；`--no-cache` 关闭。
- 缓存即断点：同一配置重跑，命中缓存的样本直接复用，只跑新增/变化部分。

---

## 10. 测试

```bash
.venv/bin/python -m pytest -q
```

**本机真实输出**（本文档交付前）：

```
122 passed in 9.37s
```

覆盖：runner 矩阵/重试/超时/重复/缓存/落盘、baseline freeze/compare/diff、CLI 端到端、
OCR/VLM adapter 缺依赖报错、以及新增的 `tests/test_cache_prompt_file.py`（改 prompt 文件缓存失效回归）
与 `tests/test_e2e_report.py`（合成数据 + 真实 smoke 数据集 → run → 报告全链路）。

---

## 11. 未验证项（明确声明，未伪造）

以下内容在本机**未真跑**过，文档/代码保留接口与单测覆盖，但未做真实端到端验证：

- **tesseract / paddleocr 真实识别结果**：系统未装二进制/包，无 sudo，只验证过「缺依赖的报错路径」与 TSV/PP-OCR 返回结构解析单测。
- **所有在线引擎的真实请求**（qwen-vl-max / gpt-4o-mini / glm-4v / gemini / 云 OCR aliyun/tencent/baidu）：无任何 API key，只验证缺 key 报错与离线假响应解析。
- **本地 VLM（ollama / transformers）真实推理**：无 GPU、无 ollama 服务，只验证 device 探测与请求构造。
- **视频 / 音频模态**：框架预留了 `media_bytes / duration_s / Line.start_ms/end_ms` 与按秒/分钟计费，数据与端到端跑通未验证。
- **GPU / CUDA 路径**：`device: cuda*` 的映射逻辑在，未真机验证。
- **`configs/full.yaml` 全量 8 引擎矩阵**：引用的 `datasets/invoice` 语料本机不存在，未整体跑通；等量级验证见 §6 的 degrade 矩阵（用了 `datasets/smoke`）。
- `label draft/review`、`dataset inspect`、`synth` 四个子命令已实现并经主控实测（见下节命令记录），但**校正页的人工交互**（浏览器里改字、点下载、拷回）只有静态渲染验证，未做真人操作验证。