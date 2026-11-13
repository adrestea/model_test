# Perfetto + Simpleperf 动手练习路线图(四级 Stage · 无设备优先)

> 模块定位:`Performance/` 目录下的**跨模块、四级能力阶梯的纵向练习编排**。配套 `tools-perfetto-simpleperf-精通.md`(交付物 A)与 `perfetto-simpleprof.md`(源参考)。源参考 §7 粒子 VBO 案例数据齐全(IPC 0.72→1.85、L1D Miss 38.2%→3.1%、最大帧时长 28ms→7.2ms),是 Lv2/Lv3 无设备主推演材料。

---

## ⚠️ 诚实性前置声明(对齐用户全局规则「未经验证须标注」)

本路线图基于「**暂无目标设备**」环境。凡需 root/真机 PMU/TMA/带符号 so 的练习标 ⬜ 待真机;机制/SQL/命令原标 **完成但未验证**(解析无误,未实跑)。**Lv0/Lv1/Lv2 核心 SQL 经 v57.2 真 trace 实测跑通**(`actual_frame_timeline_slice` / `thread_state` / jank→thread_state 联合,详见 `未验证清单.md` 第八节 V1-V7;实测发现并已修正 C1-C3);**第二轮 v57.2 实测:EXTRACT_ARG 对端 / window / cpufreq / android_jank_cuj 已验;实测修正 C4-C5 已回填(详见 `未验证清单.md` §八 V8-V12)**;TMA/PMU/`--trace-offcpu` 等真机项仍「完成但未验证」。

| 内容类 | 验证状态标注 | 含义 |
|--------|-------------|------|
| 机制原理、config 字段、SQL 语法、Python API、命令参数 | **部分验证(v57.2 真 trace SQL 实跑;真机项仍待)** | Lv0/Lv1/Lv2 核心 SQL 经 v57.2 实测跑通(见 `未验证清单.md` 第八节 V1-V7);config/Python API/真机命令仍未实跑 |
| 健康阈值表(IPC/Cache Miss/TMA 占比等) | **诊断起点 · 待真机校准** | 经验起点值,非硬门槛;因核/频率/制程而异 |
| 原始 PMU 事件编号(r03/r23/r24…)、TMA L1/L2 公式与系数 | **依 A76 示例 · 待真机/TRM 复核** | 仅适用 Cortex-A76;他核需查对应 TRM/PMU guide |
| TMA 顶层归因能力(Lv3) | **完成但未验证(只能推演,不能独立归因)** | 无真机时只能复读 §7 示例数据;对未知 perf.data 独立 L1→L2 下钻需真机 |
| simpleperf `--trace-offcpu`/`annotate.py`/原始 r 编号采样 | **推演级 · 待真机** | 需 root + 带符号 so + 目标 SoC,无设备下连「跑通命令」都做不到 |

### FrameJankType 四分类口径映射表(本路线图 ↔ M0d ↔ M3)

| 本路线图/A | M0d | M3 | 说明 |
|---|---|---|---|
| Self | (并入 App) | Self | Self⊆App;M0d 无 Self |
| App | App | App | App 段(含 Self) |
| SF | SF | SF | SurfaceFlinger 合成段 |
| Display | Display | Display | 显示段 |
| (并入 App/SF) | Missed | Missed | Missed 在 M0d/M3 单列,本路线图简化并入 App/SF 段 |

> **口径声明**:本路线图四分类 = Self/App/SF/Display;回引 M0d/M3 时按此映射对照,**M0d 无 Self、M3 含 Missed,勿直接套用**。**⚠️ v57.2 实测(`jank_type` 真实枚举,见未验证清单 §八 V5/C2)**:`jank_type` 列实际是描述性字符串(`App Deadline Missed`/`SurfaceFlinger CPU Deadline Missed`/`Buffer Stuffing`/`Display HAL`/`Prediction Error`/`Unknown Jank`/`None` 等,可含逗号组合),非 `Self/App/SF/Display` 枚举——SQL 用 `LIKE '%关键词%'` 匹配,`='App'`/`='SF'` 命中 0 行。对照表:App Deadline Missed→App 段;SurfaceFlinger CPU/GPU Deadline/Scheduling→SF 段;Display HAL→Display 段;Buffer Stuffing/Prediction Error/Unknown Jank→其他。真实 trace 实测样例分布(本机 v57.2,44.8MB):Buffer Stuffing 95 / SF CPU Deadline 22 / App Deadline Missed 5 / SF Scheduling 4 / Unknown Jank 3 / Prediction Error 3 / SF GPU Deadline 2 / Display HAL 1。

---

## 一、与各模块「五 Todolist / 验证四件套」边界声明

本路线图 = **跨模块、四级能力阶梯的纵向练习编排**(纵向:能力从认红帧到 TMA 归因逐级上升);各模块「五 Todolist / 验证四件套」= **单模块知识点横向清单**(横向:覆盖单模块全部知识点)。

**两者不重定义、不互替**:本路线图的 **Stage 验收项回引对应模块 Check 编号**(见下表),而非重新定义一套验收口径。若本路线图与某模块 Check 出现口径冲突,以**模块原文 Check 为准**,本路线图随之勘误。

### Stage 验收回引对照表

| Stage | 回引模块 | 对应 Check 编号(示例) | 备注 |
|-------|---------|----------------------|------|
| Stage0(Lv0) | `modules/L0/M0d-工具链.md` 五节 Check #1/#2/#4 | M0d Check 1(三层架构)/#2(join 链)/#4(数据源) | 本路线图 Stage0 只验「认红帧 + 读 stat」,不重写 M0d Check |
| Stage0(Lv0) | `modules/L0/M0d-工具链.md` 五节 Check #6 | M0d Check 6(simpleperf IPC + stall) | 本路线图 Stage0 只验「读 stat 判 IPC」,微架构下钻留 Stage3 |
| Stage1(Lv1) | `modules/L0/M0d-工具链.md` 五节 Check #1/#3/#4 | M0d Check 1/#3(thread_state R/S/D)/#4 | 本路线图 Stage1 验「写 config + 多表 JOIN SQL」,机制回引 M0d |
| Stage2(Lv2) | `modules/L1/M3-卡顿与帧率.md` 六节 Check #6/#7 | M3 六节 Check #6(FrameTimeline 五元组判责)+ #7(jankType 四分类 Self/App/SF/Display/Missed 对应) | **Stage2 验收① = `modules/L1/M3-卡顿与帧率.md` 六节 Check #6 + #7** |
| Stage2(Lv2) | `modules/L1/M5-ANR-AppHang治理.md` 阻塞定位相关节 | 回引 `modules/L1/M5-ANR-AppHang治理.md` 主线程阻塞定位相关节(阻塞弧线/栈解析) | Stage2 阻塞定位回引,不重写 |
| Stage2(Lv2) | `modules/L0/M0d-工具链.md` 模板 3.3/3.4/3.6 | M0d SQL 模板库 | Stage2 复用 M0d 已验证 SQL 口径,声明为深度扩展非重复 |
| Stage3(Lv3) | `modules/L0/M0d-工具链.md` 五节 Check #6 | M0d Check 6(simpleperf stall + PMU 选型,微架构归因延伸) | Stage3 TMA 回引 M0d 微架构节(声明近似性),M3 不含 TMA 微架构归因 |
| Stage3(Lv3) | `modules/L0/M0d-工具链.md` Check #12/#13 | M0d Check 12(ProfilingManager)/#13(SystemHealthManager) | Stage3 系统触发闭环回引 |

### 编号归一映射(主计划 v2.6 索引 ↔ modules/L1 文件侧)

| 主计划 v2.6 索引 | modules/L1 文件 | 归一编号(文件侧) |
|---|---|---|
| M2a View 帧率 | `M3-卡顿与帧率.md` | M3 |
| M2.5 ANR | `M5-ANR-AppHang治理.md` | M5 |
| M2.6 稳定性 | `M6-稳定性根因排查.md` | M6 |
| M2.7 输入/系统UI | `M7-输入管线与系统UI性能.md` | M7 |
| M2b Compose | `M4-Compose性能.md` | M4 |
| M1.5 系统开机 | `M2-系统开机与启动稳定性.md` | M2 |

