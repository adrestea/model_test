"""传统 OCR adapter 测试。

分层：
    - 注册/能力位/模态：不依赖任何三方包，永远跑
    - 解析逻辑（tesseract TSV / paddle 2.x·3.x / 云 OCR JSON）：用构造数据，永远跑
    - rapidocr 端到端：真实图片 + 真实推理（缺 rapidocr 则 skip）
    - tesseract 二进制缺失时的中文报错（装有 tesseract 则 skip）

跑法：
    .venv/bin/python -m pytest tests/test_ocr_adapters.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters import _ocr_common as C
from adapters.base import ENGINE_REGISTRY, build_engine, load_builtin_adapters
from core.types import Box, EngineRequest, Line

ASSETS = Path(__file__).resolve().parent / "assets"
SAMPLE_PNG = ASSETS / "ocr_sample.png"
SAMPLE_JPG = ASSETS / "ocr_sample_photo.jpg"

OCR_TYPES = ["ocr.rapidocr", "ocr.tesseract", "ocr.paddleocr", "ocr.cloud"]


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    load_builtin_adapters()


# --------------------------------------------------------------------------
# 1. 注册 + 能力位
# --------------------------------------------------------------------------
def test_all_ocr_types_registered():
    for t in OCR_TYPES:
        assert t in ENGINE_REGISTRY, f"{t} 未注册，已注册: {sorted(ENGINE_REGISTRY)}"


@pytest.mark.parametrize("t", OCR_TYPES)
def test_capabilities_and_modalities(t):
    cls = ENGINE_REGISTRY[t]
    assert set(cls.capabilities) >= {"recognize", "lines", "boxes"}
    assert cls.modalities == ("image",)


def test_config_engines_are_buildable():
    """configs/full.yaml 里的 4 个本地引擎都能 build（不需要装依赖/不需要 key）。"""
    cfgs = [
        {"id": "rapidocr", "type": "ocr.rapidocr", "params": {"device": "cpu"}},
        {"id": "tesseract", "type": "ocr.tesseract",
         "params": {"lang": "chi_sim+eng", "psm": 6, "device": "cpu"}},
        {"id": "paddleocr", "type": "ocr.paddleocr",
         "params": {"lang": "ch", "device": "cpu", "use_angle_cls": True}},
        {"id": "aliyun", "type": "ocr.cloud", "params": {"provider": "aliyun"}},
        {"id": "tencent", "type": "ocr.cloud", "params": {"provider": "tencent"}},
        {"id": "baidu", "type": "ocr.cloud", "params": {"provider": "baidu"}},
    ]
    for c in cfgs:
        eng = build_engine(c)
        assert eng.type_name == c["type"]
        assert eng.engine_id == c["id"]
        assert eng.device == "cpu"


# --------------------------------------------------------------------------
# 2. 几何 / 文本工具
# --------------------------------------------------------------------------
def test_poly_to_box_and_reading_order():
    box = C.poly_to_box([[10, 20], [110, 22], [108, 60], [8, 58]])
    assert isinstance(box, Box)
    assert (box.x1, box.y1, box.x2, box.y2) == (8.0, 20.0, 110.0, 60.0)
    assert C.poly_to_box([1, 2, 3, 4]).to_list() == [1.0, 2.0, 3.0, 4.0]


def test_join_words_cjk_vs_latin():
    assert C.join_words(["合计", "金额", "1000"]) == "合计金额1000"
    assert C.join_words(["Total", "Amount"]) == "Total Amount"


def test_image_file_from_bytes_and_path(tmp_path):
    data = SAMPLE_PNG.read_bytes()
    req = EngineRequest(sample_id="s", task="recognize", media_bytes=data)
    with C.image_file(req) as p:
        assert Path(p).is_file() and Path(p).read_bytes() == data
    assert not Path(p).exists(), "临时文件应被清理"

    req2 = EngineRequest(sample_id="s", task="recognize", media_path=str(SAMPLE_PNG))
    with C.image_file(req2) as p2:
        assert p2 == str(SAMPLE_PNG)

    with pytest.raises(FileNotFoundError, match="图片文件不存在"):
        with C.image_file(EngineRequest(sample_id="s", task="recognize", media_path="/no/such.png")):
            pass


# --------------------------------------------------------------------------
# 3. rapidocr 真实推理
# --------------------------------------------------------------------------
def _rapidocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def rapidocr_engine():
    if not _rapidocr_available():
        pytest.skip("rapidocr-onnxruntime 未安装（见 tests/assets/README 或 adapter 内安装命令）")
    eng = build_engine(
        {"id": "rapidocr", "type": "ocr.rapidocr", "params": {"device": "cpu"}, "cost": {"per_image": 0}}
    )
    eng.warmup()
    return eng


@pytest.mark.parametrize("img", [SAMPLE_PNG, SAMPLE_JPG])
def test_rapidocr_real_inference(rapidocr_engine, img):
    pred = rapidocr_engine.predict(
        EngineRequest(sample_id=img.stem, task="recognize", media_path=str(img))
    )
    assert pred.ok, pred.error
    assert pred.text.strip(), "识别全文为空"
    assert pred.lines and len(pred.lines) >= 10, f"行数过少: {len(pred.lines)}"
    # 关键字段必须认对（真实模型输出，不 mock）
    for key in ["发票代码：011002100311", "发票号码：12345678", "价税合计"]:
        assert key in pred.text, f"缺少关键字段 {key}\n{pred.text}"

    for line in pred.lines:
        assert line.text
        assert line.box is not None, "每行必须填 Line.box（下游算定位 IoU）"
        assert line.box.x2 > line.box.x1 and line.box.y2 > line.box.y1
        assert 0 <= line.box.x1 < 1240 and 0 <= line.box.y1 < 1450
        assert line.score is None or 0.0 <= line.score <= 1.0

    assert pred.text == "\n".join(l.text for l in pred.lines)
    assert pred.usage.get("images") == 1
    assert pred.latency_ms > 0
    assert pred.meta["type"] == "ocr.rapidocr"
    assert pred.meta["device"] == "cpu"


def test_rapidocr_accepts_bytes(rapidocr_engine):
    pred = rapidocr_engine.predict(
        EngineRequest(sample_id="bytes", task="recognize", media_bytes=SAMPLE_PNG.read_bytes())
    )
    assert pred.ok, pred.error
    assert "发票号码" in pred.text


# --------------------------------------------------------------------------
# 4. tesseract：TSV 解析 + 缺二进制报错
# --------------------------------------------------------------------------
_TSV = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
1\t1\t0\t0\t0\t0\t0\t0\t1240\t1400\t-1\t
4\t1\t1\t1\t0\t0\t120\t230\t420\t45\t-1\t
5\t1\t1\t1\t1\t1\t120\t230\t150\t40\t96.5\t发票代码：
5\t1\t1\t1\t1\t2\t280\t230\t260\t40\t95.0\t011002100311
5\t1\t1\t1\t2\t1\t120\t290\t150\t40\t92.0\t发票号码：
5\t1\t1\t1\t2\t2\t280\t290\t180\t40\t88.0\t12345678
"""


