"""矩阵执行层：引擎 × 数据集样本 × 任务。

职责：
  - 按引擎能力/模态生成可执行任务矩阵，不支持的组合显式跳过并记原因
  - 线程池并发，单次调用超时、失败重试、多次重复取中位延迟
  - 预测缓存（参数一变即失效）、断点续跑（缓存即断点）
  - 落盘 results/<run>/run.json + summary.json
"""
from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from adapters.base import BaseEngine, build_engine
from core.config import RunConfig
from core.dataset import list_samples, load_ground_truth
from core.text import NormalizeConfig
from core.types import EngineRequest, GroundTruth, Prediction, RunResult
from metrics import evaluate_sample
from runner.aggregate import summarize_run
from runner.cache import PredictionCache, hash_file


@dataclass(frozen=True)
class Job:
    """一个可执行的（引擎, 样本, 任务）三元组。"""

    engine_id: str
    sample_id: str
    task: str
    media_path: Path


def _sanitize(value: Any) -> Any:
    """落盘配置前屏蔽凭证类字段，避免 run.json 泄露 api key。"""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(s in str(k).lower() for s in ("api_key", "apikey", "token", "secret", "password")):
                out[k] = "***"
            else:
                out[k] = _sanitize(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


class Runner:
    """一次评测运行的编排器。"""

    def __init__(
        self,
        cfg: RunConfig,
        engines: list[BaseEngine] | None = None,
        cache: PredictionCache | None = None,
        progress: Callable[[str], None] | None = None,
    ):
        self.cfg = cfg
        self.normalize = NormalizeConfig.from_dict(cfg.normalize)
        self.metric_options = {
            "box_iou_threshold": float(cfg.normalize.get("box_iou_threshold", 0.5))
        }
        cache_dir = Path(
            (cfg.raw.get("run") or {}).get("cache_dir") or ".cache/predictions"
        )
        self.cache = cache if cache is not None else PredictionCache(
            root=cache_dir, enabled=cfg.cache
        )
        self._progress = progress
        self._engines, self.engine_errors = self._prepare_engines(engines)
        self._engine_map = {e.engine_id: e for e in self._engines}
        self._media_digests: dict[str, str] = {}

    # ---------- 准备 ----------
    def _prepare_engines(
        self, engines: list[BaseEngine] | None
    ) -> tuple[list[BaseEngine], list[dict]]:
        errors: list[dict] = []
        if engines is not None:
            return list(engines), errors
        built: list[BaseEngine] = []
        for spec in self.cfg.engines:
            try:
                built.append(build_engine(spec))
            except Exception as exc:  # noqa: BLE001 - 单个引擎构建失败不拖垮整轮
                info = {
                    "engine": spec.get("id") or spec.get("type"),
                    "type": spec.get("type"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                errors.append(info)
                if self.cfg.strict:
                    raise
        if not built:
            detail = "; ".join(f"{e['engine']}: {e['error']}" for e in errors) or "未配置引擎"
            raise RuntimeError(f"没有可用引擎（{detail}）")
        return built, errors

    def plan(self) -> tuple[list[Job], list[dict]]:
        """生成任务矩阵，返回 (可执行任务, 跳过记录)。"""
        samples = list_samples(self.cfg.dataset)
        if not samples:
            raise RuntimeError(
                f"数据集 {self.cfg.dataset.name} 没有样本："
                f"{self.cfg.dataset.media_dir}"
            )
        modality = self.cfg.dataset.modality
        jobs: list[Job] = []
        skipped: list[dict] = []
        for engine in self._engines:
            if not engine.accepts(modality):
                skipped.append({
                    "engine": engine.engine_id,
                    "reason": f"模态不匹配：引擎支持 {list(engine.modalities)}，数据集为 {modality}",
                })
                continue
            for task in self.cfg.tasks:
                if not engine.supports(task):
                    skipped.append({
                        "engine": engine.engine_id,
                        "task": task,
                        "reason": f"任务不支持：engine capabilities={list(engine.capabilities)}",
                    })
                    continue
                for sid, path in samples:
                    jobs.append(Job(engine.engine_id, sid, task, path))
        # 稳定顺序，保证并发下结果可复现
        jobs.sort(key=lambda j: (j.engine_id, j.task, j.sample_id))
        return jobs, skipped

    # ---------- 单任务执行 ----------
    def _media_digest(self, path: Path) -> str:
        key = str(path)
        if key not in self._media_digests:
            self._media_digests[key] = hash_file(path)
        return self._media_digests[key]

    def _call_once(self, engine: BaseEngine, req: EngineRequest) -> Prediction:
        """带超时的单次调用。超时用守护线程兜底（线程无法强杀，只标记失败）。"""
        timeout = self.cfg.timeout_s
        if timeout <= 0:
            return engine.predict(req)

        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["pred"] = engine.predict(req)
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc

        thread = threading.Thread(target=target, name=f"veval-{req.sample_id}", daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            return Prediction(
                engine_id=engine.engine_id,
                sample_id=req.sample_id,
                task=req.task,
                modality=req.modality,
                latency_ms=timeout * 1000.0,
                error=f"TimeoutError: 超过 {timeout:g}s 未返回",
            )
        if "error" in box:
            raise box["error"]
        return box["pred"]

    def _with_retries(self, engine: BaseEngine, req: EngineRequest) -> Prediction:
        attempts = max(1, self.cfg.retries + 1)
        errors: list[str] = []
        pred: Prediction | None = None
        for _ in range(attempts):
            try:
                pred = self._call_once(engine, req)
            except Exception as exc:  # noqa: BLE001
                pred = Prediction(
                    engine_id=engine.engine_id,
                    sample_id=req.sample_id,
                    task=req.task,
                    modality=req.modality,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if pred.error is None:
                if errors:
                    pred.meta = {**pred.meta, "retry_errors": errors}
                return pred
            errors.append(pred.error)
        assert pred is not None
        pred.meta = {**pred.meta, "attempts": errors, "attempt_count": attempts}
        return pred

    def _with_repeats(self, engine: BaseEngine, req: EngineRequest) -> Prediction:
        repeats = max(1, self.cfg.repeats)
        results = [self._with_retries(engine, req) for _ in range(repeats)]
        ok = [p for p in results if p.error is None]
        if not ok:
            last = results[-1]
            last.meta = {**last.meta, "repeats": repeats}
            return last
        first = ok[0]
        latencies = sorted(p.latency_ms for p in ok)
        mid = len(latencies) // 2
        median = (
            latencies[mid]
            if len(latencies) % 2
            else (latencies[mid - 1] + latencies[mid]) / 2
        )
        # 重复测量的总成本/总用量要累加，不能只算第一次
        cost = sum(p.cost_usd for p in results)
        usage: dict[str, float] = {}
        for p in results:
            for k, v in (p.usage or {}).items():
                if isinstance(v, (int, float)):
                    usage[k] = usage.get(k, 0) + float(v)
        first.latency_ms = median
        first.cost_usd = cost
        first.usage = usage or first.usage
        first.meta = {
            **first.meta,
            "repeats": repeats,
            "latency_ms_samples": [round(p.latency_ms, 2) for p in results],
        }
        return first

    def run_job(self, job: Job) -> Prediction:
        engine = self._engine_map[job.engine_id]
        req = EngineRequest(
            sample_id=job.sample_id,
            task=job.task,
            modality=self.cfg.dataset.modality,
            media_path=str(job.media_path),
            lang=self.cfg.dataset.lang,
            meta={"dataset": self.cfg.dataset.name},
        )
        # 先让适配器注入默认 prompt/schema，cache key 才能覆盖实际请求
        req = engine.build_request(req)

        use_cache = self.cache.enabled and self.cfg.repeats <= 1
        key = ""
        if use_cache:
            key = self.cache.key(
                engine, req, self._media_digest(job.media_path), self.normalize
            )
            hit = self.cache.get(key, sample_id=job.sample_id)
            if hit is not None:
                return hit

        pred = self._with_repeats(engine, req)
        if use_cache and pred.error is None:
            self.cache.put(key, pred)
        return pred

    # ---------- 整体运行 ----------
    def run(self) -> RunResult:
        started = time.perf_counter()
        jobs, skipped = self.plan()
        if not jobs:
            detail = "; ".join(s["reason"] for s in skipped[:5]) or "无匹配组合"
            raise RuntimeError(f"没有可执行的任务组合（{detail}）")

        for engine in self._engines:
            try:
                engine.warmup()
            except Exception as exc:  # noqa: BLE001
                self.engine_errors.append({
                    "engine": engine.engine_id,
                    "error": f"warmup 失败 {type(exc).__name__}: {exc}",
                })

        gts: dict[str, GroundTruth | None] = {
            sid: load_ground_truth(sid, self.cfg.dataset.labels_dir)
            for sid in {j.sample_id for j in jobs}
        }

        total = len(jobs)
        done = 0
        predictions: dict[tuple[str, str, str], Prediction] = {}
        with ThreadPoolExecutor(max_workers=max(1, self.cfg.concurrency)) as pool:
            futures = {pool.submit(self.run_job, job): job for job in jobs}
            for fut in as_completed(futures):
                job = futures[fut]
                try:
                    pred = fut.result()
                except Exception as exc:  # noqa: BLE001 - 兜底，保证矩阵能跑完
                    pred = Prediction(
                        engine_id=job.engine_id,
                        sample_id=job.sample_id,
                        task=job.task,
                        modality=self.cfg.dataset.modality,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                predictions[(job.engine_id, job.sample_id, job.task)] = pred
                done += 1
                if self._progress:
                    self._progress(
                        f"[{done}/{total}] {job.engine_id} · {job.sample_id}"
                    )

        ordered = [predictions[k] for k in sorted(predictions)]
        sample_metrics = [
            evaluate_sample(
                gts.get(p.sample_id), p, self.normalize, self.metric_options
            )
            for p in ordered
        ]
        duration_s = time.perf_counter() - started

        skipped_reasons: dict[str, int] = {}
        for item in skipped:
            skipped_reasons[item["reason"]] = skipped_reasons.get(item["reason"], 0) + 1

        return RunResult(
            run_name=self.cfg.name,
            config=self._config_snapshot(),
            samples=[sid for sid, _ in list_samples(self.cfg.dataset)],
            predictions=ordered,
            metrics=sample_metrics,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            env={
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "cwd": str(Path.cwd()),
                "duration_s": round(duration_s, 3),
                "requested_jobs": len(jobs),
                "engine_build_errors": self.engine_errors,
                "skipped": {
                    "count": len(skipped),
                    "reasons": skipped_reasons,
                    "examples": skipped[:50],
                },
            },
        )

    def _config_snapshot(self) -> dict:
        ds = self.cfg.dataset
        return _sanitize({
            "run_name": self.cfg.name,
            "dataset": {
                "name": ds.name,
                "modality": ds.modality,
                "lang": ds.lang,
                "media_dir": str(ds.media_dir),
                "labels_dir": str(ds.labels_dir),
                "limit": ds.limit,
                "sample_ids": ds.sample_ids,
            },
            "tasks": self.cfg.tasks,
            "concurrency": self.cfg.concurrency,
            "retries": self.cfg.retries,
            "repeats": self.cfg.repeats,
            "cache": self.cfg.cache,
            "timeout_s": self.cfg.timeout_s,
            "normalize": self.cfg.normalize,
            "strict": self.cfg.strict,
            "engines": self.cfg.engines,
        })


# ---------- 落盘 / 读取 ----------
def save_run(run: RunResult, out_dir: str | Path, run_name: str | None = None) -> Path:
    """写 results/<run>/run.json 与 summary.json，返回 run.json 路径。"""
    target = Path(out_dir) / (run_name or run.run_name)
    target.mkdir(parents=True, exist_ok=True)
    run_path = target / "run.json"
    _atomic_json(run_path, run.to_dict())
    _atomic_json(target / "summary.json", summarize_run(run))
    return run_path


def _atomic_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, path)


def load_run(path: str | Path) -> RunResult:
    return RunResult.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def resolve_run_path(arg: str | Path) -> Path:
    """接受 run.json 路径，或 run 名（自动补 results/<name>/run.json）。"""
    path = Path(arg)
    if path.is_file():
        return path
    candidates = [Path("results") / str(arg) / "run.json", Path(str(arg)) / "run.json"]
    for cand in candidates:
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        f"找不到运行结果: {arg}（可传 run.json 路径或 results/ 下的 run 名）"
    )
