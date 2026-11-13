# 任务状态清单

> 项目：`/home/archermind/workspace/ai-stack/model_test`（vlm-ocr-eval，OCR / VLM 图文识别评测与选型系统）
> 更新：2026-11-13 · 由主控逐项实测后落笔
> 标记含义：`[x]` 已实测通过 ｜ `[~]` 代码+单测就绪但未真跑外部 ｜ `[ ]` 未做/阻塞

---

## A. 环境（☑ 全部完成）

- [x] 定位卡点：pypi.org 不通（超时），切阿里云镜像写入 `~/.config/uv/uv.toml`
- [x] 用 uv 装出 `.venv`（Python 3.10.12，系统 python3 无 pip）
- [x] 基线依赖：pyyaml / pillow / numpy / pandas / jinja2 / click / jsonschema / requests / pytest
- [x] 本地 OCR 依赖：rapidocr-onnxruntime 1.4.4 + onnxruntime（**可真跑**）
- [x] 中文字体确认：`/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`
- [ ] tesseract 二进制 + 中文语言包（无 sudo，未装）
- [x] paddleocr / paddlepaddle —— **本机不可用**：无 `avx512f`，paddle 2.6.2 首推理即 SIGILL；
      已实测后卸载回滚（详见 Q 段）。镜像无 2.5.2
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
- [ ] `ocr.paddleocr` — adapter 完整（2.x/3.x 双 API），但**本机装不上也跑不了**：
      无 `avx512f` → `SelfAttentionFusePass` SIGILL，关 mkldnn 无效；见 Q 段
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

## J. 测试（☑ 155 passed / 15 个测试文件）

- [x] 全仓 `.venv/bin/python -m pytest -q` → **155 passed**
- [x] 指标 / 文本归一化 / 引擎注册 / OCR adapter / VLM（41 个 mock）/ runner / baseline / CLI / 工具 / 端到端报告 / cache prompt_file / md_gt 对齐（14 项）

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

- [x] 放入真实语料第一批：`datasets/docshot/`（2 张 1834×928 密集小字截图，来自 Perfetto 路线图 .md 源码）
- [ ] 扩充真实语料：`datasets/<场景名>/images/` + `labels/<同名>.json`（L2 带 box 最可信）——2 张相似样本不足以支撑选型
- [ ] 没有标注则先 `label draft` 出草稿，再 `label review` 人工校对；文档截图优先用 `tools/md_gt.py`
- [ ] 装 tesseract：`sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng`
- [ ] 配 API key：`DASHSCOPE_API_KEY` / `OPENAI_API_KEY` / `ZHIPU_API_KEY` / `GEMINI_API_KEY`
- [ ] 本地 VLM：装 ollama 后 `ollama pull qwen2.5vl:3b`（无 GPU 走 CPU，秒级/图）
- [ ] 决定要不要开 P2「结构化字段抽取」（OCR 侧需额外 2~3 天做版面后处理）

---

## M. 已知未验证项（诚实声明，README §11 同步）

- [ ] tesseract 真实识别结果
- [x] paddleocr 真实识别结果 → **本机不可用，见 P 段**（已实测，非推测）
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

---

## O. macOS arm64 复跑记录（2026-11-13，与 A~/K 的 Linux 记录并存）

> 上文 A~/K 是本项目在 Linux x86_64 + Python 3.10.12 上的原始记录；本段是在
> `/Users/gaogao/workspace/model_test`（macOS arm64 + Python 3.12.7）上的独立复跑，
> 两套环境都真实可跑，命令完全一致。

- [x] 环境：`uv venv .venv`（Python 3.12.7）→ `uv pip install -e . pytest rapidocr-onnxruntime onnxruntime`；
      `.venv` 325MB，项目外只写 `~/.cache/uv`，无 sudo、无系统包
- [x] 修跨平台缺陷：`tools/synth.py` 原本硬编码 Linux 的 Noto 字体路径，macOS 上 `synth` 与 6 个工具用例全失败；
      改为 `FONT_CANDIDATES` + `find_default_font()`，本机选中 `/System/Library/Fonts/Hiragino Sans GB.ttc`