def test_tesseract_tsv_parsing():
    from adapters.ocr_tesseract import _parse_tsv, _rows_to_lines

    rows = _parse_tsv(_TSV)
    assert len(rows) == 4 and all(r["conf"] > 0 for r in rows)

    lines, dropped = _rows_to_lines(rows, 0.0)
    assert dropped == 0
    assert [l.text for l in lines] == ["发票代码：011002100311", "发票号码：12345678"]
    assert lines[0].box.to_list() == [120.0, 230.0, 540.0, 270.0]
    assert lines[0].score == pytest.approx((96.5 + 95.0) / 2 / 100, abs=1e-4)

    kept, dropped2 = _rows_to_lines(rows, 0.93)
    assert dropped2 == 1 and [l.text for l in kept] == ["发票代码：011002100311"]


def test_tesseract_missing_binary_gives_chinese_hint():
    import shutil

    if shutil.which("tesseract"):
        pytest.skip("本机已装 tesseract，缺二进制的错误分支无法触发")
    eng = build_engine(
        {"id": "tesseract", "type": "ocr.tesseract", "params": {"lang": "chi_sim+eng", "psm": 6}}
    )
    pred = eng.predict(EngineRequest(sample_id="s", task="recognize", media_path=str(SAMPLE_PNG)))
    assert pred.error and "找不到可执行文件" in pred.error
    assert "apt-get install" in pred.error
    assert pred.text == ""