---

## 二、能力自评终点定义

**Lv3 终点 = 在无提示下,对一份新 trace 完成 ①jank 归因 ②阻塞定位 ③热点深挖 ④TMA L1 分类 ⑤出优化建议 五步闭环,且报告通过人工 review。**

> **诚实标注**:**无真机时,④(TMA L1 分类)与⑤(出优化建议)只能停在推演级,真机到位前不算「达到 Lv3 归因能力」**。无设备环境下,①②③可通过公开 trace + §7 案例推演练到可验收;④只能复读 §7 给定数据(不能对未知 perf.data 独立下钻);⑤只能按 TMA 主导分类矩阵给方向性建议,真机校准前的具体量化改法(如 AoS→SoA 的 miss 降幅)只能复述 §7 示例,不能独立给新场景的量化改法。Lv3 归因能力的真验证门槛是:**拿到一份从未见过的真机 perf.data,独立跑完五步且结论经真机复测验证**。

---

## 三、Stage0(Lv0 入门 · 机制驱动)

### 3.1 目标能力(一句话)

在 Perfetto UI 上打开官方示例 trace 认得红色 Jank 帧、读得 simpleperf stat 的 IPC 与 stall 方向,并能口述 Perfetto(Where/When)与 Simpleperf(Why/How much)的分工。

### 3.2 练习(无设备优先,3-5 个)

**练习 0.1【公开 trace · UI 认红帧】**
- 动作:浏览器访问 `https://ui.perfetto.dev` → `Open trace` → 选一条官方示例 trace(执行时定位具体 URL,见篇末「无设备推演资料清单」①)。展开目标进程的 `Actual Frames` 轨道,找到红色 slice(jank 帧),点开看 `jank_type` 字段。
- 输入资料:Perfetto 官方示例 trace(篇末清单①);`tools-perfetto-simpleperf-精通.md` 术语节 FrameJankType 四分类口径。
- 产出:一条 jank 帧的 `ts / dur / jank_type` 三元组(手抄或截图)。
- 判读要点:`Actual Frames` 轨道在 UI 左侧 track 列表里通常显示为进程名下的子轨道,**绿色**=按时完成(`on_time_finish=true`),**红色**=超时 jank;点开红色 slice 后在下方 `Args` 面板能看到 `jank_type` 字符串。若该示例 trace 无 frametimeline 轨道,说明数据源未含 `android.surfaceflinger.frametimeline`,需换示例或降级为「认 sched 轨道的 Running/Sleeping 颜色」。

**练习 0.2【FrameJankType 四分类口述】**
- 动作:口述 Android 16 `FrameJankType` 四分类(`Self`/`App`/`SF`/`Display`,较旧版三分类 `App`/`SF`/`None` 已细化)各自的责任方,以及「Self jank 与 App jank 的区别」。
- 输入资料:`tools-perfetto-simpleperf-精通.md` Lv0 锚点节;`perfetto-simpleprof.md` §2.1.2 FrameTimeline 表。
- 产出:一段不超过 5 行的口述文字,需含「Self = 应用自身帧提交慢」「App vs SF 责任分界」。
- 参考答案骨架:Self = 应用自己这一帧 doFrame 跑超了预期 deadline(应用主线程/RenderThread 自身责任);App = 应用侧导致的掉帧(含 Self,旧版三分类里 App 与 Self 合并);SF = SurfaceFlinger 合成阶段超时(HWC/GPU 合成慢、图层过多);Display = 显示控制器呈现阶段问题(VSYNC 偏移、硬件提交超时)。App 与 SF 的分界在「合成前」还是「合成中」。

**练习 0.3【simpleperf stat 输出判读】**
- 动作:给定一份 `simpleperf stat` 输出文本(源文档 §4.4.1 示例:IPC 0.80、Cache Miss 15.2%、Branch Miss 4.1%),口述「IPC 偏低 → backend 还是 frontend stall?下一步该 record 哪个事件?」
- 输入资料:`perfetto-simpleprof.md` §4.4.1;`modules/L0/M0d-工具链.md` Check 6(IPC < 1 + stall + PMU 选型)。
- 产出:一段判断 + 一个下一步 PMU 事件选型建议(`stalled-cycles-backend` 还是 `frontend`)。
- 判读要点:IPC 0.80 < 1.0 → CPU 在等待(stall),但单看 IPC 不能定方向;需补 `stalled-cycles-frontend`/`stalled-cycles-backend` 两个事件再判。若 backend 高 → 数据 cache miss / 内存依赖(本例 Cache Miss 15.2% 偏高,倾向 backend);若 frontend 高 → 取指/指令 cache miss。下一步 record 建议:`cpu-cycles,stalled-cycles-backend,cache-misses` 三事件同采。

**练习 0.4【工具分工一句话】**
- 动作:用一句话说清「同样掉帧,何时用 Perfetto、何时上 simpleperf?」,需含「Perfetto 定 where/when,simpleperf 定 why/how much」。
- 输入资料:`perfetto-simpleprof.md` §1.2 协同模型。
- 产出:一句话(≤ 30 字)。
- 参考答案:「先 Perfetto 定哪一帧哪条线程在什么时刻阻塞(where/when),再 simpleperf 定该线程 CPU 时间花在哪、微架构为何 stall(why/how much)。」

### 3.3 验收标准(可勾选,回引模块 Check)

- ☐ 练习 0.1:能在公开 trace 上指认 ≥ 1 个红色 jank 帧并读出 `jank_type` 字段值(非空)。**回引 `modules/L0/M0d-工具链.md` 五节 Check #1**(三层架构 + 数据源)。注意 M0d 用 App/SF/Display/Missed 四分类,不含 Self。
- ☐ 练习 0.2:能口述 FrameJankType 四分类并说出 Self 与 App 的区别(可判定:答出「Self 属应用自身帧提交慢」即过)。
- ☐ 练习 0.3:能对给定 stat 输出判 IPC 高低方向(IPC 0.80 < 1 → 偏低)并给出下一步 PMU 事件选型。**回引 `modules/L0/M0d-工具链.md` 五节 Check #6**(simpleperf IPC + stall)。
- ☐ 练习 0.4:能口述 Perfetto/Simpleperf 分工(Where/When vs Why/How much)。

### 3.4 产出物

一份 Stage0 分析报告(填篇末模板的「现象 / 责任方(jank_type)/ 验证状态」三段,其余段标 N/A),含至少 1 条 jank 帧三元组 + 1 条 stat 判读结论。

### 3.5 真机延展项(⬜ 待验证)

复现所需条件:
- ⬜ 任一 Android 12+ 真机(trigger FrameTimeline 数据源);Android 16 设备(验证四分类口径)
- ⬜ `adb shell perfetto -o <path> -t 10s sched freq gfx am -a <pkg>` 抓本机 trace
- ⬜ `adb shell simpleperf stat -p <pid> --duration 5` 跑本机 stat
- ⬜ 验证项:本机 jank 帧的 `jank_type` 是否与 UI 红色 slice 一致;本机 IPC 数值是否落在公开示例的同一量级

### 3.6 Stage0 自评门槛

完成 Stage0 全部练习 + 验收 4 项全勾 → **达到 Lv0 入门能力**。自评反问:
- 给我一份陌生 stat 输出,我能否在 30 秒内说出 IPC 偏高/偏低方向 + 下一步该采哪类事件?
- 给我一份陌生 trace,我能否在 UI 里 1 分钟内找到一个红色 jank 帧并读出 `jank_type`?
- 若任一答「否」,回练 0.3/0.1,不要进 Stage1。

---

## 四、Stage1(Lv1 中级 · 机制驱动)

### 4.1 目标能力(一句话)

