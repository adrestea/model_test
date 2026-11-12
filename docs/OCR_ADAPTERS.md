# 传统 OCR 引擎适配（rapidocr / tesseract / paddleocr / 云 OCR）

> 本文只覆盖**传统 OCR**（本地 CPU 引擎 + 云 OCR API）。VLM 系列见 `docs/` 下其它文档。
> 所有 adapter 都继承 `adapters/base.py` 的 `BaseEngine` 并用 `@register("type.name")` 注册，
> `load_builtin_adapters()` 会自动发现；`core/`、`runner/`、`metrics/`、`report/` 零改动。

## 1. 类型、能力位、文件

| type | 文件 | capabilities | modalities | 输出 |
|---|---|---|---|---|
| `ocr.rapidocr` | `adapters/ocr_rapidocr.py` | `recognize, lines, boxes` | `image` | 全文 + 每行文本 + 行框（像素）+ 置信度 |
| `ocr.tesseract` | `adapters/ocr_tesseract.py` | `recognize, lines, boxes` | `image` | 同上（TSV 聚合成行） |
| `ocr.paddleocr` | `adapters/ocr_paddleocr.py` | `recognize, lines, boxes` | `image` | 同上（PP-OCR 检测框即行框） |
| `ocr.cloud` | `adapters/ocr_cloud.py` | `recognize, lines, boxes` | `image` | 同上（provider = aliyun / tencent / baidu） |

公共工具在 `adapters/_ocr_common.py`（下划线开头，不被当成引擎模块导入）：

- `image_file(req)`：吃 `media_path` 或 `media_bytes`（字节落临时文件，用完清理）
- `poly_to_box()` / `rect_to_box()`：四点/矩形 → `Box`，统一轴对齐像素坐标
- `join_words()`：同行词拼接（中文不加空格，西文加空格）
- `lines_to_text()`：`"\n".join(行文本)`，即 L1 全文口径
- `require_module` / `require_binary` / `require_env`：缺依赖时抛**中文**错误并给安装命令

**约定**：`Line.text` 是行文本，`Line.box` 一定是像素坐标（`Box(x1,y1,x2,y2)`，原点左上），
下游定位 IoU 直接用；`EngineOutput.text = "\n".join(line.text)`。

## 2. 依赖安装与当前状态

| 引擎 | 安装命令 | 本机状态 |
|---|---|---|
| rapidocr | `uv pip install --python .venv/bin/python rapidocr-onnxruntime onnxruntime` | **[已验证]** rapidocr-onnxruntime 1.4.4 + onnxruntime 1.23.2，真实图片跑通 |
| tesseract | `sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng`（macOS：`brew install tesseract tesseract-lang`） | **[未验证]** 无 sudo、系统未装二进制；adapter 已实现并测过 TSV 解析逻辑与缺二进制的报错路径 |
| paddleocr | `uv pip install --python .venv/bin/python paddlepaddle paddleocr` | **[未验证]** 未安装（轮子数百 MB）；adapter 兼容 2.x/3.x 返回结构，解析逻辑单测覆盖 |
| 云 OCR | 无额外 pip 包（标准库 `urllib` 直连 REST） | **[未验证]** 无任何云厂商凭据，未发真实请求；响应解析用离线假响应单测覆盖 |

设计要点：三方库**一律延迟导入**（`_load()` 里），所以：
- 缺依赖时引擎类型仍然注册成功，`configs/*.yaml` 不会因为没装包而校验失败
- 只有真正推理才报错，错误信息带安装命令，且不会拖垮整轮评测（runner 记为样本 error）
- `warmup()` 会提前加载模型 / 检查 tesseract 二进制与语言包，runner 构建阶段即可发现环境问题

## 3. 配置写法

`configs/full.yaml` 里已有前三条（id 与 params 必须与配置一致）：

```yaml
engines:
  - id: rapidocr
    type: ocr.rapidocr
    params: { device: cpu }
    cost: { per_image: 0 }

  - id: tesseract
    type: ocr.tesseract
    params: { lang: chi_sim+eng, psm: 6, device: cpu }
    cost: { per_image: 0 }

  - id: paddleocr
    type: ocr.paddleocr
    params: { lang: ch, device: cpu, use_angle_cls: true }
    cost: { per_image: 0 }

  # 云 OCR：同一个 type，用 provider 区分厂商
  - id: aliyun-ocr
    type: ocr.cloud
    params: { provider: aliyun }
    cost: { per_image: 0.0042 }
```

### 参数一览

**ocr.rapidocr**