# --------------------------------------------------------------------------
# 5. paddleocr：2.x / 3.x 返回结构解析 + 缺依赖报错
# --------------------------------------------------------------------------
def test_paddle_v2_flatten():
    from adapters.ocr_paddleocr import _flatten

    raw = [[
        [[[10, 10], [300, 10], [300, 50], [10, 50]], ("发票号码：12345678", 0.98)],
        [[[10, 60], [200, 60], [200, 100], [10, 100]], ("合计金额", 0.9)],
    ]]
    got = _flatten(raw)
    assert [g[1] for g in got] == ["发票号码：12345678", "合计金额"]
    assert got[0][0].to_list() == [10.0, 10.0, 300.0, 50.0]
    assert got[0][2] == pytest.approx(0.98)


def test_paddle_v3_flatten():
    from adapters.ocr_paddleocr import _flatten

    class Item(dict):
        pass

    raw = [Item({
        "rec_texts": ["价税合计（大写）：壹仟零陆拾元整", "（小写）￥1060.00"],
        "rec_scores": [0.97, 0.95],
        "rec_polys": [
            [[10, 780], [500, 780], [500, 830], [10, 830]],
            [[10, 840], [300, 840], [300, 890], [10, 890]],
        ],
    })]
    got = _flatten(raw)
    assert len(got) == 2
    assert got[1][1].startswith("（小写）")
    assert got[1][0].to_list() == [10.0, 840.0, 300.0, 890.0]


def test_paddle_missing_dependency_gives_install_hint():
    import importlib.util

    if importlib.util.find_spec("paddleocr"):
        pytest.skip("本机已装 paddleocr，缺依赖分支无法触发")
    eng = build_engine(
        {"id": "paddleocr", "type": "ocr.paddleocr",
         "params": {"lang": "ch", "device": "cpu", "use_angle_cls": True}}
    )
    pred = eng.predict(EngineRequest(sample_id="s", task="recognize", media_path=str(SAMPLE_PNG)))
    assert pred.error and "缺少依赖 paddleocr" in pred.error
    assert "pip install" in pred.error


# --------------------------------------------------------------------------
# 6. 云 OCR：provider 校验、缺 key 报错、响应解析（离线假响应）
# --------------------------------------------------------------------------
def test_cloud_provider_validation():
    with pytest.raises(ValueError, match="provider"):
        build_engine({"id": "x", "type": "ocr.cloud", "params": {}})
    with pytest.raises(ValueError, match="不支持的云 OCR provider"):
        build_engine({"id": "x", "type": "ocr.cloud", "params": {"provider": "aws"}})


@pytest.mark.parametrize(
    "provider,env,expect",
    [
        ("aliyun", "ALIYUN_OCR_MISSING_TEST", "缺少环境变量 ALIYUN_OCR_MISSING_TEST"),
        ("tencent", "TENCENT_MISSING_TEST_ID", "缺少环境变量 TENCENT_MISSING_TEST_ID"),
        ("baidu", "BAIDU_MISSING_TEST_KEY", "缺少环境变量 BAIDU_MISSING_TEST_KEY"),
    ],
)
def test_cloud_missing_env_names_the_var(monkeypatch, provider, env, expect):
    for k in ("ALIYUN_OCR_APPCODE", "TENCENT_SECRET_ID", "TENCENT_SECRET_KEY",
              "BAIDU_OCR_API_KEY", "BAIDU_OCR_SECRET_KEY", env):
        monkeypatch.delenv(k, raising=False)
    params = {
        "aliyun": {"provider": "aliyun", "appcode_env": env},
        "tencent": {"provider": "tencent", "secret_id_env": env},
        "baidu": {"provider": "baidu", "api_key_env": env},
    }[provider]
    eng = build_engine({"id": provider, "type": "ocr.cloud", "params": params})
    pred = eng.predict(EngineRequest(sample_id="s", task="recognize", media_path=str(SAMPLE_PNG)))
    assert pred.error and expect in pred.error, pred.error