能独立写出含 `sched+freq+binder+frametimeline` 的 `trace_config.pbtx` 并逐行解释;能用 trace_processor SQL 从单表查到多表 JOIN 再到 `EXTRACT_ARG`/window;能跑通 `simpleperf record → report` 出 Top 热点函数。

### 4.2 练习(无设备优先,4-5 个)

> **Lv1 机制驱动**:以下练习全部可在公开 trace / 文档推演上完成,无需真机。SQL 部分若公开 trace 不含某表,降级为「语法对齐 M0d 已验证表名」并标待验证。

**练习 1.1【写 trace_config.pbtx 并逐行解释】**
- 动作:按 `perfetto-simpleprof.md` §4.1.1 模板写一份 `trace_config.pbtx`,至少含 `linux.ftrace`(sched_switch/sched_waking/cpu_frequency/binder_transaction)+ `android.surfaceflinger.frametimeline` + `linux.process_stats`。逐行注释每个字段含义(`buffers.size_kb`/`fill_policy`/`ftrace_events`/`atrace_categories`/`atrace_apps`/`duration_ms`)。
- 输入资料:`perfetto-simpleprof.md` §4.1.1;`modules/L0/M0d-工具链.md` §2.3 完整 config 模板。
- 产出:一份带逐行注释的 `.pbtx` 文件(文本)。

**练习 1.2【单表 → 多表 JOIN SQL】**
- 动作:在公开 trace 上跑三条 SQL(用 `trace_processor` 或 UI 内 query driver):
  1. 单表:`SELECT ts, dur/1e6 AS dur_ms, jank_type FROM actual_frame_timeline_slice WHERE jank_type != 'None' ORDER BY dur DESC LIMIT 20;`(对齐 M0d 模板 3.2 口径)
  2. 二表 JOIN:`SELECT s.name, s.dur/1e6 AS ms, t.name AS thread FROM slice s JOIN thread_track tt ON s.track_id=tt.id JOIN thread t ON tt.utid=t.utid WHERE s.name LIKE '%binder%' ORDER BY s.dur DESC LIMIT 10;`
  3. 三表 JOIN(thread + process + thread_state):`SELECT state, SUM(dur)/1e6 AS ms FROM thread_state WHERE utid IN (SELECT utid FROM thread t JOIN process p ON t.upid=p.upid WHERE p.name='<pkg>') AND dur > 1e7 GROUP BY state ORDER BY ms DESC;`
- 输入资料:`perfetto-simpleprof.md` §4.2.2;`modules/L0/M0d-工具链.md` 模板 3.1/3.4。
- 产出:三条 SQL 各返回的前 5 行结果(或截图)。

**练习 1.3【EXTRACT_ARG 提 binder arg】**
- 动作:用 `EXTRACT_ARG(arg_set_id, 'data size')`(带空格,非下划线)提 binder transaction 的 `data size`,找出 `data size` 最大的 10 次 binder 调用。口述「arg 表结构与 EXTRACT_ARG 的语义」。**v57.2 实测 binder arg key 全集(`data size`/`calling tid`/`code`/`destination process`/`destination thread`/`destination name`/`destination node`/`flags`/`offsets size`/`reply transaction?`/`transaction id`;无 `data_size` 下划线、无 `reply_size`)见未验证清单 §八 V11/C4a**。
- 输入资料:`tools-perfetto-simpleperf-精通.md` 二工具箱 Lv1 专题(EXTRACT_ARG);`perfetto-simpleprof.md` §5.1.2。
- 产出:一条含 `EXTRACT_ARG` 的 SQL + 前 10 行结果。

**练习 1.4【simpleperf record → report 火焰图】**
- 动作:给定一份 `perf.data`(篇末清单③,若可得;不可得则用源文档 §4.4.2 文字描述推演),跑 `simpleperf report -i perf.data --sort dso,symbol --percent-limit 1.0` 出 Top 热点;口述火焰图 X 轴宽度/Y 轴深度的读法。
- 输入资料:`perfetto-simpleprof.md` §4.3.3/§4.4.2;`modules/L0/M0d-工具链.md` §2.6。
- 产出:Top 5 热点函数表 + 火焰图读法口述。

**练习 1.5【Lv1 末:多表 JOIN 速查】**(计划 v2 前置练习)
- 动作:写一条 `thread JOIN process JOIN thread_state` 三表 JOIN,再加一个 `WITH` 子查询(如「主线程 Runnable 段 + 其 waker 线程名」)。口述「为何 Lv2 的 Jank→thread_state→waker 三表关联需要这个前置」。
- 输入资料:`perfetto-simpleprof.md` §5.1.1;`modules/L0/M0d-工具链.md` 模板 3.4/3.5。
- 产出:一条三表 JOIN + WITH 子查询 SQL;一段口述(为 Lv2 四层 JOIN 铺路)。
- 参考答案骨架:
```sql
-- Android 主线程名是截断后的进程名(task comm 15 字符),不是 'main';用 tid=pid 定位最稳。
WITH main_runnable AS (
  SELECT ts.ts, ts.dur, ts.state, ts.waker_utid, t.name AS thread_name, p.name AS proc_name
  FROM thread_state ts
  JOIN thread t ON t.utid = ts.utid
  JOIN process p ON p.upid = t.upid
  WHERE p.name = '<pkg>' AND t.tid = p.pid   -- 主线程 tid == 进程 pid(v57.2 实测;nexuslauncher 主线程名是 s.nexuslauncher,非 'main')
    AND ts.state = 'R' AND ts.dur > 5e6
)
SELECT mr.ts, mr.dur/1e6 AS ms, w.name AS waker_thread, wp.name AS waker_process
FROM main_runnable mr
LEFT JOIN thread w ON w.utid = mr.waker_utid
LEFT JOIN process wp ON wp.upid = w.upid
ORDER BY mr.dur DESC LIMIT 20;
```
口述:Lv2 的掉帧归因要在「帧 → thread_state → waker」三层之上再加 `actual_frame_timeline_slice` 这一层(Jank 帧 ts/dur 限定 thread_state 时间窗),所以 Lv1 末必须把「thread × process × thread_state 三表 + WITH 子查询」练熟,否则 Lv2 四层 JOIN 会因不熟 join 链而卡在语法而非归因。**v57.2 实测(见未验证清单 §八 V6/C3)**:Android App 主线程名是 task comm 截断后的进程名(15 字符),`t.name='main'` 命中 0 行;nexuslauncher 主线程名为 `s.nexuslauncher`(utid 736/tid 2782),用 `tid=pid` 定位最稳。实测主线程 thread_state 分布:S 6461.9ms / Running 175.2ms / R 149.9ms / R+ 20.2ms / D 2.6ms。

### 4.3 验收标准(可勾选,回引模块 Check)

- ☐ 练习 1.1:能写出含 `sched+freq+binder+frametimeline` 的 config 并逐行解释(可判定:能说出 `fill_policy: RING_BUFFER` 与 `duration_ms` 的作用)。**回引 `modules/L0/M0d-工具链.md` 五节 Check #4**(数据源选型)。
- ☐ 练习 1.2:能在公开 trace 上跑通三条 SQL(单表/二表/三表 JOIN)并返回非空结果。**回引 `modules/L0/M0d-工具链.md` 五节 Check #2**(join 链)/#3(thread_state R/S/D)。
- ☐ 练习 1.3:能写出含 `EXTRACT_ARG` 的 SQL 并口述 arg 表结构(声明:M0d 仅 OOM 用过一次,本练习是其深度扩展,非重复)。
- ☐ 练习 1.4:能跑 `simpleperf report` 出 Top 5 热点并口述火焰图读法(X 宽=占比,Y 深=调用栈)。
- ☐ 练习 1.5:能写三表 JOIN + WITH 子查询,为 Lv2 四层 JOIN 铺路。

> **公开 trace 可得性降级**:若执行时无法定位到含完整 sched+binder+frametimeline 的公开示例 trace,Lv1 SQL 验收降级为「语法对齐 M0d 已验证表名(`slice`/`thread_state`/`thread_track`/`actual_frame_timeline_slice`;v57.2 实测 `frame_timeline_event` 不存在)」,并标 **待验证**。本路线图 Lv0/Lv1/Lv2 核心 SQL 已用 v57.2 本机 trace 实测跑通(见 `未验证清单.md` 第八节 V1-V7)。