- [x] 回归：修前 6 failed / 135 passed，修后 **141 passed in 3.87s**（与 Linux 3.10.12 的 141 一致）
- [x] `cli.py run -c configs/smoke.yaml --run-name smoke-mac` → 3/3 成功，CER 0.000，完整率 1.000，
      行 F1 1.000，定位 IoU 0.951，P50 **354.9ms** / P90 407.6ms（Linux 同配置为 1343.8ms）
- [x] `cli.py report results/smoke-mac -o results/smoke-mac/report` → 6 个文件，`report.html` 41K，0 外链
- [x] `cli.py baseline diff results/smoke-mac/run.json results/baselines/smoke-base.json` →
      全部指标「持平」，P50 显示「变好 -988.9ms」；该差值来自机器，不是引擎变化
- [x] `cli.py synth --out-root /tmp/synthcheck -n 4 --noise 6 --blur 0.6 --rotate 1.0 --jpeg-quality 70`
      → 标注覆盖 4/4、像素 box 4 个；rapidocr 跑出 CER 0.004、行 F1 0.787、IoU 0.747
- [x] 缓存与断点续跑：同配置重跑 4 张 **0.873s → 0.148s**，延迟列显示「缓存命中」
- [x] `cli.py run -c configs/degrade-matrix.yaml --run-name degrade-mac` → rapidocr 3/3；
      tesseract 报缺二进制（提示含 `brew install tesseract tesseract-lang`）；paddleocr 报缺依赖；
      gemini / qwen-vl-max 报缺 key；local-qwen 报 11434 连接被拒；3 个 vqa 组合按能力跳过；run 正常落盘
- [x] 缓存跨平台有效：`hard` 12 张全部命中 Linux 时期缓存，`env.platform` 记为 `macOS-27.0-arm64-arm-64bit`
- [x] `cli.py label draft` 3 张草稿 + `cli.py label review` → 63K 校正页，无外链
- [x] 打包缺陷修复验证：`pyproject.toml` 的 `packages.find.include` 补 `report*`、`tools*` 后，
      `uv build` 出的 wheel 顶层含 `report/` 与 `tools/`；装进临时 venv 后在 `/tmp` 执行 `veval report` 成功
- [ ] 本段仍未验证：tesseract / paddleocr / 云 OCR / 在线 VLM / 本地 ollama 的真实识别结果（缺二进制、缺包、缺 key、缺服务）；
      GPU / CUDA 路径；视频 / 音频模态；`.pdf` 样本实际报错文本

---

## P. 真实语料接入：docshot + .md 反推标注（2026-11-13）

用户提供 2 张截图（`20261113091044_51_67.png` / `20261113112745_52_67.png`，Perfetto+Simpleperf
路线图的密集小字截屏，中英+代码+表格混排）与对应 `.md` 源文件，落地为 `datasets/docshot/`。

- [x] 目录落位：`datasets/docshot/{images,markdown,labels}` + `meta.yaml`（lang=mixed / scene=文档截图 / 5 项 hard_cases）
- [x] 新增 `tools/md_gt.py`：**只用 OCR 定位「截图照的是 .md 第几行到第几行」，标注内容取自 .md 原文**，
      避免「拿被测引擎输出当标准答案」的自证循环；对齐按行区间重叠归属（空行长度为 0，只看块起点会把
      跨空行的长匹配算到上一行，导致最后一段被截断，已修）
- [x] 对齐结果（`--dry-run` 实测）：`20261113091044` → 第 1~39 行（2305 字，覆盖率 0.91）；
      `20261113112745` → 第 1~35 行（2179 字，覆盖率 0.92）
- [x] 口径校准：定位自检改走「传文件路径」（RapidOCR 内部 cv2/BGR），与引擎适配器一致；
      改前 RGB 喂图自检 CER 7.90%/15.51%，改后 **12.10%/19.00%，与正式跑分完全相等**
