# 数据集放置规范

语料**放这里**，一个场景一个子目录，系统按目录名识别数据集。

```
datasets/
└─ <数据集名>/                  # 例：invoice / idcard / handwriting / mixed
   ├─ images/                   # 必填：图片（支持 jpg/jpeg/png/bmp/webp/tif/tiff/pdf）
   │   ├─ 001.jpg
   │   └─ 002.png
   ├─ labels/                   # 标注（可后补，缺了就跑只看延迟/成本/输出量）
   │   ├─ 001.txt               # L1 全文标注
   │   └─ 002.json              # L2/L3 结构化标注
   └─ meta.yaml                 # 可选：语言、场景、来源、许可
```

**样本 ID = 文件名去掉扩展名**（`001.jpg` → `001`）。图片与标注靠 stem 对齐，支持 `images/` 下再分子目录。

---

## 三级标注（强烈建议 L1 + L2）

### L1 全文（`labels/<stem>.txt`）
纯文本，一行一段，与图中阅读顺序一致。

```
发票号码：12345678
开票日期：2024-05-01
合计金额：￥1,234.00
```

- 用于：CER / 漏提率 / 多提率 / 完整率
- ⚠️ 局限：**行序不同会被算成错误**（中文 CER 会被虚高放大）。只在你懒得标框时用。

### L2 行级（`labels/<stem>.json`）—— 推荐，最可信
```json
{
  "text": "发票号码：12345678\n开票日期：2024-05-01",
  "lines": [
    {"text": "发票号码：12345678", "box": [120, 88, 640, 132]},
    {"text": "开票日期：2024-05-01", "box": [120, 150, 640, 194]}
  ]
}
```
- `text` 可省略（系统用 `lines` 拼）
- `box` 可省略；给了就能额外算**定位 IoU**（判断模型是真的读到了位置还是瞎猜）
- `box` 格式：`[x1,y1,x2,y2]` 像素坐标，或 `[[x,y],[x,y],[x,y],[x,y]]` 四点
- 行级指标按归一化后**行文本集合**匹配 → 免疫行序差异，这是它比 L1 可信的原因

### L3 字段级（`labels/<stem>.json`，P2 才用）
```json
{ "fields": { "发票号码": "12345678", "合计金额": "1234.00", "开票日期": "2024-05-01" } }
```

---

## meta.yaml（可选）

```yaml
lang: zh                 # zh / en / mixed
scene: 票据              # 场景标签，报告按 scene 分组对比
source: 内部扫描件        # 来源说明
license: internal
hard_cases: [模糊, 手写, 低光]   # 用于报告分难度归因
```

---

## 没有标注怎么办

**先问一句：这批语料是不是某份文档的截图？** 如果是 Markdown 源码视图截图（`#` / `**` / `|` 在画面里），真值就在源文件里，别手工转录：

```bash
# .md 放到 datasets/<名>/markdown/ 下
.venv/bin/python -m tools.md_gt --dataset <名> --dry-run   # 先看对齐到哪几行
.venv/bin/python -m tools.md_gt --dataset <名>             # 写 labels/<stem>.txt
```

原理是「OCR 只用来定位行号，标注取自 .md 原文」，所以不会拿被测引擎自己的输出当标准答案。详见 README §3。

否则再用草稿 + 人工路线：

先跑 `veval label draft`（用最强在线模型生成草稿 GT），再跑 `veval label review`（生成本地 HTML 校正页，改完导出标准标注）。人只做校对，不做全量手打。

⚠ 反例：**别用「你即将评测的那个引擎」出草稿当 GT**（比如用 rapidocr 给 rapidocr 出草稿），那是自证循环，CER 会虚低到无意义。草稿必须由更强模型生成 + 人工确认。

## 快速自检

```bash
veval dataset inspect invoice    # 统计图片数/标注覆盖/是否有 box，缺标注会列 ID
```