### 4.4 产出物

一份 Stage1 分析报告(填篇末模板的「现象 / 时间窗口 / 责任方(jank_type)/ 热点函数 / 验证状态」五段),含三条 SQL 结果 + Top 5 热点表。

### 4.5 真机延展项(⬜ 待验证)

复现所需条件:
- ⬜ Android 12+ 真机(FrameTimeline)+ `perfetto` 可执行(`adb shell perfetto` 可用)
- ⬜ `simpleperf` 可执行(NDK 自带或系统预置);`perf_event_paranoid <= 1` 或 root
- ⬜ 带调试符号的目标 App(供 `--call-graph dwarf` 解栈)
- ⬜ 验证项:自抓 trace 上跑通三条 SQL 返回非空;自抓 `perf.data` 上 `report` 出有意义 Top 热点
- ⬜ 进阶验证:`adb shell perfetto --list-data-sources` 看本机数据源是否含 frametimeline(若否,trace_processor SQL 会空,需换设备或升版本)

### 4.6 Stage1 自评门槛

完成 Stage1 全部练习 + 验收 5 项全勾 → **达到 Lv1 中级能力**。自评反问:
- 不看模板,我能否默写一份含 `sched+freq+binder+frametimeline` 的 `trace_config.pbtx` 并逐行解释?
- 给我一份陌生 trace,我能否写出「帧 × jank_type × 线程 × 状态」四维聚合 SQL 并返回非空?
- 若任一答「否」,回练 1.1/1.2/1.5,不要进 Stage2。

---

## 五、Stage2(Lv2 高级 · 问题驱动)

### 5.1 目标能力(一句话)

能对一个真实掉帧问题做 Perfetto+Simpleperf **联合闭环**:掉帧 → 锁/Binder → 调度,并用 `--trace-offcpu` 报告读法做交叉验证,产出含阻塞链与热点函数的可证伪结论。

### 5.2 练习(无设备优先,4-5 个)

> **Lv2 问题驱动**:以下练习以源文档 §7 粒子 VBO 案例为贯穿材料(数据齐全,100% 可得)。Binder 对端 SQL 修源文档 §5.1.2 笛卡尔积疑点。所有涉及 `--trace-offcpu`/真机采样的练习标推演级。

**练习 2.1【掉帧归因链 SQL(复用 M3 Case)】**
- 动作:用 `actual_frame_timeline_slice` JOIN `thread_state` JOIN `thread`(waker)三表关联,对源文档 §7.2 的 jank 帧(ts ≈ 5234000000,dur ≈ 24ms)做归因,产出「主线程 S 状态 8.2ms,blocked_function=futex_wait_queue_me,waker=RenderThread」结论。口述「为何要加 utid + 时间窗约束」(修源文档 §5.1.2 笛卡尔积风险)。
- 输入资料:`perfetto-simpleprof.md` §5.1.1/§7.2/§7.3;`modules/L1/M3-卡顿与帧率.md` 卡顿 Case(主线程等 RenderThread 锁)。
- 产出:一条三表关联 SQL(带 utid+时间窗)+ 归因结论文字。
- 参考答案骨架:
```sql
-- v57.2 实测 jank_type 是描述性字符串('App Deadline Missed' 等),用 LIKE 匹配;Android 主线程名是截断进程名,用 tid=pid 定位。
WITH jank_frames AS (
  SELECT ts, dur, jank_type, upid FROM actual_frame_timeline_slice
  WHERE jank_type LIKE '%App Deadline Missed%' AND dur > 16600000 ORDER BY dur DESC LIMIT 5
)
SELECT jf.ts, jf.dur/1e6 AS frame_ms, ts.state, ts.dur/1e6 AS state_ms,
       ts.blocked_function, w.name AS waker_thread, wp.name AS waker_process
FROM jank_frames jf
JOIN thread_state ts ON ts.upid = jf.upid
  AND ts.ts >= jf.ts AND ts.ts < jf.ts + jf.dur  -- 时间窗约束,避免笛卡尔积
  AND ts.utid = (SELECT utid FROM thread t JOIN process p ON t.upid=p.upid
                 WHERE p.name='<pkg>' AND t.tid = p.pid)  -- 主线程 tid == 进程 pid(v57.2 实测,非 name='main')
LEFT JOIN thread w ON w.utid = ts.waker_utid
LEFT JOIN process wp ON wp.upid = w.upid
WHERE ts.state IN ('S','D') AND ts.dur > 5000000
ORDER BY ts.dur DESC;
```
口述:源文档 §5.1.2 原 SQL `JOIN slice server_ts ON server_ts.name = client_ts.name` 按名匹配,多对端同名 binder transaction 会笛卡尔积;**v57.2 实测后首选 `EXTRACT_ARG(arg_set_id,'destination process')` 直接取对端 pid(arg 含对端 pid,实测命中 dest 712/1782/714,见 §八 V11/C4b),无需 name 匹配**;name 匹配仅作 arg 不可用时的备用(正确做法加 utid 约束 + 时间窗约束,把 N×M 降到 N×1)。本练习同理:thread_state 必须用 utid 锁主线程 + ts 落在 jank 帧时间窗内,否则会把同 upid 其他线程的 S 状态也算进来。**v57.2 实测联合闭环示例**(见未验证清单 §八 V7):帧 ts=12798901827074、dur=16.13ms、"App Deadline Missed",窗口内主线程 S 状态阻塞 9.15ms。**v57.2 实测本 trace `blocked_function` 全空(R9/V8)→ 降级 `waker_utid`+`io_wait`(本 trace waker_utid 75423 行有值)**。

**练习 2.2【Binder 客户端↔服务端对端关联(修笛卡尔积)】**
- 动作:写一条 Binder 对端关联 SQL。**v57.2 实测后首选写法**:`EXTRACT_ARG(s.arg_set_id,'destination process')` 直接取对端 pid(arg 含 `destination process`/`destination thread`/`calling tid`/`data size`/`code` 等,实测命中 dest pid 712/1782/714,见 §八 V11/C4b),比易笛卡尔积的 `JOIN slice server ON server.name=client.name`(R4 修补版,加 utid<> + 时间窗 + dur= 约束)**更稳更简**。**不能照抄**源文档 §5.1.2 的原版 `JOIN slice server_ts ON server_ts.name = client_ts.name`(按名匹配会多对端同名笛卡尔积)。口述「同名多对端场景为何笛卡尔积」与「为何 EXTRACT_ARG 首选」。
- 输入资料:`perfetto-simpleprof.md` §5.1.2(含待修疑点);`modules/L0/M0d-工具链.md` 模板 3.3(仅按 name like '%binder%' 列表,本练习是其深度扩展);`未验证清单.md` §八 V11/C4b。
- 产出:一条 Binder 对端 SQL(首选 EXTRACT_ARG 写法;附备用 name 匹配写法)+ 口述。
- 参考答案骨架(首选):
```sql
-- v57.2 实测首选:EXTRACT_ARG 直接取对端(arg 含 'destination process')
SELECT s.ts/1e6 AS ms, s.dur/1e6 AS dur_ms,
       EXTRACT_ARG(s.arg_set_id,'calling tid') AS caller_tid,
       EXTRACT_ARG(s.arg_set_id,'destination process') AS dest_pid,
       EXTRACT_ARG(s.arg_set_id,'destination thread') AS dest_tid,
       EXTRACT_ARG(s.arg_set_id,'data size') AS data_sz,
       cp.name AS dest_process
FROM slice s
LEFT JOIN process cp ON cp.pid = EXTRACT_ARG(s.arg_set_id,'destination process')
WHERE s.name LIKE 'binder transaction%' AND s.arg_set_id!=0 AND s.dur > 10000000
ORDER BY s.dur DESC LIMIT 10;
```
- 备用(arg 不可用时:加 utid 约束 + 时间窗,勿照抄源文档原版):
```sql
SELECT client.ts/1e6 AS start_ms, client.dur/1e6 AS ms,
       ct.name AS client_thread, st.name AS server_thread, sp.name AS server_process,
       client.name AS txn_name,
       EXTRACT_ARG(client.arg_set_id, 'data size') AS data_sz   -- 带空格,非 data_size
FROM slice client
JOIN thread_track ctt ON client.track_id = ctt.id
JOIN thread ct ON ct.utid = ctt.utid
JOIN slice server ON server.name = client.name
  AND server.ts >= client.ts                        -- 时间窗:服务端 ts 落在客户端调用期间
  AND server.ts < client.ts + client.dur
JOIN thread_track stt ON server.track_id = stt.id
JOIN thread st ON st.utid = stt.utid AND st.utid != ct.utid  -- utid 约束:排除自调用,锁定对端
JOIN process sp ON sp.upid = st.upid
WHERE client.name LIKE 'binder transaction%' AND client.dur > 10000000
ORDER BY client.dur DESC LIMIT 10;
```
口述:同名多对端场景(如 5 个进程同时调 `binder transaction:Interface1`)按名 JOIN 会把每个 client 与所有同名 server 配对,产出 5×5=25 行笛卡尔积。**首选 EXTRACT_ARG(`destination process`)避免笛卡尔积(arg 含对端 pid,实测命中)**;name 匹配仅在 arg 不可用时备用,修法:加 `server.ts BETWEEN client.ts AND client.ts+dur`(时间窗)+ `st.utid != ct.utid`(utid 排除自调用)。声明:M0d 模板 3.3 仅 `name LIKE '%binder%'` 列表无对端匹配,本练习是其深度扩展,非重复。

