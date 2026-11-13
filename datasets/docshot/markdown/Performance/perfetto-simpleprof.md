# 第 X 章：Perfetto 与 Simpleperf 性能指标深度解析——从抓取到专家级分析

> **读者须知**：本文是 `tools-perfetto-simpleperf-精通.md` 与 `perfetto-simpleperf-练习路线图.md` 的**源参考材料**。以下数处已经 v57.2 真 trace 实测发现与当前版本 drift，请以精通线/路线图为准：
> 1. **§5.1.2 Binder 对端 SQL** 使用 `JOIN slice server_ts ON server_ts.name = client_ts.name` 会在多对端场景产生笛卡尔积。实测修复：首选 `EXTRACT_ARG(arg_set_id,'destination process')` 直接取对端 pid；详见 `tools-perfetto-simpleperf-精通.md` 尾节 疑点③。
> 2. **§5.1.1 掉帧归因 SQL** 使用 `jank_type = 'App'` 精确匹配——v57.2 实测 `jank_type` 列是描述性字符串 (`"App Deadline Missed"` / `"SurfaceFlinger CPU Deadline Missed"` 等)，`='App'` 命中 0 行。正确写法用 `LIKE '%App Deadline Missed%'`。详见 `未验证清单.md` 第八节 C2。
> 3. **§2.1.2 FrameTimeline 表** 的 jank_type 含义写 `App / SurfaceFlinger / None`——v57.2 实测真实枚举含 `Buffer Stuffing` / `Prediction Error` / `Unknown Jank` 等。详见精通线 术语节 真实枚举对照表。
> 4. **§6.1.1 A76 事件编号表**的 `r28`（MEM_ACCESS_CHECKED）与 ARMv8 标准 0x28=L2I_CACHE_REFILL 冲突，可能为 A76 实现特有或编号错误。所有 r 编号仅适用 Cortex-A76，他核需查对应 TRM。
> 5. **§4.2.2 线程状态查询**用 `WHERE name = 'main'` 定位主线程——Android App 主线程名是 task comm 15 字符截断的进程名，`name='main'` 命中 0 行。正确做法用 `tid = pid`（主线程 tid == 进程 pid）。
> 6. **§6.2.1 自定义 Metric** 依赖 `android_jank_cuj` JOIN——v57.2 实测非 CUJ trace 上该内置 metric 输出空 `{}`。精通线已改为直接基于 `actual_frame_timeline_slice` 统计，CUJ 分组降为可选。
>
> 本文其余内容（配置模板、命令速查、§7 粒子 VBO 案例数据）仍然有效；与以上 6 项相关的章节，请以精通线/路线图/未验证清单 的已修正版本为准。

---

## 目录

