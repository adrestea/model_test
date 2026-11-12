# 任务状态清单

> 项目：`/home/archermind/workspace/ai-stack/model_test`（vlm-ocr-eval，OCR / VLM 图文识别评测与选型系统）
> 更新：2026-11-12 · 由主控逐项实测后落笔
> 标记含义：`[x]` 已实测通过 ｜ `[~]` 代码+单测就绪但未真跑外部 ｜ `[ ]` 未做/阻塞

---

## A. 环境（☑ 全部完成）

- [x] 定位卡点：pypi.org 不通（超时），切阿里云镜像写入 `~/.config/uv/uv.toml`
- [x] 用 uv 装出 `.venv`（Python 3.10.12，系统 python3 无 pip）
- [x] 基线依赖：pyyaml / pillow / numpy / pandas / jinja2 / click / jsonschema / requests / pytest
- [x] 本地 OCR 依赖：rapidocr-onnxruntime 1.4.4 + onnxruntime（**可真跑**）
- [x] 中文字体确认：`/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`
- [ ] tesseract 二进制 + 中文语言包（无 sudo，未装）
- [ ] paddleocr / paddlepaddle（未装，wheel 数百 MB）
- [ ] 在线 API key（DASHSCOPE / OPENAI / ZHIPU / GEMINI 均无）
- [ ] ollama 服务（未装，本机无 GPU）

---

## B. 核心骨架（☑ 完成）

- [x] `core/types.py` — 数据契约：Modality/Task/Box/Line(含 start_ms/end_ms)/GroundTruth/EngineRequest/Prediction/SampleMetrics/RunResult
- [x] `adapters/base.py` — BaseEngine + `@register` 注册表 + 统一计量/异常兜底/成本核算（token/张/秒/分钟/次）
- [x] `core/config.py` — YAML→RunConfig，模态化 media_dir 解析，引擎 id 去重校验
- [x] `core/dataset.py` — 样本扫描（image/video/audio 扩展名分流）+ L1/L2/L3 三级标注解析
- [x] `core/text.py` — 文本归一化 + 字符级编辑距离拆解
- [x] 契约冻结纪律：`core/types.py`、`adapters/base.py` 全程未被 worker 擅自修改

---

## C. 引擎适配（6 类 8 个引擎 id）

- [x] `ocr.rapidocr` — 本地 CPU，真跑通（12 张难样本 CER 0.28%）
- [~] `ocr.tesseract` — adapter 完整，缺二进制时中文报错+安装命令已验证；真实识别未跑
- [~] `ocr.paddleocr` — 同上，缺包降级已验证；真实识别未跑
- [~] `ocr.cloud` — 阿里/腾讯/百度，缺 key 报错已验证；真实请求未跑
- [~] `vlm.openai_compat` — 覆盖 Qwen-VL/GPT-4o/GLM-4V，41 个 mock 单测；真实请求未跑
- [~] `vlm.gemini` — mock 单测通过；真实请求未跑
- [~] `vlm.local` — ollama / openai_compat / transformers 三后端 + `device=auto`（cuda→mps→cpu）；只验证到探测与请求构造，真实推理未跑
- [x] `mock.text` — 测试用假引擎

---

## D. 指标（☑ 完成并实测）

- [x] CER 拆解 SUB / DEL / INS（区分 OCR 漏提 vs 大模型幻觉）
- [x] 完整率 = 1 − SUB − DEL（对应「文字提全」目标）
- [x] 行级 P/R/F1（按行集合匹配，免疫行序差异）
- [x] 定位 IoU（区分「真读到」与「猜到内容」）
- [x] 完全匹配率 / 漏多错字数
- [x] 延迟 P50/P90/P99 + 吞吐（张/分钟）
- [x] 每千张 / 每千分钟成本（USD + CNY，汇率可配）

---

## E. 执行层（☑ 完成并实测）

- [x] 引擎 × 数据集 × 任务矩阵执行、并发、重试
- [x] 单引擎失败隔离（12 样本 × 5 引擎，4 个引擎全失败不影响整体）
- [x] 预测缓存 + 断点续跑（实测二次跑 5.385s → 0.504s）
- [x] 缓存 key 含媒体字节 + 参数指纹 + task + **有效 prompt 内容**（含 prompt_file 内容，已修）
- [x] 结果落盘 `results/<run>/run.json`（config + env + 全量预测 + 全量指标）

---

## F. 报告（☑ 完成并实测）

- [x] 自包含 HTML（图片 base64 内嵌，0 外链，断网可看）
- [x] 中文 Markdown + 4 个 CSV（engines/samples/scenes/costs）
- [x] 引擎总榜（CER/完整率/漏提/多提/延迟/成本多维排序 + 帕累托前沿标注）
- [x] 选型结论自动生成（含「升级 X 换 +N 个百分点成本多少」）
- [x] 逐样本对照 + 字符级 diff 高亮（漏提红 / 多提蓝 / 错认黄）
- [x] 分场景分组、延迟分布、成本核算