**练习 2.3【simpleperf 多事件采样 + 热点下钻】**
- 动作:针对 §7.4 的 RenderThread 热点,推演 `simpleperf record -e cpu-cycles,cache-misses,stalled-cycles-backend -f 8000 --call-graph dwarf` 的预期报告:`GameRenderer::updateVertexBuffer` 占 cpu-cycles 41.2%、cache-misses 38.7%、stalled-backend 52.1%。口述「为何三个事件在同一份 perf.data 里能区分占比」。
- 输入资料:`perfetto-simpleprof.md` §7.4 表格。
- 产出:一张三类事件 × Top 3 函数的占比表(推演)+ 口述。

**练习 2.4【--trace-offcpu 报告读法交叉验证】**
- 动作:口述 `--trace-offcpu` 报告中「on-CPU 热点火焰图」与「off-CPU 等待火焰图」的差异(on-CPU 宽=CPU 跑得多;off-CPU 宽=等待时间长,非 CPU 瓶颈),并以 §7 主线程 8.2ms futex_wait 为例说明「off-CPU 段在报告中如何体现」。标 **推演级 · 待真机**(无设备连跑通命令都做不到)。
- 输入资料:`perfetto-simpleprof.md` §6.3.2;`tools-perfetto-simpleperf-精通.md` 二工具箱 Lv2 专题。
- 产出:一段 on/off-CPU 火焰图差异口述 + §7 案例映射。

**练习 2.5【ARR 帧率切换 jank 归因(Android 16 锚点)】**
- 动作:口述「ARR(Adaptive Refresh Rate)帧率切换期为何会出现 jank」(`hasArrSupport`/`getSuggestedFrameRate` 在 16 增强 API 下,帧率切换瞬间 VSYNC 周期变化导致 expected/actual 口径切换),并说明此类 jank 的 `jank_type` 归属(可能落在 Display 或 Self,而非 App)。标 **机制级 · 待真机**。
- 输入资料:`tools-perfetto-simpleperf-精通.md` Lv2 锚点节;`modules/L1/M3-卡顿与帧率.md` 六节 Check #12(RecyclerView ARR + 投票 + 场景策略)。
- 产出:一段 ARR jank 归因口述(含 jank_type 预判)。

### 5.3 验收标准(可勾选,回引模块 Check)

- ☐ 练习 2.1:能在公开 trace/§7 推演数据上跑通 jank 归因 SQL 并给出责任方(jank_type=App,阻塞=futex_wait,waker=RenderThread)。**回引 `modules/L1/M3-卡顿与帧率.md` 六节 Check #6**(FrameTimeline 五元组判责)+ **Check #7**(jankType 四分类 Self/App/SF/Display/Missed 对应)。
- ☐ 练习 2.2:能写出修笛卡尔积后的 Binder 对端 SQL(含 utid + 时间窗约束)并口述多对端风险。**声明:M0d 模板 3.3 仅按 name like '%binder%' 列表,本验收是其深度扩展,非重复**。
- ☐ 练习 2.3:能对 §7 推演数据产出三类事件 × Top 3 函数占比表,并口述多事件区分原理。
- ☐ 练习 2.4:能口述 on/off-CPU 火焰图差异并映射 §7 案例(标推演级)。**判定锚**:口述含以下三要素即过:on-CPU 宽=算力瓶颈 / off-CPU 宽=等待瓶颈 / §7 主线程 8.2ms futex_wait 映射到 off-CPU 段。
- ☐ 练习 2.5:能口述 ARR 帧率切换 jank 归因(含 jank_type 预判,标机制级)。

### 5.4 产出物

一份 Stage2 分析报告(填篇末模板的「现象 / 时间窗口 / 责任方(jank_type)/ 阻塞链(blocked_function/waker)/ 热点函数 / 验证对照(修复前/后指标)/ 验证状态」七段),含 §7 修复前/后对照(IPC 0.72→1.85、L1D Miss 38.2%→3.1%、最大帧时长 28ms→7.2ms)。

### 5.5 真机延展项(⬜ 待验证)

复现所需条件:
- ⬜ root 或 `perf_event_paranoid <= 1`(simpleperf 多事件 + `--trace-offcpu`)
- ⬜ 带符号 so(`-g` 编译,供 `--call-graph dwarf` 解栈 + `annotate.py` 源码注解)
- ⬜ Android 16 设备(验证 ARR 帧率切换 jank 归因)
- ⬜ 目标 SoC TRM(若涉及原始 r 编号,需查对应核事件号)
- ⬜ 验证项:`--trace-offcpu` 报告实跑;Binder 对端 SQL 在真机 trace 上返回非空;ARR jank 在真机 FrameTimeline 中的实际 `jank_type`
- ⬜ 进阶验证:simpleperf `--post-unwind=true` 在 on-device vs post-unwind 开销对比(丢样本率);dwarf vs fp 解栈开销对比(需 `-fno-omit-frame-pointer` 编译对照版)

### 5.6 Stage2 自评门槛

完成 Stage2 全部练习 + 验收 5 项全勾 → **达到 Lv2 高级能力**。自评反问:
- 给我一份陌生 trace 的掉帧现象,我能否独立产出「jank_type → blocked_function → waker → 热点函数」完整阻塞链 + 可证伪结论?
- 我能否口述 `--trace-offcpu` 报告里 on-CPU 热点与 off-CPU 等待的区分读法,并说明它与 Perfetto thread_state 的交叉验证关系?
- 我能否修掉源文档 §5.1.2 Binder SQL 的笛卡尔积(加 utid + 时间窗)?
- 若任一答「否」,回练 2.1/2.2/2.4,不要进 Stage3。

---

## 六、Stage3(Lv3 专家 · 问题驱动)

### 6.1 目标能力(一句话)

能用 TMA Top-Down(§7 推演数据)做 L1/L2 分类,写自定义 SQL Metric,跑 Python 自动化管线,并联合功耗/thermal;**全程标推演级,真机归因项入红线清单**。

### 6.2 前置练习:ARM PMU 架构 + 核识别 + TRM 查号(计划 v2 前置)