1. [工具定位与协同关系](#1-工具定位与协同关系)
2. [Perfetto：系统级追踪指标体系](#2-perfetto系统级追踪指标体系)
3. [Simpleperf：CPU 微架构级剖析指标体系](#3-simpleperfcpu-微架构级剖析指标体系)
4. [中级：标准抓取与基础指标解读](#4-中级标准抓取与基础指标解读)
5. [高级：多维指标关联与深度分析](#5-高级多维指标关联与深度分析)
6. [专家级：微架构 Top-Down 与自动化归因](#6-专家级微架构-top-down-与自动化归因)
7. [实战案例：从掉帧到根因的完整链路](#7-实战案例从掉帧到根因的完整链路)
8. [附录：指标速查表](#8-附录指标速查表)

---

## 1. 工具定位与协同关系

### 1.1 一句话区分

| 维度 | Perfetto | Simpleperf |
|------|----------|------------|
| **视角** | 系统全局时间线（"谁在什么时候做了什么"） | CPU 微架构采样（"CPU 的每个周期花在了哪里"） |
| **数据源** | ftrace / atrace / FrameTimeline / Binder / GPU / Memory | PMU 硬件计数器 / 软件事件 / 内核 tracepoint |
| **粒度** | 事件级（slice 起止时间戳，ns 精度） | 指令级（采样命中 IP 地址） |
| **典型问题** | 掉帧归因、线程调度、Binder 阻塞、锁竞争 | 热点函数、Cache Miss、分支预测失败、IPC 低下 |
| **输出** | `.perfetto-trace`（protobuf） | `perf.data`（ELF 格式） |

### 1.2 协同模型

```
┌─────────────────────────────────────────────────────────┐
│                    用户感知：掉帧 / 卡顿                   │
└────────────────────────┬────────────────────────────────┘
                         │
          ┌──────────────▼──────────────┐
          │   Perfetto（宏观定位）        │
          │   "哪一帧慢了？哪个线程阻塞？" │
          └──────────────┬──────────────┘
                         │ 锁定线程 + 时间窗口
          ┌──────────────▼──────────────┐
          │   Simpleperf（微观剖析）      │
          │   "该线程 CPU 时间花在哪？    │
          │    Cache/TLB/Branch 瓶颈？"  │
          └─────────────────────────────┘
```

> **核心原则**：Perfetto 回答 **"Where & When"**，Simpleperf 回答 **"Why & How much"**。

---

## 2. Perfetto：系统级追踪指标体系

### 2.1 数据源与对应指标

Perfetto 通过 `traced` + `traced_probes` 守护进程采集多路数据源，每路数据源对应一组指标：

#### 2.1.1 Ftrace / Atrace 层

| 指标类别 | 具体指标 | 含义 |
|---------|---------|------|
| **CPU 调度** | `sched_switch`（prev_state, next_comm） | 线程在 Running/Runnable/Sleeping/Disk Sleep 之间切换 |
| **CPU 频率** | `cpu_frequency`（frequency, cpu_id） | 各核实时频率（kHz） |
| **CPU 空闲** | `cpu_idle`（state） | C-state 深度（C0=活跃, C1+=休眠） |
| **线程唤醒** | `sched_waking` / `sched_wakeup` | 唤醒链（谁唤醒了谁） |
| **IRQ** | `irq_handler_entry/exit` | 中断处理耗时 |

#### 2.1.2 FrameTimeline（Android 12+）

| 指标 | 含义 | 健康阈值 |
|------|------|---------|
| `actual_frame_timeline_slice.dur` | 一帧实际耗时 | ≤ 16.6ms (60Hz) / ≤ 8.3ms (120Hz) |
| `expected_frame_timeline_slice.dur` | 系统预期帧时长 | 由 Vsync 周期决定 |
| `jank_type` | 卡顿归因类型 | `App` / `SurfaceFlinger` / `None` |
| `on_time_finish` | 帧是否按时提交 | `true` = 未掉帧 |
| `gpu_composition` | 是否走 GPU 合成 | 过度 GPU 合成 → 功耗上升 |

#### 2.1.3 Binder 驱动

| 指标 | 含义 |
|------|------|
| `binder_transaction` slice 时长 | 一次跨进程调用耗时 |
| `binder_lock` / `binder_locked` | Binder 锁竞争等待 |
| `binder_reply` | 同步回复等待时间 |

#### 2.1.4 Memory

| 指标 | 含义 |
|------|------|
| `mem.rss` / `mem.pss` | 进程物理内存占用 |
| `mem.swap` | Swap 换入换出量 |
| `ion_heap` / `dmabuf` | GPU/相机缓冲区占用 |
| `page_fault` (major/minor) | 缺页中断次数 |

#### 2.1.5 GPU / Display

| 指标 | 含义 |
|------|------|
| `gpu_frequency` | GPU 核心频率 |
| `gpu_mem_total` | GPU 显存总占用 |
| `display_frame` | 显示控制器提交帧时间戳 |

### 2.2 Trace Processor 内置 Metric（SQL 可查）

Perfetto 提供预置 metric，可通过 `trace_processor --run-metrics` 直接输出：

```bash
trace_processor --run-metrics android_startup,android_jank,android_mem \
    -o metrics_output.pb my_trace.perfetto-trace
```

| Metric 名称 | 输出内容 |
|-------------|---------|
| `android_jank_cuj` | 按 CUJ（Critical User Journey）分组的掉帧统计 |
| `android_frame_timeline` | 每帧的 expected/actual 时长、jank 归因 |
| `android_startup` | 应用启动各阶段耗时（bindApplication, activityStart, firstFrame） |
| `android_mem` | 按进程/时间聚合的 RSS/PSS/Swap |
| `android_binder` | Binder 调用 P50/P90/P99 延迟 |
| `android_cpu` | 按核/按线程的 CPU 占用率 |

---

## 3. Simpleperf：CPU 微架构级剖析指标体系

### 3.1 事件分类

Simpleperf 基于 Linux `perf_event` 子系统，支持以下事件类别：

#### 3.1.1 硬件事件（Hardware Events）

```bash
adb shell simpleperf list
```

| 事件名 | 含义 | 典型用途 |
|--------|------|---------|
| `cpu-cycles` | CPU 时钟周期数 | 衡量绝对耗时 |
| `instructions` | 退休指令数 | 计算 IPC |
| `cache-references` | 最后一级缓存（LLC）访问 | 内存压力 |
| `cache-misses` | LLC 未命中 | 内存瓶颈定位 |
| `branch-instructions` | 分支指令数 | 控制流复杂度 |
| `branch-misses` | 分支预测失败 | 流水线冲刷 |
| `bus-cycles` | 总线周期 | 外部访问频率 |
| `stalled-cycles-frontend` | 前端停顿周期 | 取指/解码瓶颈 |
| `stalled-cycles-backend` | 后端停顿周期 | 执行/访存瓶颈 |

#### 3.1.2 硬件缓存事件（HW Cache Events）

格式：`<cache>-<operation>-<result>`

| 事件 | 含义 |
|------|------|
| `L1-dcache-loads` / `L1-dcache-load-misses` | L1 数据缓存读命中率 |
| `L1-icache-load-misses` | L1 指令缓存未命中（代码 footprint 过大） |
| `LLC-loads` / `LLC-load-misses` | 最后一级缓存命中率 |
| `dTLB-loads` / `dTLB-load-misses` | 数据 TLB 命中率（大页优化依据） |
| `iTLB-load-misses` | 指令 TLB 未命中 |
| `branch-loads` / `branch-load-misses` | 分支目标缓冲区（BTB）命中 |

#### 3.1.3 软件事件（Software Events）

| 事件 | 含义 |
|------|------|
| `cpu-clock` | 高精度 CPU 时钟（无 PMU 时替代） |
| `task-clock` | 线程实际占用 CPU 时间 |
| `page-faults` / `major-faults` | 缺页中断 |
| `context-switches` | 上下文切换次数 |
| `cpu-migrations` | CPU 迁移次数 |
| `alignment-faults` | 非对齐访问 |

#### 3.1.4 原始 PMU 事件（Raw Events）——专家级

ARM Cortex-A76/A78/X1 等核心支持数百个微架构事件，`simpleperf list` 仅列出约 20 个。通过原始编号可解锁：

```bash
# 格式：r<event_number>
# 例：Cortex-A76 的 L1D_CACHE_REFILL = 0x03
adb shell simpleperf stat -e r03 -p <pid> --duration 5
```

| 原始事件（ARMv8 示例） | 编号 | 含义 |
|----------------------|------|------|
| `L1D_CACHE_REFILL` | 0x03 | L1D 缓存重填 |
| `L1D_CACHE` | 0x04 | L1D 缓存访问 |
| `L1D_CACHE_WB` | 0x15 | L1D 写回 |
| `L2D_CACHE_REFILL` | 0x17 | L2 缓存重填 |
| `L1D_TLB_REFILL` | 0x05 | L1 DTLB 重填 |
| `BR_MIS_PRED_RETIRED` | 0x22 | 退休的预测失败分支 |
| `STALL_FRONTEND` | 0x23 | 前端停顿周期 |
| `STALL_BACKEND` | 0x24 | 后端停顿周期 |
| `MEM_ACCESS_CHECKED` | 0x28 | 已检查的内存访问 |

### 3.2 关键衍生指标

| 衍生指标 | 公式 | 健康范围 | 异常含义 |
|---------|------|---------|---------|
| **IPC** (Instructions Per Cycle) | `instructions / cpu-cycles` | ≥ 1.5 (ARM big core) | < 1.0 → 严重停顿 |
| **L1D Miss Rate** | `L1-dcache-load-misses / L1-dcache-loads` | < 5% | > 10% → 数据局部性差 |
| **LLC Miss Rate** | `LLC-load-misses / LLC-loads` | < 20% | > 40% → 内存带宽瓶颈 |
| **Branch Miss Rate** | `branch-misses / branch-instructions` | < 3% | > 8% → 控制流不可预测 |
| **DTLB Miss Rate** | `dTLB-load-misses / dTLB-loads` | < 1% | > 5% → 需大页/内存池化 |
| **Frontend Bound %** | `stalled-cycles-frontend / cpu-cycles` | < 15% | > 30% → I-Cache/解码瓶颈 |
| **Backend Bound %** | `stalled-cycles-backend / cpu-cycles` | < 30% | > 50% → 执行单元/访存瓶颈 |

---

## 4. 中级：标准抓取与基础指标解读

### 4.1 Perfetto 标准抓取流程

#### 4.1.1 配置文件方式（推荐）

创建 `trace_config.pbtx`：

```protobuf
buffers {
  size_kb: 65536
  fill_policy: RING_BUFFER
}
data_sources {
  config {
    name: "linux.ftrace"
    ftrace_config {
      ftrace_events: "sched/sched_switch"
      ftrace_events: "sched/sched_waking"
      ftrace_events: "power/cpu_frequency"
      ftrace_events: "power/cpu_idle"
      ftrace_events: "binder/binder_transaction"
      ftrace_events: "binder/binder_transaction_received"
      ftrace_events: "binder/binder_lock"
      ftrace_events: "binder/binder_locked"
      ftrace_events: "binder/binder_unlock"
      atrace_categories: "view"
      atrace_categories: "gfx"
      atrace_categories: "input"
      atrace_categories: "wm"
      atrace_categories: "am"
      atrace_apps: "com.example.targetapp"
    }
  }
}
data_sources {
  config {
    name: "android.surfaceflinger.frametimeline"
  }
}
data_sources {
  config {
    name: "linux.process_stats"
    process_stats_config {
      scan_all_processes_on_start: true
      proc_stats_poll_ms: 1000
    }
  }
}
data_sources {
  config {
    name: "android.memory"
    android_memory_config {
      poll_ms: 1000
      counters: RSS
      counters: PSS
      counters: SWAP
    }
  }
}
duration_ms: 10000
```

执行抓取：

```bash
# 推送配置
adb push trace_config.pbtx /data/local/tmp/

# 开始抓取（10 秒）
adb shell perfetto \
  -c /data/local/tmp/trace_config.pbtx \
  -o /data/misc/perfetto-traces/trace.perfetto-trace

# 拉取
adb pull /data/misc/perfetto-traces/trace.perfetto-trace .
```

#### 4.1.2 快捷命令方式

```bash
# 抓取 10 秒，包含调度 + 频率 + atrace
adb shell perfetto -o /data/misc/perfetto-traces/quick.perfetto-trace \
  -t 10s \
  sched freq idle am wm gfx view binder_driver hal dalvik camera input res \
  -a com.example.targetapp
```

#### 4.1.3 在 UI 中打开

- 浏览器访问 `https://ui.perfetto.dev`
- 拖入 `.perfetto-trace` 文件
- 或使用本地 trace_processor：

```bash
trace_processor --httpd --http-port 9001 trace.perfetto-trace
# 浏览器打开 https://ui.perfetto.dev/?rpc_port=9001
```

### 4.2 Perfetto 基础指标解读（中级）

#### 4.2.1 帧渲染指标

在 UI 中展开目标进程 → `Expected Frames` / `Actual Frames` 轨道：

- **绿色 slice**：帧按时完成
- **红色 slice**：Jank 帧（超时）
- **黄色 slice**：SF（SurfaceFlinger）合成延迟

**SQL 查询掉帧统计**：

```sql
-- 查询所有 Jank 帧
SELECT
  ts,
  dur / 1e6 AS dur_ms,
  jank_type,
  on_time_finish
FROM actual_frame_timeline_slice
WHERE jank_type != 'None'
ORDER BY dur DESC
LIMIT 20;
```

#### 4.2.2 线程状态指标

```sql
-- 查询主线程在指定时间窗口内的状态分布
SELECT
  state,
  SUM(dur) / 1e6 AS total_ms,
  COUNT(*) AS count
FROM thread_state
WHERE utid = (
  SELECT utid FROM thread
  WHERE name = 'main'
  AND upid = (SELECT upid FROM process WHERE name = 'com.example.targetapp')
)
AND ts BETWEEN 1000000000 AND 2000000000  -- 1s ~ 2s
GROUP BY state
ORDER BY total_ms DESC;
```

输出示例：

| state | total_ms | count | 解读 |
|-------|----------|-------|------|
| Running | 45.2 | 312 | 实际占用 CPU |
| Runnable | 12.8 | 89 | 等待调度（CPU 竞争） |
| Sleeping | 30.1 | 156 | 等待 I/O / 锁 / Binder |
| D (Disk Sleep) | 8.5 | 12 | 不可中断 I/O 等待 |

> **中级判断标准**：`Runnable` 占比 > 20% → CPU 资源不足；`D` 状态频繁出现 → I/O 瓶颈。

### 4.3 Simpleperf 标准抓取流程

#### 4.3.1 基础 record

```bash
# 获取目标进程 PID
adb shell pidof com.example.targetapp
# 假设输出 12345

# 抓取 10 秒 CPU 采样，带调用栈
adb shell simpleperf record \
  -p 12345 \
  -e cpu-cycles \
  -f 4000 \
  --call-graph dwarf \
  --duration 10 \
  -o /data/local/tmp/perf.data

# 拉取
adb pull /data/local/tmp/perf.data .
```

参数说明：

| 参数 | 含义 |
|------|------|
| `-e cpu-cycles` | 采样事件（每 N 个 cycle 触发一次采样） |
| `-f 4000` | 采样频率 4000 Hz（每秒 4000 个样本） |
| `--call-graph dwarf` | 使用 DWARF 信息回溯调用栈（最完整） |
| `--call-graph fp` | 使用帧指针回溯（开销更低，需 `-fno-omit-frame-pointer` 编译） |
| `--duration 10` | 持续 10 秒 |

#### 4.3.2 多事件同时采集

```bash
adb shell simpleperf record \
  -p 12345 \
  -e cpu-cycles,instructions,cache-misses,branch-misses \
  -f 4000 \
  --call-graph dwarf \
  --duration 10 \
  -o /data/local/tmp/perf_multi.data
```

#### 4.3.3 生成报告

```bash
# 文本报告
simpleperf report -i perf.data --sort dso,symbol

# HTML 交互式报告（推荐）
python3 $NDK/simpleperf/report_html.py -i perf.data -o report.html

# 火焰图数据
python3 $NDK/simpleperf/report_sample.py -i perf.data --add_source_code \
  --source_dirs ./app/src/main/cpp > flamegraph.txt
```

### 4.4 Simpleperf 基础指标解读（中级）

#### 4.4.1 stat 命令——快速概览

```bash
adb shell simpleperf stat -p 12345 --duration 5
```

输出示例：

```
Performance counter statistics:
  1,234,567,890  cpu-cycles           # 246.9 MHz
    987,654,321  instructions         # 0.80 IPC
     12,345,678  cache-misses         # 15.2% of cache-references
      3,456,789  branch-misses        # 4.1% of branch-instructions
```

**中级解读**：
- IPC = 0.80 → 偏低，CPU 流水线利用率不足
- Cache Miss Rate = 15.2% → 存在内存访问瓶颈
- Branch Miss Rate = 4.1% → 略高，有优化空间

#### 4.4.2 火焰图解读

在 `report.html` 中：
- **X 轴宽度** = 函数占用 CPU 时间比例
- **Y 轴深度** = 调用栈深度
- **颜色** = 随机分配（无特殊含义）

**关注点**：
1. 最宽的"平顶"（plateau）= 真正的热点
2. 系统库（`libc.so`, `libart.so`）占比过高 → 可能存在不必要的系统调用
3. `__memcpy` / `__memset` 占比高 → 数据拷贝瓶颈

---

## 5. 高级：多维指标关联与深度分析

### 5.1 Perfetto 高级 SQL 分析

#### 5.1.1 掉帧归因链（Jank Attribution Chain）

```sql
-- 完整掉帧归因：从帧 → 线程状态 → 唤醒者
WITH jank_frames AS (
  SELECT
    ts,
    dur,
    jank_type,
    upid
  FROM actual_frame_timeline_slice
  WHERE jank_type = 'App'
    AND dur > 16600000  -- > 16.6ms
)
SELECT
  jf.ts,
  jf.dur / 1e6 AS frame_dur_ms,
  ts.state,
  ts.dur / 1e6 AS state_dur_ms,
  waker.name AS waker_thread,
  waker_proc.name AS waker_process
FROM jank_frames jf
JOIN thread_state ts ON ts.upid = jf.upid
  AND ts.ts >= jf.ts
  AND ts.ts < jf.ts + jf.dur
LEFT JOIN thread waker ON waker.utid = ts.waker_utid
LEFT JOIN process waker_proc ON waker_proc.upid = waker.upid
WHERE ts.state IN ('S', 'D')  -- Sleeping or Disk Sleep
  AND ts.dur > 5000000        -- 阻塞 > 5ms
ORDER BY ts.dur DESC;
```

#### 5.1.2 Binder 调用链追踪

```sql
-- 找出耗时最长的 Binder 调用及其对端
SELECT
  client_ts.ts / 1e6 AS start_ms,
  client_ts.dur / 1e6 AS binder_dur_ms,
  client_thread.name AS client_thread,
  server_thread.name AS server_thread,
  server_proc.name AS server_process,
  client_ts.name AS transaction_name
FROM slice client_ts
JOIN thread client_thread ON client_thread.utid = client_ts.track_id
JOIN slice server_ts ON server_ts.name = client_ts.name
  AND server_ts.ts >= client_ts.ts
  AND server_ts.ts < client_ts.ts + client_ts.dur
JOIN thread server_thread ON server_thread.utid = server_ts.track_id
JOIN process server_proc ON server_proc.upid = server_thread.upid
WHERE client_ts.name LIKE 'binder transaction%'
  AND client_ts.dur > 10000000  -- > 10ms
ORDER BY client_ts.dur DESC
LIMIT 10;
```

#### 5.1.3 CPU 频率与调度联合分析

```sql
-- 分析大核频率是否被压制（thermal throttling 检测）
SELECT
  cpu,
  MIN(value) / 1000 AS min_freq_mhz,
  MAX(value) / 1000 AS max_freq_mhz,
  AVG(value) / 1000 AS avg_freq_mhz,
  COUNT(*) AS samples
FROM counter
JOIN cpu_counter_track ON counter.track_id = cpu_counter_track.id
WHERE cpu_counter_track.name = 'cpufreq'
GROUP BY cpu;
```

> **高级判断**：若大核（cpu6/cpu7）`avg_freq_mhz` 远低于 `max_freq_mhz`（如 < 60%），且伴随掉帧 → 热降频或功耗策略限制。

#### 5.1.4 启动耗时分解

```sql
-- 应用启动各阶段耗时
SELECT
  name,
  dur / 1e6 AS dur_ms
FROM slice
WHERE track_id IN (
  SELECT id FROM thread_track
  WHERE utid = (
    SELECT utid FROM thread
    WHERE name = 'main'
    AND upid = (SELECT upid FROM process WHERE name = 'com.example.targetapp')
  )
)
AND ts >= (SELECT MIN(ts) FROM slice WHERE name = 'bindApplication')
AND ts <= (SELECT MAX(ts + dur) FROM slice WHERE name = 'reportFullyDrawn')
AND dur > 1000000  -- > 1ms
ORDER BY ts;
```

### 5.2 Simpleperf 高级分析

#### 5.2.1 按线程/DSO 过滤的热点分析

```bash
# 仅分析 RenderThread 的热点
simpleperf report -i perf.data \
  --comms RenderThread \
  --sort dso,symbol \
  --percent-limit 1.0

# 仅分析特定 so 库
simpleperf report -i perf.data \
  --dsos libgame_engine.so \
  --sort symbol \
  --print-event-count
```

#### 5.2.2 多事件关联——定位 Cache Miss 热点

```bash
# 抓取 L1D cache miss 事件
adb shell simpleperf record \
  -p 12345 \
  -e L1-dcache-load-misses \
  -f 4000 \
  --call-graph dwarf \
  --duration 10 \
  -o /data/local/tmp/perf_l1miss.data

# 生成报告：哪些函数产生最多 cache miss
simpleperf report -i perf_l1miss.data --sort dso,symbol --percent-limit 0.5
```

输出示例：

```
Overhead  Symbol
  32.5%   libgame.so  PhysicsEngine::updateParticles
  18.2%   libgame.so  Renderer::drawMesh
  12.7%   libc.so     __memcpy_aarch64
   8.1%   libgame.so  SpatialHash::query
```

> **高级解读**：`PhysicsEngine::updateParticles` 占 32.5% 的 L1D Miss → 粒子数据内存布局不连续（AoS vs SoA 问题）。

#### 5.2.3 源码级注解

```bash
# 需要带调试符号的 so（-g 编译）
python3 $NDK/simpleperf/report_html.py \
  -i perf.data \
  -o report.html \
  --add_source_code \
  --source_dirs /path/to/project/app/src/main/cpp
```

在 HTML 报告中可直接看到每行源码的采样命中次数，精确定位到具体代码行。

#### 5.2.4 对比分析（Diff Profiling）

```bash
# 优化前
adb shell simpleperf record -p 12345 -e cpu-cycles -f 4000 \
  --call-graph dwarf --duration 10 -o /data/local/tmp/before.data

# 优化后
adb shell simpleperf record -p 12345 -e cpu-cycles -f 4000 \
  --call-graph dwarf --duration 10 -o /data/local/tmp/after.data

# 生成对比报告
python3 $NDK/simpleperf/report_html.py \
  -i before.data after.data \
  -o diff_report.html
```

在 diff 报告中，红色表示占比增加，绿色表示占比减少。

### 5.3 Perfetto + Simpleperf 联合分析（高级工作流）

**场景**：Perfetto 发现某帧 Jank，主线程在 `Choreographer#doFrame` 中 Sleeping 8ms。

**Step 1**：Perfetto 定位时间窗口

```sql
-- 找到 Jank 帧的精确时间范围
SELECT ts, ts + dur AS end_ts, dur / 1e6 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'App' AND dur > 16600000
ORDER BY dur DESC LIMIT 1;
-- 输出: ts=5234000000, end_ts=5258000000, dur_ms=24.0
```

**Step 2**：确认阻塞原因

```sql
-- 该时间窗口内主线程在等什么？
SELECT state, dur/1e6 AS ms, io_wait, blocked_function
FROM thread_state
WHERE utid = <main_utid>
  AND ts >= 5234000000 AND ts < 5258000000
  AND state = 'S'
ORDER BY dur DESC;
-- 输出: state=S, ms=8.2, blocked_function=futex_wait_queue_me
```

**Step 3**：Simpleperf 深挖 CPU 热点

```bash
# 针对同一进程，抓取同一时间段的 CPU 采样
adb shell simpleperf record -p 12345 \
  -e cpu-cycles,stalled-cycles-backend \
  -f 8000 --call-graph dwarf --duration 5 \
  -o /data/local/tmp/deep.data
```

**Step 4**：关联结论

> 主线程 8.2ms 在 `futex_wait` → 等待 RenderThread 释放锁 → RenderThread 的 `stalled-cycles-backend` 占 62% → 进一步发现是 `glDrawElements` 中 vertex buffer 的 LLC Miss Rate 达 45% → **根因：顶点数据未对齐到 cache line，且每帧重新上传 VBO**。

---

## 6. 专家级：微架构 Top-Down 与自动化归因

### 6.1 ARM Top-Down Microarchitecture Analysis (TMA)

Intel 的 TMA 方法论已被移植到 ARM 平台。核心思想：将 CPU 流水线利用率分解为四个一级类别。

```
                    Total Slots (cpu-cycles × pipeline_width)
                    ┌─────────────────────────────────────┐
                    │                                     │
            ┌───────▼───────┐                   ┌────────▼────────┐
            │   Retiring    │                   │   Bad Speculation│
            │ (有效工作)     │                   │ (分支预测错误)    │
            └───────────────┘                   └─────────────────┘
                    │                                     │
            ┌───────▼───────┐                   ┌────────▼────────┐
            │ Frontend Bound│                   │  Backend Bound   │
            │ (取指/解码)    │                   │ (执行/访存)      │
            └───────────────┘                   └─────────────────┘
```

#### 6.1.1 使用 Simpleperf 采集 TMA 所需事件

```bash
# ARM Cortex-A76 示例（需 root 或 perf_event_paranoid <= 1）
adb shell su 0 simpleperf stat -p 12345 --duration 10 \
  -e cpu-cycles \
  -e instructions \
  -e r23 \
  -e r24 \
  -e r22 \
  -e r10
```

| 事件 | 原始编号 (A76) | TMA 分类 |
|------|---------------|---------|
| `STALL_FRONTEND` | r23 (0x23) | Frontend Bound |
| `STALL_BACKEND` | r24 (0x24) | Backend Bound |
| `BR_MIS_PRED_RETIRED` | r22 (0x22) | Bad Speculation |
| `CPU_CYCLES` | r11 (0x11) | 总周期 |
| `INST_RETIRED` | r08 (0x08) | Retiring |
| `OP_RETIRED` | r10 (0x10) | 微操作退休 |

#### 6.1.2 TMA 计算公式（ARM 适配）

```python
# 假设 pipeline_width = 4 (Cortex-A76 为 4-wide decode)
pipeline_width = 4
total_slots = cpu_cycles * pipeline_width

# Level 1
retiring = inst_retired / total_slots
bad_speculation = (br_mis_pred_retired * penalty_cycles) / total_slots  # penalty ≈ 11 cycles on A76
frontend_bound = stall_frontend / cpu_cycles
backend_bound = stall_backend / cpu_cycles

# Level 2: Backend Bound 细分
# 需要额外事件：r28 (MEM_ACCESS_CHECKED), r29 (MEM_ACCESS_CHECKED_RD)
backend_memory = (mem_stall_cycles) / cpu_cycles  # 需 r24 + memory access events
backend_core = backend_bound - backend_memory
```

#### 6.1.3 解读标准

| 指标 | 健康 | 警告 | 严重 |
|------|------|------|------|
| Retiring | > 60% | 40-60% | < 40% |
| Frontend Bound | < 10% | 10-20% | > 20% |
| Backend Bound (Memory) | < 20% | 20-35% | > 35% |
| Backend Bound (Core) | < 15% | 15-25% | > 25% |
| Bad Speculation | < 5% | 5-10% | > 10% |

### 6.2 专家级：Perfetto 自定义 Metric 开发

#### 6.2.1 编写自定义 SQL Metric

创建 `my_jank_metric.sql`：

```sql
-- 自定义 Metric：按 Activity 分组的 Jank 率
SELECT
  RUN_METRIC('android/android_jank_cuj.sql');

CREATE PERFETTO TABLE my_jank_summary AS
SELECT
  cuj.cuj_name,
  COUNT(*) AS total_frames,
  SUM(CASE WHEN jank_type != 'None' THEN 1 ELSE 0 END) AS jank_frames,
  ROUND(100.0 * SUM(CASE WHEN jank_type != 'None' THEN 1 ELSE 0 END) / COUNT(*), 2) AS jank_rate_pct,
  ROUND(AVG(dur) / 1e6, 2) AS avg_frame_ms,
  ROUND(MAX(dur) / 1e6, 2) AS max_frame_ms,
  -- P95 帧时长
  ROUND(
    (SELECT dur FROM actual_frame_timeline_slice
     WHERE upid = cuj.upid
     ORDER BY dur
     LIMIT 1 OFFSET (SELECT COUNT(*) * 95 / 100 FROM actual_frame_timeline_slice WHERE upid = cuj.upid)
    ) / 1e6, 2
  ) AS p95_frame_ms
FROM actual_frame_timeline_slice frame
JOIN android_jank_cuj cuj ON frame.upid = cuj.upid
  AND frame.ts >= cuj.ts
  AND frame.ts < cuj.ts + cuj.dur
GROUP BY cuj.cuj_name;
```

执行：

```bash
trace_processor --run-metrics my_jank_metric.sql \
  --metrics-output json \
  -o jank_report.json \
  trace.perfetto-trace
```

#### 6.2.2 Python 自动化分析管线

```python
from perfetto.trace_processor import TraceProcessor
import json

def analyze_trace(trace_path):
    tp = TraceProcessor(trace=trace_path)

    # 1. 掉帧检测
    jank_df = tp.query("""
        SELECT ts, dur/1e6 as dur_ms, jank_type
        FROM actual_frame_timeline_slice
        WHERE jank_type != 'None'
        ORDER BY dur DESC
    """).as_pandas_dataframe()

    # 2. 主线程阻塞分析
    blocking_df = tp.query("""
        SELECT
          ts.state,
          SUM(ts.dur)/1e6 as total_ms,
          ts.blocked_function
        FROM thread_state ts
        JOIN thread t ON t.utid = ts.utid
        WHERE t.name = 'main'
          AND ts.state IN ('S', 'D')
          AND ts.dur > 3000000
        GROUP BY ts.blocked_function
        ORDER BY total_ms DESC
        LIMIT 5
    """).as_pandas_dataframe()

    # 3. Binder 延迟分布
    binder_df = tp.query("""
        SELECT
          CASE
            WHEN dur < 1000000 THEN '<1ms'
            WHEN dur < 5000000 THEN '1-5ms'
            WHEN dur < 10000000 THEN '5-10ms'
            ELSE '>10ms'
          END AS latency_bucket,
          COUNT(*) AS count
        FROM slice
        WHERE name LIKE 'binder%'
        GROUP BY latency_bucket
    """).as_pandas_dataframe()

    # 4. 生成报告
    report = {
        'jank_frames': len(jank_df),
        'worst_jank_ms': jank_df['dur_ms'].max() if len(jank_df) > 0 else 0,
        'top_blocking_functions': blocking_df.to_dict('records'),
        'binder_latency_distribution': binder_df.to_dict('records')
    }

    tp.close()
    return report

if __name__ == '__main__':
    result = analyze_trace('trace.perfetto-trace')
    print(json.dumps(result, indent=2))
```

### 6.3 专家级：Simpleperf 原始事件 + 自动化脚本

#### 6.3.1 批量 PMU 事件采集脚本

```bash
#!/bin/bash
# expert_pmu_sweep.sh - 扫描所有关键 PMU 事件
PID=$1
DURATION=${2:-5}
OUTPUT_DIR="pmu_sweep_$(date +%s)"
mkdir -p $OUTPUT_DIR

# ARM Cortex-A76 关键事件列表
declare -A EVENTS=(
  ["cycles"]="cpu-cycles"
  ["instructions"]="instructions"
  ["l1d_refill"]="r03"
  ["l1d_access"]="r04"
  ["l2d_refill"]="r17"
  ["l2d_access"]="r18"
  ["dtlb_refill"]="r05"
  ["dtlb_access"]="r06"
  ["br_mis_pred"]="r22"
  ["br_retired"]="r21"
  ["stall_frontend"]="r23"
  ["stall_backend"]="r24"
  ["mem_access"]="r28"
)

for name in "${!EVENTS[@]}"; do
  echo "Collecting: $name (${EVENTS[$name]})"
  adb shell simpleperf stat -p $PID --duration $DURATION \
    -e "${EVENTS[$name]}" \
    > "$OUTPUT_DIR/${name}.txt" 2>&1
done

# 汇总计算
echo "=== TMA Summary ==="
CYCLES=$(grep -oP '\d+(?=.*cpu-cycles)' $OUTPUT_DIR/cycles.txt | tr -d ',')
INSTR=$(grep -oP '\d+(?=.*instructions)' $OUTPUT_DIR/instructions.txt | tr -d ',')
STALL_FE=$(grep -oP '\d+' $OUTPUT_DIR/stall_frontend.txt | head -1 | tr -d ',')
STALL_BE=$(grep -oP '\d+' $OUTPUT_DIR/stall_backend.txt | head -1 | tr -d ',')
BR_MIS=$(grep -oP '\d+' $OUTPUT_DIR/br_mis_pred.txt | head -1 | tr -d ',')
BR_RET=$(grep -oP '\d+' $OUTPUT_DIR/br_retired.txt | head -1 | tr -d ',')

echo "IPC: $(echo "scale=3; $INSTR / $CYCLES" | bc)"
echo "Frontend Bound: $(echo "scale=1; $STALL_FE * 100 / $CYCLES" | bc)%"
echo "Backend Bound: $(echo "scale=1; $STALL_BE * 100 / $CYCLES" | bc)%"
echo "Branch Miss Rate: $(echo "scale=2; $BR_MIS * 100 / $BR_RET" | bc)%"
```

#### 6.3.2 带时间戳的采样 + Perfetto 时间对齐

```bash
# Simpleperf 支持 --trace-offcpu 记录 off-CPU 时间
adb shell simpleperf record -p 12345 \
  -e cpu-cycles \
  -f 4000 \
  --call-graph dwarf \
  --trace-offcpu \
  --duration 10 \
  -o /data/local/tmp/perf_with_offcpu.data
```

`--trace-offcpu` 会在 perf.data 中嵌入 `sched_switch` 事件，使得 Simpleperf 报告能区分 **on-CPU 热点** 和 **off-CPU 等待**，与 Perfetto 的线程状态形成交叉验证。

### 6.4 专家级：系统级功耗-性能联合分析

```protobuf
# Perfetto 配置：同时采集功耗相关数据
data_sources {
  config {
    name: "linux.ftrace"
    ftrace_config {
      ftrace_events: "power/cpu_frequency"
      ftrace_events: "power/cpu_idle"
      ftrace_events: "power/gpu_frequency"
      ftrace_events: "regulator/regulator_set_voltage"
      ftrace_events: "regulator/regulator_set_voltage_complete"
      ftrace_events: "clk/clk_set_rate"
      ftrace_events: "thermal/thermal_temperature"
    }
  }
}
data_sources {
  config {
    name: "android.power"
    android_power_config {
      battery_poll_ms: 1000
      collect_power_rails: true
      battery_counters: BATTERY_COUNTER_CAPACITY_PERCENT
      battery_counters: BATTERY_COUNTER_CHARGE
      battery_counters: BATTERY_COUNTER_CURRENT
    }
  }
}
```

**专家分析 SQL**：

```sql
-- 关联掉帧时刻的 CPU 频率与温度
WITH jank_times AS (
  SELECT ts, dur FROM actual_frame_timeline_slice
  WHERE jank_type != 'None' AND dur > 16600000
)
SELECT
  jt.ts / 1e9 AS jank_time_s,
  jt.dur / 1e6 AS jank_ms,
  freq.value / 1000 AS cpu_freq_mhz,
  temp.value / 1000 AS temp_celsius
FROM jank_times jt
JOIN counter freq ON freq.ts >= jt.ts AND freq.ts < jt.ts + jt.dur
JOIN cpu_counter_track ft ON freq.track_id = ft.id AND ft.name = 'cpufreq' AND ft.cpu = 7
JOIN counter temp ON temp.ts >= jt.ts AND temp.ts < jt.ts + jt.dur
JOIN track tt ON temp.track_id = tt.id AND tt.name LIKE '%thermal%zone0%'
ORDER BY jt.ts;
```

> **专家判断**：若 Jank 帧集中出现在 `temp_celsius > 45°C` 且 `cpu_freq_mhz` 被限制在最高频率的 50% 以下 → 热降频导致的性能退化，需优化散热或降低持续负载。

---

## 7. 实战案例：从掉帧到根因的完整链路

### 7.1 问题描述

> 某游戏在 120Hz 设备上，滑动列表时出现周期性掉帧（每 3-4 秒一次明显卡顿）。

### 7.2 Step 1：Perfetto 宏观定位

```bash
adb shell perfetto -o /data/misc/perfetto-traces/game.perfetto-trace \
  -t 15s sched freq idle gfx view input hal \
  -a com.example.game
```

在 UI 中观察：
- `Actual Frames` 轨道：每 ~3.5s 出现一个红色 slice（dur ≈ 28ms，超出 8.3ms 预算）
- `jank_type = App`
- 主线程在该帧内有一段 12ms 的 `Sleeping` 状态

### 7.3 Step 2：Perfetto SQL 深挖

```sql
-- 主线程 12ms Sleeping 在等什么？
SELECT blocked_function, dur/1e6 AS ms
FROM thread_state
WHERE utid = <main_utid>
  AND state = 'S'
  AND dur > 10000000
  AND ts BETWEEN <jank_start> AND <jank_end>;
-- 结果: blocked_function = futex_wait_queue_me, ms = 12.3

-- 谁持有锁？查看同时间 RenderThread 状态
SELECT state, dur/1e6 AS ms
FROM thread_state
WHERE utid = <render_thread_utid>
  AND ts BETWEEN <jank_start> AND <jank_end>;
-- 结果: Running 11.8ms → RenderThread 在忙，主线程等它释放 mutex
```

### 7.4 Step 3：Simpleperf 微观剖析

```bash
# 针对 RenderThread 抓取
adb shell simpleperf record -p <pid> \
  -e cpu-cycles,cache-misses,stalled-cycles-backend \
  -f 8000 --call-graph dwarf --duration 15 \
  --post-unwind=true \
  -o /data/local/tmp/render.data
```

报告结果：

```
Overhead  Event          Symbol
  41.2%   cpu-cycles     GameRenderer::updateVertexBuffer
  38.7%   cache-misses   GameRenderer::updateVertexBuffer
  52.1%   stalled-cycles-backend  GameRenderer::updateVertexBuffer
```

源码注解显示：

```cpp
// 热点代码（第 247 行，占 38% cache-misses）
for (int i = 0; i < particleCount; i++) {
    vertices[i * stride + 0] = particles[i].x;  // ← 随机访问模式
    vertices[i * stride + 1] = particles[i].y;  // ← stride=12, 跨 cache line
    vertices[i * stride + 2] = particles[i].z;
    // ... 每 64 bytes 一个 cache line，stride 导致每次访问都 miss
}
glBufferData(GL_ARRAY_BUFFER, size, vertices, GL_DYNAMIC_DRAW);  // 每帧重传
```

### 7.5 Step 4：根因确认与修复

**根因**：
1. 粒子数据 AoS（Array of Structures）布局 → 遍历 x/y/z 时 stride 访问 → L1D Miss Rate 38%
2. 每帧 `glBufferData` 全量重传 VBO → RenderThread 长时间占用 → 主线程等锁 → 掉帧

**修复**：
1. 改为 SoA（Structure of Arrays）布局，连续内存访问
2. 使用 `glMapBufferRange` + `GL_MAP_INVALIDATE_BUFFER_BIT` 替代全量重传
3. 双缓冲 VBO 消除主线程等锁

**验证**：

```bash
# 修复后重新采集
adb shell simpleperf stat -p <pid> --duration 10 \
  -e cpu-cycles,instructions,L1-dcache-load-misses,L1-dcache-loads
```

| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| IPC | 0.72 | 1.85 | +157% |
| L1D Miss Rate | 38.2% | 3.1% | -92% |
| 最大帧时长 | 28ms | 7.2ms | -74% |
| Jank Rate | 4.2% | 0.1% | -97.6% |

---

## 8. 附录：指标速查表

### 8.1 Perfetto 关键 SQL 表

| 表名 | 内容 | 常用字段 |
|------|------|---------|
| `slice` | 所有 atrace/ftrace slice | ts, dur, name, track_id, depth |
| `thread_state` | 线程调度状态 | ts, dur, state, utid, cpu, waker_utid, blocked_function |
| `thread` | 线程信息 | utid, upid, name, tid |
| `process` | 进程信息 | upid, pid, name |
| `counter` | 计数器（频率/内存等） | ts, value, track_id |
| `cpu_counter_track` | CPU 相关计数器轨道 | id, cpu, name |
| `actual_frame_timeline_slice` | 实际帧时间线 | ts, dur, jank_type, on_time_finish, upid |
| `expected_frame_timeline_slice` | 预期帧时间线 | ts, dur, upid |
| `sched_slice` | 调度片段 | ts, dur, utid, cpu |

### 8.2 Simpleperf 事件速查

| 场景 | 推荐事件组合 |
|------|-------------|
| 通用热点 | `cpu-cycles` + `--call-graph dwarf` |
| IPC 分析 | `cpu-cycles,instructions` |
| 内存瓶颈 | `L1-dcache-load-misses,LLC-load-misses,dTLB-load-misses` |
| 分支预测 | `branch-instructions,branch-misses` |
| 流水线停顿 | `stalled-cycles-frontend,stalled-cycles-backend` |
| 微架构深挖 (ARM) | `r03,r04,r17,r18,r22,r23,r24,r28` |
| 上下文切换 | `context-switches,cpu-migrations` |
| 缺页分析 | `page-faults,major-faults` |

### 8.3 常用命令速查

```bash
# === Perfetto ===
# 抓取
adb shell perfetto -c config.pbtx -o /data/misc/perfetto-traces/t.perfetto-trace
# 查看内置 metric
trace_processor --list-metrics
# 运行 metric
trace_processor --run-metrics android_jank_cuj -o out.json trace.perfetto-trace
# 交互式 SQL
trace_processor trace.perfetto-trace  # 进入 SQL shell

# === Simpleperf ===
# 列出支持的事件
adb shell simpleperf list
# 快速 stat
adb shell simpleperf stat -p <pid> --duration 5
# 录制
adb shell simpleperf record -p <pid> -e cpu-cycles -f 4000 --call-graph dwarf --duration 10 -o /data/local/tmp/perf.data
# 报告
simpleperf report -i perf.data --sort dso,symbol
# HTML 报告
python3 $NDK/simpleperf/report_html.py -i perf.data -o report.html
# 火焰图
python3 $NDK/simpleperf/report_sample.py -i perf.data > sample.txt
flamegraph.pl sample.txt > flame.svg
```

### 8.4 健康阈值速查

| 指标 | 🟢 健康 | 🟡 警告 | 🔴 严重 |
|------|---------|---------|---------|
| 帧时长 (60Hz) | ≤ 16.6ms | 16.7-33ms | > 33ms |
| 帧时长 (120Hz) | ≤ 8.3ms | 8.4-16.6ms | > 16.6ms |
| Jank Rate | < 1% | 1-5% | > 5% |
| IPC (ARM big) | ≥ 1.5 | 1.0-1.5 | < 1.0 |
| L1D Miss Rate | < 5% | 5-15% | > 15% |
| LLC Miss Rate | < 20% | 20-40% | > 40% |
| Branch Miss Rate | < 3% | 3-8% | > 8% |
| DTLB Miss Rate | < 1% | 1-5% | > 5% |
| Frontend Bound | < 10% | 10-25% | > 25% |
| Backend Bound | < 30% | 30-50% | > 50% |
| 主线程 Runnable 占比 | < 10% | 10-25% | > 25% |
| Binder P99 延迟 | < 5ms | 5-20ms | > 20ms |
| Context Switch / s | < 5000 | 5000-15000 | > 15000 |

---

## 本章小结

| 级别 | 核心能力 | 工具侧重 |
|------|---------|---------|
| **中级** | 标准抓取 → 读 UI → 识别红帧/热点函数 | Perfetto UI + Simpleperf report |
| **高级** | SQL 多维关联 → 多事件采样 → 跨工具联合定位 | Trace Processor SQL + Simpleperf 多事件 + 源码注解 |
| **专家级** | TMA 微架构分解 → 自定义 Metric → 自动化管线 → 功耗-性能联合 → 原始 PMU 事件 | 原始事件编号 + Python 管线 + 自定义 SQL Metric + 热/功耗数据 |

> **最终心法**：Perfetto 告诉你"病人哪里疼"，Simpleperf 告诉你"细胞层面为什么疼"。真正的专家，是能在 30 秒内从一帧红色 slice 追溯到某条 ARM 指令的 cache line 冲突。

---

*本章完*