def test_aliyun_response_parsing(monkeypatch):
    import adapters.ocr_cloud as cloud

    monkeypatch.setenv("ALIYUN_OCR_APPCODE", "fake-code")
    monkeypatch.setattr(
        cloud, "_http",
        lambda url, body, headers, timeout, *a, **kw: (
            200,
            json.dumps({
                "prism_wordsInfo": [
                    {"word": "发票号码：12345678", "prob": 98,
                     "pos": [{"x": 120, "y": 300}, {"x": 460, "y": 300},
                             {"x": 460, "y": 340}, {"x": 120, "y": 340}]},
                    {"word": "价税合计", "x": 120, "y": 780, "width": 160, "height": 40, "prob": 0.93},
                ]
            }).encode(),
        ),
    )
    eng = build_engine({"id": "aliyun", "type": "ocr.cloud", "params": {"provider": "aliyun"}})
    pred = eng.predict(EngineRequest(sample_id="s", task="recognize", media_path=str(SAMPLE_PNG)))
    assert pred.ok, pred.error
    assert pred.text == "发票号码：12345678\n价税合计"
    assert pred.lines[0].box.to_list() == [120.0, 300.0, 460.0, 340.0]
    assert pred.lines[0].score == pytest.approx(0.98)
    assert pred.lines[1].score == pytest.approx(0.93)
    assert pred.meta["provider"] == "aliyun"


def test_tencent_response_parsing(monkeypatch):
    import adapters.ocr_cloud as cloud

    monkeypatch.setenv("TENCENT_SECRET_ID", "id")
    monkeypatch.setenv("TENCENT_SECRET_KEY", "key")
    captured: dict = {}

    def _fake(url, body, headers, timeout, *a, **kw):
        captured["url"] = url
        captured["headers"] = headers
        return 200, json.dumps({
            "Response": {
                "TextDetections": [
                    {"DetectedText": "上海测试信息技术有限公司", "Confidence": 99,
                     "Polygon": [{"X": 120, "Y": 930}, {"X": 600, "Y": 930},
                                 {"X": 600, "Y": 975}, {"X": 120, "Y": 975}]},
                    {"DetectedText": "（小写）￥1060.00", "Confidence": 97,
                     "Polygon": [{"X": 120, "Y": 840}, {"X": 400, "Y": 840},
                                 {"X": 400, "Y": 885}, {"X": 120, "Y": 885}]},
                ],
                "RequestId": "x",
            }
        }).encode()

    monkeypatch.setattr(cloud, "_http", _fake)
    eng = build_engine({"id": "tencent", "type": "ocr.cloud", "params": {"provider": "tencent"}})
    pred = eng.predict(EngineRequest(sample_id="s", task="recognize", media_path=str(SAMPLE_PNG)))

    assert pred.ok, pred.error
    # 阅读顺序：y=840 的行在前
    assert pred.text.splitlines() == ["（小写）￥1060.00", "上海测试信息技术有限公司"]
    assert pred.lines[0].box.to_list() == [120.0, 840.0, 400.0, 885.0]
    assert pred.lines[1].score == pytest.approx(0.99)
    assert captured["url"].startswith("https://ocr.tencentcloudapi.com")
    assert captured["headers"]["Authorization"].startswith("TC3-HMAC-SHA256 Credential=id/")
    assert "Signature=" in captured["headers"]["Authorization"]


def test_baidu_response_parsing(monkeypatch):
    import adapters.ocr_cloud as cloud

    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")
    cloud._BAIDU_TOKEN_CACHE.clear()

    def _fake(url, body, headers, timeout, *a, **kw):
        if "oauth" in url:
            return 200, json.dumps({"access_token": "tok", "expires_in": 3600}).encode()
        return 200, json.dumps({
            "words_result": [
                {"words": "货物或应税劳务名称：技术服务费",
                 "location": {"left": 120, "top": 570, "width": 480, "height": 44}},
            ],
            "words_result_num": 1,
            "log_id": 1,
        }).encode()

    monkeypatch.setattr(cloud, "_http", _fake)
    eng = build_engine({
        "id": "baidu", "type": "ocr.cloud",
        "params": {"provider": "baidu", "mode": "accurate_basic"},
    })
    pred = eng.predict(EngineRequest(sample_id="s", task="recognize", media_path=str(SAMPLE_PNG)))
    assert pred.ok, pred.error
    assert pred.text == "货物或应税劳务名称：技术服务费"
    assert pred.lines[0].box.to_list() == [120.0, 570.0, 600.0, 614.0]
    assert pred.meta["mode"] == "accurate_basic"