**练习 3.0a【PMUv3 / PMCR 口述】**
- 动作:口述 ARM PMUv3 架构(PMCR 寄存器、PMU 事件计数器、imp-def 事件即实现定义事件)、为何 `simpleperf list` 只列约 20 个事件而原始 `r<编号>` 可解锁更多。
- 输入资料:`perfetto-simpleprof.md` §3.1.4;`tools-perfetto-simpleperf-精通.md` Lv3 PMU 架构前置节。
- 产出:一段 PMUv3 口述(含 imp-def 概念)。

**练习 3.0b【核识别:读 midr_el1】**
- 动作:口述如何读 `/sys/devices/system/cpu/cpu*/regs/identification/midr_el1`(或 `adb shell cat`)识别目标核(Cortex-A76/A78/A710/...),并说明「不同核同事件 r 编号不同」。
- 输入资料:`tools-perfetto-simpleperf-精通.md` Lv3 PMU 架构前置节。
- 产出:一段核识别流程口述。

**练习 3.0c【TRM 查号练习】**
- 动作:对源文档 §6.1.1 的 A76 事件编号表(`r03`=L1D_CACHE_REFILL、`r23`=STALL_FRONTEND、`r24`=STALL_BACKEND 等),标 **依 A76 示例 · 待 TRM 复核**;口述「若换成 Cortex-A78,这些 r 编号是否仍然有效?该查什么文档?」(答:否,需查 A78 TRM / PMU guide)。
- 输入资料:`perfetto-simpleprof.md` §6.1.1;`tools-perfetto-simpleperf-精通.md` 诚实标注节。
- 产出:一张标「待 TRM 复核」的事件编号表 + 换核查号口述。

### 6.3 练习(无设备优先,4-5 个)

**练习 3.1【TMA L1 计算(§7 推演数据)】**
- 动作:用 §7 给定的 RenderThread 数据(`stalled-cycles-backend` 占 52.1%、`cpu-cycles` 占 41.2%),按 `perfetto-simpleprof.md` §6.1.2 公式(`pipeline_width=4`、`penalty_cycles≈11`,**均标 A76 示例,他核需另查**)计算 TMA L1 四类(Retiring/Frontend/Backend/Bad Spec)占比。口述「ARM TMA 与 Intel TMA 精度是否等价?A76 公式能照搬到 A78 吗?」(答:否,ARM 无直接 pipeline-slot 计数,TMA 是 stall 比例近似;A76 公式仅适用 A76)。
- 输入资料:`perfetto-simpleprof.md` §6.1.1/§6.1.2/§6.1.3;`tools-perfetto-simpleperf-精通.md` Lv3 TMA 近似性声明。
- 产出:一张 TMA L1 四类占比表(推演)+ A76 公式局限性口述。
- 推演结果(基于 §7 数据 + A76 公式,**诊断起点 · 待真机校准**):

| TMA L1 类别 | 公式 | §7 推演占比 | §8.4 健康范围 | 判定 |
|-------------|------|------------|--------------|------|
| Retiring | `inst_retired / (cpu_cycles × 4)` | 约 25%(估,需 inst_retired 实测) | > 60% 健康 | 严重偏低(CPU 大量周期空转) |
| Frontend Bound | `stall_frontend / cpu_cycles` | 约 8%(估) | < 10% 健康 | 正常 |
| Backend Bound | `stall_backend / cpu_cycles` | **52.1%**(§7 给定) | < 30% 健康 | **严重**(数据 cache miss / 内存瓶颈) |
| Bad Speculation | `(br_mis_pred × 11) / (cpu_cycles × 4)` | 约 5%(估) | < 5% 健康 | 边界 |

- 口述要点:① ARM 无直接 pipeline-slot 计数(Intel 有 `SLOTS` 事件),TMA 公式是 **stall 比例近似**,非 Intel slots 等价;② `penalty_cycles≈11`/`pipeline_width=4` 是 A76 imp-def 硬编码,A78/A710/A715 需查对应 TRM/PMU guide;③ 「TMA-ARM 是 ARM 自己发布的近似方法论,非 Intel 官方移植」。结论:Backend Bound 52% 与 §7 cache-misses 38.7% 吻合(数据局部性差),指向粒子数据 AoS→SoA 重构。

**练习 3.2【TMA L2 细分(§7 推演)】**
- 动作:对 L1 Backend Bound 细分 L2(Backend Memory vs Backend Core),用 `r28`(MEM_ACCESS_CHECKED)推演 Backend Memory 占比。**标:TMA L2 近似,需配合 A76 stall 事件;阈值单独列,不与 L1 阈值混用**。
- 输入资料:`perfetto-simpleprof.md` §6.1.2/§6.1.3;`tools-perfetto-simpleperf-精通.md` 诊断起点表(L2 细分阈值节)。
- 产出:一张 L2 细分占比表(推演)。

**练习 3.3【自定义 SQL Metric:my_jank_summary】**
- 动作:写一份 `my_jank_metric.sql`。**v57.2 实测后主写法**:帧统计**直接基于 `actual_frame_timeline_slice`**(按 `upid`/`layer_name` 分组)+ P95 子查询(带 `WHERE COUNT(*)>0` 守卫),**不强制 CUJ 分组**(`android_jank_cuj` 内置 metric 依赖 CUJ 交互标记,非 CUJ trace 上 `--run-metrics android_jank_cuj` 输出空 `{}`,见 §八 V12/C5);`RUN_METRIC('android/android_jank_cuj.sql')` 仅作「需 CUJ 分组时的可选(须用带 CUJ 标记的 trace)」**。口述 `RUN_METRIC` 完整流程与「为何主写法不依赖 CUJ」。**声明:M0d 完全未涉及自定义 Metric,本练习是新增**。
- 输入资料:`perfetto-simpleprof.md` §6.2.1;`tools-perfetto-simpleperf-精通.md` Lv3 自定义 Metric 节;`未验证清单.md` §八 V12/C5。
- 产出:一份 `my_jank_metric.sql`(主写法基于 `actual_frame_timeline_slice`;附可选 CUJ 分组注解)+ `RUN_METRIC` 流程口述。
- 参考答案骨架(主写法,见 `tools-perfetto-simpleperf-精通.md` Lv3 自定义 Metric 节):
```sql
-- 主写法:直接基于 actual_frame_timeline_slice(通用,非 CUJ trace 亦可用)
CREATE PERFETTO TABLE my_jank_summary AS
SELECT upid, layer_name,
       COUNT(*) AS total_frames,
       SUM(CASE WHEN jank_type != 'None' THEN 1 ELSE 0 END) AS jank_frames,
       ROUND(100.0 * SUM(CASE WHEN jank_type!='None' THEN 1 ELSE 0 END)/COUNT(*), 2) AS jank_rate_pct,
       ROUND(AVG(dur)/1e6, 2) AS avg_frame_ms,
       ROUND(MAX(dur)/1e6, 2) AS max_frame_ms
FROM actual_frame_timeline_slice GROUP BY upid, layer_name;
-- P95(带 COUNT(*)>0 守卫,直接在 actual_frame_timeline_slice 上算)
-- 可选 CUJ 分组(需带 CUJ 交互标记的 trace):RUN_METRIC('android/android_jank_cuj.sql') 后 JOIN android_jank_cuj 按 cuj_name 分组
```
`RUN_METRIC` 流程:① trace_processor 加载内置 `android_jank_cuj.sql` 定义(它 `CREATE PERFETTO TABLE android_jank_cuj`);② 本 metric 在同 session 内 `RUN_METRIC('android/android_jank_cuj.sql')` 引入该表;③ 用 `CREATE PERFETTO TABLE my_jank_summary AS SELECT ...` 基于该表造自定义聚合(P95 用 `ORDER BY dur LIMIT 1 OFFSET COUNT*95/100`);④ `trace_processor --run-metrics my_jank_metric.sql --metrics-output json -o out.json trace.pb` 输出。执行注意:P95 子查询在空表时 OFFSET 计算 may 溢出,需加 `WHERE COUNT(*) > 0` 守卫;**非 CUJ trace 上 android_jank_cuj 表为空,主写法改基于 `actual_frame_timeline_slice`**。