---

## G. 基线（☑ 完成并实测）

- [x] `baseline freeze` 冻结快照
- [x] `baseline diff` 指标涨跌 + 变好/变坏样本清单
- [x] 缺陷修复：全部命中缓存时延迟/成本误报「缺失」→ 现显示「缓存命中」
- [x] `tests/test_baseline.py` 7 项通过

---

## H. 数据集与标注工具（☑ 完成并实测）

- [x] `dataset inspect` — 图片数 / 标注覆盖率 / 有无 box / meta（真实输出已验证）
- [x] `synth` — PIL 合成数据集，自动产带真实像素 box 的 L2 标注，支持字体/字号/行数/噪点/模糊/旋转/JPEG 质量/缩放/seed
- [x] `label draft` — 指定引擎生成草稿 GT（3 张无标注图 → 3 个 json，已验证）
- [x] `label review` — 本地 HTML 校正页（102KB，0 外链，可导出标准标注）
- [ ] 校正页的人工交互（浏览器改字→下载→拷回）只有静态渲染验证，无真人操作验证

---

## I. 文档（☑ 完成）

- [x] `README.md` — 安装/目录规范/跑矩阵/出报告/基线/降级行为/加新引擎/加新模态/缓存/测试/未验证项（11 节）
- [x] `docs/ARCH.md` — 分层与依赖硬规则、模态解耦扩展点、指标插件约定、评估口径理由
- [x] `datasets/README.md` — 三级标注规范 + 无标注时的兜底流程
- [x] `docs/OCR_ADAPTERS.md`、`docs/ADAPTERS_VLM.md`

---

## J. 测试（☑ 141 passed / 14 个测试文件）

- [x] 全仓 `.venv/bin/python -m pytest -q` → **141 passed**
- [x] 指标 / 文本归一化 / 引擎注册 / OCR adapter / VLM（41 个 mock）/ runner / baseline / CLI / 工具 / 端到端报告 / cache prompt_file

---

## K. 端到端实测记录（可复现命令）

- [x] `cli.py dataset inspect smoke` → 3 张 / 标注覆盖 100% / 含 box 3
- [x] `cli.py synth --name hard --count 12 --noise 8 --blur 0.8 --rotate 1.2 --jpeg-quality 60` → 12 张 + L2 标注
- [x] `cli.py run -c configs/hard.yaml` → 5 引擎 × 12 样本，rapidocr CER 0.28% / 完整率 99.89% / 定位 IoU 0.89
- [x] `cli.py report results/hard` → report.html + report.md + 4 CSV
- [x] `cli.py baseline freeze results/hard` + `baseline diff results/hard hard` → 全指标「持平」+ 缓存命中标注
- [x] `cli.py label draft /tmp/nogt --engine '{"type":"ocr.rapidocr"}'` → 3 个草稿标注
- [x] `cli.py label review /tmp/nogt` → results/label_review/nogt.html（0 外链）

---

## L. 待你配合（阻塞真实选型）

- [ ] 放入真实语料：`datasets/<场景名>/images/` + `labels/<同名>.json`（L2 带 box 最可信）
- [ ] 没有标注则先 `label draft` 出草稿，再 `label review` 人工校对
- [ ] 装 tesseract：`sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng`
- [ ] 配 API key：`DASHSCOPE_API_KEY` / `OPENAI_API_KEY` / `ZHIPU_API_KEY` / `GEMINI_API_KEY`
- [ ] 本地 VLM：装 ollama 后 `ollama pull qwen2.5vl:3b`（无 GPU 走 CPU，秒级/图）
- [ ] 决定要不要开 P2「结构化字段抽取」（OCR 侧需额外 2~3 天做版面后处理）

---

## M. 已知未验证项（诚实声明，README §11 同步）

- [ ] tesseract / paddleocr 真实识别结果
- [ ] 所有在线引擎与云 OCR 真实请求
- [ ] 本地 VLM（ollama / transformers）真实推理
- [ ] GPU / CUDA 路径真机
- [ ] 视频 / 音频模态端到端（接口与计费口径已预留）
- [ ] `configs/full.yaml` 全量 8 引擎整体跑通（缺 `datasets/invoice` 语料）

---

## N. 过程问题记录

- [x] 3 个 worker 因账户 5 小时配额打满（429）中途退出，`tools/`、`report/stats.py` 语法错误、README、baseline 缓存缺陷由主控接手修完并实测
- [x] `report/stats.py` 中文嵌套引号导致 SyntaxError → 改用「」
- [x] 6 个已结束 worker 需用 `/team-stop` 清理（操作员动作）