| 参数 | 默认 | 说明 |
|---|---|---|
| `device` | `cpu` | 仅声明；`cuda*` 时自动开 `det/cls/rec_use_cuda`（需 onnxruntime-gpu） |
| `use_angle_cls` | 引擎默认 | 方向分类；1.x 映射成 `use_cls`，2.x 映射成 `use_angle_cls` |
| `text_score` | 0.5（引擎默认） | rapidocr 内部过滤阈值 |
| `box_score_thresh` | 0.0 | adapter 侧再过滤一道（0 = 不丢） |
| `det_model_path` / `rec_model_path` / `cls_model_path` | 内置模型 | 换自定义 ONNX |
| `rec_batch_num` | 6 | 识别 batch |

**ocr.tesseract**

| 参数 | 默认 | 说明 |
|---|---|---|
| `lang` | `chi_sim+eng` | 需对应语言包（`tesseract --list-langs` 可查） |
| `psm` | `6` | 页面分割模式 |
| `oem` | 引擎默认 | 引擎模式 |
| `tesseract_cmd` | `tesseract` | 自定义可执行文件路径 |
| `tessdata_dir` | 环境变量 | 设置 `TESSDATA_PREFIX` |
| `box_score_thresh` | 0.0 | 行置信度阈值 |

**ocr.paddleocr**

| 参数 | 默认 | 说明 |
|---|---|---|
| `lang` | `ch` | PP-OCR 语言 |
| `device` | `cpu` | `cuda:0` → 2.x 映射成 `use_gpu=True`，3.x 直接传 `device` |
| `use_angle_cls` | `true` | 3.x 映射成 `use_textline_orientation` |
| `det` / `rec` / `cls` | `true` | 2.x 子模型开关 |
| `box_score_thresh` | 0.0 | 行置信度阈值 |

**ocr.cloud** 公共：`provider`（必填）、`timeout_s`（默认 30）、`box_score_thresh` 未实现（各家已自带阈值）。
各厂商专属参数见下表。

## 4. 云 OCR 环境变量清单

| provider | 环境变量 | 用途 | 可覆盖的 params 键 |
|---|---|---|---|
| `aliyun` | `ALIYUN_OCR_APPCODE` | 阿里云市场 OCR 的 AppCode 鉴权 | `appcode_env`、`endpoint` |
| `tencent` | `TENCENT_SECRET_ID`、`TENCENT_SECRET_KEY` | 腾讯云 CAM 密钥（需 OCR 读权限） | `secret_id_env`、`secret_key_env`、`action`（默认 `GeneralBasicOCR`，可改 `GeneralAccurateOCR`）、`region`（默认 `ap-guangzhou`）、`endpoint` |
| `baidu` | `BAIDU_OCR_API_KEY`、`BAIDU_OCR_SECRET_KEY` | 百度智能云 OCR 应用 AK/SK（换 access_token） | `api_key_env`、`secret_key_env`、`mode`（`accurate_basic` 默认 / `general_basic`）、`endpoint` |

缺 key 时的行为：该样本 `Prediction.error` 为中文报错，**点名缺哪个变量**，例如

```
RuntimeError: 缺少环境变量 ALIYUN_OCR_APPCODE（阿里云市场 OCR 接口用 AppCode 鉴权）。
请先 export ALIYUN_OCR_APPCODE=<你的凭据>，或在 configs/*.yaml 的 params 里用对应的 *_env 键指向别的变量名。
```

实现细节：
- 阿里云：`POST {endpoint}`，头 `Authorization: APPCODE xxx`，body `{"img": base64}`；解析 `prism_wordsInfo`（`word`/`pos`/`prob`），兼容 `words_result` 与纯文本 `Data.Content`
- 腾讯云：TC3-HMAC-SHA256 签名（`content-type;host`），解析 `Response.TextDetections[].DetectedText/Polygon/Confidence`，`Response.Error` 直接转中文异常
- 百度：OAuth `access_token`（进程内缓存到过期前 60s），解析 `words_result[].words/location`，`error_code` 转异常
- 置信度统一归一化到 0~1（0~100 的按 /100 处理）

## 5. 验证记录（真实运行，未伪造）

环境：本机 CPU，`.venv`，Python 3.10.12，rapidocr-onnxruntime 1.4.4 / onnxruntime 1.23.2。
测试图片：`tests/assets/ocr_sample.png`（PIL 渲染的中文发票样张，1240×1400，非隐私）与
`tests/assets/ocr_sample_photo.jpg`（同内容 + 倾斜/噪点/JPEG 压缩的拍照模拟件）。
造图脚本：`tests/assets/gen_sample.py`。

直接调用（走 `BaseEngine.predict`，与 runner 同一路径）：

```bash
.venv/bin/python -c "
from adapters.base import build_engine
from core.types import EngineRequest
e = build_engine({'id':'rapidocr','type':'ocr.rapidocr','params':{'device':'cpu'}})
e.warmup()
p = e.predict(EngineRequest(sample_id='s', task='recognize', media_path='tests/assets/ocr_sample.png'))
print(p.text); print(p.lines[0].box.to_list(), len(p.lines))
"
```

