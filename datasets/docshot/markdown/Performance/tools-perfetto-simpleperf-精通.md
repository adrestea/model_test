# Perfetto + Simpleperf 工具精通线(四级能力阶梯)

> 模块 ID:无编号(主题驱动命名,工具精通线) ｜ 所属层:`modules/Performance`(与源参考同目录) ｜ 难度:★→★★★★(四级阶梯) ｜ 依赖前置:[[M0d 工具链]](`modules/L0/M0d-工具链.md`)基础 10 条 SQL 模板、adb、SQL SELECT/JOIN
> 关键点:Perfetto×Simpleperf 协同模型(Where/When ↔ Why/How much)、数据源→轨道→SQL 表心智模型、`frame_timeline_event` vs `actual_frame_timeline_slice` 二元表消解(**v57.2 实测:实际表为 `actual_frame_timeline_slice`,`frame_timeline_event` 不存在**)、trace_processor 高级函数(`EXTRACT_ARG`/window/RUN_METRIC)、UI 五大高级操作、simpleperf 高级采样(`--trace-offcpu`/`annotate.py`/`--post-unwind`/dwarf vs fp)、ARM PMUv3 + 原始 r 编号、ARM TMA(stall 近似,非 Intel 等价)、Python 自动化管线、`ProfilingManager` system-triggered 闭环、健康阈值"诊断起点·需真机校准"
> 状态:**Lv0/Lv1/Lv2 核心 SQL 经 v57.2 真 trace 实测跑通**(`actual_frame_timeline_slice` / `thread_state` / jank→thread_state 联合,详见 `未验证清单.md` 第八节 V1-V7;实测发现并已修正 C1-C3);TMA/PMU/`--trace-offcpu` 等真机项仍「内容完成 · 未验证」,粒度见尾节「状态与诚实标注」
> 关联:本线是 [[M0d 工具链]] 的**深度延伸**(不重复其 10 条 SQL);正向引用 [[M0b]]/[[M0c]]/[[M0.5]]/[[M3]]/[[M5]]/[[M6]] 与 L3 模块;编号归一映射见第七节。

> **致读者**:本线不是入门工具教程(入门见 [[M0d 工具链]]),而是把"会开 Perfetto/simpleperf"推到"能在一份新 trace 上独立产出 jank 归因 + 阻塞链 + 热点深挖 + TMA 微架构分类 + 优化建议五步闭环"的**能力阶梯**。无目标设备时,Lv3 的 TMA 归因只能停在推演级——真机到位前不算"达到 Lv3 归因能力"。所有真机级结论按四类标注(见尾节)。

---

## 〇、术语速查(0 基础先看)

> 分级口径:Lv0 必懂 / L1+ 进阶 / L3 专家。每条一句话定义。

### Lv0 必懂

| 术语 | 一句话定义 |
|------|-----------|
| **Perfetto** | Android 现役 trace 系统,回答"Where/When"(谁在什么时候做了什么);三层架构(config→`.pb`→trace_processor SQL/UI)。 |
| **Simpleperf** | 基于 PMU 硬件计数器的 CPU 采样工具,回答"Why/How much"(CPU 时间花在哪、为什么慢);输出 `perf.data`。 |
| **IPC(Instructions Per Cycle)** | `instructions / cpu-cycles`,每周期退休指令数;<1 说明 CPU 在等待(stall),是 Lv0 判 CPU 利用率的第一指标。 |
| **FrameTimeline 五元组** | SurfaceFlinger(Android 12+)上报的 `expectedPresentTime`/`actualPresentTime`/`expectedDisplayTime`/`jankType`/`presentType`,判帧责任的权威来源。 |
| **jank_type 四分类** | 本线采用 M0d/M3 统一口径的**四分类**:`Self`(App 自身段)/ `App`(App 段,含 Self 细分)/ `SF`(SurfaceFlinger 合成段)/ `Display`(硬件呈现段);底层 FrameTimeline 有更细 8 类(`AppDeadlineMissed`/`BufferStuffing`/`SurfaceFlingerCpu/GpuDeadlineMissed`/`DisplayHAL`/`PredictionError`/`Unknown`),四分类是粗分映射。**⚠️ v57.2 实测:`jank_type` 列是描述性字符串而非 `Self/App/SF/Display` 枚举**(见下方真实枚举对照表);SQL 须用 `LIKE '%关键词%'` 匹配(可含逗号组合),`jank_type='App'` 在真机上命中 0 行。 |
| **off-CPU · on-CPU** | on-CPU = 线程正在某核执行(占用 cycle);off-CPU = 线程被切走(Sleeping/Blocked/等 IO/等锁),不占 cycle 但占墙钟时间;`--trace-offcpu` 让 simpleperf 报告能区分二者。 |
| **task comm 15 字符截断** | Linux task 结构的 `comm` 字段上限 15 字节(TASK_COMM_LEN);Android App 主线程名**不是 `'main'`**,而是进程包名按 15 字符截断后的字符串。例:`com.google.android.apps.nexuslauncher` 主线程名是 `s.nexuslauncher`(utid 736/tid 2782)。**`WHERE name='main'` 在 Android App 上命中 0 行**;定位主线程要用 `tid=pid`(主线程 tid == 进程 pid)、`ORDER BY tid LIMIT 1`(tid 最小者通常即主线程)、或 `LIKE` 匹配截断进程名。v57.2 实测见 `未验证清单.md` 第八节 V6/C3。 |

### L1+ 进阶

> **`jank_type` 真实枚举对照表(v57.2 真 trace 实测,见 `未验证清单.md` 第八节 V5/C2)**
>
> | 真实 jank_type 字符串(v57.2) | 高层分类 | 责任方 |
> |---|---|---|
> | App Deadline Missed | App | 应用帧提交慢 |
> | SurfaceFlinger CPU/GPU Deadline Missed / SurfaceFlinger Scheduling | SF | 合成调度 |
> | Display HAL | Display | 显示 HAL |
> | Buffer Stuffing / Prediction Error / Unknown Jank | 其他 | 缓冲/预测/未知 |
> | None | 无 jank | — |
>
> **注**:①`jank_type` 可含逗号组合(如 `"SurfaceFlinger CPU Deadline Missed, App Deadline Missed"`),SQL 用 `LIKE '%关键词%'` 匹配;`='App'`/`='Self'`/`='SF'`/`='Display'` 会命中 0 行。②真实 trace 实测样例(本机 v57.2,44.8MB trace,来源见未验证清单 §八 V5):Buffer Stuffing 95 / SF CPU Deadline 22 / App Deadline Missed 5 / SF Scheduling 4 / Unknown Jank 3 / Prediction Error 3 / SF GPU Deadline 2 / Display HAL 1。③四分类 Self/App/SF/Display 是底层 `FrameJankType` bitmask 的高层映射,保留作对外口径,但 SQL 层须按真实字符串匹配。

| 术语 | 一句话定义 |
|------|-----------|
| **PMU(Performance Monitor Unit)** | ARM 核内的性能计数单元,按事件计数(`cpu-cycles`/`instructions`/cache 事件等);simpleperf 经 Linux `perf_event` 子系统读它。 |
| **stall(frontend/backend)** | CPU 流水线空转周期:frontend stall=取指/解码/指令 cache miss;backend stall=执行端/数据 cache miss/内存依赖;对应 TMA 的 Frontend/Backend Bound。 |
| **cache line** | CPU 缓存行,ARMv8 通常 64 字节;数据跨 cache line 访问(如 stride 12 访问 x/y/z)会导致每次访问 miss,是 Lv2/Lv3 数据布局优化的关键概念。 |
| **SoA / AoS(Structure of Arrays / Array of Structures)** | 数据布局:AoS=`struct{x,y,z}[]`(每元素三字段交错,跨 cache line);SoA=`struct{x[],y[],z[]}`(同字段连续,利于 cache/向量化);Lv3 粒子 VBO Case 用 SoA 降 L1D miss。 |
| **`EXTRACT_ARG(arg_set_id, 'key')`** | trace_processor SQL 函数,从 `args` 表提取 slice 的附加键值对(如 binder `data size`、thread `blocked_function` 来源),是 arg 下钻的核心。**v57.2 实测 binder arg key**(`'data size'` 带空格,非下划线;另含 `'calling tid'`/`'code'`/`'destination name'`/`'destination node'`/`'destination process'`/`'destination thread'`/`'flags'`/`'offsets size'`/`'reply transaction?'` 布尔/`'transaction id'`;**无 `'reply_size'` key**,reply 体积在 reply slice 上读 `'data size'` 或读 `'reply transaction?'` 布尔。见未验证清单 §八 V11/C4a) |
| **window 函数(LAG/LEAD/PARTITION BY)** | trace_processor SQL 支持的窗口函数,用于跨核迁移、唤醒链、帧间差等"与前一行/后一行比较"场景。 |

### L3 专家