**练习 3.4【Python 自动化管线】**
- 动作:按 `perfetto-simpleprof.md` §6.2.2 写一份 Python 脚本(`from perfetto.trace_processor import TraceProcessor`),含「掉帧检测 + 主线程阻塞分析 + Binder 延迟分布」三段查询,产出 JSON 报告。口述「ProfilingManager system-triggered trace 如何接入这个管线」(系统触发落 app data dir → 监听器回传 URI → Python 自动消费)。
- 输入资料:`perfetto-simpleprof.md` §6.2.2;`modules/L0/M0d-工具链.md` Check #12(ProfilingManager)。
- 产出:一份 Python 脚本 + ProfilingManager 接入口述。
- ProfilingManager 接入要点:
  1. App 用 `ProfilingTrigger.Builder(TRIGGER_TYPE_ANTR)` + `addProfilingTriggers()` 注册触发器(API 常量名以 16 SDK 为准,**待真机核实**);
  2. 系统在 ANR/冷启动触发瞬间自动起停 Perfetto,trace 落 app data dir;
  3. `registerForAllProfilingResults()` 监听器接收 trace URI → 上传自有服务器(或 pull 回本地);
  4. 本地 Python 管线 `TraceProcessor(trace=path)` 加载该 trace,跑三段查询产 JSON;
  5. 关键:system-triggered 是**被动触发**(系统触发,App 等通知),非「按需即抓」;`setRateLimitingPeriodHours(1)` 限频,低频用户偶发问题可能被限,需按触发器重要性分级限频。
