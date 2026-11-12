# 架构与扩展点

## 分层（依赖单向，禁止反向 import）

```
cli.py                    命令入口：run / report / compare / baseline / dataset / label
  └─ runner/              编排：矩阵执行、并发、重试、缓存、断点续跑
       ├─ core/           纯数据与规则层（无 IO、无模型依赖）
       │    types.py      数据契约：Modality / Task / Box / Line / Prediction / SampleMetrics
       │    dataset.py    样本扫描 + 三级标注解析
       │    config.py     YAML → RunConfig
       │    text.py       文本归一化 + 字符级编辑距离拆解（sub/ins/del）
       │    registry.py   引擎注册表
       ├─ adapters/       引擎适配层（唯一允许 import 三方 SDK 的地方）
       └─ metrics/        指标插件（可注册新指标，不改 runner）
  └─ report/              报告渲染（只读 RunResult，不碰引擎）
```

**硬规则**
- `core/` 不许 import `adapters/`、`runner/`、`report/`、任何三方模型 SDK。
- `adapters/` 不许 import `runner/`、`report/`。
- `report/` 只吃 `RunResult`，不许调引擎。
- 新模态、新指标、新引擎都不改 `core/` 的既有接口，只加文件。

## 模态解耦（为视频/音频预留）

模态已经贯穿全链路，不是图片专属：

| 环节 | 泛化点 |
|---|---|
| 样本 | `DatasetSpec.modality` + `media_dir`，目录按 `images/ videos/ audios/` 自动选 |
| 请求 | `EngineRequest.media_path / media_bytes / duration_s / modality` |
| 引擎 | `BaseEngine.modalities = ("image",)`，runner 自动跳过模态不匹配的组合 |
| 结果 | `Line.start_ms / end_ms`，图片用 `box`，音视频用时间戳，两者可并存 |
| 计费 | `per_image` / `per_second` / `per_minute` / `per_1m token` 可分项叠加 |
| 指标 | 文本类指标（CER/WER/完整率）模态无关，直接复用；时间轴类走新插件 |
| 报告 | 按 modality 分组渲染，图片显示 diff 图，音视频显示时间轴对齐表 |

### 新增「视频→文字」的实际工作量
1. `adapters/video_asr_vlm.py`：`modalities=("video",)`，抽帧或整段送模型，填 `lines=[Line(text, start_ms, end_ms)]`。
2. `metrics/timeline.py`：注册 `segment_f1`（按时间段 IoU 匹配）。
3. `datasets/<name>/videos/` + `labels/<stem>.json` 带时间戳。
4. 配置里加一条引擎。**核心层零改动。**

### 新增「音频→文字」
同上，`adapters/asr_whisper.py`（本地 faster-whisper 或在线），指标复用 `metrics/text.py` 的 CER/WER。任务名用 `Task=transcribe` 时在 `core/types.py` 的 Literal 里加一个值即可。

## 指标插件约定

```python
# metrics/text.py
@register_metric("text.cer")
def cer(gt: GroundTruth, pred: Prediction, cfg: dict) -> dict[str, float]:
    ...
```

runner 对所有已注册指标跑一遍，`SampleMetrics` 用 `extra: dict` 装插件指标，报告自动带上表头，不需要改 report 代码。

## 缓存与可复现

- cache key = `sha256(媒体字节 + engine_id + 参数指纹 + task + prompt_hash + 归一化配置)`，参数一变自动失效，不会拿旧结果冒充。
- 每次 run 落盘 `results/<run>/run.json`（含 config + env + 全部预测 + 全部指标），可直接喂给 `report` / `baseline diff`。
- `baseline freeze <run>` 冻结快照，`baseline diff <run> <baseline>` 输出指标涨跌 + 变好/变坏样本清单。

## 评估口径要点（为什么这么设）

- **CER 拆成 SUB / DEL / INS**：OCR 典型是 DEL 高（漏提），大模型典型是 INS 高（幻觉编造）。只看总 CER 会把两类错误混在一起，选型结论会错。
- **完整率 = 1 − DEL − SUB**：直接对应「文字尽可能提取完整」这个目标。
- **行级 P/R/F1 按行集合匹配**：免疫行序差异，比全文 CER 可信；L1 标注只有全文时降级用 CER。
- **定位 IoU**：区分「真读到」和「猜到内容但位置乱」。
- **效率**：单图延迟 P50/P90/P99（`repeats>1` 才有意义）+ 吞吐 + 每千张成本。