| 术语 | 一句话定义 |
|------|-----------|
| **TMA(Top-Down Microarchitecture Analysis)** | 把 CPU 流水线利用率分解为 Retiring / Frontend Bound / Backend Bound / Bad Speculation 四类;**ARM 版是 stall 比例近似(见 #6 声明),非 Intel pipeline-slot 等价**。 |
| **pipeline_width** | 核的解码/发射宽度,A76=4-wide;`total_slots = cpu_cycles × pipeline_width`,是 TMA 公式分母;**核依赖硬编码**,他核需另查 TRM。 |
| **TRM(Technical Reference Manual)** | ARM 核的技术参考手册,PMU 事件编号表与微架构参数(penalty_cycle 等)的唯一权威来源;A76/A78/A710 各自独立 TRM。 |
| **imp-def(IMPLEMENTATION DEFINED)** | ARM 架构中"由实现定义"的项——PMU 事件 ID、stall 计数语义、TMA 系数均属 imp-def,即 A76 与 A78 同名事件 r 编号可能不同。 |
| **PMUv3 / PMCR** | ARMv8 性能计数架构与控制寄存器;`PMCR` 启停计数,`PMUv3` 定义事件空间;核识别读 `midr_el1`。 |

> **`frame_timeline_event` 与 `actual_frame_timeline_slice` 关系(技术修正 #1)**:两者是**同一 frame timeline 数据源的不同投影表**。`frame_timeline_event` 是 event-like 投影(列 `actual_ts`/`display_frame_token`/`jank_type`,M0d #2 口径);`actual_frame_timeline_slice` 是 slice-like 投影(列 `ts`/`dur`/`jank_type`/`on_time_finish`/`upid`,**关联 waker/thread_state 需 ts/dur 范围**)。**v57.2 实测:`actual_frame_timeline_slice` 存在,`frame_timeline_event` 不存在**(`SELECT count(*) FROM sqlite_schema WHERE name='frame_timeline_event'` = 0)——本线 SQL 一律以 `actual_frame_timeline_slice` 为主,`frame_timeline_event` 仅作版本探测备注;不同 Perfetto 版本/数据源组合下可能仅存其一,**执行前先用 `SELECT count(*) FROM sqlite_schema WHERE name='frame_timeline_event'` 探测,再以 `.schema <table>` 校对实际列名**。

> **⚠️ `actual_frame_timeline_slice` 与 `slice` 的关联列在不同 Perfetto 版本上不统一**:可能用 `display_frame_token`/`frame_id`/`id` 等,需以 `.schema` 为准;M0d #2 原文 `display_frame_token = s.arg_set_id` **不应作权威 join 键(join key 待 `.schema` 校对)**——v57.2 实测 `actual_frame_timeline_slice` 有 `display_frame_token` 列,但与 slice 的关联列需实测确认。任何 fallback SQL 同样不假定 `display_frame_token = slice.arg_set_id`(join key 待核)。

> **⚠️ `actual_frame_timeline_slice.upid` 在不同 Perfetto 版本里指代不同**(可能指 SF 上报进程或帧 producing upid);按目标 App 过滤时优先用 `display_frame_token`/`frame_id` 关联到 `slice` 再 join 拿归属进程,而非直接 `WHERE upid=<app_upid>`(待 `.schema` 校对)。

---

## 一、问题与实现原理

本线回答:**"我看到一个性能问题,如何把 Perfetto(宏观时序)与 Simpleperf(微架构热点)协同用到位,从入门一直推到专家级 TMA 归因?"** 工具会用≠会协同;会协同≠能出可证伪结论。本线把"用工具"拆成四级阶梯,Lv0 认工具,Lv1 会抓会查,Lv2 联合闭环,Lv3 TMA 归因 + 自动化。

**纪律(贯穿)**:**Perfetto 定 Where/When,Simpleperf 定 Why/How much;先宏观后微观,先 dumpsys 后 trace,结论必须可证伪。**

> **本线是 [[M0d 工具链]] 的深度延伸,不重复其 10 条 SQL 模板**。Lv0/Lv1 起手**实测 v57.2 用 `actual_frame_timeline_slice`**(`frame_timeline_event` 在 v57.2 不存在,可能仅旧版本;执行前用 `SELECT count(*) FROM sqlite_schema WHERE name='frame_timeline_event'` 探测);Lv2/Lv3 的差异化 SQL 见第七节「去重边界声明」逐条标"不重叠"。

### 1.1 工具协同模型

```
┌─────────────────────────────────────────────────────────────┐
│              用户感知:掉帧 / 卡顿 / ANR / 耗电                │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────▼─────────────────────┐
        │   Perfetto(宏观定位:Where & When)        │
        │   "哪一帧慢了?哪个线程在哪段阻塞?         │
        │    谁唤醒了它?跑了哪个核?频率多少?"      │
        └────────────────────┬─────────────────────┘
                             │ 锁定 线程 + 时间窗口 + 核
        ┌────────────────────▼─────────────────────┐
        │   Simpleperf(微观剖析:Why & How much)    │
        │   "该线程 CPU 时间花在哪?                 │
        │    Cache/TLB/Branch/IPC 瓶颈?             │
        │    TMA:Frontend/Backend/Retiring/Spec?"   │
        └────────────────────────────────────────────┘
```

> **核心原则**:Perfetto 回答 "Where & When"(系统时间线),Simpleperf 回答 "Why & How much"(微架构计数)。先 Perfetto 锁定线程+时间窗口,再 Simpleperf 深挖该窗口的 CPU 热点。反过来(先 simpleperf 找热点再 Perfetto 找时序)只适合纯 CPU 密集型场景,对交互卡顿失效(卡顿的"热点"不一定在掉帧那帧)。

### 1.2 数据源 → 轨道 → SQL 表 心智模型

Perfetto 三层心智(理解它就能自定 config + 写 SQL,而非背命令):

```
config 数据源 (data_source)        → trace 里的轨道 (track)        → trace_processor SQL 表
─────────────────────────────────────────────────────────────────────────────────────
linux.ftrace                       sched/track                     sched, thread_state, counter
  sched_switch/sched_waking                                          (cpu, waker_utid, blocked_function)
  power/cpu_frequency                cpufreq track                   cpu_counter_track + counter
android.surfaceflinger.frametimeline Expected/Actual Timeline | `actual_frame_timeline_slice`(slice-like,v57.2 实测存在;`frame_timeline_event` v57.2 不存在,可能仅旧版本) — 同源不同投影(见 §〇、技术修正 #1) |
linux.process_stats / android.atrace process/thread tracks         thread, process, thread_track, slice
android.power                       power rail track                counter + gpu_counter_track
```

**关键 join 链**(M0d 已建立,本线复用并扩展):
- `slice` → `thread_track`(via `track_id`)→ `thread`(via `utid`)→ `process`(via `upid`)(所有"谁的 slice 耗时"的基础)
- `actual_frame_timeline_slice`(Lv0/Lv1 起手实测口径,Lv2/Lv3 关联用同一张表;**v57.2 实测 `frame_timeline_event` 不存在**)→ 关联 slice:**`actual_frame_timeline_slice` 与 slice 的关联列不同 Perfetto 版本不统一**(`display_frame_token`/`frame_id`/`id` 需以 `.schema` 为准;M0d #2 原文 `e.display_frame_token = s.arg_set_id` 不应作权威 join 键,**join key 待 `.schema` 校对**——v57.2 实测 `actual_frame_timeline_slice` 有 `display_frame_token` 列,但与 slice 的关联列需实测确认);fallback SQL 同样 join key 待核,不假定 `display_frame_token = slice.arg_set_id`
- `actual_frame_timeline_slice`(Lv2/Lv3)+ `thread_state`(via `upid` + ts/dur 范围)+ `thread`(waker via `waker_utid`)(掉帧→阻塞→唤醒者三表关联,见第三/四节)

> **`frame_timeline_event` vs `actual_frame_timeline_slice`(技术修正 #1)**:**v57.2 实测以 `actual_frame_timeline_slice` 为主**(列 `ts`/`dur`/`jank_type`/`on_time_finish`/`upid`,join `thread_state` 需 ts/dur 范围);`frame_timeline_event` 在 v57.2 不存在,可能仅旧版本。Lv0/Lv1/Lv2/Lv3 SQL 一律用 `actual_frame_timeline_slice`;若探测到 `frame_timeline_event` 存在,作为 event-like 备选(列 `actual_ts`/`display_frame_token`/`jank_type`,对齐 M0d #2)。术语节已说明二者是同源不同投影。

### 1.3 四级能力阶梯总览

| 级别 | 驱动 | 目标 | 贯穿案例(无设备可推演) | Android 16 锚点 |
|------|------|------|------------------------|---------------------------|
| **Lv0 入门** | 机制 | 认得工具分工(Perfetto=Where/When,Simpleperf=Why/How much);UI 打开 trace 认红帧;读 simpleperf stat 的 IPC | Perfetto UI 打开公开示例 trace,识别一帧 jank 并判 jank_type;读一份 stat 输出判 IPC 高低 | `FrameJankType` **四分类**(Self/App/SF/Display)口径,较旧版三分类已细化 |
| **Lv1 中级** | 机制 | 独立写 `trace_config.pbtx`;trace_processor SQL(单表→多表 JOIN→`EXTRACT_ARG`/window);simpleperf record 多事件 + report/火焰图 | 公开 trace 上跑核心 SQL 产出线程状态分布;simpleperf record→report 火焰图 | `android_jank_cuj` metric 在 16 的字段(**v57.2 实测依赖 CUJ 标记,非 CUJ trace 输出空,见 §八 V12/C5**);`ProfilingManager`(A15 主动请求,A16 system-triggered)入口 |
| **Lv2 高级** | 问题 | 一个真实问题做 Perfetto+Simpleperf **联合闭环**:掉帧→锁→Binder→调度 + `--trace-offcpu` 交叉验证 | 复用 [[M3 卡顿与帧率]] Case:主线程等 RenderThread 锁,深挖热点(粒子 VBO 子问题) | ARR 帧率切换(`hasArrSupport`/`getSuggestedFrameRate`,16 增强 API)导致的 jank 归因 |
| **Lv3 专家** | 问题 | TMA Top-Down + 自定义 SQL Metric + Python 自动化管线 + 功耗/thermal 联合(**注:无设备下只能推演,见诚实声明**) | 源 §7(粒子 VBO 案例,见源文档 `perfetto-simpleprof.md` §7)(数据齐全:IPC 0.72→1.85、L1D Miss 38.2%→3.1%、最大帧时长 28ms→7.2ms)升级:jank→L1D miss→SoA 重构;TMA L1/L2 用 §7 示例数据推演 | `ProfilingManager` **system-triggered**(A16 新增)→ trace 落 app data dir → Python 管线自动消费 |

### 1.4 二工具协同的边界与交接点(防误用)

**何时该换工具**(Perfetto→Simpleperf 交接点):
1. Perfetto 已定线程+时间窗+核+频率(thread_state 显示主线程 S/D 段长)→ 此时**单纯看 trace 已到极限**(trace 只告诉你"等",不告诉"等的同时对手线程在烧什么 cache"),必须交接 simpleperf 看对手线程的微架构开销。
2. Perfetto 显示线程 R 但 dur 短(Runnable 等不到 CPU)→ 这是**调度/CPU 资源**问题,**不该**交接 simpleperf(微架构不是瓶颈),转 M0c 调度 / M5 大小核分析。
3. simpleperf 显示某函数占 cycles 高但**该函数所在的帧没掉**→ 这是"热但不掉"(有预算余量),**不该**据此优化;优化热点要看"导致掉帧那帧的热点",不是任意热点。这就是为什么必须先 Perfetto 定窗再 simpleperf 深挖窗内。

**何时二工具合用(联合闭环 vs 单工具足够)**:
- **联合**(Perfetto+Simpleperf):交互卡顿(jank 在某帧)、调度+算力混合瓶颈、锁竞争 → Lv2 场景。
- **单 Perfetto 足够**:纯调度问题(选核/频率抖动)、Binder 阻塞(服务端慢)、IO 等待、启动阶段切分 → 这些 trace 已能定论,simpleperf 无增益。
- **单 Simpleperf 足够**:纯 CPU 密集算法内核(解码/加密/数值计算)、已知热点的火焰图深挖、IPC/miss 微架构基线 → 无时序定位需求。

**反协同(常见误用)**:
- 只抓 simpleperf 不抓 Perfetto:对交互卡顿必漏(找不到热点属于哪一帧)。
- 只抓 Perfetto 不抓 simpleperf:对算力瓶颈只能停在"线程在跑某函数"(从 atrace slice 看),看不到 cache/branch/TMA。
- 二者窗口不对齐:simpleperf 抓 30s 但 jank 出现在第 5s,报告的"Top 函数"未必是第 5s 的 Top → 必须同场景/同时长复现或精确窗口锁定。

---

## 二、工具箱(按四级分组)

> **去重边界声明**:本线工具箱**只放跨模块联合命令 / EXTRACT_ARG+window / 自定义 Metric / Python 管线 / TMA / 功耗联合 / UI 高级操作 / simpleperf 高级采样模式**;单模块工具(如 `gfxinfo framestats` 单用、`dumpsys SurfaceFlinger --latency` 单用)回引 [[M3 卡顿与帧率]] 二工具箱,不重写。M0d 的 10 条 SQL 模板本线不重复,Lv0/Lv1 起手**实测 v57.2 用 `actual_frame_timeline_slice`**(`frame_timeline_event` 在 v57.2 不存在,可能仅旧版本,探测后用)。

### 2.1 Lv0/Lv1 — Perfetto UI 五大高级操作

全部可在 Perfetto 公开示例 trace(ui.perfetto.dev → Open trace → 选示例)上练,**无设备友好**:

| 操作 | 用法 | 解决什么 |
|------|------|----------|
| **Pinning(钉 slice)** | 右键 slice → "Pin to top" | 把关键 jank slice 钉成时间锚,滚动 trace 时不丢锚;跨窗口对齐用它 |
| **Args flotation(arg 浮到 slice)** | slice 详情面板 → 把 arg 拖到轨道 | 让 binder `data size`/`'reply transaction?'`、futex `lock_addr` 等 arg 直接显示在 slice 上,无需写 SQL 即可看分布(**v57.2 实测 binder arg key 是 `data size`(带空格)、无 `reply_size`,见 §八 V11/C4a**) |
| **Slices selection(框选统计)** | 拖选一段区域 → 下方 "Slices" 面板看该区域 slice 分布 | 快速出一个窗口内"哪些 slice 占最多 dur"的统计(SQL 前的快速摸底) |
| **Query driver(UI 内直接跑 SQL)** | UI 左上角 "Query" → 进 SQL 编辑器,跑 `SELECT ... FROM actual_frame_timeline_slice WHERE jank_type != 'None'` | 不离开 UI 即可 SQL,结果可视化到轨道;适合 Lv1 反复调 SQL 时所见即所得 |
| **Track group 折叠** | 轨道头 → 折叠/展开分组 | 长会话上百条轨道时,把无关进程折叠,只展开目标 App + SF + RenderThread |

> **Lv0 推演**:打开 ui.perfetto.dev 公开示例 trace,在 Actual Frames 轨道找红色 slice(jank),右键 Pin;读详情面板的 `jank_type`(四分类 Self/App/SF/Display);用 Query driver 跑 `SELECT jank_type, COUNT(*) FROM actual_frame_timeline_slice GROUP BY jank_type` 看分布。**执行时先在示例列表里定位一条含 sched+binder+frametimeline 的具体 trace**(若找不到含全套的,Lv1 SQL 验收降级为"语法对齐 M0d 表名",见尾节诚实标注)。

**五大操作串成 Lv0 workflow**(无设备推演一条龙):
1. **Track group 折叠**:打开公开 trace 后先折叠无关进程,只展开目标 App + SurfaceFlinger;避免上百条轨道看不见重点。
2. **Slices selection 摸底**:在 Actual Frames 轨道拖选一段含明显红帧的区域 → 下方 "Slices" 面板给出该区 slice 分布 → 快速看哪些 slice 类型(drawing/measure/binder/sync)占 dur 最多(SQL 前摸索)。
3. **Pinning 锚定**:右键最红的 jank slice → Pin to top → 它成为时间锚;后续滚 trace 看前后帧时不丢锚。
4. **Args flotation**:点开该 jank slice 详情,把 `jank_type`/`on_time_finish`/`upid` 等 arg 拖到 slice 上方显示 → 不写 SQL 即可看到这帧的判责字段。
5. **Query driver 验证**:左上角 Query → 跑 `SELECT jank_type, COUNT(*) AS n FROM actual_frame_timeline_slice GROUP BY jank_type ORDER BY n DESC;` → 验证 UI 摸底的印象(量子集 vs 全集)。结果可视化到轨道(每行结果在轨道上高亮)。

**Lv0 输出**:能说"这份 trace 全会话 jank_type 分布(App 占 60%、SF 占 30%、Display 占 10%),最红那帧 jank_type=App、dur=24ms、on_time_finish=false";决定下一步用 Perfetto 下钻(若 App/SF 占多)还是 simpleperf(若已发现某线程 cycles 高)。

### 2.2 Lv1 — trace_processor 进阶函数(`EXTRACT_ARG` + window + `CREATE PERFETTO TABLE` + `RUN_METRIC`)

> **与 M0d 不重复**:M0d 仅在模板 3.10 用过一次 `EXTRACT_ARG`(OOM `oom_score`);本线讲透 **arg 表结构** 与 **window 语义**。

#### 2.2.1 arg 表结构与 `EXTRACT_ARG`

trace_processor 把 slice/instant 的附加键值对存到 `args` 表,经 `arg_set_id` 关联:

```sql
-- 摸底:看某 slice 都有哪些 arg key
SELECT DISTINCT flat_key, key, int_value, string_value, real_value
FROM args WHERE arg_set_id = (
  SELECT arg_set_id FROM slice WHERE name LIKE 'binder%' AND dur > 1e7 LIMIT 1
);
-- 典型 binder slice 的 arg(**v57.2 实测**):'data size'(带空格)、'calling tid'、'code'、'destination process'/'destination thread'/'destination name'/'destination node'、'flags'、'offsets size'、'reply transaction?'(布尔)、'transaction id' —— **无 'data_size' 下划线 key、无 'reply_size'**(见未验证清单 §八 V11/C4a)
```

`EXTRACT_ARG(arg_set_id, 'key')` 是封装好的提值函数(Lv1/Lv2 用):

```sql
-- Lv1:提 binder 调用的数据大小/对端,arg 下钻(与 M0d 不重叠:M0d #3 仅 LIKE '%binder%' 列表)
-- v57.2 实测:binder arg key 是 'data size'(带空格,非 'data_size');无 'reply_size'(用 'reply transaction?' 布尔或在 reply slice 上读 'data size')。见未验证清单 §八 V11/C4a
SELECT
  s.ts/1e6 AS start_ms, s.dur/1e6 AS dur_ms, s.name,
  t.name AS thread_name,
  EXTRACT_ARG(s.arg_set_id, 'data size') AS data_sz,
  EXTRACT_ARG(s.arg_set_id, 'reply transaction?') AS is_reply,
  EXTRACT_ARG(s.arg_set_id, 'destination process') AS dest_pid
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE s.name LIKE 'binder transaction%'
  AND s.dur > 1e7   -- >10ms
ORDER BY s.dur DESC LIMIT 20;
```

#### 2.2.2 window 函数(`LAG`/`LEAD`/`PARTITION BY`)

跨核迁移、唤醒链、帧间差等"与相邻行比较"场景:

```sql
-- Lv1:线程跨核迁移次数(M0d #5 用了 LAG,本线讲透 PARTITION BY 场景:按 utid 分组看迁移)
SELECT
  utid,
  cpu,
  ts,
  LAG(cpu) OVER (PARTITION BY utid ORDER BY ts) AS prev_cpu
FROM thread_state
WHERE utid IN (SELECT utid FROM thread WHERE name GLOB '*RenderThread*')
-- 外层包 COUNT(*):WHERE cpu != prev_cpu(Lv1 末 JOIN 速查会给完整版)
```

```sql
-- Lv1:跨核迁移完整版(LAG + PARTITION BY,外层包 COUNT 求 count,内层给明细)
WITH migrations AS (
  SELECT utid, cpu, ts,
         LAG(cpu) OVER (PARTITION BY utid ORDER BY ts) AS prev_cpu
  FROM thread_state
  WHERE utid IN (SELECT utid FROM thread WHERE name GLOB '*RenderThread*')
)
SELECT utid, COUNT(*) AS migration_count
FROM migrations
WHERE cpu != prev_cpu                -- 真正发生迁移的行(prev_cpu 为 NULL 的首行不算)
GROUP BY utid;
-- 解读:迁移次数 > 10 in 10s → 调度抖动,衔接 [[M5 大小核调度]];
--      迁移多 + Runnable 占比高 → CPU 资源不足 + 调度策略偏(小核→大核频繁抖)
```

```sql
-- Lv1:唤醒链(waker → wakee)的前驱后继
SELECT
  ts.name AS waker_thread,
  we.name AS wakee_thread,
  ws.ts/1e6 AS wake_ms,
  LEAD(ws.dur) OVER (PARTITION BY ws.utid ORDER BY ws.ts) AS next_run_dur
FROM thread_state ws
JOIN thread ts ON ws.waker_utid = ts.utid
JOIN thread we ON ws.utid = we.utid
WHERE ws.state = 'R' AND ws.waker_utid IS NOT NULL
ORDER BY ws.ts DESC LIMIT 50;
-- 读法:next_run_dur = 该 wakee 被唤醒后实际跑的时长;长 = 真干活,短 = 被唤醒又很快被切走(惊群/抖动)
```

```sql
-- Lv1:帧间差(LEAD 看下一帧 deadline 偏移,识别周期性 jank)
WITH frames AS (
  SELECT ts, dur, jank_type FROM actual_frame_timeline_slice
  WHERE upid = (SELECT upid FROM process WHERE name='<pkg>')  -- v57.2 实测 upid = 帧生产进程(见未验证清单 §八 V3),可正确过滤;join key 待 .schema 校对
)
SELECT ts/1e6 AS frame_ms, dur/1e6 AS dur_ms, jank_type,
       dur - LAG(dur) OVER (ORDER BY ts) AS dur_delta_ns
FROM frames
WHERE jank_type != 'None'
ORDER BY ts;
-- 读法:dur_delta 正值连串 = 帧时长持续增长(GC/内存压力累积型);周期性正负交替 = 调度抖动型
```

#### 2.2.3 `CREATE PERFETTO TABLE` + `RUN_METRIC`

```sql
-- Lv1/Lv3:自定义中间表(本线 Lv3 的 my_jank_summary Metric 会用到)
CREATE PERFETTO TABLE my_app_jank AS
SELECT ts, dur, jank_type, upid
FROM actual_frame_timeline_slice
WHERE upid = (SELECT upid FROM process WHERE name = '<your.pkg>')  -- v57.2 实测 upid = 帧生产进程;join key 待 .schema 校对
  AND jank_type != 'None';

-- RUN_METRIC 加载官方 metric 供 join(本线 Lv3 自定义 Metric 基础)
SELECT RUN_METRIC('android/android_jank_cuj.sql');
-- 之后可 JOIN android_jank_cuj 表
-- ⚠️ v57.2 实测:android_jank_cuj 依赖 CUJ 交互标记,非 CUJ trace 上该 metric 输出空 {}(见 §八 V12/C5);
--    故本线 Lv3 my_jank_summary 主写法改为直接基于 actual_frame_timeline_slice(按 upid/layer_name 分组),
--    不强制 CUJ;RUN_METRIC('android/android_jank_cuj.sql') 仅作「需 CUJ 分组时的可选(须用带 CUJ 标记的 trace)」。
```

> **部分验证(SQL 实跑;真机 PMU/TMA 项仍待)**:以上 `actual_frame_timeline_slice` / `thread_state` / `EXTRACT_ARG` / window SQL 经 v57.2 真 trace(44.8MB)实跑跑通(见 `未验证清单.md` 第八节 V1-V7);`counter` vs `cpu_frequency` 等其他表名仍需 `.schema` 校对(见尾节)。

### 2.3 Lv2 — simpleperf 高级采样模式

> 单模块 simpleperf 基础命令回引 [[M0d 工具链]] 2.6;本节只放高级/联合模式。

| 高级模式 | 命令要点 | 解决什么 / 读法 |
|----------|----------|------------------|
| **`annotate.py`(inline 源码注解)** | `python3 $NDK/simpleperf/report_html.py -i perf.data --add_source_code --source_dirs ./cpp`(需 `-g` 编译的 so) | HTML 报告里每行源码显示采样命中数,精确定位到代码行;与 `report_html.py --add_source_code` 同源(`annotate.py` 命令行版,适合 CI 产文本) |
| **`--per-thread-comm`(多线程按线程拆 comm)** | `simpleperf record -p <pid> --per-thread-comm ...` | 多线程 App 按线程拆 comm,报告里 RenderThread/主线程/worker 各自统计,不混在一起;复杂 App 必用 |
| **`--trace-offcpu`(报告读法)** | `simpleperf record ... --trace-offcpu`;`report` 看 on/off 差异 | 见下:on-CPU 火焰图 vs off-CPU 火焰图读法 |
| **`--post-unwind`(权衡)** | `--post-unwind=true` 设备端只录原始样本,PC 端用 `simpleperf unwind` 离线回栈 | 设备省 CPU/电池(不实时回栈)但产 raw 数据需后处理;on-device unwind 实时但占设备 CPU 影响测量;**长抓或电池敏感场景用 post-unwind,短抓用 on-device** |
| **dwarf vs fp 开销** | `--call-graph dwarf`(DWARF,需 unwind,开销大但完整)/ `--call-graph fp`(帧指针,需 `-fno-omit-frame-pointer` 编译,开销小但漏栈) | 性能敏感场景用 fp(快但要求编译支持);未知/第三方 so 用 dwarf(慢但完整);**对比测量时统一选一种,别混** |

**`--trace-offcpu` 报告读法(高频面试题)**:
- **on-CPU 火焰图**:`simpleperf report` 默认看 `cpu-cycles` 采样的栈,宽=占用 CPU 时间多=CPU 热点(算力瓶颈)。
- **off-CPU 火焰图**:加 `--trace-offcpu` 后 `report --children` 看含 sched_switch 事件的"off-CPU 栈"(线程被切走时的栈),宽=等待时间长=同步/IO/锁瓶颈(非算力而是等待)。
- **判读**:同一函数 on-CPU 宽=算力不够(优化算法/数据布局);off-CPU 宽=等锁/IO(改并发/异步/缓存);两者都宽=既慢又等(最糟,先治等待再治算力)。

> **推演级 · 待真机**:`--trace-offcpu`/`annotate.py`/`--post-unwind`/dwarf vs fp 开销实测数据全部依赖真机 + 带符号 so + 目标 SoC,无设备下连"跑通命令"都做不到;本节给的是命令骨架与读法,真机实测前不标"已验证"。

### 2.4 Lv3 — 自动化与扩展(Python `trace_processor` API + `ProfilingManager` 闭环 + Macrobenchmark 复用 + `--symfs`+addr2line 区分 JIT/AOT)

```python
# Lv3:Python trace_processor API + pandas 自动化管线
from perfetto.trace_processor import TraceProcessor
import pandas as pd

def analyze_trace(trace_path):
    tp = TraceProcessor(trace=trace_path)
    # 1. 掉帧检测(actual_frame_timeline_slice 口径,Lv0/Lv1 起手表;v57.2 实测 frame_timeline_event 不存在)
    jank_df = tp.query("""
        SELECT ts/1e6 AS actual_ms, jank_type, display_frame_token
        FROM actual_frame_timeline_slice
        WHERE jank_type != 'None'
        ORDER BY ts
    """).as_pandas_dataframe()
    # 2. 主线程阻塞分析(Lv2 关联)
    # Android 主线程名是截断后的进程名(task comm 15 字符),不是 'main';
    # v57.2 实测 nexuslauncher 主线程名为 s.nexuslauncher,用 tid=pid 定位最稳(见未验证清单 §八 V6/C3)。
    blocking_df = tp.query("""
        SELECT ts.state, SUM(ts.dur)/1e6 AS total_ms, ts.blocked_function
        FROM thread_state ts
        JOIN thread t ON t.utid = ts.utid
        WHERE t.upid = (SELECT upid FROM process WHERE name = '<pkg>')
          AND t.tid = (SELECT pid FROM process WHERE name = '<pkg>')  -- 主线程 tid == 进程 pid
          AND ts.state IN ('S','D') AND ts.dur > 3e6
        GROUP BY ts.blocked_function ORDER BY total_ms DESC LIMIT 5
    """).as_pandas_dataframe()
    # 3. Binder 延迟分桶
    binder_df = tp.query("""
        SELECT CASE WHEN dur<1e6 THEN '<1ms' WHEN dur<5e6 THEN '1-5ms'
                    WHEN dur<1e7 THEN '5-10ms' ELSE '>10ms' END AS bucket,
               COUNT(*) AS n
        FROM slice WHERE name LIKE 'binder%' GROUP BY bucket
    """).as_pandas_dataframe()
    tp.close()
    return {'jank': jank_df, 'blocking': blocking_df, 'binder': binder_df}
```

**`ProfilingManager` system-triggered 闭环(A16)**:见 [[M0d 工具链]] 2.8 注册 API;本线的角色是**消费端**:trace 落 app data dir → 监听器拿 URI → 上传服务器 → 本线 Python 管线自动消费,形成"线上 ANR/启动难复现 bug → 自动抓 trace → 自动归因报告"闭环。

**Macrobenchmark trace 复用**:Macrobenchmark 跑完会产 `.perfetto-trace`,本线 SQL(线程状态/帧 jank/Binder)可直接在它上面跑,把"基准跑出了 janky% 升高"细化到"第几帧、哪个线程、等了什么"——不必额外抓 trace。

**`--symfs` + addr2line 区分 `.oat`(AOT) vs JIT 区域**:
```bash
# 准备符号目录:symfs 的 .so/.oat 带符号,addr2line 解析 IP
simpleperf report -i perf.data --symfs ./symbols --sort dso,symbol
# 关键:看热点落在 libfoo.oat(已 AOT 编译,稳定)还是 jit 段(JIT 实时编译,可能未优化)
#   .oat 段命中多 = AOT 已覆盖该路径(Baseline Profile 有效)
#   jit 段命中多 = AOT 未覆盖(JIT 实时编译开销大,需补 Baseline Profile 或预热)
addr2line -e libfoo.oat -f -C -i 0x12345   # 解析具体源码位置(0x12345 = report 里的 raw IP)
```

> **部分验证(SQL 实跑;真机项仍待)**:Python `trace_processor` API 形态对齐 `pip install perfetto` 官方文档,掉帧检测 + 主线程阻塞分析 SQL 经 v57.2 真 trace 实跑跑通(见 `未验证清单.md` 第八节 V1-V7,C1-C3 已修正);`ProfilingManager` 闭环机制对齐 M0d 已述(常量名以 16 SDK 为准);`--symfs`/addr2line 用法对齐 NDK simpleperf doc;二者均未真机实跑。

---

## 三、分析方法与得出结论的流程(每级一套 SOP)

> 每级 SOP 含三件:**输入 + 步骤 + 结论**。Lv1 末加「多表 JOIN 速查」前置(为 Lv2 铺路);Lv3 开头加「ARM PMU 架构前置」(消除微架构梯度断层)。

### 3.1 Lv0 SOP — 看懂 UI + 读 stat

- **输入**:一份 Perfetto 公开示例 trace(或真机 10s 短抓)+ 一份 `simpleperf stat` 输出。
- **步骤**:
  1. UI 打开 trace,定位目标进程的 Expected/Actual Frames 轨道。
  2. 在 Actual Frames 找红色 slice(jank),右键 Pin,读切片详情的 `jank_type`(四分类 Self/App/SF/Display)。
  3. UI Query driver 跑 `SELECT jank_type, COUNT(*) FROM actual_frame_timeline_slice GROUP BY jank_type` 看全会话 jank 分布。
  4. 读 `simpleperf stat` 输出末行的 `IPC = instructions/cycles`,判 CPU 利用率:大核 IPC≥1.5 健康(诊断起点·待真机校准,见第六节)。
- **结论**:能说出"这份 trace 里 jank 主导类型是 App(占 X%)还是 SF;IPC 是高还是低",并据此决定下一步用 Perfetto 下钻(若时序类)还是 simpleperf(若微架构类)。

### 3.2 Lv1 SOP — 写 config + SQL(单表→多表 JOIN→EXTRACT_ARG/window)+ report

- **输入**:目标 App 包名 + 一台能 adb 的设备(或公开 trace 复用)。
- **步骤**:
  1. 按问题裁剪 `trace_config.pbtx`(开场用 M0d 2.3 模板;判帧加 `android.surfaceflinger.frametimeline`;判 Binder 加 `binder/binder_transaction`;判功耗加 `android.power` + thermal ftrace)。
  2. `adb shell perfetto -c config.pbtx -o ...` 抓 + `adb pull` + `trace_processor -q` 跑 SQL。
  3. 单表起步:`SELECT jank_type, COUNT(*) FROM actual_frame_timeline_slice GROUP BY jank_type`(**v57.2 实测用此表**;`frame_timeline_event` 在 v57.2 不存在,执行前用 `SELECT count(*) FROM sqlite_schema WHERE name='frame_timeline_event'` 探测)。
  4. 多表 JOIN:见下方「多表 JOIN 速查」。
  5. `EXTRACT_ARG` 下钻 binder arg;window 函数看跨核迁移/唤醒链(见 2.2.2)。
  6. `simpleperf record -e cpu-cycles,instructions,cache-misses,branch-misses --call-graph dwarf -f 999`;`report --sort dso,symbol` 出 Top 函数。
- **结论**:产出一组"线程×核×状态×时长""帧×jank_type""Top 热点函数"的结构化数据,而非"肉眼滚 trace"。

#### 【Lv1 末前置】多表 JOIN 速查(thread JOIN process JOIN thread_state → WITH 子查询)

> 为 Lv2 的"掉帧→thread_state→waker 三表关联"铺路。Lv1 先掌握三表 + WITH 子查询。

```sql
-- 基础三表:thread + process + thread_state
-- 目标:某进程的主线程在指定时间窗内的状态分布
-- Android 主线程名是截断后的进程名(task comm 15 字符),不是 'main';用 tid=pid 定位最稳。
WITH main_utid AS (
  SELECT t.utid FROM thread t
  JOIN process p ON t.upid = p.upid
  WHERE p.name = '<your.pkg>' AND t.tid = p.pid   -- 主线程 tid == 进程 pid(v57.2 实测)
  LIMIT 1
)
SELECT ts.state,
       SUM(ts.dur)/1e6 AS total_ms,
       COUNT(*) AS count,
       ts.cpu,
       ts.blocked_function
FROM thread_state ts
WHERE ts.utid = (SELECT utid FROM main_utid)
  AND ts.ts BETWEEN <start_ns> AND <end_ns>
GROUP BY ts.state, ts.cpu
ORDER BY total_ms DESC;
```

**JOIN 链记忆法**:`thread`(utid) ←→ `process`(upid)是"谁属于哪个进程";`thread_state`(utid) ←→ `thread` 是"某线程每段状态";`slice`(track_id) → `thread_track`(utid) → `thread` 是"某 slice 是哪个线程的"。**WITH 子查询**用来先缩小 utid/upid 范围再 JOIN,避免大表全扫。

### 3.3 Lv2 SOP — 定位窗口(Jank 时间范围)→ 确认阻塞 → 深挖热点 → 关联结论

- **输入**:一个真实掉帧问题(复用 [[M3 卡顿与帧率]] Case,如主线程等 RenderThread 锁)。
- **步骤**:
  1. **定位窗口**:`SELECT ts, ts+dur AS end_ts, dur/1e6 FROM actual_frame_timeline_slice WHERE jank_type LIKE '%App Deadline Missed%' AND dur>16.6e6 ORDER BY dur DESC LIMIT 1`,拿到 jank 帧 ts/dur(此时窗)。**注**:v57.2 实测 `jank_type` 是描述性字符串(`App Deadline Missed`/`SurfaceFlinger CPU Deadline Missed`/...),不是 `App`/`SF` 枚举,`='App'` 命中 0 行;用 `LIKE '%关键词%'` 匹配(可含逗号组合)。
  2. **确认阻塞**:在此时窗内查主线程 thread_state(`blocked_function`):
     ```sql
     SELECT state, dur/1e6 AS ms, io_wait, blocked_function, waker_utid
     FROM thread_state
     WHERE utid = <main_utid>
       AND ts >= <jank_ts> AND ts < <jank_ts + jank_dur>
       AND state IN ('S','D') AND dur > 5e6
     ORDER BY dur DESC;
     ```
     **fallback**:若 trace 未含 `blocked_function` 列(版本/数据源差异),降级用 `waker_utid` + `io_wait` 列(配合 sched_waking ftrace event);若连 sched_waking 都没采,只能从 `R` 段看唤醒者。**v57.2 实测本 trace `blocked_function` 全空(0/254659 行;R9/V8)→ 降级 `waker_utid`+`io_wait` 链路通(`waker_utid` 75423 行有值、`io_wait` 971 行有值);是否非空取决于 trace 是否开 `sched/blocked_reason` 等 ftrace**。
  3. **找到唤醒者**:`SELECT name, upid FROM thread WHERE utid = <waker_utid>`;JOIN process 拿进程名(如果是 RenderThread 持锁,唤醒者就是 RT)。
  4. **深挖热点**:`simpleperf record -p <pid> -e cpu-cycles,cache-misses,stalled-cycles-backend --call-graph dwarf -f 8000 --duration 5`(对同一场景重抓或在窗口内对齐),`report --comms RenderThread --sort dso,symbol`。
  5. **`--trace-offcpu` 交叉验证**:加 `--trace-offcpu` 重抓,报告里看主线程 off-CPU 等待栈是否落在 futex_wait(锁)还是 io_read(IO),与 Perfetto 的 blocked_function 互证。
  6. **关联结论**:把"jank 帧 → 主线程 blocked_function → 唤醒者进程 → 唤醒者热点函数 + TMA 分类"串成可证伪结论。
- **结论**:例如"第 N 帧 jank(App),主线程在 [ts, ts+12ms] blocked_function=futex_wait,waker=RenderThread;RT 在同窗 `GameRenderer::updateVertexBuffer` 占 41% cycles + 38% cache-misses(stalled-backend 52%),根因是粒子数据 AoS 跨 cache line + 每帧重传 VBO"(源文档 §7 示例)。

> **Lv2 与 M3 的边界**:Lv2 只**复用 [[M3 卡顿与帧率]] 的 Case 场景与编号**(主线程等 RT 锁等),不重述帧管线/FrameTimeline 原理(M3 已述);本线侧重"Perfetto+Simpleperf 联合闭环"这个**方法**,而非卡顿性能原理本身。

#### Lv2 阻塞子类判定决策树(落地 step 2-3)

拿到"主线程 S/D 段长"后,按 `blocked_function`(或 fallback 的 waker_utid + io_wait)判阻塞子类,定优化方向:

```
主线程 thread_state S/D 段 > 5ms
        │
        ├─ blocked_function = futex_wait_queue_me ─→ 锁竞争
        │      └─ waker = RenderThread ─→ RT 持锁(治 RT 算力/双缓冲)
        │      └─ waker = binder thread ─→ 跨进程锁(治并发)
        │
        ├─ blocked_function = io_wait / io_read ─→ 主线程 IO
        │      └─ 修:SP/DB 异步、StrictMode detectDiskReads
        │
        ├─ blocked_function = doBinderTransaction / binder_transaction ─→ Binder 阻塞
        │      └─ 治:对端慢(查服务端 `EXTRACT_ARG(arg_set_id,'data size')` 带空格、`'destination process'` 取对端 pid;v57.2 实测见 §八 V11/C4a)+ 异步 binder
        │
        ├─ state = D (Disk Sleep) ─→ 不可中断 IO/驱动
        │      └─ 治:减少主线程 IO,移到 IO 线程;若驱动慢属系统侧(非 App 可控)
        │
        └─ state = R 但 dur 短 + 紧接 S ─→ Runnable 等不到 CPU
               └─ 治:核不够/调度抖(衔接 [[M5 大小核调度]]),Check 4 wakeup latency
```

**fallback 链**(blocked_function 列缺失时):
1. 优先看 `waker_utid`:谁唤醒主线程 = 谁释放资源 → 推断阻塞源(RT 持锁 / binder 服务端 / IO 完成中断)。
2. 看 `io_wait` 列(部分版本有):区分 IO wait vs futex wait。
3. join `slice` 表 `name GLOB '*futex*'`/`'*binder*'`/`'*io*'` 看同窗 slice(辅助定位)。
4. 补采 ftrace `sched/sched_waking` + `sched/sched_wakeup` 重抓,拿唤醒链。
5. 最后手段:从 `R` 段(wakeup 到 running)算 wake-up latency(M0d #8 模板),长 = 等 CPU,短 = 等资源。

### 3.4 Lv3 SOP — TMA 采集 → L1/L2 计算 → 自动化报表 → 功耗联合

#### 【Lv3 开头前置】ARM PMU 架构 + 核识别 + TRM 查号

> ARM PMU 是 imp-def,不讲清架构,Lv3 的 r 编号全部变成"复制粘贴后跑不通"。本前置消除这个断层。

- **PMUv3 / PMCR**:ARMv8 性能计数架构 PMUv3,控制寄存器 PMCR 启停;事件经 `PMXEVTYPER` 选 event ID;Linux `perf_event` 子系统封装,simpleperf 经 syscalls 调它。
- **核识别**:不同核(大核 A76/A78/A710、小核 A55)各自有独立 PMU,**同事件 r 编号不同**。读核型号:
  ```bash
  adb shell cat /sys/devices/system/cpu/cpu*/regs/identification/midr_el1    # 读各核 midr_el1
  # midr_el1 含 implementer + variant + architecture + part number + revision
  # 例:part=0xd0c=A76, part=0xd41=A78, part=0xd4d=A710(Arm 官方 part number 表)
  adb shell cat /proc/cpuinfo | grep -iE 'cpu part|model'                     # 备选(非所有设备暴露 midr)
  ```
- **命名事件 vs 原始 r 编号**:`simpleperf list` 只列出约 20 个通用命名事件(`cpu-cycles`/`instructions`/`cache-misses`…);原始微架构事件(STALL_FRONTEND r23 等)用 `r<hex>` 直接传 event number。**命名事件是 simpleperf 对原始 r 编号的部分封装**,不覆盖全部;专家级必须用 r 编号 + TRM。
- **查目标核 TRM 的 PMU 事件号**:`simpleperf list hw-cache` 看缓存事件;但 `STALL_FRONTEND`/`STALL_BACKEND`/`MEM_ACCESS_CHECKED` 等需查目标核 TRM 的 "PMU events" 章节(A76 TRM、A78 TRM 各自的 `DDIxxxx` 文档,Arm 官网下载)。**源文档 §6.1.1 的 A76 编号表(r03/r04/r05/r17/r22/r23/r24/r28 等)需对照 Cortex-A76 TRM 复核**(见尾节疑点 ①)。

#### 【#6 ARM TMA 近似性声明】(Lv3 SOP 前必读)

- **① ARM 无直接 pipeline-slot 计数**,Intel TMA 用 slots(分配/退休/停顿的槽位),ARM 只能算 **stall 周期比例**(`STALL_FRONTEND/cycles`、`STALL_BACKEND/cycles`),是近似非 Intel 等价。
- **② 各核 PMU 事件 ID 与系数(penalty_cycles、pipeline_width)是 imp-def**;源文档 §6.1.2 的 `penalty≈11`/`pipeline_width=4` 是 **A76 硬编码**,A78/A710/A715 需查对应 TRM/PMU guide。
- **③ "TMA-ARM 是 ARM 自己发布的近似方法论,非 Intel 官方移植"**:四分法结构借用 Intel(顶层 Retiring/Frontend/Backend/Bad Spec),但底层计数完全不同,精度低于 Intel TMA。
- **结论**:本线 Lv3 TMA 公式**仅适用 Cortex-A76**(依源文档示例),他核需重查 TRM 重算系数;真机到位前,Lv3 TMA 归因只能推演,不能独立归因。

- **输入**:TMA 所需事件 + 同一场景的 perf.data(§7 粒子 VBO 示例数据齐全,无设备主路径)。
- **步骤**:
  1. **采集 TMA 所需事件**(A76 示例,r 编号待 TRM 复核):
     **⚠️ 下述 r 编号仅适用 Cortex-A76 示例,他核无效;实跑前必须先 `cat /sys/devices/system/cpu/cpu*/regs/identification/midr_el1` 定核 + 查目标核 TRM 改 r 编号(见尾节疑点 ①,依 A76 示例·待 TRM 复核)**
     ```bash
     adb shell su 0 simpleperf stat -p <pid> --duration 10 \
       -e cpu-cycles,instructions,r23,r24,r22
     #   r23 = STALL_FRONTEND(A76)
     #   r24 = STALL_BACKEND(A76)
     #   r22 = BR_MIS_PRED_RETIRED(A76)
     # ! 仅 A76 适用;A78/A710 查对应 TRM 改 r 编号
     ```
  2. **L1 计算**(依 §6.1.2 公式,A76 示例):
     ```python
     pipeline_width = 4                      # A76 4-wide
     total_slots = cpu_cycles * pipeline_width
     retiring = inst_retired / total_slots
     bad_spec = br_mis_pred * 11 / total_slots   # penalty≈11,A76 核依赖
     frontend = stall_frontend / cpu_cycles
     backend = stall_backend / cpu_cycles
     ```
  3. **L2 细分**:Backend Bound 拆 Memory/Core,需 `r28`(MEM_ACCESS_CHECKED)等;**L2 阈值需配合 A76 stall 事件**,源文档 §6.1.3 的 L2 细分阈值单独列标"TMA L2 近似·需 A76 stall 事件",不并入诊断起点表。
  4. **自动化报表**:用 §2.4 Python 管线把上面计算封装;若 trace 含 power/thermal,加「功耗联合」:
     ```sql
     -- 关联掉帧时刻的 CPU 频率与温度(Lv3 功耗-性能联合)
     WITH jank_times AS (
       SELECT ts, dur FROM actual_frame_timeline_slice
       WHERE jank_type != 'None' AND dur > 16.6e6
     )
     SELECT jt.ts/1e9 AS jank_s, jt.dur/1e6 AS jank_ms,
            f.value/1000 AS cpu_freq_mhz, t.value/1000 AS temp_c
     FROM jank_times jt
     JOIN counter f ON f.ts >= jt.ts AND f.ts < jt.ts+jt.dur
     JOIN cpu_counter_track ft ON f.track_id = ft.id AND ft.name='cpufreq' AND ft.cpu=7
     JOIN counter t ON t.ts >= jt.ts AND t.ts < jt.ts+jt.dur
     JOIN track tt ON t.track_id = tt.id AND tt.name LIKE '%thermal%zone0%'
     ORDER BY jt.ts;
     ```
  5. **归因**:据 TMA 四分类比例定瓶颈主导(Retiring 低 + Backend 高=内存/数据布局;Frontend 高=指令 cache/分支等),出优化建议。
  6. **优化对照**(TMA 四分类主导 → 优化方向矩阵):
     | TMA 主导 | 典型成因 | 优化方向 | 案例 |
     |----------|----------|----------|------|
     | **Backend Bound(Memory)高** | 数据 cache miss / TLB miss / 内存带宽 | AoS→SoA、连续化、大页、prefetch、减 working set、循环展开对齐 | §7 粒子 VBO(L1D miss 38.2%) |
     | **Backend Bound(Core)高** | 执行单元争用 / 数据依赖链长 | 指令级并行(打破依赖链)、向量化(SIMD)、避免长 latency 指令 | 算法循环重写 |
     | **Frontend Bound 高** | 指令 cache miss / 分支密集 / 代码 footprint 大 | 函数拆小、热路径放一起、PGO/Baseline Profile、BRANCH 预测友好 | 启动冷路径 |
     | **Bad Speculation 高** | 分支预测失败(不可预测 if/switch) | 数据驱动替代多分支、查表(table-driven)、热路径排序 | JSON 解析多分支 |
     | **Retiring 高(>60%)** | 健康:大部分周期在退休有用指令 | 维持,无需微架构优化 | 紧致算法 |
- **结论**:示例(§7 粒子 VBO,A76 示例数据):Retiring 偏低(≈35%) + Backend Bound(≈52%)主导 → 下钻 backend_memory:r28/r03/r04 → L1D Miss 38.2% → AoS 数据布局跨 cache line(stride 12 访问 x/y/z) → 改 SoA({x[],y[],z[]}连续)+ 双缓冲 VBO + `glMapBufferRange` 替代全量重传;修后 IPC 0.72→1.85（+157%）、L1D Miss 38.2%→3.1%（-92%）、最大帧时长 28ms→7.2ms（-74%）。**推演级:**这些数值来自源文档 §7 示例,非本环境真机复测;真机到位前 Lv3 TMA 归因只能推演,不能独立归因。

#### Lv3 能力终点 & 报告模板

> **Lv3 终点定义**(能力达成门槛):在无提示下,对一份新 trace 完成 ①jank 归因 ②阻塞定位 ③热点深挖 ④TMA L1 分类 ⑤出优化建议 五步闭环,且报告通过人工 review。**诚实标注**:无真机时 ④与⑤只能停在**推演级**(只能复现 §7 推导链,不能对新 perf.data 独立归因);真机到位前不算"达到 Lv3 归因能力"。

**报告模板最小字段**(对齐能力自评):
1. **现象**:用户感知(掉帧/卡顿/ANR)+ 重现条件(场景/频率)
2. **时间窗口**:trace 里 jank 帧 ts/dur
3. **责任方**:jank_type 四分类(Self/App/SF/Display)
4. **阻塞链**:blocked_function → waker 线程/进程(若 S/D 阻塞)
5. **热点函数**:simpleperf report Top 函数(带 cycles/cache-miss/stall 占比)
6. **微架构分类**:TMA L1(Retiring/Frontend/Backend/Bad Spec 占比)+ L2(若采集)
7. **修复建议**:据 TMA 主导分类矩阵给方向 + 具体代码改法
8. **验证对照**:修复前/后指标(IPC/L1D Miss/帧时长/jank rate)
9. **验证状态标注**:完成但未验证 / 诊断起点·待校准 / 依 A76 示例·待 TRM 复核 / 推演级·待真机 之一

> **车机 AAOS guest 提示(完整性)**:车机 guest(Android)的 `cpu_freq`/`thermal` track 受 hypervisor 限制(guest 看到的是虚拟频率/温度,非 host 真实值);跨域性能分析需对齐 host 时钟(QNX/Momentics System Profiler 抓 host 线程 timeline,guest trace 与 host trace 时间戳对齐),交叉引用 [[M9.5 QNX与混合架构性能]]。

---

## 四、Case 实战(四个贯穿案例对 Lv0-Lv3,每案例给无设备推演路径)

> **资源清单(诚实标注)**:
> - ① **Perfetto 公开示例 trace**:ui.perfetto.dev → Open trace → 示例。**执行时先在示例列表定位一条含 sched+binder+frametimeline 的具体 URL**(若找不到含全套的,Lv1 SQL 验收降级为"语法对齐 M0d 表名",标「待公开示例核实」)。
> - ② **源文档 §7 粒子 VBO 案例**:数据齐全(IPC 0.72→1.85、L1D Miss 38.2%→3.1%、最大帧时长 28ms→7.2ms),**100% 可得,是 Lv2/Lv3 无设备主路径**。
> - ③ **AOSP/NDK simpleperf 示例 perf.data**:标「若可得」;不可得则统一改用 §7 推演数据,不把不可得当可执行验证基础。
> - 真机复现项标 **待真机复核**。

### Case 4.1 — Lv0:公开示例 trace 认 jank + 读 stat(机制级)

- **目标**:认工具分工,UI 认红帧,读 IPC,判 jank_type 四分类。
- **场景**:首次接触 Perfetto/simpleperf,需在 5 分钟内对一份 trace 说出"jank 主导类型 + IPC 高低"。
- **推演路径**:
  1. 浏览器开 https://ui.perfetto.dev → "Open trace" → 选一条公开示例(优先含 "SurfaceFlinger"/"Android"/"Pixel" 关键字的)。**执行时先在示例列表里定位一条含完整 sched+binder+frametimeline 的具体 trace**(若找不到含全套的,Lv0/1 SQL 验收降级为"语法对齐 M0d 表名",标「待公开示例核实」,见尾节)。
  2. 展开目标进程 → 找 "Actual Frames"/"Expected Frames" 轨道。红色 slice = jank 帧(dur 超 deadline);绿色 = 按时完成;黄色 = SF 合成延迟(见 [[M3 卡顿与帧率]] §1.6 颜色码)。
  3. 右键红色 slice → Pin(不丢时间锚)→ 详情面板读 `jank_type`(四分类 Self/App/SF/Display 之一,与底层 8 类对应见术语节)。
  4. UI Query driver(左上角 "Query")跑 jank 分布:
     ```sql
     -- 若 trace 含 actual_frame_timeline_slice 表:
     SELECT jank_type, COUNT(*) AS n
     FROM actual_frame_timeline_slice
     GROUP BY jank_type ORDER BY n DESC;
     -- 若仅含 frame_timeline_event 表(复用 M0d #2 口径,表名/列名需用 .schema 校对):
     SELECT jank_type, COUNT(*) AS n
     FROM frame_timeline_event
     GROUP BY jank_type ORDER BY n DESC;
     ```
     两种表先 `.schema <table>`(或 UI 左侧 schema 面板)校对存在哪张,再跑对应 SQL。**v57.2 实测**:`actual_frame_timeline_slice` 存在,`frame_timeline_event` 不存在(`sqlite_schema` 计数=0);本线统一用 `actual_frame_timeline_slice`。
  5. 读一份 `simpleperf stat` 输出(可用源文档 §4.4.1 文本,或自己设备 `adb shell simpleperf stat -p <pid> --duration 5`)📱(真机):
     ```
       1,234,567,890  cpu-cycles           # 246.9 MHz
         987,654,321  instructions         # 0.80 IPC
          12,345,678  cache-misses         # 15.2% of cache-references
     ```
     判读:末行 `IPC = 0.80` → 不健康(诊断起点:大核 IPC≥1.5,见第六节;但**须先确认采样线程跑在哪个核**,小核 0.8 可能正常,见 Check 3)→ 判"CPU 在等";`cache-misses` 15.2% → 偏高(L1D Miss 诊断起点 <5%)。
  6. 据上面两步决定下钻方向:四分类里 App 占多 + IPC 低 → Perfetto 定窗后 simpleperf 深挖;SF 占多 → 转合成路径分析(M3);IPC 不低但还 jank → 非算力问题(等锁/IO,查 thread_state blocked_function)。
- **结论**:能说出"这份 trace jank 主导类型(App-12/总-30/SF-3)+ IPC 0.80 落在大核判断偏低",并据此定下钻工具。这是 Lv0 验收:工具分工 + 认红帧 + 读 IPC + 判四分类。**真实 trace 实测样例(v57.2,本机 44.8MB trace,见未验证清单 §八 V5)**:Buffer Stuffing 95 / SF CPU Deadline 22 / App Deadline Missed 5 / SF Scheduling 4 / Unknown Jank 3 / Prediction Error 3 / SF GPU Deadline 2 / Display HAL 1——主导是 Buffer Stuffing + SF CPU Deadline(非典型 App 主导),说明真实分布与教科书 Case 不同,SQL 必须按真实 `jank_type` 字符串聚合。
- **常见坑**:
  - **坑 1**:不标 jank_type 四分类口径与底层 8 类对应,直接用 `AppDeadlineMissed`/`BufferStuffing` 等细分值 → 与 M3/M0d 口径不一致;本线统一四分类(Self/App/SF/Display)对外,底层细分在 join 用。**⚠️ v57.2 实测修正**:`jank_type` 列实际就是 `App Deadline Missed`/`Buffer Stuffing`/`SurfaceFlinger CPU Deadline Missed` 等描述性字符串(非 `App`/`SF` 枚举),且可含逗号组合;SQL 用 `LIKE '%关键词%'` 匹配,`='App'`/`='SF'` 命中 0 行(见术语节真实枚举对照表 + 未验证清单 §八 V5/C2)。
  - **坑 2**:IPC 数值不报核/频率前提 → 无意义(小核 0.8 正常,大核 0.8 异常)。报 IPC 必报核 + 频率(见 Check 3)。
  - **坑 3**:示例 trace 找不到含全套数据的 → 降级"语法对齐"(能写出 SQL 即验收),不把不可得当可执行验证基础。
- **资源**:① 公开示例 trace(待定位具体 URL);真机项 **待真机复核** 反推真机自己的 jank 分布 + 实测 IPC。
- **Android 16 锚点**:`FrameJankType` 四分类(Self/App/SF/Display)口径较旧版三分类(App/SF/None)已细化;Lv0 起手即用四分类对外。

### Case 4.2 — Lv1:公开 trace 上跑核心 SQL + simpleperf multi-event record(机制级)

- **目标**:会写裁剪 config、SQL(单表→多表 JOIN→EXTRACT_ARG/window)、multi-event record + 火焰图。
- **场景**:从"会认红帧"进阶到"能 SQL 出结构化结论 + 能用 simpleperf 多事件抓分析"。
- **推演路径**:
  1. **写 config**(裁剪 M0d 2.3 模板,加 frametimeline + binder + sched_waking):
     ```protobuf
     # trace_config_lv1.pbtx —— 判帧 + 判锁 + 判调度
     duration_ms: 10000
     buffers { size_kb: 65536 fill_policy: RING_BUFFER }
     data_sources { config { name: "linux.ftrace" ftrace_config {
       ftrace_events: "sched/sched_switch"
       ftrace_events: "sched/sched_waking"      # 唤醒链(本线扩展,M0d 模板未单独列)
       ftrace_events: "power/cpu_frequency"
       ftrace_events: "binder/binder_transaction"
       ftrace_events: "binder/binder_transaction_received"
     } } }
     data_sources { config { name: "android.atrace" atrace_config {
       categories: "view" categories: "am" categories: "gfx"
       atrace_apps: "<your.pkg>"                 # 限本 App 减 buffer 占用
     } } }
     data_sources { config { name: "android.surfaceflinger.frametimeline" } }   # 判帧核心
     data_sources { config { name: "linux.process_stats" } }
     ```
     **执行**(📱 真机):`adb shell perfetto -c /data/local/tmp/trace_config_lv1.pbtx --txt -o /data/misc/perfetto-traces/lv1.pb && adb pull /data/misc/perfetto-traces/lv1.pb`。无设备时直接在公开 trace 上跑下面 SQL。
  2. **单表起步**(**v57.2 实测用 `actual_frame_timeline_slice`;`frame_timeline_event` 在 v57.2 不存在**):
     ```sql
     SELECT jank_type, COUNT(*) AS n
     FROM actual_frame_timeline_slice
     WHERE jank_type != 'None'
     GROUP BY jank_type ORDER BY n DESC;
     ```
     执行前用 `SELECT count(*) FROM sqlite_schema WHERE name='frame_timeline_event'` 探测;若旧版本该表存在,改用 `frame_timeline_event`(对齐 M0d #2)。
  3. **多表 JOIN 速查 SQL**(§3.2 末给过的三表版)在公开 trace 上跑,产出"某线程在窗内 R/S/D 分布 + blocked_function"。**注意**:`blocked_function` 列需 ftrace 含 `sched/sched_switch` 的 blocked_function 来源(部分版本/数据源无此列 → fallback 用 waker_utid + io_wait,见 Case 4.3)。
  4. **`EXTRACT_ARG` arg 下钻**(§2.2.1 SQL):提 binder `data size`(带空格)/`'destination process'`。**v57.2 实测:binder arg key 是 `'data size'`(非下划线),无 `'reply_size'`**(用 `'reply transaction?'` 布尔或在 reply slice 上读 `'data size'`);先摸底发某 trace 的 binder slice 都有哪些 arg key(用 `SELECT DISTINCT flat_key,key,int_value FROM args WHERE arg_set_id=...`),再 EXTRACT_ARG(见 §八 V11/C4a)。
  5. **window 函数看跨核迁移**(§2.2.2):对 RenderThread 主轨,`LAG(cpu) OVER (PARTITION BY utid ORDER BY ts)` 外层包 `WHERE cpu != prev_cpu` count 迁移次数;迁移多 → 调度抖动,衔接 [[M5 大小核调度]]。
  6. **simpleperf multi-event record**(📱 真机):
     ```bash
     adb shell simpleperf record -p <pid> \
       -e cpu-cycles,instructions,cache-misses,branch-misses \
       -f 999 --call-graph dwarf --duration 10 \
       -o /data/local/tmp/lv1.data
     adb pull /data/local/tmp/lv1.data
     simpleperf report -i lv1.data --sort dso,symbol --percent-limit 1.0   # Top 函数
     python3 $NDK/simpleperf/report_html.py -i lv1.data -o lv1.html         # 火焰图
     ```
  7. **火焰图判读**:最宽的"平顶"(plateau)= 真正热点(源文档 §4.4.2);`libc.so`/`libart.so` 占比过高 → 可能过多系统调用;`__memcpy`/`__memset` 高 → 数据拷贝瓶颈。
- **结论**:`SELECT state, SUM(dur)/1e6 FROM thread_state WHERE utid=... GROUP BY state` 给出"线程时间花在 R/S/D 哪类"的结构化结论;`report --sort dso,symbol` 给出"哪个函数吃最多 cycles"。两者一对应,就能说"主线程 S 长(等)+ RT 在某函数吃 cycles(慢)= 联合根因"。
- **常见坑**:
  - **坑 1**:多行 SQL 在交互式 shell 报 syntax error → 改 `-q` 非交互(M0d 已述)。
  - **坑 2**:table 名版本差异(`frame_timeline_event` vs `actual_frame_timeline_slice`、`counter` vs `cpu_frequency`)→ 先 `.schema`/`.tables` 校对。
  - **坑 3**:**sample 频率 `-f 4000` 与 `-f 999`**:4000Hz 是 cycles 高频采样(源文档用);999Hz 避 1kHz 共振(M0d 经验)。本线推荐 999Hz 兜底(避共振),cycles 事件需高频可临时用 4000-8000,但不混用。
  - **坑 4**:`EXTRACT_ARG` 的 key 名(`'data size'` 带空格 vs `'size'` 等)各版本可能不同 → 先 `SELECT DISTINCT key FROM args` 摸底。**v57.2 实测 binder arg key 全集见 §2.2.1 / §八 V11/C4a**。
- **资源**:① 公开示例 trace(待定位,Sql 跑通即验收;若表名不匹配按 `.schema <table>` 校对降级);③ NDK simpleperf 示例 perf.data(若可得)。**待真机复核** 在自己 App 上复跑 config + record。
- **Android 16 锚点**:`android_jank_cuj` metric 在 16 的字段(按 CUJ 分组;**v57.2 实测依赖 CUJ 交互标记,非 CUJ trace 输出空 `{}`,见 §八 V12/C5——本线主写法已改为直接基于 `actual_frame_timeline_slice`**);`ProfilingManager`(A15 主动请求入口,A16 system-triggered)入口与 Python 管线消费衔接准备。

### Case 4.3 — Lv2:联合闭环(掉帧→锁→Binder→调度 + `--trace-offcpu`)(问题驱动,复用 M3)

- **目标**:对一个真实卡顿做 Perfetto×Simpleperf **联合闭环归因**,产出可证伪结论。
- **场景**(复用 [[M3 卡顿与帧率]] Case 编号,不重述帧率原理):App 在 120Hz 滑动列表周期性掉帧(每 3-4s 一次明显卡顿),主线程等 RenderThread 释放锁导致 jank。结合源文档 §7 粒子 VBO 子问题:RT 在 `updateVertexBuffer` 吃 L1D miss。
- **推演路径**:
  1. **定位 jank 窗口**:`actual_frame_timeline_slice`(Lv2/Lv3 用此表,因关 thread_state 需 ts/dur 范围):
     ```sql
     SELECT ts, ts+dur AS end_ts, dur/1e6 AS dur_ms, jank_type, upid
     FROM actual_frame_timeline_slice
     WHERE jank_type LIKE '%App Deadline Missed%' AND dur > 16.6e6     -- 120Hz deadine 8.3ms;v57.2 实测 jank_type 是描述性字符串,用 LIKE
     ORDER BY dur DESC LIMIT 3;
     ```
     假设拿到 ts=5234000000、dur=24000000(24ms)。v57.2 实测联合闭环命中示例(见未验证清单 §八 V7):帧 ts=12798901827074、dur=16.13ms、jank_type="App Deadline Missed",窗口内主线程 S 状态阻塞 9.15ms。
  2. **窗内主线程 thread_state + 唤醒者**(三表关联,本线核心):
     > **Android 主线程名是截断后的进程名(task comm 15 字符),不是 'main'**;v57.2 实测 nexuslauncher 主线程名为 `s.nexuslauncher`(utid 736/tid 2782)。**用 `tid=pid` 定位主线程最稳**(主线程 tid == 进程 pid),`WHERE t.name='main'` 在 Android App 上命中 0 行。主线程 utid 取法:`SELECT utid FROM thread WHERE upid=(SELECT upid FROM process WHERE name='<pkg>') AND tid=(SELECT pid FROM process WHERE name='<pkg>')`。实测主线程 thread_state 分布样例(utid 736,S 6461.9ms/874段 / Running 175.2ms/1033段 /R 149.9ms/970段 /R+ 20.2ms/60段 /D 2.6ms/5段,见未验证清单 §八 V6)。
     ```sql
     SELECT ts.state,
            ts.dur/1e6 AS state_ms,
            ts.blocked_function,
            ts.waker_utid,
            w.name AS waker_thread,
            wp.name AS waker_process
     FROM thread_state ts
     LEFT JOIN thread w  ON w.utid  = ts.waker_utid
     LEFT JOIN process wp ON wp.upid = w.upid
     WHERE ts.utid = <main_utid>                    -- 主线程 utid
       AND ts.ts >= 5234000000 AND ts.ts < 5258000000
       AND ts.state IN ('S','D') AND ts.dur > 5e6   -- 阻塞>5ms
     ORDER BY ts.dur DESC;
     ```
     输出(§7 示例数据):state=S、dur=12.3ms、blocked_function=futex_wait_queue_me、waker_thread=RenderThread。
     **fallback**:若 trace 无 `blocked_function` 列(版本/数据源),降级:① 看 `waker_utid` 对应的唤醒者(谁唤醒主线程=谁释放锁);② 看 `io_wait` 列(区分 futex vs IO wait);③ 补 ftrace `sched/sched_waking` 重抓;④ 用 M0d #6 模板 `SELECT ... FROM slice WHERE name GLOB '*futex*' AND dur>2e7` 锁竞争列表辅助。
  3. **RT 同窗状态**(确认 RT 在忙):
     ```sql
     SELECT state, SUM(dur)/1e6 AS total_ms, cpu
     FROM thread_state
     WHERE utid = <render_thread_utid>
       AND ts >= 5234000000 AND ts < 5258000000
     GROUP BY state, cpu ORDER BY total_ms DESC;
     ```
     输出:Running 11.8ms(在 cpu6 大核)→ RT 在忙,主线程等它释放 mutex。
  4. **simpleperf 对 RT 深挖**(📱 真机,或用 §7 推演数据):
     ```bash
     adb shell simpleperf record -p <pid> \
       -e cpu-cycles,cache-misses,stalled-cycles-backend \
       --comms RenderThread --call-graph dwarf -f 8000 \
       --duration 15 -o /data/local/tmp/rt.data
     simpleperf report -i rt.data --sort dso,symbol --percent-limit 0.5
     ```
     报告(§7 示例):`GameRenderer::updateVertexBuffer` 占 41.2% cycles + 38.7% cache-misses + 52.1% stalled-backend。
     **`--comms RenderThread`** 只采 RT 线程(避免主线程/worker 噪声),是 Lv2 多线程 App 关键;若用 `--per-thread-comm`(§2.3)可一起抓各线程,报告里按线程拆。
  5. **`--trace-offcpu` 交叉验证**(📱 真机):
     ```bash
     adb shell simpleperf record -p <pid> -e cpu-cycles \
       --call-graph dwarf --trace-offcpu --duration 15 -o /data/local/tmp/offcpu.data
     simpleperf report -i offcpu.data --children      # 看 off-CPU 栈
     ```
     读法:主线程 off-CPU 栈落在 `futex_wait_queue_me`(锁等待,非算力)→ 与 Perfetto 的 blocked_function=futex_wait_queue_me **互证**。若 off-CPU 栈落 `io_read` 而 Perfetto 说 S 状态但无 blocked_function → 补采 sched_waking + 确认是 IO 等待(改优化方向:不治锁而治 IO 缓存)。
  6. **关联结论**(可证伪):
     > "第 N 帧 jank_type=App,主线程在 [ts=5234000000, +24ms] 阻塞 state=S dur=12.3ms,blocked_function=futex_wait_queue_me,waker=RenderThread;RT 同窗 Running 11.8ms 在 cpu6,`updateVertexBuffer` 占 41.2% cycles + 38.7% cache-misses + 52.1% stalled-backend;off-CPU 栈互证主线程 futex_wait。**根因**:RT 在 updateVertexBuffer 内因粒子数据 AoS 布局跨 cache line(stride=12 访问 x/y/z)致 L1D miss 38% + 每帧 glBufferData 全量重传 VBO 致 RT 长占 → 主线程等锁 → 24ms 帧 jank。"
- **结论**:可证伪结论模板(现象→时间窗→责任方→阻塞链→热点函数→TMA 分类→修复建议),对齐能力自评五步闭环的前四步。
- **常见坑**:
  - **坑 1**:直接跑 simpleperf 抓整进程,把主线程/RT/worker 热点混一起 → RT 热点被稀释。**必须** `--comms RenderThread` 或 `--per-thread-comm` 拆线程。
  - **坑 2**:不用 `--trace-offcpu`,只看 on-CPU 火焰图 → 看到 `updateVertexBuffer` 宽就以为要优化算法,实际主线程瓶颈是**等待**(off-CPU),优化的应是 RT 的数据布局降算力 + 降 RT 占用时长从而降等锁时长,而非主线程。
  - **坑 3**:Perfetto 窗和 simpleperf 窗不对齐 → 抓 hot 热点不一定是导致那帧 jank 的热点。**对齐方法**:simpleperf 抓同场景复现(滑动同样手势),或用 `--duration` 精确锁定 3-4s 复现窗口;真机能拿到 trace 内嵌 simpleperf 最好(Perfetto 有 simpleperf 数据源,但配齐较繁)。
  - **坑 4**:blocked_function 列缺失不 fallback → SQL 空。本线 fallback 链见步骤 2。
- **资源**:主路径 ② §7 粒子 VBO(数据齐全,IPC 0.72→1.85、L1D 38.2%→3.1%、帧 28ms→7.2ms);真机项 **待真机复核**(blocked_function 有效性、--trace-offcpu 实跑、--comms 实跑)。
- **Android 16 锚点**:ARR 帧率切换(`hasArrSupport`/`getSuggestedFrameRate`,16 增强 API)导致的 jank 归因——若滑动卡顿仅出现在帧率切换瞬间,用 ARR 查询 API 确认是否切 mode 引发的 jank(非算力/锁),优化方向不同(衔接 [[M3 卡顿与帧率]] §1.8 ARR 调度链)。

### Case 4.4 — Lv3:TMA 归因 + 自定义 Metric + Python 管线 + 功耗联合(问题驱动,推演级)

- **目标**:对 §7 粒子 VBO 做 TMA L1/L2 分类 + 自定义 Metric + Python 管线自动化 + 功耗-thermal 联合(无设备下推演)。
- **场景**:把 Lv2 的"RT 在 updateVertexBuffer 吃 cache-miss"结论**向上推一层**:为什么 cache-miss?微架构哪个分类主导?基于 TMA 给出可量化的修复判断 + 修复前/后 TMA 比例对照。
- **推演路径**:
  1. **PMU 架构前置**(§3.4):
     ```bash
     adb shell cat /sys/devices/system/cpu/cpu6/regs/identification/midr_el1    # 读 cpu6(大核)的 midr
     # 解析 midr:implementer(0x41=Arm) + part(A76=0xd0c / A78=0xd41 / A710=0xd4d)
     # 假设 part=0xd0c → A76 → 查 Cortex-A76 TRM 的 PMU events 章节(待 TRM 复核)
     ```
     **核识别是 Lv3 第一步**:不读 midr_el1 直接用 §6.1.1 的 r 编号可能在 A78/A710 设备跑错(simpleperf 报 invalid event 或采样数值无意义)。
  2. **采集 TMA L1 所需事件**(A76 示例,r 编号 **待 TRM 复核**):
     **⚠️ 下述 r 编号仅适用 Cortex-A76 示例,他核无效;实跑前必须先 `cat /sys/devices/system/cpu/cpu*/regs/identification/midr_el1` 定核 + 查目标核 TRM 改 r 编号(见尾节疑点 ①,依 A76 示例·待 TRM 复核)**
     ```bash
     adb shell su 0 simpleperf stat -p <pid> --duration 10 \
       -e cpu-cycles,instructions,r23,r24,r22
     #   r23 = STALL_FRONTEND(A76)
     #   r24 = STALL_BACKEND(A76)
     #   r22 = BR_MIS_PRED_RETIRED(A76)
     # ! 仅 A76 适用;A78/A710 查对应 TRM 改 r 编号
     ```
  3. **L1 计算**(§6.1.2 公式,A76 示例):
     ```python
     # tma_l1.py —— 推演用,真机到位后改成读 stat 输出实际计数
     def tma_l1(cycles, inst_retired, stall_fe, stall_be, br_mis, op_retired):
         pipeline_width = 4                  # A76 4-wide ! 他核另查
         penalty = 11                       # A76 approximation ! 他核另查
         total_slots = cycles * pipeline_width
         retiring       = inst_retired / total_slots
         bad_spec       = (br_mis * penalty) / total_slots
         frontend_bound = stall_fe / cycles
         backend_bound  = stall_be / cycles
         return {'retiring':retiring,'bad_spec':bad_spec,
                 'frontend':frontend_bound,'backend':backend_bound}
     # 代入 §7 示例(假设计数比例):retiring≈35%、backend≈52%、frontend≈5%、bad_spec≈8%
     # 对照诊断起点:Retiring <40%(严重)、Backend >50%(严重)、Frontend <10%(健康)、Bad Spec 5-10%(警告)
     # → 后端主导,数据/内存瓶颈分支
     ```
  4. **L2 下钻 backend_memory vs core**(需 r28 等额外 stall 事件):
     **⚠️ 下述 r 编号仅适用 Cortex-A76 示例,他核无效;实跑前必须先 `cat /sys/devices/system/cpu/cpu*/regs/identification/midr_el1` 定核 + 查目标核 TRM 改 r 编号(见尾节疑点 ①,依 A76 示例·待 TRM 复核)**
     ```bash
     adb shell su 0 simpleperf stat -p <pid> --duration 10 -e r24,r28,r04,r03
     #   r24=STALL_BACKEND, r28=MEM_ACCESS_CHECKED(A76), r04=L1D_CACHE, r03=L1D_CACHE_REFILL
     ```
     计算 L1D Miss Rate = r03/r04;§7 示例 38.2%(严重,>15%)→ 确认 backend_memory 主导(非 backend_core)。
     **L2 细分阈值**(§6.1.3,标"TMA L2 近似·需配合 A76 stall 事件",不并入诊断起点主表):Backend Memory >35% 严重、Backend Core >25% 严重。
  5. **自定义 `my_jank_summary` Metric**(帧统计直接基于 `actual_frame_timeline_slice`,不强制 CUJ 分组):
     **v57.2 实测**(`android_jank_cuj` 内置 metric **依赖 CUJ 交互标记**,在非 CUJ trace 上 `--run-metrics android_jank_cuj` 输出空 `{}`;见 §八 V12/C5):帧统计应**直接基于 `actual_frame_timeline_slice`**(按 `upid`/`layer_name` 分组)计算,**不强制 CUJ 分组**;若需 CUJ 分组则注明「需 CUJ 交互标记的 trace(如 InteractionJankReporter / 特定 CUJ atrace 段)」。
     ```sql
     -- my_jank_metric.sql —— Lv3 自定义 Metric(M0d 未涉及;不重叠)
     -- 主写法:直接基于 actual_frame_timeline_slice(通用,非 CUJ trace 亦可用)
     CREATE PERFETTO TABLE my_jank_summary AS
     SELECT upid, layer_name,
            COUNT(*) AS total_frames,
            SUM(CASE WHEN jank_type != 'None' THEN 1 ELSE 0 END) AS jank_frames,
            ROUND(100.0 * SUM(CASE WHEN jank_type!='None' THEN 1 ELSE 0 END)/COUNT(*), 2) AS jank_rate_pct,
            ROUND(AVG(dur)/1e6, 2) AS avg_frame_ms,
            ROUND(MAX(dur)/1e6, 2) AS max_frame_ms
     FROM actual_frame_timeline_slice GROUP BY upid, layer_name;
     -- P95(直接在 actual_frame_timeline_slice 上算,带 COUNT(*)>0 守卫)
     CREATE PERFETTO TABLE my_jank_p95 AS
     SELECT upid, layer_name,
       (SELECT dur FROM actual_frame_timeline_slice f2
        WHERE f2.upid=f1.upid AND (f2.layer_name=f1.layer_name OR (f2.layer_name IS NULL AND f1.layer_name IS NULL))
        ORDER BY f2.dur LIMIT 1
        OFFSET (SELECT CASE WHEN COUNT(*)>0 THEN (COUNT(*)*95/100) ELSE 0 END
                FROM actual_frame_timeline_slice f3
                WHERE f3.upid=f1.upid AND (f3.layer_name=f1.layer_name OR (f3.layer_name IS NULL AND f1.layer_name IS NULL)))) AS p95_dur_ns
     FROM (SELECT DISTINCT upid, layer_name FROM actual_frame_timeline_slice) f1;
     -- 可选 CUJ 分组(需带 CUJ 交互标记的 trace;非 CUJ trace 上 android_jank_cuj 表为空)
     -- SELECT RUN_METRIC('android/android_jank_cuj.sql');  -- 加载后 JOIN android_jank_cuj cuj ON frame.upid=cuj.upid ... GROUP BY cuj.cuj_name;
     ```
     ```bash
     trace_processor --run-metrics my_jank_metric.sql --metrics-output json \
       -o jank_report.json trace.perfetto-trace
     ```
  6. **Python 管线自动化报表**(§2.4 完整代码 + TMA 计算 + Metric 输出):
     把 §2.4 `analyze_trace()` 加上 TMA L1/L2 计算函数 + `my_jank_summary` 查询,输出 JSON 报告。报告字段(对齐能力自评终点报告模板):现象 → 时间窗口 → 责任方(jank_type)→ 阻塞链(blocked_function/waker)→ 热点函数 → 微架构分类(TMA L1/L2)→ 修复建议 → 验证对照(修复前/后指标)→ 验证状态标注。
  7. **功耗-thermal-频率联合**(若 trace 含 power/thermal):
     ```sql
     WITH jank_times AS (
       SELECT ts, dur FROM actual_frame_timeline_slice
       WHERE jank_type != 'None' AND dur > 16.6e6
     )
     SELECT jt.ts/1e9 AS jank_s, jt.dur/1e6 AS jank_ms,
            f.value/1000 AS cpu_freq_mhz, t.value/1000 AS temp_c
     FROM jank_times jt
     JOIN counter f ON f.ts >= jt.ts AND f.ts < jt.ts+jt.dur
     JOIN cpu_counter_track ft ON f.track_id = ft.id AND ft.name='cpufreq' AND ft.cpu=7
     JOIN counter t ON t.ts >= jt.ts AND t.ts < jt.ts+jt.dur
     JOIN track tt ON t.track_id = tt.id AND tt.name LIKE '%thermal%zone0%'
     ORDER BY jt.ts;
     ```
     判据(§6.4 专家判断):jank 集中在 temp>45°C 且 cpu_freq<满频 50% → 热降频。**车机 AAOS guest 提示**:guest 的 cpu_freq/thermal 受 hypervisor 限制(虚拟值),跨域分析需对齐 host 时钟(交叉引 [[M9.5 QNX与混合架构性能]])。
  8. **归因 + 优化建议 + 验证对照**:
     - TMA L1:Backend Bound(52%)主导 + L1D Miss 38.2%(backend_memory)
     - 根因:粒子数据 AoS 布局(`struct{x,y,z}[]`,stride 12 跨 cache line)+ 每帧 `glBufferData` 全量重传 VBO
     - 修复:①AoS→SoA(`{x[],y[],z[]}` 连续访问,降 L1D miss);②`glMapBufferRange` + `GL_MAP_INVALIDATE_BUFFER_BIT` 替代全量重传;③双缓冲 VBO 消除主线程等锁
     - 验证对照(§7 数据,修后):IPC 0.72→1.85（+157%）、L1D Miss 38.2%→3.1%（-92%）、最大帧 28ms→7.2ms（-74%）、Jank Rate 4.2%→0.1%（-97.6%）
- **结论**:**推演级·待真机** — §7 数据非本环境复测(设备 + 带 -g so + A76 TRM 三者齐全才能复现);Lv3 TMA 归因真机到位前**不能独立归因**(只能复现 §7 推导链);能力达成标志:真机拿到新 perf.data → 独立跑 r 编号采样 → L1/L2 计算 → 出 TMA 分类 + 优化建议,且报告通过人工 review。
- **常见坑**:
  - **坑 1**:不读 midr_el1 直接用 r 编号 → 在 A78/A710 设备采样数值无意义或报 invalid event。Lv3 第一步必须核识别。
  - **坑 2**:直接照搬 §6.1.2 的 penalty=11/width=4 → 他核算错 TMA 比例。每核查 TRM 重算系数(#6 ARM TMA 近似性声明)。
  - **坑 3**:把 TMA-ARM 当 Intel TMA 等价 → 精度预期错(ARM 是 stall 近似,非 slot 等价);给结论时标"近似"。
  - **坑 4**:自定义 Metric 不 `RUN_METRIC('android/android_jank_cuj.sql')` 先加载 → `android_jank_cuj` 表不存在,JOIN 失败。**更进一步:v57.2 实测 `android_jank_cuj` 依赖 CUJ 交互标记,非 CUJ trace 上 `--run-metrics android_jank_cuj` 输出空 `{}`(§八 V12/C5)→ 主写法应直接基于 `actual_frame_timeline_slice`(按 upid/layer_name 分组),`RUN_METRIC('android/android_jank_cuj.sql')` 仅作「需 CUJ 分组时的可选」**。
  - **坑 5**:无设备下声称"已校准阈值" → 诊断起点非硬门槛,真机到位前标"待校准"。
- **资源**:主路径 ② §7(100% 可得,数据齐全);① 公开示例 trace 用于 SQL syntax 对齐;③ NDK simpleperf 示例(若可得)。**待真机复核** r 编号有效性(待 A76 TRM)+ TMA 实测占比 + 绝对阈值校准 + thermal track 命名校对。
- **Android 16 锚点**:`ProfilingManager` **system-triggered**(A16 新增)→ trace 落 app data dir → Python 管线自动消费闭环;Lv3 的"自动化报表"环节正好接 ProfilingManager 监听器拿到的 trace URI,形成"线上难复现 ANR/启动慢 → 自动抓 trace → 自动 TMA 归因报告"闭环。

---

## 五、Todolist 实施 & Check

> 分级可勾选清单(✅ 已掌握 / ⬜ 待做;**📱 需真机** 标真机项)。

### Lv0 入门实施清单

- ⬜ 在 ui.perfetto.dev 打开一条公开示例 trace,能在 Actual Frames 轨道认出红色 jank slice
- ⬜ 读通 jank_type 四分类(Self/App/SF/Display)与底层 8 类的对应关系
- ⬜ 在 UI Query driver 跑通 `SELECT jank_type, COUNT(*) FROM actual_frame_timeline_slice GROUP BY jank_type`
- ⬜ 读一份 `simpleperf stat` 输出,能指出 IPC 数值并判高低(大核 ≥1.5 健康起点)
- ⬜ 能口述 Perfetto=Where/When、Simpleperf=Why/How much 的分工

### Lv1 中级实施清单

- ⬜ 按问题裁一份 `trace_config.pbtx`(开场判帧加 frametimeline,判 Binder 加 binder_transaction)
- ⬜ 跑通"adb perfetto → pull → trace_processor -q SQL"闭环 📱
- ⬜ 单表 SQL:`SELECT jank_type, COUNT(*) FROM actual_frame_timeline_slice GROUP BY jank_type`(v57.2 实测用此表;`frame_timeline_event` v57.2 不存在,探测后用)
- ⬜ 多表 JOIN 速查 SQL(thread JOIN process JOIN thread_state + WITH 子查询)跑出线程状态分布 📱
- ⬜ `EXTRACT_ARG` 提 binder `'data size'`(带空格)/`'destination process'`/`'calling tid'`;window 看跨核迁移 📱(**v57.2 已验 binder arg key**,见 §八 V11/C4a)
- ⬜ `simpleperf record -e cpu-cycles,instructions,cache-misses,branch-misses --call-graph dwarf -f 999` + `report --sort dso,symbol` 📱
- ⬜ 用 `report_html.py` 出火焰图,认"最宽的平顶"=热点 📱

### Lv2 高级实施清单

- ⬜ 完整跑通§3.3 Lv2 SOP:定位 jank 窗→thread_state blocked_function→waker→RT 热点 📱
- ⬜ `thread_state.blocked_function` 不可用时降级用 waker_utid + io_wait fallback 验证
- ⬜ `--trace-offcpu` 抓一次,报告里区分 on-CPU 热点 vs off-CPU 等待 📱
- ⬜ `annotate.py` / `--add_source_code` 看 inline 源码命中行 📱
- ⬜ `--per-thread-comm` 拆线程看 RenderThread/主线程各自统计 📱
- ⬜ `--post-unwind` 权衡:对比 on-device vs post-unwind 开销 📱
- ⬜ dwarf vs fp 两种 call-graph 开销对比(同场景跑两次看样本量差异)📱
- ⬜ 修源文档 Binder SQL 笛卡尔积(首选 EXTRACT_ARG 取对端 / 备用 name+utid+时间窗,见第七节差异化表 + §八 V11/C4b)📱

### Lv3 专家实施清单

- ⬜ 读 `midr_el1` 识别目标设备各核型号(A76/A78/A710/A55…)📱
- ⬜ 查目标核 TRM 的 PMU 事件号,与源文档 §6.1.1 A76 编号表比对 📱
- ⬜ 跑 TMA L1 四分类计算(cpu-cycles/instructions/r23/r24/r22)📱
- ⬜ TMA L2 细分(backend memory vs core,需 r28 等 stall 事件)📱
- ⬜ 自定义 `my_jank_summary` Metric(基于 `actual_frame_timeline_slice` 按 upid/layer_name 分组 + P95 子查询;CUJ 分组可选需 CUJ trace)跑步跑通 📱(**主写法已按 §八 V12/C5 改为非 CUJ 依赖**)
- ⬜ Python trace_processor API 管线产自动化报告(掉帧+阻塞+Binder+TMA)📱
- ⬜ `ProfilingManager` system-triggered 注册 ANR/cold-start trigger,验证落 trace 📱(Android 16)
- ⬜ Macrobenchmark trace 复用:在测完的 `.perfetto-trace` 上跑本线 SQL 细化 janky% 升高原因 📱
- ⬜ `--symfs` + addr2line 区分 `.oat`(AOT) vs JIT 段命中分布 📱
- ⬜ 功耗-thermal-频率×掉帧四表关联 SQL 跑通,看是否热降频 📱
- ⬜ AAOS guest 对齐 host 时钟提示:车机 cpu_freq/thermal 受 hypervisor 限制 📱(车机)

### 终点自评(能力达成)

- ⬜ 无提示下,对一份新 trace 完成 ①jank 归因 ②阻塞定位 ③热点深挖 ④TMA L1 分类 ⑤出优化建议 五步闭环,且报告通过人工 review
- **诚实**:无真机时 ④与⑤只能停在**推演级**,真机到位前不算"达到 Lv3 归因能力"
- **报告须含 9 字段模板**(见 §3.4 末):现象 / 时间窗口 / 责任方 / 阻塞链 / 热点函数 / 微架构分类 / 修复建议 / 验证对照 / 验证状态标注

---

## 六、Check 项详解(每项展开:原理 / 命令 / 结论)含「诊断起点·需真机校准」表

### 6.0 能力达成验收矩阵(对应第五节 Todolist 各级)

| 级别 | 验收口径 | 完成证据 | 真机要求 |
|------|----------|----------|----------|
| **Lv0** | 工具分工 + UI 认红帧 + 读 IPC + 判四分类 | 能口述 Perfetto=Where/When·Simpleperf=Why/How much;能指红色 jank slice 说 jank_type;能读 stat 输出 IPC 并报核前提 | 公开 trace 可验证;真机 stat 可选 |
| **Lv1** | 写裁剪 config + SQL(单→JOIN→EXTRACT_ARG/window)+ multi-event record | 能裁含 frametimeline+binder+sched_waking 的 config;能跑通线程状态分布 SQL;能出 Top 函数报告 | 公开 trace 跑 SQL 即一验收;真机 record 是二验收 📱 |
| **Lv2** | 完整联合闭环出可证伪结论 | 能产"jank 帧→blocked_function→waker→热点函数→TMA 分类"五段式结论;能区分 on/off-CPU;能修 Binder 对端关联(首选 EXTRACT_ARG 取对端,备用 name+utid+时间窗) | 必须真机(blocked_function/--trace-offcpu/--comms) 📱 |
| **Lv3** | TMA L1/L2 分类 + 自定义 Metric + Python 管线 + 功耗联合,五步闭环过人工 review | 能读 midr_el1 + 查 TRM 定 r 编号;能跑 TMA L1/L2 计算并按矩阵给优化方向;能搭 Python 管线产报告;能判热降频 | 必须真机 + 带 -g so + 目标 SoC TRM 📱;**无真机下只能推演级,不达成**。**终点定义见 §3.4 末『Lv3 能力终点 & 报告模板』(五步闭环 + 报告 9 字段)** |

**判读**:Lv0/Lv1 的"机制级"能力可无设备达成(公开 trace + 示例数据);Lv2/Lv3 的"问题驱动"能力**必须真机**——这是无设备环境下诚实标注的核心。

### 6.1 健康阈值诊断起点表

> **声明**:本表是**经验起点 · 需真机校准,非硬门槛**;与本模块体系各模块三节「验证四件套」阈值**互补**——本线给跨模块通用起点,各模块给专用阈值。列「适用核/频率/制程前提」逐条标注。

| 指标 | 🟢 健康(诊断起点) | 🟡 警告 | 🔴 严重 | 适用核/频率/制程前提 |
|------|--------------------|---------|---------|----------------------|
| 帧时长(60Hz) | ≤16.6ms | 16.7-33ms | >33ms | 标准 VSYNC 周期;具体 deadline 随设备 VSYNC 偏移而异 |
| 帧时长(120Hz) | ≤8.3ms | 8.4-16.6ms | >16.6ms | 标准 VSYNC 周期 |
| Jank Rate | <1% | 1-5% | >5% | 静态场景;<5% 滑动场景另议(经验值) |
| **IPC** | 大核 ≥1.5 | 1.0-1.5 | <1.0 | **大核满频 SPEC 类负载;小核(A55)典型上限仅 1.0-1.2**(大小核阈值不同) |
| L1D Miss Rate | <5% | 5-15% | >15% | **64KB L1D,代码 footprint 适配时;大 working set 视场景放宽** |
| LLC Miss Rate | <20% | 20-40% | >40% | LLC 大小设备相关 |
| Branch Miss Rate | <3% | 3-8% | >8% | 分支密集代码 |
| DTLB Miss Rate | <1% | 1-5% | >5% | 大页/池化优化依据 |
| **Frontend Bound** | <10% | 10-25% | >25% | **TMA L1 stall 比例近似,仅适用标定核;A76 公式,他核不通**(依 A76 示例·待 TRM 复核) |
| **Backend Bound** | <30% | 30-50% | >50% | **TMA L1 stall 比例近似,仅适用标定核;A76 公式,他核不通**(依 A76 示例·待 TRM 复核)。**L2 拆分(Memory/Core)见 §6.1b** |
| Retiring | >60% | 40-60% | <40% | TMA L1 近似,标定核 |
| Bad Speculation | <5% | 5-10% | >10% | 分支预测相关 |
| 主线程 Runnable 占比 | <10% | 10-25% | >25% | Runnable+Running 占比;>25% 提示 CPU 资源不足 |
| Binder P99 延迟 | <5ms | 5-20ms | >20ms | 跨进程调用;具体读 binder_transaction slice |
| Context Switch /s | <5000 | 5000-15000 | >15000 | 调度密度;与核数相关,多核设备上限更高 |

> **来源**:本表以源文档 §8.4 速查表为**诊断起点**(口径打架三处 — §3.2 / §6.1.3 / §8.4 — 本线以 §8.4 为准,§6.1.3 L2 细分单独列且标"TMA L2 近似·需 A76 stall 事件",§3.2 不再使用)。**完成但未验证**(数值为经验起点,非硬门槛,需真机实测校准)。

#### 6.1b TMA L2 细分阈值单独列(不并入诊断起点主表·依 A76 示例·待 TRM 复核)

> 计划要求:源文档 §6.1.3 的 L2 细分阈值**单独列**且标"TMA L2 近似·需配合 A76 stall 事件",不并入 §6.1 主表(主表给跨模块通用起点,L2 是微架构专属需 A76 stall 事件,口径不同)。

| L2 细分(Backend 拆) | 🟢 健康 | 🟡 警告 | 🔴 严重 | 前提 |
|-----------------------|---------|---------|---------|------|
| Backend Bound(Memory) | <20% | 20-35% | >35% | **A76 stall 事件 + r28(MEM_ACCESS_CHECKED);TMA L2 近似,仅适用标定核** |
| Backend Bound(Core) | <15% | 15-25% | >25% | 同上;Core = Backend − Memory |
| L1D Miss Rate(支撑 L2) | <5% | 5-15% | >15% | 64KB L1D;A76 r03/r04 算(他核另查) |
| DTLB Miss Rate(支撑 L2) | <1% | 1-5% | >5% | A76 r05/r06 算;大页优化依据 |

**计算公式**(A76 示例):
- `backend_memory = stall_backend_with_mem / cpu_cycles`(需 r24 + r28 组合,或源文档 §6.1.3 给的近似公式)
- `backend_core = backend_bound − backend_memory`
- 当 `backend_memory > 35%` → 数据 cache/TLB/带宽主导 → 数据布局/连续化/大页
- 当 `backend_core > 25%` → 执行单元/数据依赖主导 → 指令级并行/打破依赖链

**与主表关系**:§6.1 主表的 Backend Bound<30% 是 **L1 顶层** 经验起点(跨模块通用);本表 Backend Memory/Core 是 **L2 细分**(微架构专属,需 A76 stall 事件)。两者互补:先看 L1 顶层判断"是否 Backend 主导",再看 L2 决定"Memory 还是 Core 子类"。**依 A76 示例·待 TRM 复核**——A78/A710 系数不同。

### 6.2 各 Check 项详解(原理 / 命令 / 结论)

**Check 1 — Perfetto 选型:Where & When 怎么定?**
- **原理**:Perfetto 通过 ftrace+atrace+frametimeline 等数据源采"系统时间线";时序类问题(谁何时多久)用它定线程+时间窗+核+频率;定了窗才下 simpleperf。
- **命令**:`adb shell perfetto -o <path> -t 10s am view sched freq gfx` + frametimeline 数据源。
- **结论**:Perfetto 锁线程+时间窗是联合闭环第一步;反过来(先 simpleperf)只适合纯 CPU 密集,交互卡顿必先 Perfetto。

**Check 2 — `frame_timeline_event` vs `actual_frame_timeline_slice` 何时用哪个?**
- **原理**:见术语节 + §1.2。前者 event-like(列 `actual_ts`/`display_frame_token`/`jank_type`,M0d #2 口径),后者 slice-like(Lv2/Lv3 关联 waker/thread_state 需 ts/dur 范围)。
- **命令**:`SELECT count(*) FROM sqlite_schema WHERE name='frame_timeline_event'` 先探测;`.schema <table>` 校对实际版本存在哪张表。**v57.2 实测:`actual_frame_timeline_slice` 存在,`frame_timeline_event` 不存在**——Lv0/Lv1/Lv2/Lv3 统一用 `actual_frame_timeline_slice`;旧版本若 `frame_timeline_event` 存在,Lv0/Lv1 可用 event-like 口径。
- **结论**:不是"哪个更对"而是"哪个适配当前 JOIN 需求";版本差异时以实际 schema 为准并标注。v57.2 起统一用 `actual_frame_timeline_slice`。

**Check 3 — IPC=0.8 一定有问题吗?大小核为何阈值不同?**(高频面试题)
- **原理**:IPC 受核微架构 + 频率 + 负载类型影响。大核(A76 4-wide OoO)满频跑 SPEC 类负载 IPC >2 很常见,所以 <1.5 才算偏低;<1.0 严重 stall。小核(A55 2-wide 顺序)设计就是高效低功耗,满频也跑不到大核 IPC,典型上限 1.0-1.2;小核 IPC=0.8 可能完全正常(它本来就慢),硬套大核阈值会误判。
- **命令**:`simpleperf stat -e cpu-cycles,instructions -p <pid> --duration 5` 看 IPC;**必须同时记录线程跑在哪个核**(`thread_state.cpu`),否则 IPC 数值无意义。
- **结论**:IPC 阈值按核分:大核 ≥1.5(诊断起点)、小核 1.0-1.2 上限;报 IPC 必报核 + 频率前提。

**Check 4 — EXTRACT_ARG + window 解决什么?与 M0d 10 条 SQL 关系?**
- **原理**:`EXTRACT_ARG(arg_set_id,'key')` 提 slice 附加键值(binder `'data size'`(带空格)/`'destination process'`/`'reply transaction?'`、futex `lock_addr` 等;**v57.2 实测无 `'data_size'`/`'reply_size'`**,见 §八 V11/C4a),M0d 只在 OOM 模板用过一次;window(LAG/LEAD/PARTITION BY)做跨核迁移/唤醒链/帧间差。本线讲透 arg 表结构 + window 语义,不与 M0d 重叠。
- **命令**:见 §2.2.1/§2.2.2。
- **结论**:EXTRACT_ARG 是 arg 下钻核心;window 是"相邻行比较"类问题的唯一解;二者是 Lv1→Lv2 SQL 进阶的分水岭。

**Check 5 — `--trace-offcpu` 报告怎么读?**
- **原理**:加 `--trace-offcpu` 后 perf.data 含 sched_switch 事件,报告能区分 on-CPU 栈(占 cycle=算力瓶颈)vs off-CPU 栈(等锁/IO=同步瓶颈)。
- **命令**:`simpleperf record ... --trace-offcpu`;`report --children` 看 off-CPU 栈。
- **结论**:on-CPU 宽=优化算法/数据布局;off-CPU 宽=改并发/异步/缓存;两者都宽先治等待再治算力。

**Check 6 — TMA 四分类怎么算?ARM 与 Intel 精度等价吗?A76 公式能照搬 A78 吗?(#6 近似性)**
- **原理**:见 §3.4「#6 ARM TMA 近似性声明」。ARM 无 pipeline-slot,是 stall 比例近似;系数 imp-def;A76 公式(penalty≈11、width=4)仅适用 A76;他核查 TRM 重算。
- **命令**:`simpleperf stat -e cpu-cycles,instructions,r23,r24,r22 --duration 10`(A76 r 编号)。
- **结论**:ARM TMA 精度 < Intel TMA;A76 公式不能照搬 A78/A710;真机到位前 L3 TMA 归因只能推演不可独立归因。

**Check 7 — TMA 顶层归因能力 Lv3 天花板在哪?**(无设备诚实声明)
- **原理**:无真机时只能复读 §7 示例数据(给定的 IPC/miss/TMA 比例)复现推导链;对未知新 perf.data 独立 L1→L2 下钻需真机跑 r 编号采样拿到真实计数,无设备做不到。
- **命令**:无设备下无法跑 `simpleperf stat -e r23,r24...`,只能推演。
- **结论**:Lv3 终点能力达成需真机 + 目标 SoC 的 TRM;真机前标"推演级·待真机",不能称 Lv3 归因能力达成。

**Check 8 — `ProfilingManager` system-triggered 闭环怎么搭?**
- **原理**:A16 App 注册 ANR/cold-start/reportFullyDrawn 触发器 → 系统在触发瞬间自动起停 Perfetto trace 落 app data dir → 监听器接 URI 上传 → 本线 Python 管线自动消费。
- **命令**:见 [[M0d 工具链]] 2.8 `addProfilingTriggers()`/`registerForAllProfilingResults()`;本线管消费端。
- **结论**:闭环 = 线上难复现 bug → 自动抓 trace → 自动归因报告;API 常量名以 16 SDK 为准(机制级未逐条核实)。

**Check 9 — 车机 AAOS guest 的 cpu_freq/thermal 与 host 关系?(完整性)**
- **原理**:guest 看到虚拟频率/温度(受 hypervisor 限制);跨域分析需对齐 host 时钟(QNX Momentics System Profiler 抓 host timeline)。
- **命令**:本线 SQL 的 cpu_freq/thermal track 在 guest 上是虚拟值;车机需额外对齐 host trace。
- **结论**:车机 guest single-side 功耗-频率联合分析有局限,需 host trace 配合;交叉引 [[M9.5 QNX与混合架构性能]]。

**Check 10 — `.oat` vs JIT 段命中怎么区分?(JIT/AOT perf 视角)**
- **原理**:`simpleperf report --symfs ./symbols --sort dso,symbol` 看热点落在 `.oat`(已 AOT 编译,Baseline Profile 覆盖)还是 jit 段(JIT 实时编译,AOT 未覆盖)。
- **命令**:`addr2line -e libfoo.oat -f -C -i 0x12345` 解析具体行。
- **结论**:jit 段命中多 = AOT 未覆盖(需补 Baseline Profile 或预热);.oat 命中多 = AOT 已覆盖(BP 有效)。

---

## 七、关联与跨模块

### 7.0 编号归一映射表

> 主计划 v2.6 索引口径与 `modules/L1` 文件侧归一口径对照:

| 主计划 v2.6 索引 | modules/L1 文件 | 归一编号(文件侧) |
|---|---|---|
| M2a View 帧率 | `M3-卡顿与帧率.md` | M3 |
| M2.5 ANR | `M5-ANR-AppHang治理.md` | M5 |
| M2.6 稳定性 | `M6-稳定性根因排查.md` | M6 |
| M2.7 输入/系统UI | `M7-输入管线与系统UI性能.md` | M7 |
| M2b Compose | `M4-Compose性能.md` | M4 |
| M1.5 系统开机 | `M2-系统开机与启动稳定性.md` | M2 |

### 7.1 正向引用(本线复用各模块素材)

- [[M0d 工具链]](`modules/L0/M0d-工具链.md`):**基础**,本线是其深度延伸,不重复 10 条 SQL;Lv0/Lv1 起手**实测 v57.2 用 `actual_frame_timeline_slice`**(M0d #2 `frame_timeline_event` 在 v57.2 不存在);simpleperf/Perfetto 命令基础回引。
- [[M0b 图形渲染管线]]:供 Lv2 jank 帧管线(App→RT→SF→Display)原理,本线不重述。
- [[M0c 调度与电源基础]]:供 Lv2 频率 ramp-up、Lv3 功耗联合。
- [[M0.5 线程并发]]:供 Lv2 futex 锁竞争场景。
- [[M3 卡顿与帧率]](`modules/L1/M3-卡顿与帧率.md`):供 Lv2 Case 场景(只读其 Case 编号与场景,不重述帧率原理)。
- [[M5 ANR-AppHang治理]]:大小核调度阈值;供 Lv2 主线程阻塞判 R/S/D 子类。
- [[M6 稳定性根因排查]]:供 Lv2 阻塞/Watchdog 关联的 simpleperf 视角。
- L3 模块:M6/M7/M8 的工具视角延伸回引本线对应 Lv(见下)。

**车机 AAOS guest 提示(完整性)**:Lv3 功耗节加注:**车机 guest 的 cpu_freq/thermal track 受 hypervisor 限制,跨域分析需对齐 host 时钟**(QNX/Momentics System Profiler 抓 host 线程 timeline,guest trace 时间戳对齐)。交叉引 [[M9.5 QNX与混合架构性能]]。

### 7.2 差异化 SQL 表(本线 SQL 与 M0d 关系,逐条标"不重叠")

| 本线 SQL | 用途 | 与 M0d 关系 |
|---|---|---|
| Lv1:`EXTRACT_ARG` 提 binder `'data size'`(带空格)/`'destination process'`/`'reply transaction?'` | arg 下钻研判 binder 载荷与对端 | **不重叠**:M0d 只在 OOM 模板用过一次 EXTRACT_ARG,本线讲透 arg 表结构与 binder arg 下钻。**v57.2 实测 binder arg key 全集 + 无 `data_size`/`reply_size` 已回填(§八 V11/C4a)** |
| Lv1:window 函数(`LAG`/`LEAD`/`PARTITION BY`)看跨核迁移/唤醒链 | 相邻行比较类问题 | **深度扩展**:M0d #5 单线程 LAG 求 migration count;本线新增 `PARTITION BY utid` 多线程分组 + 显式处理 prev_cpu NULL 首行 + LEAD 唤醒链前驱后继(语义增量) |
| Lv2:Jank→thread_state→waker 三表关联(`actual_frame_timeline_slice`) | 掉帧归因到唤醒进程 | **声明为 M0d #2/#4 的深度扩展,非重复**:M0d #2 仅 frame+slice 单层,M0d #4 仅 thread_state 单层;本线新增 waker 进程归因(三表 JOIN) |
| Lv2:Binder 客户端↔服务端对端关联(**首选 `EXTRACT_ARG('destination process'/'destination thread'/'calling tid')` 取对端**;name 匹配 JOIN 为备用) | 跨进程调用对端匹配 | **C4b 已落实(v57.2 实测,§八 V11/C4b)**:主体写法见 §3.3/尾节疑点③——`EXTRACT_ARG(arg_set_id,'destination process')` 直接给对端 pid(实测 dest 712/1782/714),JOIN process 拿名字;R4 name-matching JOIN(name + dur= + utid<> 约束)降为「arg 不可用时的备用」。M0d #3 仅 `LIKE '%binder%'` 列表层 |
| Lv3:自定义 `my_jank_summary` Metric + P95 | 帧统计(直接基于 `actual_frame_timeline_slice`,按 upid/layer_name;CUJ 分组可选) | **不重叠**:M0d 完全未涉及自定义 Metric/RUN_METRIC。**C5 已落实(v57.2 实测 `android_jank_cuj` 依赖 CUJ 标记,非 CUJ trace 输出空;主写法改基于 `actual_frame_timeline_slice`,见 §八 V12/C5)** |
| Lv3:功耗/thermal/频率×掉帧四表关联 | 热降频归因 | **声明为 M0d #7 扩展**:M0d #7 仅单表频率查询;本线新增 thermal+freq+jank 四表关联 |

### 7.3 反向声明(各模块可回引本线)

各模块可在其「二工具箱」「三分析方法」回引本线对应 Lv,例如:
- 「Perfetto+Simpleperf 联合闭环见 `tools-perfetto-simpleperf-精通.md` Lv2」
- 「TMA 微架构归因见 `tools-perfetto-simpleperf-精通.md` Lv3」
- 「ProfilingManager 消费端 Python 管线见 `tools-perfetto-simpleperf-精通.md` §2.4/Lv3」

### 7.4 去重边界声明

- ① **二工具箱**:本线只放联合/自动化/高级/专题命令(UI 高级/EXTRACT_ARG+window/simpleperf 高级采样/Python 管线/TMA/功耗联合);单模块工具(如 `gfxinfo framestats` 单用、`dumpsys SurfaceFlinger --latency` 单用)回引 [[M3 卡顿与帧率]] 等二工具箱,不重写。
- ② **SQL**:本线 SQL 与 M0d 10 条 SQL 关系见 7.2 差异化表,逐条标"不重叠"或"深度扩展"。

### 7.5 主计划指针暂不动声明(体系审查)

> **本线暂不主动修改主计划 `android16-perf-learning-plan.md`**(避免破坏 v2.6 版本语义)。改由本线「七关联」**单向引用** [[M0d 工具链]];等主计划下次正常 bump 版本时一并加指针 + 修订对照条目(主题命名 `tools-perfetto-simpleperf-精通`,非编号族)。这与交付物 B(练习路线图)边界声明一致。

**与各模块三节「验证四件套」的关系**:各模块三节(命令+对照+采样+阈值)阈值是**模块专用阈值**(如 [[M3 卡顿与帧率]] 的 janky<5%/动画<3%);本线第六节诊断起点表是**跨模块通用起点**(IPC/Cache/TMA)。两者**互补**——本线给通用起点,各模块给专用阈值。本线阈值降级为"诊断起点·需真机校准"(非硬门槛),明确与各模块专用阈值不冲突、不重复。

---

## 八、面试与场景问答(含答案)

**Q1:同样掉帧,何时用 Perfetto、何时上 simpleperf?**
- **答**:先 Perfetto 后 simpleperf 几乎总是对的(交互卡顿)。Perfetto 定 Where/When(哪帧、哪个线程、哪段阻塞、跑了哪个核、频率多少);定了窗再 simpleperf 定 Why/How much(该线程 CPU 时间花在哪、Cache/TLB/Branch/IPC 瓶颈、TMA 四分类)。反过来(先 simpleperf 找热点)只适合纯 CPU 密集型场景(算法内核、解码),对交互卡顿会失效——卡顿的"热点"不一定在掉帧那帧(可能是上帧未完成导致的级联)。联合闭环:Perfetto 定窗 → simpleperf 深挖窗内热点。

**Q2:IPC=0.8 一定有问题吗?大核 vs 小核阈值为何不同?**
- **答**:不一定。IPC 受核微架构 + 频率 + 负载类型影响。大核(A76 4-wide OoO)满频跑 SPEC 类负载 IPC >2 常见,<1.5 才算偏低,<1.0 严重 stall。小核(A55 2-wide 顺序)设计就是高效低功耗,满频也跑不到大核 IPC,典型上限 1.0-1.2;小核 IPC=0.8 可能完全正常,硬套大核阈值会误判。**报 IPC 必报核 + 频率前提**,否则数值无意义。诊断起点表标"大核 ≥1.5 满频 SPEC;小核上限 1.0-1.2"(需真机校准)。

**Q3:ARM 的 TMA 与 Intel 的 TMA 精度等价吗?A76 公式能照搬到 A78 吗?(#6 近似性)**
- **答**:不等价,不能照搬。① ARM 无直接 pipeline-slot 计数,Intel TMA 用 slots(分配/退休/停顿的槽位),ARM 只能算 stall 周期比例(`STALL_FRONTEND/cycles`),是**近似非 Intel 等价**;② 各核 PMU 事件 ID 与系数(penalty_cycles、pipeline_width)是 imp-def,A76 的 penalty≈11、width=4 是 A76 硬编码,A78/A710/A715 需查各自 TRM/PMU guide;③ TMA-ARM 是 ARM 自己发布的近似方法论,非 Intel 官方移植,精度低于 Intel TMA。结论:A76 公式仅适用 A76,他核查 TRM 重算;真机到位前 L3 TMA 归因只能推演不可独立归因。

**Q4:`frame_timeline_event` 和 `actual_frame_timeline_slice` 什么关系?什么场景用哪个?**
- **答**:两者是同一 frame timeline 数据源的不同投影表。`frame_timeline_event` 是 event-like(列 `actual_ts`/`display_frame_token`/`jank_type`,对齐 M0d #2),`actual_frame_timeline_slice` 是 slice-like(列 `ts`/`dur`/`jank_type`/`on_time_finish`/`upid`,JOIN `thread_state` 需要 ts/dur 时间范围、JOIN thread 拿 upid 关联唤醒链)。**v57.2 实测:`actual_frame_timeline_slice` 存在,`frame_timeline_event` 不存在**——Lv0/Lv1/Lv2/Lv3 统一用 `actual_frame_timeline_slice`;旧版本若 `frame_timeline_event` 存在,Lv0/Lv1 可用 event-like 口径。不同 Perfetto 版本/数据源组合可能仅存其一,执行时用 `SELECT count(*) FROM sqlite_schema WHERE name='frame_timeline_event'` 探测 + `.schema <table>` 校对实际 schema。技术修正 #1 落地点。

**Q5:`--trace-offcpu` 报告怎么区分 on-CPU 热点和 off-CPU 等待?**
- **答**:加 `--trace-offcpu` 后 perf.data 嵌入 sched_switch 事件,`report --children` 看含 off-CPU 栈。on-CPU 火焰图宽=占用 cycle 多=算力瓶颈(优化算法/数据布局);off-CPU 火焰图宽=等待时间长=同步/IO/锁瓶颈(改并发/异步/缓存);两者都宽=既慢又等(最糟,先治等待再治算力)。与 Perfetto 的 thread_state + blocked_function 形成**交叉验证**:Perfetto 说主线程 futex_wait → off-CPU 栈确实落在 futex_wait 就互证;若 off-CPU 栈落在 io_read 而 Perfetto 说 S 状态但没 blocked_function,补采 sched_waking + 增强 trace config。

**Q6:无真机时,Lv3 TMA 归因能练到什么程度?天花板在哪?**
- **答**:天花板在"独立归因"。无真机下:能练 ①理解 TMA 四分类 + ARM 近似性(#6 声明)②复现 §7 粒子 VBO 的推导链(给定的 IPC/miss/TMA 比例 → AoS→SoA 优化 → 修后数据)③写 Python 管线封装 TMA 计算逻辑④写自定义 Metric SQL。但**不能**做:对未知新 perf.data 独立 L1→L2 下钻(需真机跑 r 编号采样拿真实计数)、校准绝对阈值(经验起点需真机校准)、核实 r 编号有效性(待 TRM 复核)。真机到位前标"推演级·待真机",不能称 Lv3 归因能力达成。

**Q7:Perfetto UI 这么强,为什么还要 trace_processor SQL?肉眼不行吗?**
- **答**:不行。trace 价值在 SQL 聚合,不在肉眼滚屏(抓了 10GB 只肉眼看几眼 = 没结论)。UI 适合探索期认现象(找红帧、Pinning);但"全会话 jank_type 分布""某窗内线程×核×状态×时长 Top""多少帧是 App jank vs SF jank"这类**结构化结论必须 SQL 聚合**——它产出可证伪、可复现、可入库的结论,而非主观"感觉这慢"。推荐:UI 认现象 → SQL 出结论 → 反过来在 UI 里 Pin 验证。Query driver 让 UI 内直接跑 SQL,二者不必割裂。

**Q8:差异化本线 SQL 跟 M0d 的 10 条 SQL 怎么分?会不会重复?**
- **答**:有明确边界。M0d 10 条 SQL 是**单模块基础模板**(启动切片/帧 jank 单表/Binder 列表/线程状态单表/跨核迁移 count/futex 列表/频率单表/Runnable 单表/SF Slice/LMK);本线只放**联合/高级/扩展**:EXTRACT_ARG arg 下钻(M0d 只 OOM 用过一次)、window PARTITION BY 语义、Lv2 三表关联 frame+thread_state+waker(M0d #2 #4 的深度扩展)、Binder 对端匹配加 utid+时间窗(修源文档笛卡尔积)、Lv3 自定义 Metric + 功耗四表关联。逐条标"不重叠"或"深度扩展",见第七节差异化表。

---

## 状态与诚实标注

> 按「诚实性前置声明」表四类标注,逐条归项(对齐用户全局规则「未经验证须标注」)。本线基于「暂无目标设备」环境。**Lv0/Lv1/Lv2 核心 SQL 经 v57.2 真 trace 实测跑通**(`actual_frame_timeline_slice` / `thread_state` / jank→thread_state 联合,详见 `未验证清单.md` 第八节 V1-V7;实测发现并已修正 C1-C3);**第二轮 v57.2 实测:EXTRACT_ARG 对端 / window / cpufreq / android_jank_cuj 已验;实测修正 C4-C5 已回填(详见 `未验证清单.md` §八 V8-V12)**;TMA/PMU/`--trace-offcpu` 等真机项仍「完成但未验证」。

### 已验证(v57.2 真 trace)— Lv0/Lv1/Lv2 核心 SQL

- **trace_processor 加载真 trace + SQL 实跑**:用 `/usr/local/bin/trace_processor`(v57.2)+ 本机 `trace.pftrace`(44.8MB,含 systemui/surfaceflinger/nexuslauncher/googlequicksearchbox 帧)实跑 Lv0/Lv1/Lv2 SQL,均跑通(见 `未验证清单.md` 第八节 V1-V7)。
- **`actual_frame_timeline_slice` 表 + 列**:存在;列含 id/ts/dur/track_id/name/arg_set_id/display_frame_token/surface_frame_token/upid/layer_name/present_type/on_time_finish/gpu_composition/jank_type/jank_severity_type/prediction_type/jank_tag 等;Lv2/Lv3 假设的 ts/dur/jank_type/on_time_finish/upid **全部正确**。
- **`actual_frame_timeline_slice.upid` 语义**: = 帧生产进程(719=systemui/450=surfaceflinger/735=nexuslauncher/755=quicksearchbox/710=system_server),`WHERE upid=<app>` **可正确过滤该 App 帧**。
- **`thread_state` 表 + state 枚举**:存在;state ∈ {D, I, R, R+, Running, S, X, Z}。本线 `IN('S','D')`/`=R` 与真实枚举一致。
- **Lv2 jank→thread_state 联合闭环**:实跑命中——帧 ts=12798901827074(16.13ms,"App Deadline Missed")窗口内主线程 S 状态阻塞 9.15ms。
- **实测修正 C1-C3**(已回填本线):C1 `frame_timeline_event` v57.2 不存在(统一用 `actual_frame_timeline_slice`);C2 `jank_type` 是描述性字符串(用 `LIKE '%关键词%'`,非 `='App'`/`='SF'`);C3 Android 主线程名是截断进程名(非 `'main'`,用 `tid=pid` 定位)。
- **第二轮 v57.2 实测 V8-V12**(已回填本线):V8 `blocked_function` 本 trace 全空 → 降级 `waker_utid`+`io_wait`(链路通);V10 window 跨核迁移 SQL 跑通;V11 `EXTRACT_ARG(arg_set_id,'destination process'/'calling tid'/'data size'/'code')` 取 binder 对端实跑命中(dest pid 712/1782/714);V12 `android_jank_cuj` 非 CUJ trace 输出空 `{}`。**实测修正 C4a(binder arg key `'data size'` 带空格、无 `reply_size`)/ C4b(Binder 对端首选 EXTRACT_ARG,R4 name 匹配降为备用)/ C5(jank 统计直接基于 `actual_frame_timeline_slice`,不强制 CUJ)已回填**(见 §八 C4a/C4b/C5)。

### 完成但未验证(机制/命令解析无误,但本环境未实跑;真机首跑可能撞版本/口径差异)

- **Perfetto config 字段、数据源、Python `trace_processor` API、simpleperf 命令参数**:对照 perfetto.dev/docs/analysis/sql-tables、NDK simpleperf doc、`pip install perfetto` 官方文档;语法解析无误,部分 SQL 经 v57.2 实测跑通(见上)。剩余版本差异风险:`counter` vs `cpu_counter_track` 与 `cpu_frequency` 表名、非 binder 类 `EXTRACT_ARG` 的 arg key 命名,需真机 `.schema <table>` 校对(**binder arg key 已 v57.2 实测,见 §八 V11/C4a**)。
- **UI 五大高级操作**(pinning/args flotation/slices selection/query driver/track group):在公开示例 trace 上可验证,但本环境未实际打开 ui.perfetto.dev 操作。
- **`ProfilingManager` system-triggered 闭环机制**:对齐 [[M0d 工具链]] 2.8 与 developer.android.com ProfilingManager;机制级描述未在真机逐条核实 API 重载/常量名(以 16 SDK 为准)。
- **`--symfs` + addr2line 用法**:对齐 NDK simpleperf doc;未真机实跑区分 .oat vs JIT。

### 诊断起点 · 待真机校准(经验起点值,非硬门槛;因核/频率/制程而异)

- **健康阈值诊断起点表全部数值**(IPC 大核≥1.5/小核 1.0-1.2、L1D<5%、LLC<20%、Branch<3%、DTLB<1%、Frontend<10%、Backend<30%、Retiring>60%、Bad Spec<5%、Runnable<10%、Binder P99<5ms、CS/s<5000 等):以源文档 §8.4 为诊断起点,经验值非硬门槛,需真机实测校准。表顶已声明"经验起点 · 需真机校准,非硬门槛";每条标了适用核/频率/制程前提。来源口径打架三处(§3.2/§6.1.3/§8.4)已按计划以 §8.4 为准,§6.1.3 L2 细分单独列。

### 依 A76 示例 · 待真机/TRM 复核(仅适用 Cortex-A76;他核需查对应 TRM/PMU guide)

- **原始 PMU 事件编号表**(r03=L1D_CACHE_REFILL、r04=L1D_CACHE、r05=L1D_TLB_REFILL、r17=L2D_CACHE_REFILL、r22=BR_MIS_PRED_RETIRED、r23=STALL_FRONTEND、r24=STALL_BACKEND、r28=MEM_ACCESS_CHECKED 等):源文档 §3.1.4/§6.1.1 给出,标注"Cortex-A76 示例"。他核(A78/A710/A715/A55)同事件 r 编号不同(imp-def),需查各自 TRM 的 PMU events 章节。**待对照 Cortex-A76 TRM 与真机 `simpleperf list` 复核**(源文档疑点 ①)。
- **TMA L1/L2 公式与系数**:源文档 §6.1.2 的 `pipeline_width=4`、`penalty_cycles≈11` 是 A76 硬编码;他核 4-wide/6-wide、penalty 不同。`retiring = inst_retired/total_slots`、`bad_spec = br_mis_pred*penalty/total_slots`、`frontend = stall_frontend/cycles`、`backend = stall_backend/cycles` 仅适用 A76;A78/A710 需查对应 TRM/PMU guide 重算。**A76 公式仅适用 A76,不能照搬 A78**(技术修正 #6)。
- **Lv3 功耗-thermal-频率联合 SQL** 的 thermal track 名(`%thermal%zone0%`):具体 track 命名因设备/PMIC 而异,需真机 `.tables` 校对。

### 推演级 · 待真机(需 root + 带符号 so + 目标 SoC,无设备下连"跑通命令"都做不到)

- **simpleperf `--trace-offcpu`/`annotate.py`/`--post-unwind`/原始 r 编号采样**:无设备下无法实跑,本线给的命令骨架与读法未真机验证;真机复测前不标"已验证"。
- **Lv3 TMA 顶层归因能力**:无真机下只能复读源文档 §7 粒子 VBO 示例数据(IPC 0.72→1.85、L1D Miss 38.2%→3.1%、最大帧 28ms→7.2ms)复现推导链;对未知新 perf.data 独立 L1→L2 下钻需真机。**真机到位前 Lv3 TMA 归因只能推演,不能独立归因**,能力达成须真机 + 目标 SoC TRM。
- **§7 粒子 VBO 案例的全部数值**:来自源文档 §7 示例(非本环境真机复测);作为 Lv2/Lv3 无设备主路径的推演数据,非实测验证。

### 源文档 4 处疑点复核状态

1. **§6.1.1 A76 事件编号表(r03/r04/r05/r17/r22/r23/r24/r28 等)与 ARM PMUv3/Cortex-A76 TRM 一致性** → 标「**待 TRM 复核**」(已落实:§3.4 PMU 架构前置、术语节 TRM 条、尾节「依 A76 示例·待 TRM 复核」归项)。
2. **§6.1.2 `penalty_cycles≈11`、`pipeline_width=4` 核依赖硬编码** → 标「**A76 示例,他核需另查**」(已落实:§3.4 #6 声明、Check 6、尾节归项)。
3. **§5.1.2 Binder SQL 按 name 匹配(`JOIN slice server_ts ON server_ts.name = client_ts.name`)笛卡尔积风险** → **v57.2 实测后改写:C4b 已落实(首选 EXTRACT_ARG 取对端,R4 name 匹配降为备用,见 §八 V11/C4b)**。**首选写法**(arg 含 `destination process`,实测直接给对端 pid,无需 name 匹配):
   ```sql
   -- v57.2 实测首选:EXTRACT_ARG 直接取对端,arg 含 'destination process'(dest pid 712/1782/714 实测命中)
   SELECT s.ts/1e6 AS ms, s.dur/1e6 AS dur_ms,
          EXTRACT_ARG(s.arg_set_id,'calling tid') AS caller_tid,
          EXTRACT_ARG(s.arg_set_id,'destination process') AS dest_pid,
          EXTRACT_ARG(s.arg_set_id,'destination thread') AS dest_tid,
          EXTRACT_ARG(s.arg_set_id,'data size') AS data_sz,
          cp.name AS dest_process
   FROM slice s
   LEFT JOIN process cp ON cp.pid = EXTRACT_ARG(s.arg_set_id,'destination process')
   WHERE s.name LIKE 'binder transaction%' AND s.arg_set_id!=0 AND s.dur > 5000000
   ORDER BY s.dur DESC LIMIT 10;
   ```
   **备用写法**(arg 不可用时用 name 匹配 JOIN,加 utid+时间窗+等长+异线程约束;**首选 EXTRACT_ARG 见上**):
   ```sql
   -- 修源文档 §5.1.2:对端匹配加 utid 约束(避免多对端同名笛卡尔积)+ 时间窗 + 等长 + 异线程
   SELECT client.ts/1e6 AS start_ms, client.dur/1e6 AS dur_ms,
          ct.name AS client_thread, st.name AS server_thread, sp.name AS server_proc
   FROM slice client
   JOIN thread_track ctt ON client.track_id = ctt.id
   JOIN thread ct ON ctt.utid = ct.utid          -- 客户端线程
   JOIN slice server ON server.name = client.name
     AND server.ts >= client.ts AND server.ts < client.ts + client.dur
     AND server.dur = client.dur                       -- 对端 slice 等长(binder transaction 两端 dur 接近)
   JOIN thread_track stt ON server.track_id = stt.id
   JOIN thread st ON stt.utid = st.utid          -- 服务端线程(utid 区分,避免同名)
   JOIN process sp ON st.upid = sp.upid
   WHERE client.name LIKE 'binder transaction%' AND client.dur > 1e7
     AND stt.utid <> ctt.utid                            -- 排除同线程自己的同名 slice
   ORDER BY client.dur DESC LIMIT 10;
   -- 仅近似修对端匹配——真正稳的做法是关联 `binder_reply`/`binder_transaction_received` ftrace event
   -- (需 config 开 `binder/binder_transaction_received`,见 §3.2)
   -- **v57.2 实测:arg 含 'destination process',首选 EXTRACT_ARG 取对端(见上首选写法);本 name 匹配仅 arg 不可用时备用**
   ```
4. **阈值三口径打架(§3.2 vs §6.1.3 vs §8.4)** → **本线以 §8.4 为诊断起点**(第六节诊断起点表),§6.1.3 的 L2 细分阈值单独列且标"TMA L2 近似·需配合 A76 stall 事件",§3.2 不再使用(已落实:第六节表顶声明 + 备注)。

---

## 参考与延伸阅读

> 链接以官方文档优先;第三方仅作概念补强,标注"第三方"。URL 可能随站点改版变化,失效按标题搜索官方站。

**Perfetto / trace_processor**
- Perfetto 官方文档:https://perfetto.dev/docs/ — config / 数据源 / trace_processor 全套,§1.1/§2.1/§2.2 依据。
- trace_processor SQL 表结构:https://perfetto.dev/docs/analysis/sql-tables — `slice`/`thread_track`/`thread`/`process`/`thread_state`/`sched`/`frame_timeline_event`/`actual_frame_timeline_slice`/`args`,§2.2/§3.1/Check 2 依据(**版本差异需 `.schema` 校对**)。
- FrameTimeline 数据源:https://perfetto.dev/docs/data-sources/frametimeline — jankType 分类,术语节/§1.2 依据。
- trace_processor Python API:pip 包 `perfetto`,https://perfetto.dev/docs/quickstart/trace-analysis — §2.4 Python 管线依据。
- Perfetto UI:https://ui.perfetto.dev/ — 公开示例 trace + 五大高级操作 + Query driver。

**ARM PMU / TMA / TRM**
- ARM PMUv3 架构:https://developer.arm.com/documentation/ddi0461/ — PMUv3/PMCR/事件计数,§3.4 PMU 架构前置依据。
- Cortex-A76 TRM(Arm 官网搜 "Cortex-A76 TRM"):PMU events 章节,r 编号表唯一权威源,§3.4/尾节疑点 ① 复核依据(**待对照**)。
- Cortex-A78/A710/A715 TRM:各自独立,同事件 r 编号不同,他核归因依据。
- ARM TMA-ARM(ARM 自己发布的方法论,非 Intel 移植):搜 "ARM top-down microarchitecture analysis" — §3.4 #6 近似性声明依据。

**NDK simpleperf**
- simpleperf 官方:https://android.googlesource.com/platform/system/extras/+/refs/heads/main/simpleperf/doc/README.md — PMU 事件、IPC、record/report/annotate 三步、`--trace-offcpu`/`--post-unwind`/`--per-thread-comm`、dwarf vs fp,§2.3/§3.1/Check 5 依据。
- simpleperf 命令参考:同上 doc/commands 节。
- annotate.py / report_html.py:同上 doc/report 节。

**Android 16 ProfilingManager**
- `ProfilingManager`:https://developer.android.com/reference/android/os/ProfilingManager — 15 App-triggered、16 system-triggered,§2.4 闭环依据(**API 常量名以 16 SDK 为准,待核实**)。
- `ProfilingTrigger`:https://developer.android.com/reference/android/os/ProfilingTrigger — Builder,§2.4 依据。
- Android 16 features:https://developer.android.com/about/versions/16 — system-triggered profiling 所属版本。

**源文档出处**
- `modules/Performance/perfetto-simpleprof.md`(1170 行):本线主要素材来源(§1-8);4 处疑点见尾节复核状态。

**关联模块**
- [[M0d 工具链]](`modules/L0/M0d-工具链.md`):基础 10 条 SQL 模板,本线是其深度延伸。
- [[M0b 图形渲染管线]] / [[M0c 调度与电源基础]] / [[M0.5 线程并发]]:Lv2 场景复用素材。
- [[M3 卡顿与帧率]](`modules/L1/M3-卡顿与帧率.md`):Lv2 Case 场景(主线程等 RT 锁)。
- [[M5 ANR-AppHang治理]] / [[M6 稳定性根因排查]]:阻塞/Watchdog 关联。
- [[M9.5 QNX与混合架构性能]]:车机 guest cpu_freq/thermal 受 hypervisor 限制 + host 时钟对齐(§3.4 车机提示)。

---

*本线完。Lv0/Lv1/Lv2 核心 SQL 经 v57.2 真 trace 实测跑通(详见 `未验证清单.md` 第八节 V1-V7;C1-C3 已回填);真机到位前,Lv3 TMA 归因为推演级;所有"诊断起点"阈值需真机校准;源文档 4 处疑点已按计划逐条标注复核状态。*