真实输出（`ocr_sample.png`，13 行全部命中，`warmup` 后单图 ~2.0s，冷启动含建模 ~2.3s）：

```
增值税电子普通发票
发票代码：011002100311
发票号码：12345678
开票日期：2024年05月01日
购买方名称：北京示例科技有限公司
纳税人识别号：91110108MA01ABCD2X
货物或应税劳务名称：技术服务费
数量：1单价：1000.00金额：1000.00
税率：6%税额：60.00
价税合计（大写）：壹仟零陆拾元整
（小写）￥1060.00
销售方名称：上海测试信息技术有限公司
备注：本图片由 PIL 渲染生成，仅用于 OCR adapter 自测
```

前 3 行结构（像素坐标 + 置信度）：

```
('增值税电子普通发票',      [422.0, 127.0, 886.0, 176.0], 0.9968)
('发票代码：011002100311',  [121.0, 242.0, 539.0, 277.0], 0.9998)
('发票号码：12345678',      [121.0, 300.0, 461.0, 339.0], 0.9998)
```

端到端 runner 冒烟（临时数据集，out_dir 指到 /tmp，未污染 results/）：

```
rapidocr  2 样本 2 成功 0.0% 错误率  P50 1778.5ms  P90 1818.1ms
tesseract 2 样本 0 成功 100%          （引擎构建阶段 warmup 失败 → 已跳过并给出安装提示）
aliyun    2 样本 0 成功 100%          （无 ALIYUN_OCR_APPCODE → 样本 error，不影响其它引擎）
```

单图延迟参考：干净扫描件 P50 ≈ 1.7–1.8s，拍照件 ≈ 1.7s（CPU，13 行，含 det+cls+rec）。
`meta.stage_ms` 还会带 `det_ms / cls_ms / rec_ms` 分阶段耗时。

单元测试：

```bash
.venv/bin/python -m pytest tests/test_ocr_adapters.py -q
# 24 passed
```

覆盖：4 个 type 注册 / 能力位 / 模态、`configs/full.yaml` 四条本地配置可构建、
图片路径与字节两种输入、多边形→Box、TSV 聚合行与阈值、paddle 2.x·3.x 结构解析、
云 OCR provider 校验、三家缺 key 的点名报错、三家响应 → 行/box/score 映射（离线假响应）。

## 6. 已知限制

1. **tesseract / paddleocr 未在真机跑过**（无 sudo / 包太大）。二进制/依赖缺失、语言包缺失的分支已实现且有单测，
   但真实识别质量与延迟未测；上机后请补一次 `veval run` 并回填数据。
2. **云 OCR 未发过真实请求**。签名按各家公开文档实现，但：
   - 阿里云用的是**市场版 AppCode**（`ocrservice/advanced`）。若用官方 OCR SDK/AccessKey 签名，
     需另补一套签名（`params.endpoint` 可换，但鉴权头不同）；
   - 阿里云响应字段随接口版本差异较大，已做多键兼容（`prism_wordsInfo`/`words_info`/`words_result`/`Data.Content`），
     仍可能遇到未覆盖的形状；
   - 百度/腾讯按官方 v1 REST 实现，若厂商改默认接口版本需同步调整。
3. **行框是"检测框并集"，不是字符级框**：tesseract 按 TSV 的 `block/par/line` 聚合词框；
   rapidocr / paddle / 云 OCR 直接把检测框当行框。若业务行比检测行长（模型把两行并成一个框），
   IoU 会偏低——这是引擎行为，不是 adapter 的问题。
4. **阅读顺序是启发式**：按行框中心 y 再按 x 排序，多栏排版（双栏发票、表格）可能串行；
   下游行集合指标免疫顺序，但 L1 全文 CER 会受影响。
5. **tesseract 行内空格**：中文行词间不加空格、西文加一个空格，可能与标注的空格习惯不一致，
   CER 前请用 `run.normalize.strip_whitespace`。
6. **rapidocr `box_score_thresh` 之外还有引擎内置阈值**（1.4.4 默认 `text_score=0.5`），
   低置信框可能在 adapter 之前就被丢弃；需要"全量召回"时把 `params.text_score` 调低。
7. **图像预处理不做**：旋转/去畸变交给各引擎内部；PDF 未直接支持（`dataset` 收集到的 `.pdf`
   需先转图，rapidocr/paddle 均不吃 PDF 路径）。
8. 云 OCR 的成本按 `cost.per_image` 计（`usage={"images":1}`）；若厂商按"页/次"有阶梯价，
   需在 `cost` 里自行折算成每张单价。