- [x] 过程残留清理：`label draft` 用 rapidocr 出的草稿 json 已移到 `labels_draft_rapidocr/`，
      否则 `.json` 优先级高于 `.txt`（`core/dataset.py:56`），会把自证循环的标注当 GT
- [x] `cli.py run -c configs/docshot.yaml`（新增配置，单引擎 rapidocr）实测：
      **CER 0.156 = SUB 0.049 + DEL 0.107 + INS 0.000，完整率 0.844**，P50 11319ms（无 GPU，CPU ~11s/图）
- [x] `cli.py report results/docshot` → 6 个文件（report.html 133K，0 外链）
- [x] `tests/test_md_gt.py` 14 项（空行跨段归属、范围补齐、无关文本拒绝、dry-run/跳过/失败三种退出码）
      → 全仓 **155 passed**
- [ ] 未验证：这些数字只是 rapidocr 单引擎基线，**没有第二个引擎可比，不构成选型结论**；
      tesseract / 云 OCR / 在线 VLM 仍缺二进制、缺 key；paddleocr 已实测在本机不可用（见 Q 段）

---

## Q. paddleocr 接入尝试：实测失败并回滚（2026-11-13）

目标：给 `datasets/docshot` 加第二个引擎，把只有一行的对比表变成真实选型。

- [x] 安装：`paddlepaddle==2.6.2` + `paddleocr==2.9.1`（阿里云镜像，cp310 只有 2.6.2 与 3.x，
      **没有 2.5.2** —— 那个是已知能在纯 AVX2 CPU 上跑的版本，装不上）
- [x] 补齐 `setuptools`（`uv venv` 默认不装，`import paddle` 会因缺它挂掉）
- [x] 导入 OK：`paddle 2.6.2` / `paddleocr 2.9.1` / `is_compiled_with_cuda()=False`
- [x] **首次推理直接 SIGILL**：`FatalError: Illegal instruction`，
      崩在 `paddle::framework::ir::SelfAttentionFusePass::ApplyImpl`（`OptimizeInferenceProgram` 阶段）
- [x] 根因定位：CPU 是 `i7-13700`，有 avx/avx2/fma，**没有 avx512f**（12 代以后 Intel 全线砍掉）。
      paddle 2.6.x 的 Linux 轮子里存在 AVX512 专用代码路径 → 不是参数问题，换 `enable_mkldnn=False` 仍崩
- [x] 回滚：`uv pip uninstall paddlepaddle paddleocr`；回归 **155 passed**，
      numpy 停在 1.26.4（未被升级，pandas/onnxruntime/rapidocr 均正常）
- [x] 副作用记录：装 paddle 期间测试出现 `1 skipped`（`test_ocr_adapters.py:239`
      「本机已装 paddleocr，缺依赖分支无法触发」）—— 装了不可用的包反而降低测试覆盖，
      这也是回滚的理由之一；venv 从 462M 涨到 944M，paddle 引入的依赖（scipy/opencv*/scikit-learn/
      matplotlib 等）仍在，未清理（怕破坏可用环境，如需干净可用 `uv venv --clear` 重建，uv 缓存已热）

**比失败更有价值的发现**：`rapidocr_onnxruntime/models/` 里是
`ch_PP-OCRv4_det_infer.onnx` + `ch_PP-OCRv4_rec_infer.onnx` + `ch_ppocr_mobile_v2.0_cls_infer.onnx`
—— **rapidocr 跑的就是 PaddleOCR 的 PP-OCRv4 模型**，只是换成 onnxruntime 推理。
所以「加 paddleocr 2.x 做对比」本质是**同模型换运行时**，CER 大概率几乎相同，
对「该选哪个 OCR」这个问题几乎没有信息量。

→ 结论：真正有信息量的第二引擎只有三条，
  ① `tesseract`（需 sudo，模型与前两者完全无关，能回答「15.6% 是 rapidocr 的问题还是这批样本本来就难」）
  ② 云端 VLM（需 key，是「本地免费 vs 花钱」这个真决策的分水岭）
  ③ `paddleocr 3.x`（PP-OCRv5，模型确实换代；但要再下 ~1.5G 且能否避开 SIGILL 未知）
