"""Tesseract（本地 CLI + TSV 输出）适配。

type: ocr.tesseract
configs/full.yaml:
    - id: tesseract
      type: ocr.tesseract
      params: { lang: chi_sim+eng, psm: 6, device: cpu }
      cost: { per_image: 0 }

实现方式：**直接调 tesseract 可执行文件**（`tesseract img stdout -l chi_sim+eng --psm 6 tsv`），
不依赖 pytesseract，解析 TSV 的 level=5（词）行，再按 (block,par,line)
聚合成行级结果 + 行包围盒。

参数（params）：
    lang          语言包，默认 chi_sim+eng（需 tesseract-ocr-chi-sim）
    psm           页面分割模式，默认 6（统一文本块）
    oem           引擎模式，可选
    tesseract_cmd 自定义可执行文件路径
    tessdata_dir  TESSDATA_PREFIX，语言包不在默认目录时用
    box_score_thresh 行置信度阈值（0~1），默认 0.0 不丢
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from adapters._ocr_common import (
    image_file,
    image_size,
    join_words,
    lines_to_text,
    rect_to_box,
    require_binary,
)
from adapters.base import BaseEngine, register
from core.types import Box, EngineOutput, EngineRequest, Line

INSTALL_CMD = (
    "sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng\n"
    "    # macOS: brew install tesseract tesseract-lang\n"
    "    # 仅需 Python 封装（可选）：uv pip install --python .venv/bin/python pytesseract"
)


@register("ocr.tesseract")
class TesseractEngine(BaseEngine):
    type_name = "ocr.tesseract"
    capabilities = ("recognize", "lines", "boxes")
    modalities = ("image",)

    def _validate(self) -> None:
        # 不在构造期抛错：配置校验阶段允许 "装了就能跑"，
        # 真正推理时才提示缺二进制/语言包。
        self.lang = str(self.params.get("lang") or "chi_sim+eng")
        self.psm = int(self.params.get("psm") or 6)

    def _binary(self) -> str:
        cmd = self.params.get("tesseract_cmd") or "tesseract"
        if os.path.sep in str(cmd):
            if not os.path.isfile(str(cmd)):
                raise RuntimeError(
                    f"找不到 tesseract 可执行文件: {cmd}\n请先安装：\n    {INSTALL_CMD}"
                )
            return str(cmd)
        return require_binary(
            str(cmd),
            INSTALL_CMD,
            why="Tesseract 是本地 OCR 引擎，需要系统级可执行文件 + 中文语言包。",
        )

    def warmup(self) -> None:
        """跑一次 --version / --list-langs，提前暴露缺二进制或语言包。"""
        exe = self._binary()
        env = self._env()
        proc = subprocess.run(
            [exe, "--list-langs"], capture_output=True, text=True, env=env, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"tesseract 不可用: {proc.stderr.strip()[:400]}")
        self._check_lang_packs(proc.stdout)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.params.get("tessdata_dir"):
            env["TESSDATA_PREFIX"] = str(self.params["tessdata_dir"])
        return env

    def _check_lang_packs(self, listed: str) -> None:
        available = {l.strip() for l in listed.splitlines()[1:] if l.strip()}
        if not available:
            return
        missing = [l for l in self.lang.split("+") if l and l not in available]
        if missing:
            raise RuntimeError(
                f"tesseract 缺少语言包: {', '.join(missing)}（已有: {', '.join(sorted(available))}）\n"
                f"请安装对应语言包，例如中文：\n"
                f"    sudo apt-get install -y tesseract-ocr-chi-sim"
            )

    # ---- 推理 ----
    def _predict(self, req: EngineRequest) -> EngineOutput:
        exe = self._binary()
        args = [exe]
        with image_file(req) as path:
            size = image_size(path)
            args += [path, "stdout", "-l", self.lang, "--psm", str(self.psm)]
            if self.params.get("oem") is not None:
                args += ["--oem", str(self.params["oem"])]
            args += ["tsv"]

            env = self._env()
            t0 = time.perf_counter()
            proc = subprocess.run(
                args, capture_output=True, text=True, env=env,
                timeout=float(self.params.get("timeout_s") or 120),
            )
            infer_ms = (time.perf_counter() - t0) * 1000

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            if "Failed loading language" in stderr or "Error opening data file" in stderr:
                raise RuntimeError(
                    f"tesseract 语言包缺失（lang={self.lang}）：{stderr[:300]}\n"
                    f"请安装：sudo apt-get install -y tesseract-ocr-chi-sim"
                )
            raise RuntimeError(f"tesseract 执行失败(rc={proc.returncode}): {stderr[:500]}")

        rows = _parse_tsv(proc.stdout)
        lines, dropped = _rows_to_lines(
            rows, float(self.params.get("box_score_thresh", 0.0) or 0.0)
        )

        return EngineOutput(
            text=lines_to_text(lines),
            lines=lines,
            usage={"images": 1},
            raw=rows,
            meta={
                "engine": "tesseract",
                "version": _first_line(proc.stderr) or None,
                "lang": self.lang,
                "psm": self.psm,
                "image_size": list(size) if size else None,
                "infer_ms": round(infer_ms, 2),
                "words": len(rows),
                **({"dropped_low_score": dropped} if dropped else {}),
            },
        )


def _first_line(s: str | None) -> str:
    for line in (s or "").splitlines():
        line = line.strip()
        if line.startswith("tesseract"):
            return line
    return ""


def _parse_tsv(tsv: str) -> list[dict[str, Any]]:
    """解析 tesseract TSV，只保留 level=5（词）且 conf>=0 的行。"""
    header: list[str] | None = None
    out: list[dict[str, Any]] = []
    for raw in tsv.splitlines():
        if not raw.strip():
            continue
        cols = raw.split("\t")
        if header is None:
            header = cols
            continue
        if len(cols) < len(header):
            cols += [""] * (len(header) - len(cols))
        rec = dict(zip(header, cols))
        try:
            level = int(rec.get("level", 0))
            conf = float(rec.get("conf", -1))
            left, top = int(rec.get("left", 0)), int(rec.get("top", 0))
            width, height = int(rec.get("width", 0)), int(rec.get("height", 0))
        except (TypeError, ValueError):
            continue
        text = rec.get("text", "")
        if level != 5 or conf < 0 or not str(text).strip():
            continue
        rec.update(
            conf=conf, left=left, top=top, width=width, height=height,
            text=str(text),
        )
        out.append(rec)
    return out


def _rows_to_lines(rows: list[dict[str, Any]], thresh: float) -> tuple[list[Line], int]:
    """按 (page,block,par,line) 聚合词 → 行；行框 = 词框并集。"""
    if not rows:
        return [], 0

    groups: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
    for r in rows:
        key = (
            int(r.get("page_num", 0) or 0),
            int(r.get("block_num", 0) or 0),
            int(r.get("par_num", 0) or 0),
            int(r.get("line_num", 0) or 0),
        )
        groups.setdefault(key, []).append(r)

    lines: list[Line] = []
    dropped = 0
    for key in sorted(groups):
        words = sorted(groups[key], key=lambda r: int(r["left"]))
        text = join_words([str(w["text"]) for w in words])
        box: Box | None = None
        boxes = [rect_to_box(w["left"], w["top"], w["width"], w["height"]) for w in words]
        boxes = [b for b in boxes if b is not None]
        if boxes:
            box = Box(
                min(b.x1 for b in boxes), min(b.y1 for b in boxes),
                max(b.x2 for b in boxes), max(b.y2 for b in boxes),
            )
        score = sum(float(w["conf"]) for w in words) / len(words) / 100.0
        if thresh and score < thresh:
            dropped += 1
            continue
        lines.append(Line(text=text, box=box, score=round(score, 4)))

    return lines, dropped
