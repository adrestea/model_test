"""核心数据类型。所有 adapter / metrics / report 都只依赖这里的定义。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

Task = Literal["recognize", "extract", "vqa"]
Modality = Literal["image", "video", "audio", "text"]

# 引擎能力位：adapter 声明自己支持什么，runner 据此跳过不支持的组合
CAP_RECOGNIZE = "recognize"   # 输出全文
CAP_LINES = "lines"           # 输出行级文本
CAP_BOXES = "boxes"           # 输出坐标框
CAP_EXTRACT = "extract"       # 支持按 schema 抽字段
CAP_VQA = "vqa"               # 支持自由问答
CAP_TIMELINE = "timeline"     # 输出带时间戳的分段（视频/音频字幕场景）


@dataclass
class Box:
    """轴对齐矩形，像素坐标，原点左上。"""
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def iou(self, other: "Box") -> float:
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def to_list(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]

    @classmethod
    def from_any(cls, v: Any) -> "Box | None":
        """支持 [x1,y1,x2,y2] 与 [[x,y],...] 两种标注写法。"""
        if v is None:
            return None
        if isinstance(v, Box):
            return v
        if isinstance(v, (list, tuple)):
            if len(v) == 4 and all(isinstance(x, (int, float)) for x in v):
                return cls(*[float(x) for x in v])
            if all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in v):
                xs = [float(p[0]) for p in v]
                ys = [float(p[1]) for p in v]
                return cls(min(xs), min(ys), max(xs), max(ys))
        return None


@dataclass
class Line:
    """一行/一段识别结果。音频、视频段用 start_ms/end_ms 代替 box，两者可并存。"""
    text: str
    box: Box | None = None
    score: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class GroundTruth:
    """单个样本的标注。三级可混用，缺哪级就少算哪级指标。"""
    sample_id: str
    text: str | None = None                      # L1 全文
    lines: list[Line] | None = None              # L2 行级（带 box 可额外算定位）
    fields: dict[str, Any] | None = None         # L3 字段级（P2 抽取用）
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineRequest:
    """模态无关的推理请求。image/video/audio 共用 media_* 字段。"""
    sample_id: str
    task: Task
    modality: Modality = "image"
    media_path: str | None = None
    media_bytes: bytes | None = None
    duration_s: float | None = None    # 视频/音频时长，用于按秒/分钟计费与吞吐
    prompt: str | None = None          # 运行时覆盖默认 prompt
    schema: dict | None = None         # extract 任务用
    lang: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    # 兼容别名：图片场景下 adapter 可继续用 image_path
    @property
    def image_path(self) -> str | None:
        return self.media_path

    @property
    def image_bytes(self) -> bytes | None:
        return self.media_bytes


@dataclass
class EngineOutput:
    """adapter 只需填这个，耗时/成本/错误由 base 层统一处理。"""
    text: str = ""
    lines: list[Line] | None = None
    fields: dict[str, Any] | None = None
    raw: Any = None
    usage: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Prediction:
    """一次推理的完整记录，落盘为 cache / 结果文件。"""
    engine_id: str
    sample_id: str
    task: Task
    modality: Modality = "image"
    text: str = ""
    lines: list[Line] | None = None
    fields: dict[str, Any] | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    raw: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "engine_id": self.engine_id,
            "sample_id": self.sample_id,
            "task": self.task,
            "modality": self.modality,
            "text": self.text,
            "lines": [
                {
                    "text": l.text,
                    "box": l.box.to_list() if l.box else None,
                    "score": l.score,
                    "start_ms": l.start_ms,
                    "end_ms": l.end_ms,
                }
                for l in (self.lines or [])
            ] or None,
            "fields": self.fields,
            "latency_ms": round(self.latency_ms, 2),
            "cost_usd": round(self.cost_usd, 8),
            "usage": self.usage,
            "error": self.error,
            "raw": _jsonable(self.raw),
            "meta": _jsonable(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Prediction":
        lines = None
        if d.get("lines"):
            lines = [
                Line(
                    text=l.get("text", ""),
                    box=Box.from_any(l.get("box")),
                    score=l.get("score"),
                    start_ms=l.get("start_ms"),
                    end_ms=l.get("end_ms"),
                )
                for l in d["lines"]
            ]
        return cls(
            engine_id=d["engine_id"], sample_id=d["sample_id"], task=d["task"],
            modality=d.get("modality", "image"),
            text=d.get("text") or "", lines=lines, fields=d.get("fields"),
            latency_ms=d.get("latency_ms") or 0.0, cost_usd=d.get("cost_usd") or 0.0,
            usage=d.get("usage") or {}, error=d.get("error"), raw=d.get("raw"),
            meta=d.get("meta") or {},
        )


@dataclass
class SampleMetrics:
    """单样本评分。字段名与 reports 里展示的中文表头绑定。"""
    sample_id: str
    cer: float | None = None
    sub_rate: float | None = None       # 错认：该有的字认错了
    del_rate: float | None = None       # 漏提：该有的字没提取出来
    ins_rate: float | None = None       # 多提/幻觉：多出来的字
    char_recall: float | None = None    # 完整率 = 1 - del - sub
    line_precision: float | None = None
    line_recall: float | None = None
    line_f1: float | None = None
    box_iou_mean: float | None = None   # 仅在有 GT box 且有预测 box 时
    exact_match: float | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None


@dataclass
class RunResult:
    run_name: str
    config: dict
    samples: list[str]
    predictions: list[Prediction]
    metrics: list[SampleMetrics]
    created_at: str
    env: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_name": self.run_name,
            "created_at": self.created_at,
            "config": self.config,
            "env": self.env,
            "samples": self.samples,
            "predictions": [p.to_dict() for p in self.predictions],
            "metrics": [asdict(m) for m in self.metrics],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RunResult":
        return cls(
            run_name=d["run_name"], config=d.get("config", {}), samples=d.get("samples", []),
            predictions=[Prediction.from_dict(p) for p in d.get("predictions", [])],
            metrics=[SampleMetrics(**m) for m in d.get("metrics", [])],
            created_at=d.get("created_at", ""), env=d.get("env", {}),
        )


def _jsonable(o: Any) -> Any:
    try:
        json.dumps(o)
        return o
    except TypeError:
        return str(o)