- 声明:ProfilingManager API 常量名/重载在 16 仍可能微调,以 SDK 为准(对齐 M0d Check #12 待人工核实项)。

**练习 3.5【功耗/thermal/频率×掉帧四表关联(§8.4 推演)】**
- 动作:按 `perfetto-simpleprof.md` §6.4 写一条「掉帧时刻 × CPU 频率 × 温度」关联 SQL,推演「Jank 集中出现在 temp > 45°C 且 freq < 60% max → 热降频」结论。**标:推演级,真机校准需 power rail + thermal track**。
- 输入资料:`perfetto-simpleprof.md` §6.4;`modules/L0/M0d-工具链.md` 模板 3.7(仅单表频率,本练习新增关联,声明为深度扩展)。
- 产出:一条四表关联 SQL + 热降频推演结论。
- **声明**:`%thermal%zone0%` track 命名因设备/PMIC 异,真机 `.tables` 校对;若设备无 thermal track 该 SQL 空,降级为只关联 cpu_freq。

### 6.4 验收标准(可勾选,回引模块 Check)

- ☐ 练习 3.0a/b/c:能口述 PMUv3/imp-def、核识别流程、换核查号(答「否,A76 公式不能照搬 A78」)。**回引 `modules/L0/M0d-工具链.md` 五节 Check #6**(simpleperf IPC + stall + PMU 选型,微架构归因延伸;声明 ARM TMA 近似性;M3 不含 TMA 微架构归因)。
- ☐ 练习 3.1:能用 §7 数据算出 TMA L1 四类占比并口述 ARM TMA 近似性(标推演级)。**回引 `modules/L0/M0d-工具链.md` Check #6**(simpleperf stall,声明为微架构归因延伸)。
- ☐ 练习 3.2:能推演 TMA L2 细分(Backend Memory vs Core)并标「L2 近似,需配合 stall 事件」。
- ☐ 练习 3.3:能写 `my_jank_metric.sql` 并口述流程(声明:M0d 未涉及,新增)。**判定锚**:主写法 `CREATE PERFETTO TABLE my_jank_summary AS ... FROM actual_frame_timeline_slice GROUP BY upid, layer_name` + P95 子查询带 `WHERE COUNT(*) > 0` 守卫;口述「主写法直接基于 `actual_frame_timeline_slice`(因 `android_jank_cuj` 依赖 CUJ 标记,非 CUJ trace 上输出空,见 §八 V12/C5)+ 可选 CUJ 分组需 CUJ trace + RUN_METRIC 四步流程」即过。
- ☐ 练习 3.4:能写 Python 管线(三段查询 + JSON)并口述 ProfilingManager 接入。**回引 `modules/L0/M0d-工具链.md` Check #12**(ProfilingManager system-triggered)。
- ☐ 练习 3.5:能写四表关联 SQL 并推演热降频结论(标推演级)。**判定锚**:SQL 含 `actual_frame_timeline_slice JOIN counter(cpu_freq) JOIN counter(thermal)` 三表关联且产 `jank_ms`/`freq_mhz`/`temp_c` 三列即过,热降频推演结论数值标为参考答案示例(非判定项)。

> **Lv3 红线声明**:练习 3.1/3.2/3.5 的占比数值与绝对阈值在无真机下**只能停在推演级**,真机到位前的「占比计算」是复读 §7 给定数据,不能算「对未知 perf.data 独立归因」。Lv3 归因能力的真验证门槛见篇首「能力自评终点定义」。

### 6.5 产出物

一份 Stage3 分析报告(填篇末模板全部字段,含「微架构分类(TMA L1/L2)」段),含 §7 修复前/后所有指标 + 热降频推演结论。报告中 ④(TMA 分类)与⑤(优化建议)段必须标注「**推演级 · 待真机**」。

### 6.6 真机延展项(⬜ 待验证)

真机验证红线见**篇末 §8.2 红线清单 R1-R10**(以 §8.2 为权威清单)。Stage3 相关项映射:
- 原始 PMU 编号 + r 编号采样 → R1
- TMA L1/L2 实测占比 + 公式系数对目标核适用性 → R2/R5
- 绝对阈值校准 → R3
- `--trace-offcpu`/`annotate.py` 实跑 + 带符号 so(`-g` 编译,供 addr2line 解 `.oat` vs JIT 区域)→ R4
- ARM TMA 公式系数对目标核适用性 → R5
- ProfilingManager system-triggered 落盘 trace 自动消费闭环 → R8
- power rail + thermal track(验证热降频归因)→ R10

---

## 七、报告模板(篇末 · 可直接填)

### 7.1 字段清单(最小字段,带说明)

| 字段 | 说明 | 示例 |
|------|------|------|
| **现象** | 用户感知或观测到的问题一句话 | 「120Hz 设备滑动列表周期性掉帧,每 3-4s 一次」 |
| **时间窗口** | trace 中的 jank 帧时间范围(ts + dur),ns 或 ms | 「ts=5234000000, dur=24ms」 |
| **责任方(jank_type)** | FrameJankType 四分类归属 | 「App」 |
| **阻塞链(blocked_function/waker)** | 主线程阻塞函数 + 唤醒者线程/进程 | 「futex_wait_queue_me / waker=RenderThread」 |
| **热点函数** | simpleperf report Top 1-3 函数(含事件类型) | 「GameRenderer::updateVertexBuffer(cpu-cycles 41.2%)」 |
| **微架构分类(TMA L1/L2)** | TMA 四类占比 + L2 细分(标推演级) | 「Backend Bound 52%(Memory 35%/Core 17%)(推演级)」 |
| **修复建议** | 针对根因的优化方向 | 「粒子数据 AoS→SoA;glMapBufferRange 替代全量重传;双缓冲 VBO(推演级)」 |
| **验证对照(修复前/后指标)** | before/after 关键指标对比 | 「IPC 0.72→1.85;L1D Miss 38.2%→3.1%;最大帧时长 28ms→7.2ms(推演级)」 |
| **验证状态标注** | 本报告的诚实状态 | 「完成但未验证 / 推演级 · 待真机」 |

### 7.2 报告模板骨架(可直接填)

```markdown
# 性能分析报告(Stage X)

## 现象
<一句话描述用户感知或观测到的问题>

## 时间窗口
- jank 帧 ts: <ns>
- jank 帧 dur: <ms>
- trace 时间范围: <start_ts> ~ <end_ts>

## 责任方(jank_type)
<FrameJankType 四分类:Self / App / SF / Display>

## 阻塞链(blocked_function / waker)
- 主线程阻塞函数: <blocked_function>
- 唤醒者线程: <waker_thread>
- 唤醒者进程: <waker_process>
- 阻塞时长: <ms>

## 热点函数
| 事件 | 函数 | 占比 |
|------|------|------|
| cpu-cycles | <symbol> | <%> |
| cache-misses | <symbol> | <%> |
| stalled-cycles-backend | <symbol> | <%> |

## 微架构分类(TMA L1/L2)
> 状态:<完成但未验证(推演级)/ 待真机> —— 数值若来自 §7 示例须标注「§7 推演」,不得作为自测结果
- Retiring: <%>
- Frontend Bound: <%>
- Backend Bound: <%>(Memory <%> / Core <%>)
- Bad Speculation: <%>
- 公式依据:<A76 示例 · 待 TRM 复核>

## 修复建议
1. <建议 1>
2. <建议 2>
3. <建议 3>

## 验证对照(修复前/后指标)
| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| IPC | <val> | <val> | <%> |
| L1D Miss Rate | <val> | <val> | <%> |
| 最大帧时长 | <val> | <val> | <%> |
| Jank Rate | <val> | <val> | <%> |

## 验证状态标注
- 本报告状态:<完成但未验证 / 推演级 · 待真机 / 已验证>
- 待真机项:<列出 ⬜ 红线项>
```

---

## 八、无设备推演资料清单(附录)

### 8.1 可用推演资料

| 序号 | 资料 | 可得性 | 用途 |
|------|------|--------|------|
| ① | **Perfetto 官方示例 trace**:浏览器访问 `https://ui.perfetto.dev` → `Open trace` → 示例列表 | 公开可得(**执行时定位具体 URL 写入此处**) | Stage0/1 的 UI 认红帧 + SQL 练习 |
| ② | **源文档 §7 粒子 VBO 案例**(`perfetto-simpleprof.md` §7):IPC 0.72→1.85、L1D Miss 38.2%→3.1%、最大帧时长 28ms→7.2ms | 100% 可得(本仓库内文档) | **Stage2/3 无设备主推演材料** |
| ③ | **NDK simpleperf 示例 perf.data**:NDK simpleperf doc 附带示例 | 标「若可得」;不可得则统一改用 §7 推演 | Stage1/2 的 report/火焰图练习 |
| ④ | **M0d 工具链模板库**:10 条 trace_processor SQL(`modules/L0/M0d-工具链.md` §2.7) | 100% 可得 | Stage1/2 SQL 口径回引 |

### 8.2 「需真机验证」红线清单(⬜ 待真机)

> 以下项在无设备下**只能停在推演级或完成但未验证**,真机到位前不得对外称「已验证」。逐条标复现所需条件。

| 序号 | 待验证项 | 复现所需条件 | 风险 |
|------|---------|-------------|------|
| R1 | **原始 PMU 事件编号有效性**(`r03`/`r23`/`r24` 等对目标核是否正确) | root + `perf_event_paranoid <= 1` + 目标核 TRM / PMU guide | A76 编号照搬他核会采错事件,数据无意义 |
| R2 | **TMA L1/L2 实测占比**(`pipeline_width=4`/`penalty_cycles≈11` 系数对目标核适用性) | 目标核 TRM + 真机 stat 多事件采集 | A76 公式仅适用 A76,A78/A710 需另查;ARM TMA 是 stall 近似,非 Intel slots 等价 |
| R3 | **绝对阈值校准**(IPC ≥ 1.5 / L1D Miss < 5% 等的核/频率/制程前提) | 真机 + 目标负载 + 控温/控频 | 经验起点值,因核/频率/制程而异,非硬门槛 |
| R4 | **`--trace-offcpu` / `annotate.py` 实跑** | root + 带符号 so + simpleperf 可执行 | 无设备连「跑通命令」都做不到 |
| R5 | **ARM TMA 公式系数对目标核适用性** | 目标核 TRM | A76 公式照搬 A78 会得错误占比 |
| R6 | **`--trace-offcpu` 报告 on/off-CPU 火焰图实跑读法** | root + 带符号 so + 目标负载 | 推演级口述未经实跑验证 |
| R7 | **ARR 帧率切换 jank 归因的 `jank_type` 实测归属** | Android 16 设备 + ARR 支持 | 机制级口述,真机 `jank_type` 可能与预判不同 |
| R8 | **ProfilingManager system-triggered trace 自动消费闭环** | Android 16 设备 + `addProfilingTriggers` + 监听器回传 | API 常量名/重载在 16 仍可能微调,以 SDK 为准 |
| R9 | **Binder 对端 SQL 修笛卡尔积后在真机 trace 上返回非空** | 真机 trace 含 binder_transaction + 完整 utid | 语法对齐 M0d,真机表结构可能版本差异 |
| R10 | **热降频归因(掉帧 × freq × thermal 四表关联)** | power rail + thermal track + 真机控温 | 推演级,真机可能无 power rail 数据源 |

---

## 九、状态与诚实标注

- **Lv0/Lv1/Lv2 核心 SQL**:已验证(v57.2 真 trace,见 `未验证清单.md` 第八节 V1-V7;实测发现并已修正 C1-C3:`frame_timeline_event` 缺席 → 用 `actual_frame_timeline_slice`;`jank_type` 真实枚举 → `LIKE` 匹配;主线程名非 `'main'` → `tid=pid`)。**第二轮 v57.2 实测 V8-V12(已回填)**:V8 `blocked_function` 全空→降级 `waker_utid`+`io_wait`;V11 `EXTRACT_ARG` 取 binder 对端命中(dest pid 712/1782/714);V12 `android_jank_cuj` 非 CUJ trace 输出空;**C4a(binder arg key `'data size'` 带空格、无 `reply_size`)/ C4b(Binder 对端首选 EXTRACT_ARG,R4 name 匹配降为备用)/ C5(jank 统计直接基于 `actual_frame_timeline_slice`,不强制 CUJ)已回填**(见 §八 C4a/C4b/C5)。
- **机制原理、config 字段、Python API、命令参数**:完成但未验证(解析无误,部分 SQL 经 v57.2 实测跑通;真机首跑可能撞版本/口径差异)。
- **健康阈值表 / TMA L1-L2 占比**:诊断起点 · 待真机校准(经验起点值,非硬门槛)。
- **原始 PMU 事件编号 / TMA 公式系数**:依 A76 示例 · 待真机/TRM 复核(仅适用 A76)。
- **TMA 顶层归因能力(Lv3)**:完成但未验证(只能推演,不能独立归因)。
- **`--trace-offcpu` / `annotate.py` / 原始 r 编号采样**:推演级 · 待真机。
- **公开示例 trace URL**:执行时定位具体 URL 写入附录①,无法定位则 Lv1 SQL 验收降级为「语法对齐 M0d 表名」并标待验证。
- **源文档疑点**(对齐计划 v2 诚实性前置声明):
  1. §6.1.1 A76 事件编号表 → 标「待 TRM 复核」(本路线图练习 3.0c 已落地)
  2. §6.1.2 `penalty_cycles≈11`/`pipeline_width=4` → 标「A76 示例,他核需另查」(练习 3.1 已落地)
  3. §5.1.2 Binder SQL 笛卡尔积 → **v57.2 实测后改:首选 `EXTRACT_ARG('destination process')` 取对端(arg 含对端 pid),R4 name+utid+时间窗 约束降为备用**(练习 2.2 已落地,见 §八 V11/C4b)
  4. 阈值三口径打架 → 以 §8.4 为诊断起点表,§6.1.3 L2 细分阈值单独列并标「TMA L2 近似」(练习 3.2 已落地)

---

*本路线图完 · 基于计划 v2 交付物 B · 无设备环境 · Lv0/Lv1/Lv2 核心 SQL 经 v57.2 真 trace 实测跑通(C1-C3 已回填,见 `未验证清单.md` 第八节)· 真机项入红线清单*