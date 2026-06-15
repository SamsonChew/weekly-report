# futures 因子迁移工程全记录（cafe_syin + fut2cafe）

> 读这一篇，了解 `future_junjie/cafe_syin` 和 `future_junjie/fut2cafe` 两个 repo 的**来龙去脉、如何跑通、目前进展**。
> 整理人：Claude（外网），基于 syin 内网协作产出的全部文档/脚本/日志逆向梳理。覆盖日期范围 **2026-05-18 ~ 2026-05-21**。
> 这是别人（syin）做的工作，你（samson）现在要先把整个流程跑通。两个 repo 很乱，本文件就是你的导航图 + runbook。

---

## 0. 一句话总览

把公司已有的 **fut-alpha**（C++20 期货因子库，8 个 signalRepo，~235 个因子，CSV→CSV，靠 `tools/replay` 驱动）迁移到 cnfuture 团队的内部框架 **cafe**（预编译主程序 `caf` + `dlopen` 用户写的 `libfactors_v1.so` 插件，mdb→feather），并**逐因子验证数值与 fut-alpha 一致**。在此基础上又加了 **OFR 订单流重建** 的在线 C++ 移植，以及一套**建模/回测**代码。

**最终状态（2026-05-21）**：一个 `libfactors_v1.so` 内含 **216 单标的因子 + 11 跨品种 Assist 因子 + 41 OFR 衍生因子 + 9 OFR 探针列 = 277 列**；内网端到端跑通；同输入逐因子对比 fut-alpha **203 MATCH / 6 CLOSE / 2 DIVERGE（96.8% 数值准确）**；OFR 与 Python 真值逐位一致；建模侧 rolling stacking OOS IC ≈ 0.27。

---

## 1. 两个 repo 是什么关系（最容易迷路的地方）

它们是**同一个工程**的两个 repo，**fut2cafe 是 cafe_syin 的干净交付版**：

| repo | 定位 | 你跑流程主要用哪个 |
|---|---|---|
| **`fut2cafe`** | **干净的生产交付仓**。只留「因子插件源码 + 配置 + build/run/train 三个入口脚本 + 建模代码」。无中间产物、无 probe、无 bit-level infra。 | ✅ **跑通流程用这个**（build.sh → run.sh → train.sh） |
| **`cafe_syin`** | **完整研发历史仓**。所有协作脚本（`scripts/01..53`）、架构文档、build/run 日志、验证脚本、OFR 开发副本（`ofr2cafe/`）、GPU 模型库（`model/`）、bit-level 对比工具、fut-alpha 本地编译 vendor。 | 📚 理解历史 / 查 debug / 跑 GPU 模型库时用 |

关键子目录的归属：
- `cafe_syin/ofr2cafe/` = OFR 移植的**独立开发副本**（含 `OPTIMIZATION.md`、`bench/`）。开发完后 OFR 引擎+因子**已并入 `fut2cafe/plugin/factors_v1/ofr/`**，与 216+11 因子共用一个 `.so`。
- `cafe_syin/model/` = **GPU 多架构模型库**（3 族 × 4 模型），吃 fut2cafe 产出的 feather。
- `fut2cafe/model/` = **生产建模**（rolling stacking + dashboard），是 cafe_syin/model 复用的数据加载/sim/dashboard 基础。
- `fut2cafe/temp/` = **learning-rate / grid 调参工具**。
- 还有两个本文件范围**之外**但被反复引用的 repo：`fut-alpha`（源因子库，在内网 `/mnt/nvme2/syin/fut-alpha`）、`fut_model`（本机模型优化验证，~80 实验，walk-forward 最优 IC+71%）。

> 注意：两个 repo 的 git 历史都只有 2 个 commit（`6ff9c61 Initial commit` + `fc63995 futures baseline dump from syin`）—— 这是 syin 把内网成果一次性 dump 到本机的快照，**不是逐步提交的历史**。真实演进史在 `cafe_syin/debug.md`（Q1–Q40 时间顺序）和各 `summary` 文档里。

---

## 2. 背景与目标

| 项 | 内容 |
|---|---|
| **源** | `fut-alpha`：C++20，`signalRepo0/4/5/7/8/9/10/12`，~235 因子。因子基类 `DynamicPredictorBase`，3-phase 生命周期（`onTradingData` → `getForecasterValue` → `finishMarketDataUpdate`），`tools/replay` + JSON config 驱动，吃 CSV 出 CSV。支持 primary+assist 多标的。 |
| **目标框架** | `cafe`（上游 `git.9th-tech.com/jyuan/cafe.git`）：预编译 `caf` 主程序 `dlopen` 用户 `.so` 插件；因子是 `FeatureCalc` 派生类，`SUPPORT_FACTORY_DECLARE("name")` 注册，每个 snapshot 触发 `onSnapshot(symbol, services, msg)`，`setValue(double)` 写值；吃 mdb 出 feather。 |
| **核心要求**（mentor 原话） | cafe 跑出来的因子值「**跟我们现在存的完全对上**」（bit-level 对齐）。 |
| **协作模式** | 公司防火墙阻断 AWS dev 直连内网 → **全程走 git 中转**：Claude（外网）写脚本/代码 push → syin（内网 `nv-3090-39`，借 mentor `jyuan` 账号）pull + 执行 → 产物 push 回来 → Claude 拉下分析迭代。`ssh.txt` 用于内网 RDP 不能粘贴外网内容时，靠 GitLab raw 复制命令。 |

---

## 3. 历史时间线（按阶段，这是「来龙去脉」）

### 阶段 A — 跑通 demo + 理解架构（Stage 0–2，2026-05-18）
1. **Stage 0**：建 repo 骨架 + 协作脚本约定（`scripts/NN_*.sh` 编号体系）。
2. **Stage 1**：`scripts/01` clone cafe 上游 + rsync mentor 工作副本（`/cpfs/user2/jyuan/jyuan/cafe`，binary 只列清单不入 git）；`scripts/02` 搬进 repo。
3. **Stage 2a**：通读 cafe 源码（`FeatureCalc`/`AllCalc`/`CustomStatApi`/`cne_fut_md`），写 3 份架构文档（`notes/architecture/01_cafe_overview.md`、`02_migration_plan.md`、`03_migration_recipe.md`）。
4. **Stage 2b**：`scripts/04` 用 mentor binary + config 跑通 demo（`adapter_fut_test.sh 20260515`），拿到参照 feather `output/future/200401/20260515.feather`。
5. **Stage 2c/2d**：inventory v2 跑完，定位 build 障碍（详见阶段 B）；装 pyarrow（清华镜像）读 feather schema。

> 关键认知（架构速成见 §5）：`caf` 是**预编译主程序不重编**；用户写**插件 .so**；**两层 JSON** 驱动（主配置 `caf.json` + 信号配置由 `ALGO_CONFIG` 指向）；因子靠 `SUPPORT_FACTORY_DECLARE` 宏**静态注册**；fut-alpha 与 cafe **字段语义高度兼容**，因子数学可 1:1 平移只换字段名。

### 阶段 B — 打通 build（攻克 5 个环境坑）
首次在内网编译 cafe + 自己的因子，连续踩坑（全在 `summary.md §4` / `debug.md`）：
1. **`Not in a Git repository`**：`build.sh` 第 1 步 `git_info_generator.sh` 要求 cwd 是 git 工作区，而 rsync 副本没 `.git` → `git init` + 空提交修复（已固化进 `fut2cafe/scripts/build.sh`）。
2. **conan「假性 auth 失败」**：实为 mentor `~/.conan2/` 缓存已有全部 20 个包（asio/boost/quill/arrow…），共用 jyuan 账号 cache，**离线 install OK，不需要 auth 也不需要联网**。
3. **`set -e` 自陷**：脚本里 `set +e/set -e` 切换导致后续 `cp` 失败就死 → 删掉切换，全局无 `-e`。
4. **脚本步骤错序**：rsync our_plugin 必须在 build **之前**，否则编的是旧源码。
5. **`cne_fut_md` 命名空间陷阱**：cafe 有**两个**同名 struct（全局 namespace 的 `<.../CN/cl2.h>` vs `CNE::FUT` 的 `<future/fut_mdb_datatype.hh>`），demo 用后者 → 切 include 修复。

### 阶段 C — 第一个因子 RT 端到端闭环（Stage 3，里程碑 ⭐）
移植 `fut-alpha sr0::RtnPredictor` → cafe `RT`（EMA-based return）：源码 → 编译 `libfactors_v1.so` → 运行出 feather → **numpy 独立重算交叉验证**：`abs_max=2.65e-6`，完全在 feather `use_float32:true` 存储精度内 → **算法实现等价**。随后扩到 RT/BT/DBT 3 因子。这一步打通了「源码→编译→运行→输出→数值校验」的完整模板。

### 阶段 D — 批量移植 216 个单标的因子（generator + hand-port）
- 写 **`tools/gen.py`**（早期叫 `gen_sr5.py`）：regex AST-lite 翻译器，把 fut-alpha 三段生命周期包成 cafe `onSnapshot` 里的 IIFE-lambda（`setValue([&]{ ...三段... return v; }())`），自动重写 `data->bid_prices[i]` → `bid_price_at(msg,i)` 等。覆盖 sr5/7/8/10/12 全部 + sr4 + sr9 + sr0 single（~130）。
- **hand-port**（generator 展不开的模板类）：sr0 LS（19，CRTP）+ sr0 Multi（37，变参模板 `<Levels...>` → 按 (family,level) 拆成具名类 + `DECL_MULTI` 宏）+ sr10 ObThick + sr12 MaxSizeDiff + sr9 RelOBThickness + sr4 Bar/BookRS（~50）。
- 期间逐个修 generator 的翻译缺陷（`debug.md` Q3–Q12）：CRTP、EMA 头冲突、`Cls::  method` 双空格 regex、`update_snapshot_fixedNum` override 识别、`.X[var]` 下标形式、`instrument_id` guard 重写、BarGenerator 默认 ctor、`SUPPORT_FACTORY_DECLARE` 名字要 `#CafeName` 不是 `#SignalId`（否则工厂查不到 → segfault）、`col_selection` 白名单漏加。
- 达成 **216 个单标的因子**，覆盖 fut-alpha 单 symbol 部分 ~100%。

### 阶段 E — 数值验证（从弱到强三轮）
1. **off-feather 健康度可视化**（`tools/factor_viz/`，`debug.md` Q18）：211 因子 183 alive，|IC|≥0.05 有 103 个、≥0.10 有 37 个（长尾，典型高频 alpha 库）；跨市场 149 因子在 IC(股指) 和 LH(生猪) 同号（仅 1 sign-flip）。
2. **研究-IC 排名对比**（Q23）：vs fut-alpha param-search 输出，81 共享因子符号一致 91.5%。（辅助证据）
3. **同输入逐因子统计对比**（最强证据，Q26–Q31）：让 fut-alpha 在 **cafe 自己 dump 的同一份 snapshot CSV** 上 replay（`SnapshotDumper` 导出 27 列 CSV），逐因子比 mean/std/分位。输入相同 ⇒ 忠实 port ⇒ 逐位一致。**最终 203 MATCH / 6 CLOSE / 2 DIVERGE**，覆盖 211/216 配对。期间发现并修复真实 bug：sr8_VolReverse（reset 预填 deque 被翻成 noop → 越界）、sr9×3 corr（reset 的 EWM 权重丢失）、sr4_MassCenter（公式）、sr4_AmountProportion（BarGenerator 多更新）、sr4_MFITechnical（公式 + bar 默认参数）。**唯一真 cafe bug 是 VolReverse**，其余多是对比方法问题（时间基 machine-time vs 交易所 UpdateTime）。

### 阶段 F — 交付干净仓 fut2cafe + 日期区间能力（Stage 4，Q24）
另起 **`fut2cafe`** 干净仓，核心升级：`run.sh <product|ukey> <start> <end>` 支持**任意日期区间** + **自动换月**（逐日从 universe 解析主力 ukey/tick/multiplier）+ **参数化模板**（`__UKEY__/__TICK__/__MULT__` 占位符）。

### 阶段 G — 11 个跨品种 Assist 因子（多标的难点攻克）
fut-alpha sr0 Assist 家族用「一个交易合约 + 一个 assist 合约」联合出信号（**生猪 lh × 玉米 c 同月**，玉米是饲料成本价格领先）。cafe 是 per-ukey 实例化，解法 = **`GlobalData.str_objs` 共享黑板**：每个因子注册**两个实例**（交易 ukey 出信号 + assist ukey 喂数据），共享 `shared_ptr<State>`。11 个因子全部活信号，**LeadLag IC +0.109、BookTilt +0.079 最强**（证明玉米→生猪 lead-lag 真实有预测力）。`ASSIST_PRODUCT=c bash scripts/run.sh lh ...` 激活。

### 阶段 H — OFR 订单流重建在线 C++ 移植（41 因子 + 9 探针）
把 Python OFR v8 批处理重建（`/mnt/nvme2/syin/OFR`）移植成 cafe 的**逐 snapshot 在线** C++（`ofr/OFRRecon.hpp`）：方向概率 6 项加权 → 7 候选买量 argmin → prior/在线校准 → 仓位四流 + 逐档 trade/cancel/add → market_ofi/cvd/ofi。**每 ukey 一个共享引擎**（`str_objs["OFR:<ukey>"]` + stale-ts 守卫，每 tick 只重建一次，41 因子共享读）。dev 端对 Python 真值 **100% 逐位一致、corr 1.0、MAE<1e-4**（prior_offset=0）。对齐三坑：`np.rint`=round-half-even（用 `std::nearbyint`）、首行 prev=NaN→evidence=0.5、session 起点清零。内网端到端跑通，`OFR_*` 探针列 mean/std 与 Python 对齐。

### 阶段 I — 归并 + 性能优化（`ofr2cafe/OPTIMIZATION.md`）
OFR 并入 fut2cafe 单插件（277 列）。性能优化（全部 checksum 验证不动数值）：①常量权重表只算一次 ②缓存 per-ukey 引擎指针 ③`-O3`（**绝不 fast-math**）④RollingTime/TimeShift 换环形缓冲。**实测**：隔离引擎微基准 **6.14×**（18→113 M calls/s）；真实 1 月端到端 **1.11×**（122→110s，逐位一致 6072 列 0 差异）。可选 A1（跳过恒等 sigmoid，默认关，opt-in `OFR_FAST_CALIB`）。

### 阶段 J — 建模 / 回测
- `fut2cafe/model/`：**rolling stacking**（2 个 LGBM 基模型：回归器 + 三分类器，stacking = 分类器分数逐日 rolling 校准再与回归等权）+ 完整 dashboard。4 折 walk-forward OOS IC ≈ **0.265~0.285**（见 §7.5 实测）。
- `cafe_syin/model/`：**GPU 3 族×4 模型**（强基线 / 低延迟 NN / 短时序 NN）。
- `fut2cafe/temp/`：lr_sweep + grid_sweep 调参工具。
- 外部 `fut_model`：~80 实验，walk-forward 最优 IC +71% / Sharpe +36.5%（**诚实边界**：真实 TMStrategy sim 含费后净 PnL 仍为负 → 相关性强 ≠ 真实可盈利）。

---

## 4. 目录结构

### 4.1 fut2cafe（生产交付，跑流程主用）
```
fut2cafe/
├── README.md
├── plugin/factors_v1/              # cafe 因子插件源码（277 列）
│   ├── CMakeLists.txt              #   GLOB_RECURSE *.cpp → libfactors_v1.so（CONFIGURE_DEPENDS）
│   ├── main.cpp                    #   extern "C" create()/icaf_version()/icaffeature_metadata() 模块入口
│   ├── utils.h  EMA.h             #   共享工具（accessor bid_price_at / EMA / EMASTD / BarGenerator / SR4Base）
│   ├── {RT,BT,DBT,MT,VO}.{h,cpp}   #   5 个 cafe meta 因子
│   ├── auto_sr{0,4,5,7,8,9,10,12}/ #   generator 自动转换（每目录数十个 .h/.cpp）
│   ├── sr{0,4,9,10,12}_handport/   #   手写移植（sr0 LS/Multi/Assist、sr4 Bar/BookRS…）
│   └── ofr/                        #   OFR 引擎 + 41 因子 + 9 探针（8 文件）
│       ├── OFRRecon.hpp            #     在线 V8 重建引擎（框架无关，updateCumulative 喂累计量）
│       ├── OFRFactorBase.h         #     每 ukey 共享引擎 + L1-5 accessor
│       ├── GACommon.hpp            #     RollingTime/EwmTime/TimeShift（环形缓冲）
│       ├── snapshot/  flow/        #     13 RAW + 28 OFR/both 因子头
│       └── OFRProbe.{h,cpp}        #     9 个 OFR_* 探针列（+ create() 入口故意放这，绕 GLOB 缓存坑）
├── config/
│   ├── caf.json                    # caf 引擎级（md 源 / universe / work_dir / stat_lib.so_path）
│   └── signals.json.template       # 因子注册 signals[] + 输出白名单 col_selection[]（__UKEY__/__TICK__/__MULT__ 占位）
├── tools/
│   ├── gen.py                      # fut-alpha → cafe regex AST-lite 翻译器
│   └── regen_all.sh                # 一键重生成所有 auto_sr*（需 fut-alpha 源码 + re-apply 手工修复）
├── model/                          # rolling stacking + dashboard（见 §6.3）
│   ├── stacking.py  sim.py  sim_dashboard.py  train.py
│   ├── redraw_dashboard.py  check_label_horizon.py
│   ├── REQUIREMENTS.md             # 建模依赖清单（anaconda base 通常只缺 lightgbm）
│   └── output/                     # 已存结果：dashboard png + rolling/stacking_summary.json
├── temp/                           # lr_sweep / grid_sweep 调参（自包含 sweeplib.py）
└── scripts/
    ├── build.sh    # 部署 plugin + 编译 → install/lib/libfactors_v1.so
    ├── run.sh      # 日期区间因子计算 → feather（自动换月 + Assist + JOBS 并行）
    ├── train.sh    # 4 折 rolling 训练 + dashboard
    └── setup_env.sh # 建模依赖一键装（清华源）
```

### 4.2 cafe_syin（研发历史 + 工具 + 模型库）
```
cafe_syin/
├── README.md  summary.md  cafe_summary.md  cafe_summary_0521.md  0518report.md  debug.md  # ← 历史/总结/Q&A
├── scripts/                # 01..53_*.sh 内网协作脚本（pull/probe/build/run/dump/compare/assist…）
├── upstream_cafe/          # cafe.git 上游快照
├── mentor_snapshot/        # /cpfs/.../jyuan/cafe 源码快照（text only，无 binary）
├── mentor_demo/            # cnfut_simple 小配置（test.csv 等）
├── our_plugin/             # 早期因子插件源码 + 配置（RT/BT/DBT 时代，已被 fut2cafe 取代）
├── vendor/fut_alpha_src/   # fut-alpha 本地 conan-free 编译用（含 nlohmann/json + stub）
├── ofr2cafe/               # OFR 移植独立开发副本（OPTIMIZATION.md + bench/ + plugin/）
├── model/                  # GPU 模型库（model1/2/3.sh，3 族×4 模型，自包含 common.py）
├── tools/                  # gen_cafe_factor.py / bitlevel_compare/ / factor_stats/ / factor_viz/
└── notes/
    ├── architecture/       # 01_overview / 02_migration_plan / 03_migration_recipe（架构理解）
    ├── work_log/           # 按日期工作日志（kickoff / stage2 / stage2c）
    ├── analysis/           # verify_*.py + factor_viz_report + cafe_vs_futalpha_stats 报告 + figs/
    ├── internal_state/ build_logs/ run_logs/ feather_samples/   # 内网产物 / 编译日志 / 样本 feather
    └── internal_pull_inventory.txt
```

---

## 5. cafe 框架架构速成（跑之前先懂这个）

- **主程序 `caf`**：预编译（~3.7 MB，在 `.externals/caf/lib/caf`，`bin/caf` 是符号链接）。用户**不重编它**。它 `dlopen` 用户的 `.so`。
- **插件 `.so`**：用户写因子库，编成 `install/lib/libfactors_v1.so`。每个 `.so` 必须导出三个 `extern "C"`：`icaf_version()` / `icaffeature_metadata()` / `create("simple_caf")`（返回 `CafStatLib*`）。
- **因子注册**：`.so` 里所有 `SUPPORT_FACTORY_DECLARE(Cls,"name")` 的类，静态初始化时自动注册到全局工厂；`caf` 按 JSON 里的 `type` 字符串实例化。**注册名必须 == JSON `type` 字段**（不一致 → 工厂返回 null → segfault）。
- **因子生命周期**：`init(json params)` → `post_init(all_features)`（注册 `EVENT_TYPE_SNAPSHOT` 回调）→ 每帧 `onSnapshot(symbol, mds, const CNE::FUT::cne_fut_md& msg)` → `setValue(double)` 提交因子值。
- **两层 JSON 配置**：
  - **主配置** `caf.json`：`country/asset`、`md.datum[]`（行情源：lv2 mdb + oe_handler）、`work_dir`（输出根）、`dl`（data loader `libcafdl.so`）、`interval.stat_lib.so_path`（指向你的 `libfactors_v1.so`，mode `simple_caf`）。
  - **信号配置**（`ALGO_CONFIG` env 指向，即 `signals.json`）：`signals[]`（每因子 `{id,type,ukey,output,+params}`）+ `col_selection[]`（输出白名单，**漏加 = init 了但不写 feather**）+ **必需脚手架** `output`（必须是对象 `{so_path:libcafoutput.so, name:CnFutSnapCut, file_type:feather}`，写成字符串会报误导性错）/ `y_def`（`timey` 1min）/ `model`（dummy_model）/ `strat`（dummy_strat，缺它报 `expect strategy not null`）/ `trade_split` / `custom_stats`。
- **数据字段对齐**（fut-alpha → cafe）：`bid_prices[0..4]`→`BidPrice1..5`、`bid_size`→`BidVolume1..5`、`ask_*` 同理、`last_price`→`LastPrice`、`machine_time_stamp`(ns)→`cur_time`(ns)、`nsToUs(...)`→`cur_time/1000.0`。**Volume/Turnover 是累计值**（OFR 内部 diff 成逐 tick）。**`cur_time` 是 machine 接收时间**（比交易所 UpdateTime 早 150-450ms 网络延迟，与 fut-alpha 生产 `machine_time_stamp` 同语义）。
- **ukey** = caf 内部合约整数 ID。例：`200401`=IC2606（CFFEX，tick 0.2，mult 200）、`222102`=lh2607（DCE 生猪，tick 5.0，mult 16）。**ukey 必须从 `cn_player_ukey_product_info/<date>.csv` 查**（caf 真用的 universe），不要用 `cn_main/cn_pukey.feather`。

迁移配方（`notes/architecture/03_migration_recipe.md`）：**因子数学完全不动**，只做 6 条机械替换（基类 `PredictorBase`→`FeatureCalc`+注册宏 / `onConfig`→`init` / `cfg[].get`→`json_get` / `onTradingData`→`onSnapshot`+register_callback / `value_=X`→`setValue(X)` / 字段名映射）。

---

## 6. 如何跑通（runbook）⭐

> **根本约束（先读这条）：数据本地性决定一切。** `/gpfs/hddfs`（原始行情 mdb + universe）和 `/cpfs`（cafe build 树 + conan 缓存 + 输出 feather）都是**只挂在内网的文件系统**，外面的 dev 机 mount 不到。所以凡是「碰数据」的步骤——`build.sh`（读 /cpfs 的 $CAFE_BUILD + conan 缓存）、`run.sh`（caf 读 /gpfs 的 mdb）、`train.sh`（读 /cpfs 的 feather）——**物理上只能在内网跑**，不是「建议在内网」。这也是整个 git 中转协作模式存在的原因：dev 机永远没法直接跑，只能改代码 push 进去、把**小产物**（feather 样本/snapshot CSV/统计/图）push 出来分析；数据本体永远出不来。唯一反向例外：编原始 fut-alpha 是纯代码不碰数据，反而只能在 dev 机编（内网工具链编不了，见 X.2 / S6.6）。
> **跑通的真正前提就一句话**：你能不能在内网拿到①一个能 `./build.sh -t release` 的 `$CAFE_BUILD`，②一个能读 `/gpfs/hddfs` 的账号。这两个有了，下面动作 1→2→3 就通；没有，先找 mentor 要那棵 cafe build 树 + 数据访问权限。
> 运行机：ailab / cnfuture 机（如 `nv-3090-39/5`）。

### 6.0 前置条件
- **cafe build 树** `$CAFE_BUILD`（默认 `/cpfs/user2/jyuan/syin/cafe_build`）：mentor 的 cafe 工程，含 `bin/caf`、`build.sh`、`install/lib/`、conan 缓存。需能独立 `./build.sh -t release`（conan 包已在 `~/.conan2/` 缓存，离线可编）。
- **行情数据**：lv2 MDB `$MDB_DIR/<date>.mdb.new`（默认 `/gpfs/hddfs/cnqr/futures/lv2_mdb`）；ukey universe `$UNIV_DIR/<date>.csv`（`cn_player_ukey_product_info`，含 `ukey/product/is_main/price_tick/multiplier`）。
- **fut2cafe 仓**：clone 到内网，`git pull --rebase` 取最新。
- **建模依赖**（仅 train/sweep 用）：`lightgbm pyarrow pandas numpy scipy scikit-learn joblib matplotlib`（NN 另需 torch）。`bash scripts/setup_env.sh`（清华源，只装缺的；anaconda base 通常只缺 lightgbm）。

### 6.1 编译插件（第一步）
```bash
cd fut2cafe && bash scripts/build.sh
```
做三件事：①`rsync -a --delete plugin/factors_v1/ → $CAFE_BUILD/libs/src/factors_v1/`；②确保 `libs/src/CMakeLists.txt` 有 `ADD_SUBDIRECTORY(factors_v1)`；③`touch` 该 CMakeLists 强制 re-glob 后 `./build.sh -t release`。产出 `$CAFE_BUILD/install/lib/libfactors_v1.so`。
**自检**（必做）：`nm -D --defined-only $CAFE_BUILD/install/lib/libfactors_v1.so | grep -E ' (create|icaf_version)$'` 必须有 `create`，否则 caf 报 "no create function found"。

### 6.2 计算因子出 feather（第二步）
```bash
bash scripts/run.sh lh 20250901 20260331            # 单标的，逐日自动换月
bash scripts/run.sh 222102 20260518 20260518        # 固定 ukey，单日
bash scripts/run.sh IC 20260501 20260531            # IC 主力整月
ASSIST_PRODUCT=c bash scripts/run.sh lh 20250901 20260331   # +11 Assist 列（玉米同月，自动逐日解析）
JOBS=4 bash scripts/run.sh lh 20260501 20260531     # 4 个交易日并行（16 核甜点）
FORCE=1 ...                                          # 重算已存在 feather（首次带 OFR 列必须）
```
`run.sh` 对区间内每个有 MDB 的交易日：从 universe 解析主力 `ukey/price_tick/multiplier` → sed 填 `signals.json.template` 的占位符 → 写 `ukey_select.csv` → `caf -t <date> -c caf.json`。
**输出** `$OUT_ROOT/future/<ukey>/<date>.feather`（默认 `OUT_ROOT=/cpfs/user2/jyuan/syin/cafe_syin_outputs`），每个交易日一个，列 = 277 因子 + 盘口 + `y1min_1s`。

### 6.3 训练 + dashboard（第三步，可选）
```bash
bash scripts/train.sh <ukey> <start> <end>
bash scripts/train.sh 222102 20250515 20260515
```
特征 = `col_selection`（已含 41 OFR + 9 探针）；label 默认 **15s 前向 mid 收益**（`--horizon <秒>` / `--horizon-ticks <数>` / `--horizon 0` 用 cafe 自带 1min）。模型 = 2 个 LGBM（回归 + 三分类）stacking。dashboard 输出 `model/output/dashboard_single_stacking_full.png`（改绘图后 `python3 model/redraw_dashboard.py` 不重训重绘）。
**GPU 多模型库**（在 cafe_syin）：`cd cafe_syin/model && bash model1.sh & bash model2.sh & bash model3.sh & wait`（3 族各 4 模型钉 GPU0-3）。

### 6.4 改了 fut-alpha 源码后重生成因子
```bash
FUT_SRC=/path/to/fut-alpha/src bash tools/regen_all.sh   # 重跑 gen.py 全量；尾部列的手工修复需 re-apply
```

### 6.5 常见报错速修（详见 `cafe_syin/debug.md` Q32–Q40）
| 报错 | 原因 | 修 |
|---|---|---|
| `no create function found in module .so` | CMake GLOB 缓存没收新 .cpp / 缺 create | create 放进已 globbed 的 OFRProbe.cpp；CONFIGURE_DEPENDS + build.sh touch；nm 自检 |
| `[Initialize] expect strategy not null` | signals 缺 strat/model/y_def 脚手架 | 从能跑的 `factors_v1_signals.json` 抄 5 段（config 改动，不重编） |
| `no so_path/name in y_def` | `output` 字段写成字符串了 | 改成对象 `{so_path,name,file_type}`（报错张冠李戴，直接 diff 能跑的配置最快） |
| `target_compile_* on ALIAS target` | `cc_library` 把 factors_v1 设成 ALIAS | foreach 里 `ALIASED_TARGET` 跳过别名，只对 _shared/_static 加 `-O3` |
| 因子值全 0 / feather 少列 | col_selection 没含 / GLOB 没收 | 检查 col_selection + 重 configure |
| 模型脚本「训练前就 FAIL」 | common.py 模块顶层 import lightgbm（内网没装） | common.py 改自包含 + 启动加数据预检 + tail train.log |

---

## 7. 目前进展全表（confirm 全部已同步）

### 7.1 因子覆盖（一个 `libfactors_v1.so`，277 列）
| 类别 | 数量 | 方式 |
|---|---|---|
| sr0 LS | 19 | hand-port 宏（CRTP） |
| sr0 Multi（DBT/dt/cdt/dd/cdd/cweak/sibp/oc/rb × levels） | 37 | template + DECL_MULTI 宏 |
| sr0 Single + sr4 + sr5/7/8/10/12 + sr9 | ~155 | generator + 少量 hand-port |
| cafe meta（RT/BT/DBT/MT/VO） | 5 | 手写模板 |
| **单标的小计** | **216** | 覆盖 fut-alpha 单 symbol ~100% |
| sr0 Assist（生猪×玉米） | 11 | hand-port CRTP + str_objs 共享黑板 |
| OFR 衍生（13 RAW + 28 OFR/both） | 41 | gen_cafe_factors.py + 共享引擎 |
| OFR 探针列（OFR_buy_prob/market_ofi/cvd/…） | 9 | 直接输出重建字段供核对 |
| **总计** | **277** | signals 模板 277 列 / 266 信号 |

### 7.2 数值验证（同输入逐因子对比 fut-alpha，最强证据）
- **203 MATCH（逐位一致）/ 6 CLOSE（<5% 浮点噪声）/ 2 DIVERGE**，覆盖 211/216 名称配对 → **209/211 ≈ 96.8% 数值准确**。
- 5 个名称无对应（未验证）：OBI、sr7_Spread/SpreadSize、sr12_TradeImbUpgrade、sr4_LTBookRSLevel。
- **2 个 deferred 残留**（不阻塞交付）：
  1. `sr9_DiffPctChgDiff`：依赖 `br::multi_window_queue`（cafe 用近似 stub），init() 补权重后「从死复活」但有 4× 缩放残差，忠实移植 multi_window 工程量过大，暂留。
  2. `sr4_MFITechnical`：**移植本身正确**（Python 逐 tick 复刻在 5/6e9 参数下与 fut-alpha 逐位吻合 20.01/40.8，源码 init() 与 config 均 5/6e9），但运行时 `.so` 仍跑旧参数 10/10e9，**clean rebuild 后仍未收敛，根因待查**（候选：init 赋值被覆盖 / stats feather 没用新 .so 重生成 / .so 加载路径不对）。

### 7.3 OFR 重建验证
- dev 端对 `/mnt/nvme2/syin/OFR` Python 真值：buy/sell/market_ofi/cvd + 30 个逐档流 **100% 逐位一致、corr 1.0、MAE<1e-4**（prior_offset=0；跨日 prior_offset 默认关，开启在高量合约引 <0.1% 偏差）。
- 内网端到端探针列对齐：OFR_market_ofi mean/std -0.0308/3.80 ✓、OFR_cvd -220.92/361.47 ✓、OFR_buy_prob 0.147 ✓、OFR_confidence 0.991 ✓。

### 7.4 性能优化（checksum 验证不动数值）
- 隔离引擎微基准 **6.14×**（dev 21→130 M calls/s；ailab 18.35→112.6，checksum 一致 `-833907662.877846`）。
- 环形缓冲真实窗口热路径 **1.35×**。
- 真实 LH 2025-09（22 日）整插件端到端 **1.11×**（122→110s），**逐位一致**（6072 列 0 差异，worst abs diff 0.000e+00）。

### 7.5 建模结果（已存在 fut2cafe/model/output/）
- **rolling stacking**（ukey 222102，20250520–20260520，4 折 walk-forward，5.6M 行 / 155 天）：OOS IC（stack）逐折 ≈ **fold1 0.246 / fold2 0.285 / fold3 0.274 / fold4 0.265**，stacking 与单模型相近（stack 略优或持平）。sim 总 np 646712。
- **lr_sweep**（`temp/lr_sweep_results.csv`）：IC 在 lr≈0.02–0.08 取峰（~0.298），两侧下降；rank_IC ~0.326；ICIR ~11–12；理想化 sign-Sharpe ~41。**注意 net_pnl 在多数 lr 为负**（真实成本下不盈利，印证「相关性强 ≠ 可盈利」）。
- **grid_sweep**（reg_lr × clf_lr）：IC 最高 ~0.306（reg_lr 0.03 / clf_lr 0.05 附近），但 net_pnl 全负（-690 万 ~ -780 万级），sharpe_gross ~41–44。
- 外部 `fut_model` walk-forward 最优：重正则 LGBM + 样本权重 → IC **+71%**（0.152→0.260）/ Sharpe +36.5% / ret +57%；**诚实边界**：真实 TMStrategy sim 含费后净 PnL 仍为负。

---

## 8. 关键技术坑汇总（已沉淀，避免重踩）

1. **cafe config `output` 必须是对象**，不是字符串 `"feather"`。
2. **`SUPPORT_FACTORY_DECLARE` 注入的注册 ctor 不走用户初始化列表** → 所有成员必须 default-constructible（BarGenerator 要加默认 ctor + 默认值）。
3. **新增因子三处同步**：`signals[]` 注册 + `col_selection[]` 白名单 + 注册名 == JSON `type`。
4. **`reset()`→noop 是系统性隐患**：generator 把 fut-alpha 的 `reset()`（session 预填容器）翻成 noop → 空 deque 越界（VolReverse + sr9×3 都中招）→ 这类因子要在 init() 手动补预填。
5. **per-factor 默认参数可能不同**（MFI 的 bar 默认 5/6e9 ≠ Amount/BOP 的 10/10e9），不能想当然统一。
6. **时间字段语义**：cafe `cur_time` = machine 接收时间；做 dump/对比务必用 machine 时间，否则采样网格错位（sr7 多个因子曾差 7-54%）。
7. **CMake GLOB 首次 configure 缓存**：新增 .cpp 不会被重新 glob → create() 放进已被 glob 的文件 + CONFIGURE_DEPENDS + build.sh touch。
8. **跨脚本/跨 repo 依赖「最新代码」很脆**：把工具需要的东西 bundle 进自己目录（如 `temp/sweeplib.py` 自包含），用合成数据端到端 smoke 再交付。
9. **bit-level 严格对齐 defer**：fut-alpha 在 dev box 能编、内网编不了（工具链/C++20 行为差异），bit-level infra 全保留，resume 路径在 `tools/bitlevel_compare/README.md`（推荐 dev box 跑）。当前用「同输入逐因子统计对比」替代，已足够强。
10. **secret 泄露**：曾把 token 粘进 `ssh.txt` 并 commit 进公开 git 历史 → HEAD 清理只是表面，**必须 rotate token**。

---

## 9. 关键路径速查

| 物件 | 位置 |
|---|---|
| **生产插件 + build/run/train** | `fut2cafe/`（scripts/{build,run,train}.sh + plugin/factors_v1/ + config/） |
| **OFR 引擎源码** | `fut2cafe/plugin/factors_v1/ofr/`（OFRRecon.hpp / OFRFactorBase.h / GACommon.hpp / snapshot/ / flow/ / OFRProbe.cpp） |
| **OFR 开发副本 + 优化文档 + bench** | `cafe_syin/ofr2cafe/`（OPTIMIZATION.md, bench/） |
| **generator 翻译器** | `fut2cafe/tools/gen.py` + `regen_all.sh` |
| **GPU 模型库（3 族×4）** | `cafe_syin/model/`（model1/2/3.sh） |
| **生产建模（stacking+dashboard）** | `fut2cafe/model/`（stacking.py, train.py, output/） |
| **调参工具** | `fut2cafe/temp/`（lr_sweep.sh, grid_sweep.sh） |
| **全程 debug Q&A（Q1–Q40）** | `cafe_syin/debug.md` |
| **架构理解** | `cafe_syin/notes/architecture/01_overview.md, 02_plan.md, 03_recipe.md` |
| **各阶段总结** | `cafe_syin/{0518report,summary,cafe_summary,cafe_summary_0521}.md` |
| **因子健康度 + 一致性报告** | `cafe_syin/notes/analysis/`（factor_viz_report.md, cafe_vs_futalpha_stats_*.md, figs/） |
| **因子分类（RAW/OFR/both）** | `future/OFR_FACTOR_CLASSIFICATION.md`（在 fut_v2 工程，非本 repo） |

---

## 10. 同步确认 & 下一步建议

**本文件已覆盖的进展**（逐项核对两个 repo 全部文件后确认）：
- ✅ 历史：Stage 0 → demo → build 攻坚 → 首因子 RT → 216 批量移植 → 三轮验证 → 干净交付 fut2cafe → 11 Assist → OFR 41+9 → 归并优化 → 建模（阶段 A–J）。
- ✅ 如何跑通：build.sh / run.sh / train.sh 三入口 + 前置条件 + 环境变量 + 常见报错速修（§6）。
- ✅ 目前进展：277 列因子、203/6/2 数值验证、OFR 逐位一致、6.14×/1.11× 优化、stacking IC≈0.27、lr/grid sweep、fut_model IC+71%（§7）。
- ✅ 全部坑与决策沉淀（§8，对应 debug.md Q1–Q40）。

**两个 deferred 残留**（如要 100% 收口）：sr9_DiffPctChgDiff（移植 multi_window_queue）、sr4_MFITechnical（定位运行时 10/10e9 根因）。

**你（samson）现在跑通流程的最短路径**：
1. 在内网确认 `$CAFE_BUILD` 可独立 `./build.sh -t release`（conan 缓存在不在）。
2. `cd fut2cafe && bash scripts/build.sh` → `nm -D` 自检有 `create`。
3. `bash scripts/run.sh 222102 20260518 20260518` 单日单 ukey 先跑通一天，看 feather 列数对不对。
4. 跑通后再扩日期区间 / 加 `ASSIST_PRODUCT=c` / `JOBS=4`。
5. 建模：`bash scripts/setup_env.sh` → `bash scripts/train.sh 222102 <start> <end>`。

> 卡住时优先查 `cafe_syin/debug.md`（按报错关键词搜 Q 编号）和本文件 §6.5 / §8。

---
---

# 【S1】跑通主链路 — 逐行精读 + 执行 checklist + 失败排查树

> 本节是对 §6 快速 runbook 的**深挖补全**：把 build.sh / run.sh / caf.json / signals.json.template 的每个机制讲透，给出一份能在内网照着一步步执行、每步带预期输出的 checklist，外加失败排查树。读完这一节，你应该能独立把 feather 跑出来、出错也知道往哪查。

## S1.1 数据流全景（搞清「一层套一层」到底套在哪）

整条链路有**两套目录**：你编辑的「源」（fut2cafe 仓） + 内网真正干活的「构建/运行树」（`$CAFE_BUILD`）。build.sh 的本质就是把源 **rsync 进** 构建树再编译。

```
【源：fut2cafe 仓】                              【运行树：$CAFE_BUILD（=/cpfs/user2/jyuan/syin/cafe_build）】
                                                 （这是 mentor 的 cafe 工程，含预编译 bin/caf + build.sh + conan 缓存）
plugin/factors_v1/  ──build.sh step1 rsync──►   libs/src/factors_v1/
                                                       │ build.sh step2: 确保 libs/src/CMakeLists.txt 有 ADD_SUBDIRECTORY(factors_v1)
                                                       │ build.sh step3: ./build.sh -t release（GLOB *.cpp → cc_library SHARED）
                                                       ▼
                                                 install/lib/libfactors_v1.so   ◄── caf 运行时 dlopen 它

config/caf.json ───run.sh 部署期 sed caf_path/out_root（一次）──►  config/fut2cafe/caf.json
config/signals.json.template ──run.sh 每个交易日 sed __UKEY__/__TICK__/__MULT__──►  config/fut2cafe/signals_<date>.json
                                                                  └ run.sh 每日还写  config/fut2cafe/ukey_<date>.csv（选哪个/哪些 ukey）

运行：caf -t <date> -c config/fut2cafe/caf.json
  环境变量（run.sh 设）：CAF_UKEY_SELECTION_FILE=ukey_<date>.csv，ALGO_CONFIG=signals_<date>.json，
                        LD_LIBRARY_PATH=$CAFE_BUILD/bin，ROOT_DIR=$CAFE_BUILD，TZ=Asia/Shanghai
  读：MDB $MDB_DIR/<date>.mdb.new  +  universe $UNIV_DIR/<date>.csv  +  libfactors_v1.so
  写：$OUT_ROOT/future/<ukey>/<date>.feather   ←── 最终产物
```

**关键认识**：两个 repo（fut2cafe / cafe_syin）里**没有任何东西在本地能跑**。能跑的前提是内网有一棵可独立 `./build.sh -t release` 的 `$CAFE_BUILD`（mentor 给的）。build.sh 只是把你的因子塞进那棵树。**「一层套一层」= 源仓 → 内网构建树 → install 产物 → caf dlopen，四层；这是设计如此，不是冗余**（冗余在别处，见 S1.7 / §12）。

## S1.2 caf.json 逐字段（主配置，引擎级）

文件 `fut2cafe/config/caf.json`（run.sh 部署时把两个绝对路径 sed 成 `$CAFE_BUILD`/`$OUT_ROOT`）：

| 字段 | 值 | 作用 / 注意 |
|---|---|---|
| `country/asset` | `cn` / `future` | 选 cn 期货数据通路 |
| `is_prod` | `false` | 回测/特征模式 |
| `define.caf_path` | `/cpfs/.../cafe_build` | **占位锚点**，run.sh sed 成 `$CAFE_BUILD`；下文 `${caf_path}` 引用它 |
| `define.out_root` | `/cpfs/.../cafe_syin_outputs` | sed 成 `$OUT_ROOT` |
| `md.univ.cn_future` | `.../cn_player_ukey_product_info/$date.csv` | **caf 真正用的 ukey universe**（`$date` 由 caf 自己按 `-t` 替换） |
| `md.datum[0]` | `$MDB_DIR/$date.mdb.new`，type `cn_future` | 行情主源（lv2 五档） |
| `md.datum[1]` | `oe_handler` / `mock_server` | 订单事件（mock，喂 onRawOrder 等） |
| `md.#sub_file` | （`#` 前缀=注释掉） | ukey 选择**不走这里**，走 `CAF_UKEY_SELECTION_FILE` 环境变量（run.sh 每日设） |
| `md.close_time` | `154000000` | 15:40:00 收盘（HHMMSSmmm） |
| `work_dir` | `${out_root}/future/` | feather 输出根 |
| `calendar` | `/cpfs/equity/calendar` | 交易日历 |
| `dl[0]` | `${caf_path}/bin/libcafdl.so`，name `cnfut_dl` | data loader：universe(`cn_player_ukey_full`)、pre_close(`days.csv`)、time_range、product_info |
| `interval.stat_lib` | `${caf_path}/install/lib/libfactors_v1.so`，mode `simple_caf` | **你的插件挂载点**——caf dlopen 它、调 `create("simple_caf")` |

> 易错点：`${caf_path}`/`${out_root}` 是 caf 自己解析的 `define` 变量；而 `/cpfs/user2/jyuan/syin/cafe_build` 这种**字面绝对路径**是 run.sh 用 sed 改的。改部署目录时**改 run.sh 的 sed 或 env，不要手改 caf.json 的字面量**。

## S1.3 signals.json.template 逐段（信号配置，因子级）

文件 `fut2cafe/config/signals.json.template`，run.sh 每个交易日 sed `__UKEY__/__TICK__/__MULT__` 生成 `signals_<date>.json`，由 `ALGO_CONFIG` 指向：

| 段 | 内容 | 缺了会怎样 |
|---|---|---|
| `ukey` | `__UKEY__`（顶层主合约） | sed 没替换 → caf 解析失败 |
| `output` | **对象** `{so_path:bin/libcafoutput.so, name:CnFutSnapCut, file_type:feather, use_float32:true}` | 写成字符串 → 报误导性 `no so_path/name in y_def` |
| `col_selection` | 输出白名单（AccImbalance/Atr/BT/…/RT_60s/…/sr10_*/OFR_*，~277 列） | 因子没列进来 → init 了但**不写 feather** |
| `signals[]` | 每因子 `{id,type,ukey,output,+params}`，`type` 必须 == 注册名 | type 对不上注册名 → 工厂返回 null → segfault |
| `y_def` | `libcafy.so` `timey` 1min（skip 1s）→ 产出 `y1min_1s` 标签列 | 缺 → init 报错 |
| `model` / `strat` | `dummy_model` / `dummy_strat`（占位，因子计算不需要真模型） | 缺 strat → `[Initialize] expect strategy not null` |
| `trade_split` / `custom_stats` | 脚手架 | 缺 → init 报错 |

> 即使只算因子、不做策略，cafe 的 `simple_caf` 流水线 md→stat→y→model→strat→output **每段都要挂一个（哪怕 dummy）**。这就是为什么 signals 里有一堆「跟因子无关」的脚手架段。

## S1.4 run.sh 的每日循环（精读关键逻辑）

[run.sh](../../future_junjie/fut2cafe/scripts/run.sh) 干的事（已在 §6.2 概述，这里补机制细节）：
1. **一次性**把 caf.json sed 部署到 `$CAFE_BUILD/config/fut2cafe/caf.json`。
2. **一个 python pass 预解析整段日期**（`mapfile PLAN`）：对 `[START,END]` 每天，要求 ① `$MDB_DIR/<date>.mdb.new`（或 `.mdb`）存在 ② universe `<date>.csv` 存在；然后从 universe 解析：传**数字 ukey** → 固定该合约；传**产品代码**（lh/IC）→ 选 `is_main` 主力合约的 `ukey/price_tick/multiplier`（**自动换月**）。开 `ASSIST_PRODUCT` 时再解析**同月** assist 合约 ukey（玉米）。输出 `date ukey tick mult assist` 行。
3. **每个交易日 `run_one`**：渲染 `signals_<date>.json` + `ukey_<date>.csv`（每日独立文件，**并行不打架**）；Assist 模式额外 python 注入 11 个 trading+feed 实例、双 ukey 写进 ukey_select；非 Assist 模式从 col_selection **剔除** Assist 列（否则 caf 等不到这些列报错）；然后 `CAF_UKEY_SELECTION_FILE=... ALGO_CONFIG=... caf -t <date> -c caf.json > /tmp/caf_<date>.log`。
4. **幂等**：feather 已存在则跳过（`FORCE=1` 强制重算；**首次带 OFR 列必须 FORCE=1**，因为旧 feather 没那些列）。
5. **并行**：`JOBS=N` 用 `wait -n` 控制在跑 N 个交易日（16 核甜点 4）。

> caf 单日日志在 `/tmp/caf_<date>.log`（**不在仓里**），caf rc≠0 时第一时间 `tail /tmp/caf_<date>.log`。

## S1.5 一步步执行 checklist（内网照做，每步带预期输出）

```bash
# ── 步骤 0：确认运行树存在且能独立编 ────────────────────────────────
ls $CAFE_BUILD/bin/caf $CAFE_BUILD/build.sh $CAFE_BUILD/install/lib/   # 都在？
#   预期：caf（符号链接到 .externals/caf/lib/caf）、build.sh、install/lib（mentor 的 .so 们）
ls ~/.conan2/p 2>/dev/null | head             # conan 缓存在不在（离线编的前提）
#   预期：一堆包目录；空 → build 会卡依赖（见失败树 F-A）

# ── 步骤 1：编因子插件 ────────────────────────────────────────────
cd fut2cafe && bash scripts/build.sh
#   预期尾部：[build] OK: .../install/lib/libfactors_v1.so (XXX KB/MB)
nm -D --defined-only $CAFE_BUILD/install/lib/libfactors_v1.so | grep -E ' (create|icaf_version)$'
#   预期：看到 create 和 icaf_version；缺 create → 失败树 F-C

# ── 步骤 2：先跑通「一天 + 固定 ukey」（最小验证）──────────────────
FORCE=1 bash scripts/run.sh 222102 20260518 20260518
#   预期：[run] ...dates=1...  然后  [20260518] ukey=222102 OK 32M (5s)
#   产物：$OUT_ROOT/future/222102/20260518.feather

# ── 步骤 3：核对 feather 列数对不对（确认 277 列因子都在）──────────
python3 - <<'PY'
import pyarrow.feather as f
t = f.read_table("$OUT_ROOT/future/222102/20260518.feather")  # 手填实际路径
print("rows", t.num_rows, "cols", t.num_columns)
print([c for c in t.column_names][:20], "...")
PY
#   预期：cols ≈ 277+元数据；含 RT_60s/BT/DBT/OFR_market_ofi/y1min_1s 等

# ── 步骤 4：跑通后再放量 ──────────────────────────────────────────
JOBS=4 bash scripts/run.sh lh 20250901 20260331              # 区间+自动换月+并行
ASSIST_PRODUCT=c JOBS=4 bash scripts/run.sh lh 20250901 20260331   # +11 Assist 列

# ── 步骤 5（可选）：建模 ──────────────────────────────────────────
bash scripts/setup_env.sh                                    # 看到 all model deps OK
bash scripts/train.sh 222102 20250901 20260331               # 出 dashboard + summary
```

## S1.6 失败排查树

```
build.sh 失败？
├─ F-A "找不到 Boost/asio/... 依赖" / conan install 卡住
│     → ~/.conan2 缓存空 or remote 不可达。确认用的是 mentor jyuan 账号缓存；
│       缓存在就离线能编，别去配 auth（debug.md Q-conan：auth 是假象）。
├─ F-B "Not in a Git repository"（[1/N] Generating git_info.hpp）
│     → $CAFE_BUILD 不是 git 工作区。build.sh 已自动 git init+空提交；若仍报，
│       手动 cd $CAFE_BUILD && git init && git add -A && git commit -m init。
├─ F-C build OK 但 nm 看不到 create
│     → CMake GLOB 缓存没收新 .cpp。build.sh 已 touch CMakeLists 强制 re-glob；
│       仍缺 → 确认 create() 在已被 glob 的 ofr/OFRProbe.cpp 里（§5 / debug.md Q33）。
└─ F-D "target_compile_* on ALIAS target"
      → factors_v1 是 cc_library 的 ALIAS。CMakeLists 里 foreach 用 ALIASED_TARGET 跳过别名。

run.sh / caf 失败（看 /tmp/caf_<date>.log）？
├─ "[Initialize] expect strategy not null"  → signals 缺 strat/model/y_def 脚手架（S1.3）
├─ "no so_path/name in y_def"               → output 字段写成字符串了，改成对象（S1.3）
├─ "no create function found in module .so" → 见 F-C
├─ segfault / rc=139                          → 某因子 type ≠ 注册名，工厂返回 null（debug.md Q4）
├─ feather 写出但少列 / 某因子全 0           → col_selection 没含该因子（S1.3）
├─ "[run] nothing to do"                     → 该区间没 MDB 或 universe 不匹配（核对 $MDB_DIR/$UNIV_DIR + 产品代码大小写）
└─ Assist 跑了但 caf 报等不到某列             → 非 Assist 模式没剔 Assist 列 / Assist 模式 col_selection 没含（run.sh 已处理，检查 ASSIST_PRODUCT 拼写）
```

## S1.7 这条链路里哪些文件「真正参与跑通」（其余都是历史/参考）

**跑通只需要这几样**（其它全可忽略）：
- `fut2cafe/scripts/{build,run,train,setup_env}.sh`
- `fut2cafe/config/{caf.json, signals.json.template}`
- `fut2cafe/plugin/factors_v1/`（整个因子源码树）
- `fut2cafe/model/`（仅 train 时）
- 内网的 `$CAFE_BUILD`（mentor 给）、`$MDB_DIR`、`$UNIV_DIR`

→ **cafe_syin 整个仓在「跑通流程」里一行都不需要**；它是研发历史 + 参考 + 工具。详见 §12 冗余分析。

---

# 【冗余分析】哪些是核心 / 哪些是历史/参考/重复（回答「一层套一层、有没有多余代码」）

你看到的嵌套来自两件事：**(1) 同一份东西在演进里被复制了好几份**（早期插件 → 干净仓 → 内网构建树）；**(2) cafe_syin 把「别人的框架/源库」也一并 vendor 进来当参考**。下面按「能不能动」分级。

## 12.1 总览表（按目录）

| 路径 | 大小 | 是什么 | 级别 | 跑通需要? | 能删? |
|---|---|---|---|---|---|
| `fut2cafe/plugin/` `config/` `scripts/` `model/` | — | **生产核心**：因子源码 + 配置 + 入口 + 建模 | 🟢 核心 | ✅ 必需 | ❌ 不能 |
| `fut2cafe/temp/` | 小 | lr/grid 调参工具 + 历史 sweep 结果 | 🟡 工具 | ⛔ 否 | 结果可清，脚本留 |
| `cafe_syin/ofr2cafe/` | 436K | OFR **开发副本**：plugin/ 已并入 fut2cafe 的 `ofr/`；只 OPTIMIZATION.md + bench/ 有独立价值 | 🟠 重复+文档 | ⛔ 否 | plugin/ 可删，留 OPTIMIZATION.md+bench/ |
| `cafe_syin/our_plugin/` | 1.8M | **早期插件**（RT/BT/DBT + 部分 auto_sr10），Stage 3-4 产物，**已被 fut2cafe/plugin 完全取代** | 🔴 历史副本 | ⛔ 否 | ✅ 可删（除非想看演进） |
| `cafe_syin/upstream_cafe/` | 1.1M | cafe 框架的 **git clone 快照**（别人的代码，参考用） | 🔵 参考 | ⛔ 否（真树在内网 $CAFE_BUILD） | ✅ 可删（需要时重 clone） |
| `cafe_syin/mentor_snapshot/` | 6.6M | cafe 框架的 **mentor 工作副本快照**（含 build.sh/install/compile_commands，比 upstream 多本地产物） | 🔵 参考 | ⛔ 否 | ✅ 可删 |
| `cafe_syin/vendor/fut_alpha_src/` | 2.8M | **fut-alpha 源** vendored（conan-free 本地编译 + bit-level 参考，含 nlohmann/json + stub） | 🔵 参考 | ⛔ 否 | 保留（bit-level resume 用）或挪走 |
| `cafe_syin/notes/` | 24M | build_logs(~100)、feather_samples、analysis 报告、architecture、work_log | 🟣 历史 | ⛔ 否 | build_logs/feather_samples 可清；architecture/analysis 有价值留 |
| `cafe_syin/scripts/01..53` | 336K | 一次性 probe/diagnose/build/dump/compare 协作脚本，**已被 fut2cafe 的 build/run 取代** | 🟣 历史 | ⛔ 否 | ✅ 可删（debug.md 已沉淀结论） |
| `cafe_syin/tools/` | 164K | bitlevel_compare / factor_stats / factor_viz / gen_cafe_factor | 🟠 验证工具 | ⛔ 否 | 验证时才用，可留 |
| `cafe_syin/model/` | 64K | GPU 3族×4模型库（复用 fut2cafe/model 的 load/sim/dashboard） | 🟡 工具 | ⛔ 否（只在跑 GPU 模型时） | 留 |
| `cafe_syin/mentor_demo/` `ssh.txt` | 小 | demo 小配置 / 内网粘贴脚本 | 🟣 历史 | ⛔ 否 | ssh.txt **应删**（曾泄 token，见 §8.10） |

## 12.2 三组「真重复」（同一份东西的多个副本）

1. **因子插件的三代副本**：`cafe_syin/our_plugin/`（早期，RT/BT/DBT）→ `fut2cafe/plugin/factors_v1/`（当前生产，216+11+OFR）→ 运行时 `$CAFE_BUILD/libs/src/factors_v1/`（build.sh rsync 出的副本）。**唯一权威是 `fut2cafe/plugin/`**；our_plugin 是历史可删；$CAFE_BUILD 里那份是构建产物（被 rsync `--delete` 覆盖，不要手改）。
2. **OFR 引擎两副本**：`cafe_syin/ofr2cafe/plugin/factors_v1/`（开发副本，`Factory.cpp`）↔ `fut2cafe/plugin/factors_v1/ofr/`（生产，重命名 `OFRFactory.cpp`）。**生产用 fut2cafe 的**；ofr2cafe 的 plugin/ 是历史，但 `ofr2cafe/OPTIMIZATION.md` + `bench/` 是独有文档/基准，留着。
3. **cafe 框架两快照**：`upstream_cafe/`（纯 clone）↔ `mentor_snapshot/`（mentor 工作副本，多 install/build 产物）。两份都是**别人的框架**、都不是真正跑用的（真树是内网 `$CAFE_BUILD`）；留一份参考足矣，甚至都可删（需要时按 `_SNAPSHOT_HEAD.txt` 重 clone）。

## 12.3 「插件内部一层套一层」是否冗余？——不是

`fut2cafe/plugin/factors_v1/` 下的 `auto_sr{0,4,5,7,8,9,10,12}/` + `sr{0,4,9,10,12}_handport/` + `ofr/{snapshot,flow}/` 是**按来源/移植方式的合理分层**，不是重复：`auto_*`=generator 自动转换，`*_handport`=手写，`ofr/`=OFR。同一因子不会两处都有（generator 跳过的才进 handport，靠 `--skip` 控制）。这层结构**该保留**。

## 12.4 建议（如果你要给自己减负，但不必现在做）

- **立刻可删**（纯历史，结论已进 debug.md）：`cafe_syin/our_plugin/`、`cafe_syin/scripts/01..53`、`cafe_syin/notes/build_logs`、`cafe_syin/ssh.txt`（**安全考虑应删**）。
- **可瘦身**：`cafe_syin/ofr2cafe/plugin/`（留 OPTIMIZATION.md+bench/）、`upstream_cafe/` 或 `mentor_snapshot/` 二选一。
- **保留**：两个 repo 的 `fut2cafe/{plugin,config,scripts,model}`、`cafe_syin/{tools,notes/architecture,notes/analysis,debug.md,各 summary,vendor/fut_alpha_src,model}`。
- **不要碰**：内网 `$CAFE_BUILD`（mentor 的，rsync 目标）、`$MDB_DIR`/`$UNIV_DIR`（共享只读数据）。

> 一句话：**真正要维护的只有 `fut2cafe/`**；`cafe_syin/` 里除了少量工具/文档/参考，大半是研发过程的历史副本和别人框架的快照，看懂后大可冷藏。

---
---

# 【cafe 框架详解】它到底是个什么东西（展开 §5，从零讲清）

> §5 是速查表，这里从「它解决什么问题、为什么这么设计、各部件怎么咬合」从零讲一遍，配 mentor demo 的真实代码。源码出处：`cafe_syin/mentor_snapshot/libs/src/demo/`（demo 插件）、`.../external/caf_feat/include/featurebase/FeatureCalc.h`（因子基类）、`.../config/cnfut_simple/sample_cnfut_signal.json`（配置样例）。

## C.1 一句话：cafe 是「行情驱动的特征计算 / 回测引擎」

你给它**一天的行情**（mdb 文件）+ 一份**「要算哪些信号」的清单**（signals.json），它就**逐 tick 把行情喂给你的因子代码**，把每个因子每个时刻的值，按时间串成一个 **feather**（一张大表：行=时间点，列=因子）。内部代号 **CAF**（团队叫它 "China Alpha Framework" / QuantVerse）。

它对标的就是 fut-alpha 的 `tools/replay`——都是「读行情 → 跑因子 → 出表」，只是 cafe 更工程化（mdb 而非 CSV、feather 而非 CSV、还自带订单簿重建 / label / 模型 / 策略 / 输出的完整流水线）。

## C.2 核心设计：预编译主程序 + 用户插件（为什么这么分）

```
┌─────────────────────────────────────────────────────────┐
│  caf （预编译主程序，~3.7MB，所有人共用，永不重编）        │
│  干所有"脏活"：读 mdb、解析行情、按时间排序事件、          │
│  维护订单簿(LOB)、触发回调、算 label、串 feather 输出      │
└───────────────────────┬─────────────────────────────────┘
                        │ 运行时 dlopen
                        ▼
┌─────────────────────────────────────────────────────────┐
│  libfactors_v1.so （你写的插件，几百 KB）                  │
│  只装"因子数学"：一堆 FeatureCalc 子类                     │
└─────────────────────────────────────────────────────────┘
```

**为什么这样分**：因子怎么算是天天变的，但「读行情、维护订单簿、串输出」这些跟具体因子无关、且很重，所以把它们做成**一次编译好的主程序**，所有人共用；用户只写会变的那部分（因子数学），编成一个小 `.so`，引擎运行时动态加载。**加一个因子，你只编那个几百 KB 的 `.so`，绝不碰 3.7MB 的 caf。** 这就是 §6 / S1 里 build.sh 只 rsync+编 plugin、从不重编 caf 的原因。

## C.3 心智模型最重要的一张图：六段流水线

每个 tick，数据流过一条**固定的流水线**，每一段是一个「插槽」，可以挂一个 `.so`：

```
 md  ──►  stat/feature  ──►   y    ──►  model  ──►  strat  ──►  output
行情      你的因子(算值)     label    （可选）   （可选）    写 feather
         ★我们只关心这段★    前向收益   dummy      dummy      引擎自带
```

- **md**：引擎读 mdb、解析成 `cne_fut_md` 快照、维护订单簿。
- **stat/feature**：**我们的因子**就挂这段（`interval.stat_lib.so_path` = libfactors_v1.so）。
- **y**：算 label（`timey` 1min → 列 `y1min_1s`，前向 mid 收益）。
- **model / strat**：跑模型 / 策略。我们只算因子不交易，所以挂 **dummy**。
- **output**：把 `col_selection` 白名单里的因子值每 tick 写一行进 feather。

> **关键约束**：哪怕你只想算因子，这六段**每段都必须有人占位**，否则引擎初始化就报错（缺 strat → `expect strategy not null`）。这就解释了为什么 signals.json 里有一大堆「和因子无关」的 `y_def / model / strat / trade_split / custom_stats` 脚手架段——它们是流水线的占位符，不是因子。

## C.4 一个因子是怎么跑起来的（FeatureCalc 生命周期）

你的因子 = 一个继承 `FeatureCalc` 的类（[FeatureCalc.h](../../future_junjie/cafe_syin/mentor_snapshot/external/caf_feat/include/featurebase/FeatureCalc.h)）。引擎按 JSON **每个 ukey 实例化一个**，然后依次调：

```
create(按 type 字符串从工厂 new)         ← 见 C.5
  → init(json params)                    ← 读这个因子的 JSON 参数（decay/tick_size…）
  → post_init(all_features)              ← 注册要监听的事件 / 拿别的信号指针
  → 【运行期，每个行情事件触发对应回调】：
       onSnapshot(symbol, mds, cne_fut_md& msg)   ← 五档快照（我们的因子几乎全用这个）
       onRawOrder / onRawTrade                    ← 逐笔委托 / 逐笔成交
       onInferredOrder / onInferredTrade          ← 引擎重建的订单簿事件
       addTimer 注册的定时回调                      ← 按时间触发
  → 因子每算出一个值就  setValue(double)
       └ 引擎把它写进 m_gdata->m_values[m_idx]（全局值数组里"你这一格"）
```

`output` 段每个 tick 把白名单因子各取一格，拼成 feather 的一行。**因子的全部职责就是：在回调里读 `msg` 的盘口字段 → 算 → `setValue`。** 这正是 §5「6 条机械替换」要把 fut-alpha 的 `onTradingData + value_=X` 翻成 `onSnapshot + setValue(X)` 的原因。

## C.5 工厂注册：为什么用一个宏（SUPPORT_FACTORY_DECLARE）

引擎根本不认识你的类名。`SUPPORT_FACTORY_DECLARE(MyFactor, "MyFactor")` 干的事：让这个类在 `.so` 被 dlopen 时、靠 C++ **静态初始化自动登记到一张全局工厂表**（名字 → 构造器）。引擎拿到 JSON 里的 `type` 字符串，去工厂表 `new` 出对应实例。

```cpp
// 头文件
class MyFactor final : public FeatureCalc {
    SUPPORT_FACTORY_DECLARE(MyFactor, "MyFactor")   // ← 第二参数 = JSON 的 type 字段
    void init(const nlohmann::json& params) final;
    void onSnapshot(const MDSymbol&, MDServices*, const CNE::FUT::cne_fut_md& msg);
    bool static_trigger() const final { return true; }
};
// .cpp
SUPPORT_FACTORY_IMPLEMENT(MyFactor)
```

**推论（也是最常见的坑）**：JSON 里的 `type` 必须和注册名**逐字一致**，否则工厂查不到 → 返回 null → 引擎解引用 → segfault（debug.md Q4 整批 LS 因子就是栽在 `#SignalId` vs `#CafeName`）。这也是「加因子不用动引擎」的根本：引擎全靠字符串查表，不靠编译期类型。

## C.6 两层 JSON：配置怎么映射到代码

| 配置 | 谁指向它 | 管什么 | 类比 |
|---|---|---|---|
| **caf.json**（主配置） | `caf -c` | 引擎级：数据从哪来、输出到哪、加载哪个因子 `.so` | 「整个工厂的水电管线」 |
| **signals.json**（信号配置） | `ALGO_CONFIG` 环境变量 | 因子级：实例化哪些因子、各什么参数、输出哪些列、y/model/strat 挂谁 | 「这条产线今天生产什么」 |

`signals[]` 里**每一条 = 一个因子实例**：
```json
{ "id": "RT_60s", "type": "RT", "ukey": 200401, "output": true, "decay": 60000000 }
//  实例名(列名)   类名(注册名)  哪个合约    是否输出     该因子的参数
```
`col_selection[]` 是**输出白名单**：只有列在里面的因子才写进 feather（注册了但没进白名单 = 白算，不落盘）。

## C.7 进阶：信号能依赖信号（demo 的精髓，也是 Assist 的底子）

cafe 因子不只是「各算各的叶子」，**因子之间能组合成依赖图**。看 mentor demo（[sample_cnfut_signal.json](../../future_junjie/cafe_syin/mentor_snapshot/config/cnfut_simple/sample_cnfut_signal.json)）：

- `SigMain`（在 200401 上）用 `use_signal` 声明它要用 `SigSuppTgt`（200401）、`SigSuppPred1`（200402）、`SigSuppPred2`（200403）、`SigInfer1`（200403）。
- 它在 `post_init` 里对每个被依赖信号 `addValueListener`，谁的值一变就触发自己重算（`on_value_change` 里累加差值）。
- 引擎据此建一张**信号依赖 DAG**，按拓扑序（`m_topoidx`）触发。跑 demo 日志里 `SigMain/SigSuppTgt/SigSuppPred1/2/SigInfer1 ... wire up success` 就是这张图接好了。

我们迁移的 216 个因子**大多是叶子**（只吃行情、不依赖别的信号）。但**11 个 Assist 跨品种因子**用的就是这套「信号间共享」思想——只不过因为要跨 ukey（生猪读玉米），用的是 `GlobalData.str_objs` 共享黑板而非 `addValueListener`（后者同 ukey 才方便），详见 S4。

## C.8 进阶：CustomStat（多因子共享的 per-symbol 状态）

有些状态多个因子共用（比如某合约的 spread）。做成一个 `CustomStat`（继承 `CustomStatApi`），在 `custom_stats[]` 里配置，因子用 `m_ac->get_custom_stat(name)` 取。demo 的 **DemoStat** 就从快照算 spread，`SigSuppPred` 取来用。

→ 我们的 **OFR 共享引擎**是同一思路的「加强版」：每 ukey 一个 `OFRRecon` 引擎，41 个 OFR 因子共享读（只不过存在 `GlobalData.str_objs["OFR:<ukey>"]` 而非走 CustomStatApi）。详见 S3。

## C.9 其它要知道的

- **`.so` 入口三件套**（[demo/main.cpp](../../future_junjie/cafe_syin/mentor_snapshot/libs/src/demo/main.cpp)）：`extern "C"` 的 `icaf_version()`（ABI 版本，必须和 caf 一致）/ `icaffeature_metadata()`（元信息）/ `create("simple_caf")`（返回 `caf::CafStatLib*`，引擎持有）。缺 `create` → 「no create function found」。
- **订单簿（LOB）**：需要 order 级信息的因子可 `m_ac->setLob()` 拿订单簿，`ForEachBid_If / ForEachBidOrder_If` 遍历档位/挂单。我们多数因子只用五档快照，不碰 LOB。
- **线程模型**：引擎对**每个 symbol 单线程顺序**处理，symbol-local 状态**无需加锁**。这是 OFR 共享引擎敢假设「同 ukey 单线程、每 tick 只重建一次」的依据（OPTIMIZATION.md 里 B2「确认 per-ukey 线程模型」就是要坐实这条）。
- **`changeThresh`**：`setValue` 只有当值变化超过阈值才通知监听者（省传播开销）；`alwaysCallValueListeners=true` 可强制每次都通知。

## C.10 把 demo 串起来（一个具体例子）

mentor demo 跑 ukey `200401/402/403` 三个合约：
- 200402、200403 各挂一个 **DemoStat**（算各自 spread）；
- `SigSuppTgt` 在 200401 出目标信号；`SigSuppPred1/2` 在 402/403 上分别用各自 DemoStat 的 spread 出预测信号；`SigInfer1` 在 403 上出推断信号；
- `SigMain` 在 200401 上**聚合**上面四个（`use_signal`），`addValueListener` 接好依赖图，`wire up success`；
- `output` 把 `col_selection`（SigMain/SigSuppTgt/SigSuppPred1）写进 `200401/<date>.feather`。

**我们的工程把「feature 这一段」从 demo 的 5 个示例信号，换成了 216+11+41+9 个真因子；其余五段（md/y/model/strat/output）基本沿用 demo 的脚手架。** 理解了 demo 这套，就理解了我们整个 plugin 的运行骨架。

---
---

# 【S2】216 单标的因子 — gen.py 翻译机制 + 逐目录清点

> 本节深挖 216 个单标的因子**怎么从 fut-alpha 的 C++ 翻译过来**、**逐目录到底有哪些因子**。基于对 `fut2cafe/tools/gen.py`、`regen_all.sh` 和 `plugin/factors_v1/` 全部子目录的逐文件清点。

## S2.0 一个数字更正：是「约 222」不是精确 216

逐文件实测：fut-alpha 派生的单标的因子共 **222 个**（去重，全部在 `col_selection`）= **142 generator 自动翻译**（`auto_sr*`）+ **80 手写**（`sr*_handport`）。「216」是 `debug.md` Q10「179 → 216」那一刻（刚加完 37 个 multi-level）的列数快照，之后又补了几个到 222。`col_selection` 共 **277 列** = 222（fut-alpha 派生，含 11 Assist）+ 5（cafe meta：RT 以 `RT_60s` 输出 + BT/DBT/MT/VO）+ 50（自研新因子：41 OFR `_W/_NS/_R` + 9 `OFR_*` 探针）。

> 和前文「216 单标的 + 11 Assist + 41 OFR + 9 探针 = 277」对账：那个「216」= 211 fut-alpha single（不含 Assist）+ 5 meta；本节的「222」= 211 single + 11 Assist（把 Assist 也算进 fut-alpha 派生）。**两种分桶都加到 277**，只是 Assist 和 meta 归哪边的差别。下文用「222 fut-alpha 派生（142 auto + 80 handport）」这个口径。

## S2.1 翻译器 gen.py：3-phase 生命周期 → 一个 onSnapshot

fut-alpha 的 predictor 是裸 class（sr5+ 多数无基类，sr4 用 `DynamicPredictorBase`），回放框架按 tick 调三个方法：
1. `onTradingData(data)` — 用**上一 tick 状态**算当前值，内含大量提前 `return;`（空盘口/volume 倒退等），只退出本阶段。
2. `getForecasterValue()` — `return` 一个成员当输出。
3. `finishMarketDataUpdate()` — 刷新「上一 tick」状态（如 `m_lastDataTime = current_time`）。

cafe 的 `FeatureCalc` 只有一个 `onSnapshot`，一次算完 `setValue()`。gen.py 把三段塞进**三个 IIFE-lambda**：
```cpp
[&]() { /* phase1: onTradingData body，早退 return; 只退出本 lambda */ }();
double _value = [&]() -> double { /* phase2: getForecasterValue body */ return 0.0; }();
setValue(_value);
[&]() { /* phase3: finishMarketDataUpdate body */ }();
```
**精髓**：phase1 的早退 `return;` 被 lambda 隔离，不会跳过 phase2/3 → 复刻 fut-alpha「早退只保留旧值」语义。phase2 里每个 `return EXPR;` 被改写成 `{ setValue(EXPR); return; }`（带花括号防 if/else 悬空）。

**解析流程**：先 `strip_method_bodies`（消去内联方法体防把方法当成员）+ `expand_comma_decls`（拆 `double a,b,c;`）；`_balanced_body` 配平花括号抽函数体且**跳过注释/字符串里的花括号**（sr8 CountMomentum 注释里 `//for(){` 的坑）；同时支持 `void Cls::method(){}`（.cpp）和内联 `void method(){}`（sr10/12 .hpp）。

**BODY_REPLACEMENTS 核心替换规则**（按序执行）：

| fut-alpha 写法 | 翻译结果 |
|---|---|
| `auto& snapshot = *data;` | `const auto& snapshot = msg; (void)snapshot;` |
| `snapshot.bid_prices[0]` / `data->bid_prices[0]` | `msg.BidPrice1`（0→1 下标 +1） |
| `bid_size[0]` | `static_cast<double>(msg.BidVolume1)` |
| `bid_prices[i]`（变量下标） | `bid_price_at(msg, i)`（utils.h 的 switch 辅助） |
| `.last_price/.volume/.turnover/.open_interest/.machine_time_stamp` | `msg.LastPrice` / `static_cast<double>(msg.Volume)` / `msg.Turnover` / `msg.OpenInterest` / `static_cast<int64_t>(msg.cur_time)` |
| `ask_prices = snapshot.ask_prices;`（别名指针） | 整行删除（后续 `ask_prices[i]` 直接译 `msg.X`） |
| `cfg.value("k", D)` | `json_get<double>(params, "k", D)` |
| `reset();` | `(void)0; /* reset() — cafe noop */` |
| `boost::math::sign` / `signalRepo4::` / `market_data_type` | `sign` / 去前缀 / `CNE::FUT::cne_fut_md` |
| `if(snapshot.instrument_id[1]!=m_symbol[1]) return;` | 改成注释（cafe 已按 ukey 过滤，guard 恒真） |

**命令行参数**：`--prefix`（sr7/8/9/10/12 加 `srN_` 前缀防撞名，sr5 不加）、`--class-pattern`（默认 `\w+Predictor[_\w]*`，sr9 类名不带 Predictor → `\w+`）、`--base-class`（默认 `FeatureCalc`，sr4 用 `SR4Base`）、`--skip`（跳过手写/展不开的类）。名字清洗：剥 `_fu/_fuFix/Predictor` 后缀。

**真实例子**（auto_sr5/OBI）：`snapshot.ask_size[0]*snapshot.bid_size[0]==0` → `static_cast<double>(msg.AskVolume1)*static_cast<double>(msg.BidVolume1)==0`；`buy_force = bid_size[0]*ask_prices[0]`（别名）→ `static_cast<double>(msg.BidVolume1)*msg.AskPrice1`；三段被包成上面的 IIFE-lambda 结构。`m_symbol` 成员和别名指针成员被丢弃。

## S2.2 逐目录因子清单（实测）

| family | 目录 | 因子数 | 来源 | 代表因子 |
|---|---|---|---|---|
| sr0 single | `auto_sr0/` | 19 | generator | DiffThickness, CDiffDensity, SideImbalance8, Orderchange, Push, Rebound, VolumeOrderImbalance2/3/4 |
| sr4 | `auto_sr4/` | 20 | generator(`SR4Base`) | sr4_MassCenter, sr4_MeanSpreadRatio, sr4_ArgmaxOrder, sr4_BrushingArea |
| sr5 | `auto_sr5/` | 23 | generator | OBI, MACD, TRIX, CCI, Atr, Bolling, VOI, SizePower, FillRatePredictorFix |
| sr7 | `auto_sr7/` | 24 | generator(`sr7_`) | sr7_BigTrade, sr7_SizeCorr, sr7_ResidMR, sr7_SpreadSize, sr7_EMAStd |
| sr8 | `auto_sr8/` | 24 | generator(`sr8_`) | sr8_VOI..VOI6, sr8_DeltaMACD, sr8_CountMomentum, sr8_VolReverse |
| sr9 | `auto_sr9/` | 6 | generator(`\w+`) | sr9_VwapCd, sr9_TradeFollow, sr9_PriceVolChgCorr, sr9_DiffPctChgDiff |
| sr10 | `auto_sr10/` | 21 | generator(`sr10_`) | sr10_BBIC, sr10_CorrPV, sr10_MaxSizeImbFix, sr10_SizeChgDiff |
| sr12 | `auto_sr12/` | 5 | generator(`sr12_`) | sr12_NewMinusCancel, sr12_QuoteSlopeFix, sr12_ResistanceBreak |
| **auto 小计** | | **142** | | |
| sr0 LS | `sr0_handport/LS_family.*` | 19 | handport CRTP | sr0_ls00611, sr0_ls00631_2, sr0_ls0091 |
| sr0 multi-level | `sr0_handport/MultiLevel.*` | 37 | handport 变参模板 | sr0_DBT_multi_1..5, sr0_dt_multi_2..5, sr0_sibp_multi_2..5 |
| sr0 Assist | `sr0_handport/Assist*` | 11 | handport CRTP wrap | sr0_AssistRt, sr0_AssistVO, sr0_AssistLeadLag（详见 S4） |
| sr4 BookRS | `sr4_handport/BookRS.*` | 1 | handport | 注册名 `BookRS`（无前缀，见 S2.4） |
| sr4 bar | `sr4_handport/Bar_factors.*` | 3 | handport BarGenerator CRTP | sr4_AmountProportion, sr4_BOPTechnical, sr4_MFITechnical |
| sr9 thickness | `sr9_handport/RelativeOrderBookThickness.*` | 3 | handport CRTP | sr9_RelativeOrderBookThickness, sr9_Bid/AskSlope... |
| sr10 ObThick | `sr10_handport/ObThick.*` | 3 | handport CRTP | sr10_ObThickAlp, sr10_ObThickDeltaSum, sr10_ObThickMidPRtMa |
| sr12 MaxSizeDiff | `sr12_handport/MaxSizeDiff.*` | 3 | handport 变参+共享struct | sr12_MaxSizeDiffPos/Neg/Bi |
| **handport 小计** | | **80** | | |
| **fut-alpha 派生总计** | | **222** | 全进 col_selection ✓ | |

> auto 目录 `.h` 数 ≈ 因子数（1:1）；handport 目录因子数 ≫ 文件数（一个 `.h` 用宏批量产出多个因子）。另：cafe meta `RT/BT/DBT/MT/VO`（根目录手写，5 个）+ 自研 50 列不属 fut-alpha 迁移，但同在 col_selection。

## S2.3 generator vs handport 的分界（为什么有些必须手写）

generator 是**逐 class 文本翻译器**，对「一个 fut-alpha class = 一个独立 onTradingData」有效。展不开、必须手写的 4 类：

1. **CRTP**（基类持算法、派生只改一点）—— `class LS00611 : public LS00F2<LS00611>`。generator 只抓单 class 体，无法合并基类+派生。涉及 sr0 LS(19)、sr9 thickness(3)、sr10 ObThick(3)。手写技巧：**抽共享 state struct**（`LS00F2State` 等）+ **`DECL_LS_FACTOR(名,id,字段/公式)` 宏**批量产 thin class。
2. **变参模板 multi-level** —— `DBTMultiPredictor<1,2,3,4,5>` 一个实例吐 5 值，cafe 一实例只一个值 → 展成 37 个 (family,level) 类。技巧：`template<int Level> class XMultiBase` + **`DECL_MULTI(FAMILY,LEVEL)` 宏**具体化（`SUPPORT_FACTORY_DECLARE` 不能作用于模板，必须具名派生）。
3. **bar 聚合 CRTP** —— `BarGenerator<Self> bg{this, bar_len}` 把 tick 聚合成 OHLCV bar 回调 `onBarDataReceived`。涉及 sr4 的 3 个。把 BarGenerator port 进 utils.h（含一个 fut-alpha quirk：非空 bar 分支**不更新** m_last_turnover，为 bit 对齐必须复刻）。
4. **multi-symbol / Assist**（跨合约）—— 11 个 sr0_Assist*，用 `AssistBase<Derived,State>` CRTP 双回调手写（详见 S4）。

handport 共用套路 = **共享 state struct + 宏批量产生**：宏内嵌 `SUPPORT_FACTORY_DECLARE` + init/post_init/onSnapshot/static_trigger 骨架，差异部分（公式/取哪字段）作宏参数。

## S2.4 col_selection ↔ signals 对账 + 「输出名 ≠ 类名」的坑

- `col_selection` 277 列（无重复）= 输出白名单；`signals[]` 是每个 id 的完整配置。222 个 fut-alpha 派生因子**全部命中** col_selection，无漏输出、无 by-design dead（早期 sr4 的 5 个 dead 都修活了）。
- **输出名 ≠ C++ 类名的两处**（写代码/查因子时注意）：
  1. **RT**：类名 `RT`，但 id 是 **`RT_60s`**（type 仍 `RT`，靠 `decay=60000000` 区分）——唯一「类名≠列名」。
  2. **sr4 BookRS**：`sr4_handport/BookRS.h` 注册名是无前缀的 **`BookRS`**；而 auto_sr4 里另有带前缀的 `sr4_BookRSFOD`——是两个不同因子，都在 col_selection。

## S2.5 关键坑（写代码前必读）

1. **regen 后需手动重打的 hand-fix**（`regen_all.sh` 尾部列了清单，generator 重跑会覆盖）：
   - `auto_sr7/sr7_SpreadSize.h`：`interval{6*1e9}` → `interval = 6*1e9`（防 narrowing）
   - `auto_sr8/sr8_VOI5.h`：手加 `double weight[5]={1.5,1.2,1.0,0.8,0.5};`
   - `auto_sr8/sr8_VolReverse.cpp`：init 必须预填 `returns(9)/max_volatility(30)/min_returns(30)=0`（复刻 reset()，**唯一真 cafe bug 的修复点**）
   - `auto_sr10/sr10_SizeChgDiff.cpp`、`auto_sr12/sr12_ResistanceBreak.h`（int→double）
   - 定位：搜 `Hand-fixed` / `hand-added` / `promoted from int` 注释。
2. **single vs multi 数值差 10–1000× 是 by design**（debug.md Q12）：如 `DiffDensity`(single) 和 `sr0_dd_multi_2`(multi) 公式不同（multi 分母只用 level-2 cumBid），naming overlap 误导，**不是 bug**。
3. **`Fix/Fast` 后缀是 fut-alpha 的修正版变体**，不是 cafe 加的（FillRatePredictorFix、sr8_SpreadPredictorFix、sr10_MaxSizeImbFix 等）。
4. **CircularBuffer / br:: 类型是「忠实复刻含 UB」**：utils.h 的 `CircularBuffer` 注释明说 fut-alpha 原版 `reserve()` 不改 size、越界访问是 UB，但为逐 bit 一致照搬；`br::ring_buffer/multi_window_queue` 是为编译过做的薄 stub（std::deque 背）。
5. **`SUPPORT_FACTORY_DECLARE` 注入私有 ctor** 会抑制隐式默认 ctor，但 `newInstance()` 又 `new CafeName` → 所有手写宏都显式 `CafeName()=default;` 补回。
6. **EMA.h 必须在 `namespace factors_v1 {` 之前 include**（否则嵌成 `factors_v1::factors_v1::EMA`）。
7. **generator 的两个隐藏修复**（debug.md Q6）：`update_snapshot_fixedNum` override 提取（sr4 MeanSpreadRatio 等重写基类方法，不当 shadowing 重 emit 会调到基类版→deque 永空→输出恒 0）；`void Cls::  method` 双空格 gap 的 `\s*::\s*` 容忍（否则 sr4_HighLowTunnel 抽不出 body）。

---
---

# 【S3】OFR 订单流重建引擎（41 因子 + 9 探针）

> 深挖 `fut2cafe/plugin/factors_v1/ofr/`：把 Python OFR v8 批处理重建移植成 cafe 的**逐 snapshot 在线 C++**，每 ukey 一个共享引擎、41 因子共享读。系数/字段全部从代码读出。

## S3.1 在线重建算法（OFRRecon.hpp，逐 snapshot）

入口 `updateCumulative()`（cafe 喂数路径，先把累计 Volume/Turnover **差分**成逐 tick：`v = cum - prev_cum`、`amt = cum_turn - prev_cum_turn`，截负）→ `updateRaw()`（真正算法）。**session 标注**：`gap_s>120` 或集合竞价（08:59/20:59）或首 tick ⇒ session 起点，清零 `sess_signed_/sess_volume_/cvd_`。

**① 方向概率 `raw_prob`（6 项加权）**：权重 `AMOUNT_W=0.60, LAST_W=0.18, DEPTH_W=0.16, QUOTE_W=0.06, TICK_W=0.001, MICRO_W=0.003`（归一化后作用于）：`amount_prob`(vwap 在买卖价区间位置) / `last_prob`(最新价位置) / `depth_prob`(5档减少量加权 `exp(-0.55k)`) / `quote_prob`(中价位移) / `tick_prob`(上行 0.76/下行 0.24/平 0.5) / `micro_prob`(微价位置) → `clamp(·, 0.02, 0.98)`。

**② 7 候选买量的 argmin**：候选 = {floor/ceil/round(top_float), round(v·raw_prob), round(v·last_prob), 全买, 全卖}；目标函数 `score = amount_err + 1.45·|p-raw_prob| + 0.40·|p-last_prob| + depth_pen(0.25,方向与深度不一致) + repl_pen(0.18,quote补充)`，取 argmin。`evidence_prob = clamp(0.84·raw_prob + 0.16·best_prob_amt, 0.02, 0.98)`。

**③ prior + 在线 session 校准**：method 分 A/B/C/NoTrade（按 amount_err/consistency/|raw_prob-0.5| 判），置信度 A=0.90+、B=0.56+、C=0.28。**跨日 prior**：`buy_prob_prior = sigmoid(logit(evidence)+prior_offset·gate)`（`prior_offset` 默认 0 ⇒ 恒等）。**在线校准**：`imbalance_before = sess_signed_/sess_volume_`（用**当前 tick 之前**的累计），`online_off = clamp(-1.5·imbalance_before, ±0.26)·gate`，`buy_prob = sigmoid(logit(buy_prob_raw)+online_off)`，`buy_volume = round(v·buy_prob)`。**校准后才推进累计器**（保 exclude-current 语义）。

**④ 仓位四流 + 逐档分配**：`doi = clamp(oi-prev_oi, ±v)`，`v_open=0.5(v+doi)` → long_open/short_open/short_close/long_close 四流；逐档把成交量从 L1 沿价格台阶搬到 2-5 档使重建成交额逼近真实 amount，每档 `cancel = max(red-trade,0)`、`add = add_same + new + max(trade-red,0)`。

**⑤ 派生量**：`market_ofi = buy_vol - sell_vol`；`add_ofi/cancel_ofi`(逐档加权 `exp(-0.55k)`)；`book_ofi`(cont-OFI 逐档)；`cvd_ += market_ofi`(session 内累计)。

**在线性**：逐 tick 全是当前帧+上一帧的 O(1) 算术；跨 tick 只缓存「上一 snapshot 5 档 + prev_oi」和「当日 session 累计 sess_signed_/sess_volume_/cvd_」；跨日仅 `prior_offset`(默认关)。所以吞吐与原生因子同量级。

## S3.2 与 Python 真值逐位对齐的关键实现

1. **`np.rint` → `std::nearbyint`**（`rnd()`，round-half-to-even）：全引擎所有取整都走它，**绝不 `floor(x+0.5)`**（half-up 在 v=1,p=0.5 给 1 而非 0）；这也是 OPTIMIZATION 铁律「禁 -ffast-math」的原因（会改取整模式）。
2. **首行 prev=NaN → evidence=0.5**：`if(!have_prev_) evidence_prob = 0.5;`（C 侧 prev 初始化为有限的 0 会算出非 0.5，显式覆盖复刻 Python）。
3. **session 起点清零** + `book_ofi` 首行 prev=NaN→0。
4. **updateCumulative 差分**：caf 逐日跑，prev_cum 从 0 起 → 当日首行 diff = 累计值 = DCE CSV 逐 tick Volume，对齐 Python。

验证：buy/sell/market_ofi/cvd + 30 个逐档流 **100% 逐位、corr 1.0、MAE<1e-4**（prior_offset=0）。

## S3.3 共享引擎机制（OFRFactorBase.h）

CRTP 基类 `OFRFactorBase<Derived>` 派生自 `FeatureCalc`，每因子提供 `kName/onInit/onTick(msg, eng)`。
- **每 ukey 一个引擎**：`str_objs["OFR:<ukey>"]` get-or-create 一个 `shared_ptr<OFRRecon>`，同 ukey 所有 OFR 因子拿同一个。
- **每 tick 只重建一次**：`onSnapshot` 里 `if (ts != eng->lastTs())` 才 `updateCumulative`——第一个看到该 snapshot 的因子推进引擎，其余因子 `ts==lastTs()` 跳过、直接读 getter。所以订阅多少因子，每 snapshot 只重建一次（O(1)/tick）。
- **缓存引擎指针（优化 #2）**：首 tick 查一次缓存到成员 `m_eng`，之后用裸指针，省每 tick ~50 次 str_objs 查表+any_cast。
- **因子两类**：RAW（snapshot/，`(void)eng` 忽略引擎，直接读盘口）；OFR/both（flow/，从 eng 读 `buyVolume/cvd/marketOfi/addOfi/askCancel(k)/...` getter）。

## S3.4 GACommon 滚动机器（环形缓冲）

时间=int64 纳秒、窗口=秒。`RollingTime`(时间窗 O(1) sum/mean/std/back + O(N) min/max/valueAt，增量维护 sum_/sum_sq_)、`EwmTime`(pandas ewm 在线等价)、`TimeShift`(at-or-before 查询)、`CvdDirGate`(内含 TimeShift(60s)，`multiplier = 1+0.3·sign(cvd_t - cvd_{t-60s})` 落 **[0.7,1.3]**，**flow 族几乎都用它做方向门**)、`DelayedEmitter`(未来 +Ns 对齐，PostImpactResilience 用)。环形缓冲用 SoA 双 vector + **指针自增回绕替代 modulo**（比 deque + `%cap_` 快），全部 `OFR_LEGACY_ROLL` 宏可切回 deque 版。

## S3.5 因子清单（41 + 9）

**snapshot/（RAW，只读盘口）**：BookConvexity_NS / FarTouchDepthShare_W / BidAskQuoteVolRatio_W / EMV_W / ExtremeRtnAmtRatio_W / FarBlockDistanceImb_NS / HumpShiftSpeed_W / OBImbSkew_W / QueueRefillRate_W / QuoteImbalanceMomentum_W / UpAmtShare_W / VShapeReversalRate_W。

**flow/（OFR/both，多数收尾 `× cvd_gate[0.7,1.3]`）**：HAR_PD_RV_W(纯回报,不读eng) / BreakoutScore_W / CancelEscape5_W / CancelEscapeNear_W / L1CancelShockDiff_W / L1CancelShockRel_W / AddImbalance5_W / AddNetFlow_W / MarketCancelDom_R / CancelToTradeFlowRatio_W / FleetingCancelRate_W / SweepExhaustion_W / BuyProbConfZ_W / BuyProbSlope_W / AggressorRunLen / EffectiveSpread / CVDMomZ_W / FlowAccelShortLong_W / HawkesIntensityRatio_W / LargePrintHawkes_W / KyleLambdaCovVar_W / DepthAdjustedFlow / OpenIntent_W / VolRegimeFlow_W / PostImpactResilience_W / ResilienceAsymmetry_W / AbsorptionReversal_W / RestingAggrDiff_W / RestingAggrDelta_W。

**OFRProbe（9 探针）**：`OFR_buy_prob / OFR_buy_volume / OFR_sell_volume / OFR_market_ofi / OFR_cvd / OFR_add_ofi / OFR_cancel_ofi / OFR_book_ofi / OFR_confidence`——直接输出重建字段，与 Python 真值逐列核对。

> **口径校正（重要）**：磁盘上 `snapshot/` = 12 文件、`flow/` = 29 文件（共 41）；README 的「RAW 13 / OFR 28」是 gen_alpha 的**逻辑分类**——`HAR_PD_RV_W` 物理在 flow/ 但本质纯中价回报的 RAW（onTick 里 `(void)eng`），分类计入 RAW 一侧 → 13+28。两种切法总数都是 41，别被「目录数对不上」误导。

## S3.6 性能优化（宏门控 + checksum 验证）

| # | 优化 | 宏门控旧路径 | 动结果? |
|---|---|---|---|
| #1 | 权重表只算一次（`static` 首次填） | `OFR_LEGACY_WEIGHTS` | 否 |
| #2 | 缓存 per-ukey 引擎指针 | `OFR_LEGACY_LOOKUP` | 否 |
| A3 | `-O3`（无 fast-math） | `OFR_LEGACY=1` 走 -O2 | 否 |
| B1 | 环形缓冲 | `OFR_LEGACY_ROLL` | 否 |
| A1 | 跳过恒等 sigmoid(logit) | `OFR_FAST_CALIB`(**默认关**) | 可能差 ULP |

CMake 对 ALIAS target 加 `-O3` 的坑：`get_target_property(... ALIASED_TARGET)` 跳过别名，只对真实 `_shared/_static` 加。**实测**：隔离引擎 6.14×、滚动 1.35×、真实 1 月端到端 1.11×（122→110s，**逐位一致 6072 列 0 差异**）。

---
---

# 【S4】跨品种 Assist 多标的因子（生猪 lh × 玉米 c）

> 深挖 11 个 sr0 Assist 因子怎么在 cafe 的「per-ukey 单标的」引擎上实现「双合约联合出信号」。源码 `fut2cafe/plugin/factors_v1/sr0_handport/Assist*`，激活逻辑在 `scripts/run.sh`。配对来自 fut-alpha `configs/replay/sr0_all.json`（primary `lh2605` 生猪 + assist `c2605` 玉米，同月同 DCE）。**经济根因：玉米是生猪饲料成本，价格领先生猪。**

## S4.1 cafe 多标的机制（核心难点）

**天然限制**：cafe 引擎按 ukey 实例化，`onSnapshot` 只对该实例自己的 ukey 触发——一个生猪因子实例**永远收不到玉米 tick**（探针 `assist_fired=0` 实证），`UkeyContext.lastsnap` 此 build 也不填。**所以不能在一个实例里直接读另一个合约的盘口。**

**绕过方案（AssistBase.h 三件套）**：
1. **同一因子类注册两个实例**：一个绑生猪（trading，出信号）、一个绑玉米（assist-feed，喂数据）。**角色靠 `ukey_` 判定**：`ukey_==m_assist_ukey` ⇒ feed，`==m_trade_ukey` ⇒ trading（不是靠 `is_sep` 开关）。
2. **共享黑板 `GlobalData.str_objs`**：两实例通过一个 `shared_ptr<State>` 通信，key = `因子名:trade_ukey:assist_ukey`（保证每配对每因子唯一）。两实例算出同一 key ⇒ 拿到同一 State ⇒ 共享读写。
3. **单一 onSnapshot 按 ukey 分流**：
   ```cpp
   if (symbol.ukey == m_assist_ukey) {   // 玉米 tick：把玉米一档盘口写进 State + onAssistTick()(更新EMA等) + setValue(astMid)
   if (symbol.ukey == m_trade_ukey) {    // 生猪 tick：onTradingTick()(读State算信号) + stale守卫(>=50s→0) + setValue(v)
   ```

**时序**：每个玉米 tick → feed 实例更新共享 State 的玉米盘口/EMA、刷新 `lastAssistTime`；每个生猪 tick → trading 实例从 State 读最新玉米盘口、结合本合约算信号、`setValue`。feed 实例的 `setValue(astMid)` 仅为让 caf 给玉米 ukey 也写 feather（离线对照），`output:False` 非交易输出。

**CRTP 结构**：`AssistBase<Derived,State>`（裸双合约 + 50s staleness）对应 fut-alpha `AssistPredictorBase`；`AssistRel.h` 的 `RelTradingSide`（ratio 价格换算）对应 `AssistRelPredictorBase`。`AssistStateBase` 携带跨合约字段（`lastTradingTime/lastAssistTime`、`astBid/astAsk/astMid/astBidSize/astAskSize/astLastPx/astVolume/astTurnover/astValid`）+ `stale(): (lastTradingTime-lastAssistTime)>=50e9 ns`。

**ratio 机制**（`AssistRel.h`，把玉米价格投影到生猪空间）：`midEMA`(生猪mid)、`ratioEMA`(玉米mid/生猪mid，`rel_decay`默认30s)；`convertPrice(p)=p/ratioEMA`、`convertDelta(d)=d/ratioEMA`。**5 个因子用 ratio**：BookTilt/LeadLag/ExcessTrade/VO/VO2；其余 6 个不用。

## S4.2 run.sh 怎么激活（ASSIST_PRODUCT=c）

- **开关**（run.sh:40-45）：`ASSIST_FACTS` 列了 11 个因子名；`ASSIST_PRODUCT=c` 激活。
- **逐日解析玉米同月合约**（:98-107）：按生猪合约月份代码（正则 `(\d{3,4})$`）找玉米同月 ukey，没有则退回玉米主力。生猪换月时玉米 assist 自动跟换。
- **双 ukey + 注入两条 signals**（:134-150）：`ukey_select` 写生猪+玉米两行（让 caf 同时 stream 两条流）；每个 Assist 因子注入 **trading 条目**（`ukey=生猪, id=因子名, output:True`）+ **feed 条目**（`ukey=玉米, id=因子名_feed, output:False`），两条共享 `trade_ukey/assist_ukey` ⇒ 黑板同 key ⇒ 共享 State。
- **注入参数**：`decay=60e6`(astMid EMA)、`rel_decay=30e6`(ratio EMA)、`ast_book_decay=60e6`(assist 盘口量 EMA 归一化分母)、`tick_size=1.0`、`point_value=10.0`、`is_diff=False`(走比值非差值)、`is_sep=True`(EMA 只在 trading tick 更新)、`normalize=False`。与 fut-alpha sr0_all.json 一致。
- **非 Assist 模式**（:152-160）：只 stream 生猪，并从 `col_selection` **剔除** 11 个 Assist 列（否则 caf 找不到列报错）。

## S4.3 11 个因子逐个（含 fut-alpha 原型 + 算什么 + 是否用 ratio）

`astXxx`=玉米侧，`curXxx`=生猪侧，所有因子受 50s staleness 守卫。

| cafe 因子 | fut-alpha 原型 | 算什么 | ratio |
|---|---|---|---|
| **AssistLeadLag** | AssistLeadLagPredictor | 玉米盘口投影进生猪空间后的「错位压力」`bidPred=max(bestBid-curBid,0)`、`askPred=max(curAsk-bestAsk,0)`，`(bidPred-askPred)/curMid`——玉米盘口已移到生猪盘口外，预示生猪跟 | ✅ |
| **AssistBookTilt** | AssistBookTiltPredictor | 玉米盘口倾斜 `(astBidSize-astAskSize)/(astBidSize+astAskSize)` × 玉米中价收益，同号才留 | ✅ |
| AssistRt | AssistRtnPredictor | 玉米自身短期收益 `(astMid-EMA(astMid))/astMid` | ✗ |
| AssistMidTrade | AssistMidTradePredictor | 玉米成交价偏离中价的二阶差分 `(diff2-diff1)/mid` | ✗ |
| AssistExt | AssistExtPredictor | 玉米 LastPrice 透传（normalize 时 ×tick/curMid，默认 false） | ✗ |
| AssistExcessTrade | AssistExcessTradePredictor | 玉米超额成交 `ET=winsorize((vwap-prevMid)/tick)*2*sqrt(dVol/astBookEMA)` × 玉米 vwap 收益，同号才留 | ✅ |
| AssistVO | AssistVolumeOrderImbalancePredictor | 玉米盘口量变化(订单流不平衡) × 玉米中价收益，同号才留 | ✅ |
| AssistVO2 | AssistVolumeOrderImbalance2Predictor | 同 VO，唯一区别：价格下移分支 VO 记 0、VO2 记 `-prevSize`（共用 `AssistVOImpl<Derived,VO2>` 模板布尔切换） | ✅ |
| AssistPush | AssistPushPredictor | 玉米流上跑单标的 Push（盘口被穿价的对数量）透传，**稀疏事件因子** | ✗ |
| AssistOrderchange | AssistOrderchangePredictor | 玉米流上跑单标的 Orderchange（逐档量增减累乘）透传 | ✗ |
| AssistDiffDensity | AssistDiffDensityPredictor | 玉米流上跑单标的 DiffDensity（买卖侧单位价格厚度量密度之差）透传 | ✗ |

## S4.4 验证（lh2607 222102 × c 同月 220301，20260520）

11 个全部活信号（caf rc=0，各 nonzero>100）。单因子 fwd30 IC：**AssistLeadLag +0.109、AssistBookTilt +0.079** 最强，Rt/MidTrade/DiffDensity +0.018~0.036，Push 稀疏（131 非零，正常）。

**为什么 LeadLag/BookTilt 最强**：二者恰好直接编码「玉米盘口→生猪盘口」的领先关系——LeadLag 量化玉米盘口投影后越过生猪盘口的距离（就是 lead-lag 定义），BookTilt 捕捉玉米订单流方向与价格同向。+0.109 的 IC 证明「玉米作为饲料成本价格领先生猪」在 tick 级真实成立。其余是玉米自身弱信号透传，传导更间接故偏弱但仍正向。

## S4.5 坑 / 注意

1. **50s staleness 守卫**：玉米成交比生猪稀疏，超 50s 没更新 → trading 实例信号清零，防陈旧玉米盘口出错信号（移植自 fut-alpha `isStale()`）。
2. **角色靠 ukey 不靠开关**：`ukey_==assist_ukey`(feed) / `==trade_ukey`(trading)；`is_sep/is_diff` 只控 ratio EMA 更新策略，别混淆。
3. **跨合约只有黑板一条路**：`lastsnap` 不填、onSnapshot 只触发自己 ukey，所以必须「双实例 + str_objs 共享 shared_ptr<State>」——这是 cafe 单标的引擎做跨品种的唯一可行模式。
4. **is_diff=true 未实现**：replay 配置 is_diff 恒 false（走比值），cafe 故意没实现差值分支（要用需补 feed 侧 astMidEMA）。
5. **配对自动换月**：lh+c 同月同 DCE，run.sh 逐日按月份解析，生猪换月玉米跟换。

---
---

# 【S5】建模 / 回测栈

> 三套代码：`fut2cafe/model`（生产 rolling stacking）、`cafe_syin/model`（GPU 3族×4模型）、`fut2cafe/temp`（lr/grid 调参）。共享同一份数据口径（cafe feather）、同一个 tick 模拟器、同一个 dashboard 渲染器，结果可横向对比。

## S5.1 数据加载 + label

- **输入**：cafe feather `feather_dir/<ukey>/<date>.feather`（run.sh 产出）。默认 ukey 222102（lh2607 主力）。
- **特征 X** = `col_selection` 的 216 因子；`to_numeric→float32`，NaN 用 `ffill().fillna(0)`，再 **drop 零方差死因子**（LH 上约 28 个 std=0 被丢，剩约 188 live）。
- **mid** = `(BidPrice+AskPrice)/2`（不用 last_price，避免买卖跳动噪声）。**label 默认 = 15s 前向 mid 收益**，**逐日在单 feather 内算**（绝不跨日跨 session）。
- **三种横轴**（关键：tick 不是固定时长）：`horizon_ticks>0` 跨 N 个 snapshot（计数）/ `horizon>0`（默认 15s）按秒 / `horizon<=0` 用 cafe 自带 `y1min_1s`（1min）。load 时实测当日 snapshot 中位间隔 Δt 打印秒↔tick 换算（如 60 ticks@500ms=30s）。
- **EXCLUDE**：代码里叫 `META_COLS`（ukey/ticktime/DataDate/TimeStamp/盘口/y1min_1s/dummy_alpha）。`check_label_horizon.py` 扫 5/15/30/60/120 秒横轴的单因子 |IC|，自动指出 mean|IC| 最高的横轴（应训练用），并验证 `corr(y1min_1s, fwd@h)≈1` 确认 cafe 的 y 是 60s。

## S5.2 stacking 模型（stacking.py）

**两个 LGBM 基模型**：
- **回归器**（连续 label）：深树 `n_estimators=200, max_depth=10, lr≈0.041, num_leaves=160, min_data_in_leaf=800, λ1=0.09/λ2=0.38, bagging=0.55`，objective=regression。
- **三分类器**（tick 阈值 label + 类平衡权重）：浅树 `max_depth=8, lr≈0.047, num_leaves=80`，objective=multiclass(3)。三类 label：`thr = 0.5·tick_size/mid`，`y>thr→up/y<-thr→down/else flat`；类平衡权重 `1/sqrt(count)`；分类器分数 = `P(up)-P(down)`。

**stacking（无前视）**：分类器分数做**逐日 rolling pmatch 校准**——每个交易日 d 只用它**前面 10 个交易日**（trailing window）算 mean/std，把 clf 分数线性匹配到回归器近期收益量纲；最终 `pred = 0.5·reg_pred + 0.5·clf_cal`（等权）。

**walk-forward 4 折**：全样本按五分位切，第 i 折训练 `[0, oos_l)`、OOS 测第 i 个五分位 → 4 折覆盖后 80%，F4≈最后 20%（最接近真实测试）。

**真实结果**（rolling_summary.json，222102，20250520–20260520，5.6M 行/155 天）：OOS IC（stack）逐折 **0.246/0.285/0.274/0.265 ≈ 0.27 均值**，stacking 略优于单模型但提升小。sim 全段 net PnL **+646,712**（简化 sim，见边界）。

## S5.3 tick 模拟器 sim.py（简化 sign 策略）

`sign(pred)` 仓位 + 迟滞（穿反向阈值才反手），逐 tick PnL = 存货 MTM `pos·Δmid·point_value` − 交易成本 `|Δpos|·(half_spread+fee_ticks·tick)·point_value`（`half_spread=0.5·tick`、`fee_ticks=0.1`、`point_value=16`、`tick=5`）。输出 `gp`(gross)/`np`(net)，**gross−net = 累积交易成本**。**这是简化版，与 fut_syin 完整 TMStrategy 不同**——PnL 绝对值不可互比，但 dashboard 面板布局一致。

## S5.4 dashboard

`dashboard_single_stacking_full.png`（5 行）：PnL 主图（gross 虚线 / net 实线，按日绿红底纹）+ 预测分布 + 双尾 + IC 时序(50min 桶) + ToD + 方向一致性 + rolling-IC（标 4 折切换）+ pred-vs-true 散点+OLS（斜率=beta，r=IC）。`redraw_dashboard.py` 从已存 parquet 重绘**不重训**。

## S5.5 GPU 模型库（cafe_syin/model，12 模型）

3 个 sh 各起 4 模型钉 GPU0-3：
- **m1 强基线**：ridge / logistic3 / huber(SGD) / stacking(自包含 LGBM reg+3分类)
- **m2 低延迟 NN**（Huber loss）：mlp(BN+GELU) / kan_mlp(KAN B样条头) / resnet(Tabular-ResNet 残差块) / ft_lite(FT-Transformer 精简，特征分组 tokenize→2层 encoder→CLS)
- **m3 短时序 NN**（输入最近 L=32 tick）：gru / lstm / tcn(因果膨胀卷积) / flat_mlp

**common.py 自包含**（教训）：旧版 import fut2cafe → 连带 import lightgbm → 内网没装 → **训练前就 ImportError**。改成直接读 feather + 自带 IC/Sharpe + matplotlib，NN 只依赖 torch/numpy/pandas/pyarrow/matplotlib。**短时序无泄漏**：`build_seq_index` 只保留长度 L 窗口落在**同一交易日**的样本（跨日窗口剔除）。
> 口径差异：fut2cafe stacking 用 216 个 col_selection（drop 死因子后~188 live）；cafe_syin/common.py 用**全部非 META 列**（~277，含 Assist+OFR+探针）。折边界两边一致。

## S5.6 调参 temp/

- **lr_sweep**：固定其余只扫 lr（`n400/leaves63/mcs400/λ3·α1` + 样本权重：零收益行×0.5 + 线性 recency 0.3→1.0），算 IC+真实 NetPnL+Sharpe，出单/合并 dashboard。**实测**：IC 峰在 **lr=0.03（IC=0.299）**，rank_IC~0.326，ICIR~11；**net_pnl 几乎全负**（仅 lr 0.005/0.01 非负），gross 全正随 lr 升 → net 转负完全是交易成本（lr 大→预测抖→翻仓频→成本吃掉 gross）。
- **grid_sweep**：扫 reg_lr×clf_lr（7×7，省算力：各训一次再 blend）。**最高 IC≈0.307**，但 **net_pnl 全 49 格负**（−6.9M~−8.2M），`sharpe_gross`（理想 sign 策略）却全 +40~44。
- `sweeplib.py` 自包含（复制 load/evaluate/dashboard），不依赖 cafe_syin 是否最新。

## S5.7 诚实边界（相关性强 ≠ 可盈利）⭐

IC/rankIC 确实强（stacking OOS IC≈0.27、lr_sweep 峰 0.30、grid 0.31、rankIC≈0.33），**但真实成本下 net PnL 多为负**（lr_sweep 仅最小两个 lr 非负，grid 全负）。gross 全正 → net 转负完全来自交易成本。`evaluate` 的 **Sharpe 是理想化 sign 策略**（只扣极小 flip 罚）给出 +40 量级漂亮 Sharpe，但同组预测过真实 sim 后日 net Sharpe 是 −75 量级——**两者差一个交易成本结构**。外部 fut_model 也独立印证：重正则 LGBM 把相对 IC/Sharpe/ret 提 +71%/+36%/+57%（"相对+10%"达成），但过真实 TMStrategy sim 净 PnL 仍为负（"绝对盈利"未达成）。**任何"净盈利"结论都必须以真实成本 sim 为准。**

---
---

# 【S6】数值验证体系（证明 cafe 因子 == fut-alpha）

> 深挖「怎么证明移植的因子和 fut-alpha 数值一致」的基础设施。验证从弱到强三轮，最终落点是「同输入逐因子统计对比」。工具在 `cafe_syin/tools/`，报告在 `notes/analysis/`，权威叙事是 `debug.md` Q13–Q31。

## S6.1 三轮验证（从弱到强）

1. **off-feather 健康度可视化**（最弱，零依赖）：`tools/factor_viz/viz_lh_factors.py` 吃 git 里的 sanity CSV，算相对 cafe 自己 y 的 IC，出 5 图。211 因子/183 alive，|IC|≥0.05=103、≥0.10=37；family 箱线 sr9/sr0_ls/sr4 最强、sr12 最弱（fut-alpha 自己也弱）；跨市场 149 共享因子仅 1 个 sign-flip（sr7_UID）。**能证**因子像正经因子、无 family 灾难；**不能证**——完全没碰 fut-alpha 数值。
2. **研究-IC 排名对比**（弱，首次碰 fut-alpha）：`compare_futalpha_vs_cafe.py` vs fut-alpha param-search 的 best_params_by_factor.csv（同品种同 horizon）。81 共享因子，|IC| rank corr **0.449**、符号一致 **91.5%**（n=47）。**不同输入下的统计巧合度**，弱证据。
3. **同输入逐因子统计对比**（最强，见 S6.2）。

## S6.2 同输入对比的完整流程（核心）

**证明链**：输入相同 ⇒ 忠实 port ⇒ 因子值逐位一致 ⇒ 分布统计一致。
1. **cafe 跑因子记统计**（`scripts/40` → `cafe_factor_stats.py`）：每因子 mean/std/分位/skew/kurtosis/ac1/ic。
2. **SnapshotDumper dump 同一份 snapshot 成 27 列 CSV**：一个特殊 FeatureCalc，每 onSnapshot 写一行（列对齐 fut-alpha replay 的 CsvRow）。**时间列用 machine `cur_time` 不用交易所 UpdateTime**（关键，Q21/Q27）——cur_time 比 UpdateTime 早 150-450ms（实测 row1 差 454ms），与 fut-alpha 生产 machine_time_stamp 同语义；用错会让 sr7 时间区间采样因子差 7-54%。
3. **dev box conan-free 编 fut-alpha**（内网编不了，Q14/Q20）：补 stub（future_def/tech_channel/boost::sign）+ **vendor nlohmann/json 整树 44 文件**，8 repo + 235 factories 全编。
4. **fut-alpha replay 吃这份 CSV**（`scripts/33` 8 步），8 repo 各跑，按行号 merge。
5. **compare 脚本**（`compare_cafe_vs_futalpha_stats.py`）：**repo-aware 名称匹配**（跨 repo 撞名按 repo 分桶）+ **去重**（replay 在 data/finish 两回调各写一行 → 每 snapshot 2 行，stateful 因子第二行=0 → 方差减半的「√2 簇」→ 按 ts 去重）+ 全 ns 时间 + **显式 ALIAS 表**（VOI↔vol_order_imbalance 等）。
- **最终**：matched 211，**203 MATCH / 6 CLOSE / 2 DIVERGE**，覆盖 211/216（5 个无对应：OBI、sr7_Spread/SpreadSize、sr12_TradeImbUpgrade、sr4_LTBookRSLevel）。

## S6.3 覆盖率陷阱（Q29）——「148/4/0」是假象

最早报「148 MATCH/4 CLOSE/0 DIVERGE」，但加起来 152、总共 216 → **64 个被静默跳过（没参与对比 = 没验证）**。根因：名称归一化只剥 CamelCase `Predictor`，不剥 fut-alpha snake_case `_fu` → sr4/7/8 大批配不上。修法：**小写优先 + 剥 `_fu` + 保留 Fix + 显式 ALIAS 表**。修后覆盖 **152→211/216**，**更全的对比暴露了之前被隐藏的真实分歧**。**教训：验证工具的覆盖率本身要先验证——先确认分母对，再看通过率。**

## S6.4 逐个修复的真实分歧（区分真 bug vs 对比方法 bug）

| 因子 | 根因 | 结果 |
|---|---|---|
| **sr8_VolReverse** | **唯一真 cafe bug**：reset() 预填 3 个 deque(9/30/30 个 0) 被 generator 翻成 noop → 空 deque 越界读 | init() 补 assign → **MATCH** |
| sr9_PriceVolChgCorr ×2 | 同类：reset() 的 EWM 权重被丢 → 输出全 0 | init() 补设 → MATCH |
| sr4_MassCenter | calc_massCenter 公式写错 | utils.h 改对 → MATCH |
| sr4_AmountProportion | BarGenerator 多更新 m_last_turnover（fut-alpha 故意不更新的 quirk） | 删掉 → MATCH |
| sr7 RetAc/EMAStd/TRVol/ResidSpd/UID | **对比方法 bug**：dumper 早期用 UpdateTime → 采样网格错位差 7-54% | 改用 machine cur_time → MATCH |

两条系统教训：(1) generator `reset()→noop` 对「用 reset 预填容器/初始化权重」的因子是系统性隐患（VolReverse + sr9×3 都中招）；(2) per-factor 默认参数可能不同（MFI），不能想当然统一。

## S6.5 两个 deferred 残留

1. **sr9_DiffPctChgDiff**：依赖 `br::multi_window_queue`（cafe 用近似 stub），init() 补权重后从死复活但有 4× 缩放残差（cafe std 4.644 vs fa 1.167），忠实移植工程量过大，暂留。根因明确（stub 不保证 bit 对齐），只是没修。
2. **sr4_MFITechnical**（诊断方法学范例，Q31）：`repro_mfi_bargen.py` Python 逐 tick 复刻 BarGenerator+MFI **扫参数**——5/6e9 给 20.01/40.80=fut-alpha ✓，10/10e9 给 3.93/36.37=当前 cafe ✗。**源码 init() 与 config 都是 5/6e9（移植本身对），运行时 .so 却跑 10/10e9（member 默认值）**。初判「增量编译漏编」被 **clean rebuild 后仍 3.93/36.37 推翻**。3 个待查候选：init 赋值被覆盖 / stats feather 没用新 .so 重生成 / .so 加载路径不对。教训：**别在没验证的修复上写"预期 MATCH"**（上一版断言"clean rebuild 必 MATCH"被打脸）。

## S6.6 bitlevel_compare（cell 级，最终 defer）

`tools/bitlevel_compare/compare.py`：reference-agnostic cell 级 differ（max|Δ|/pearson/spearman/sign_agree），`--join row`（两边时间格式不同时按行号）+ `--self-test`（合成数据自检）。三个 reference 候选：(A) fut-alpha replay 同输入【gold】、(B) mentor canonical【探测确认没我们的因子，淘汰】、(C) numpy【太重】。**defer 原因**（Q22）：fut-alpha 内网编不了（工具链/C++20 差异）；理由是单 symbol 已 100% 覆盖、stats-level 已证健康、bit-level 锦上添花。**infra 全保留**，resume 推荐 dev box 跑。

## S6.7 怎么复现验证（最短路径）

已跑通的 stats-level：`scripts/40`(cafe 记统计) → `scripts/32`/`42`(dump 同输入 CSV) → **dev box** `scripts/31`(编 fut-alpha) + 8 repo replay → `compare_cafe_vs_futalpha_stats.py`。cell 级（deferred）：`scripts/33` 8 步全自动，但**必须 dev box 跑**。自检：`compare.py --self-test`。

---
---

# 【原始 fut-alpha vs 融入 cafe 后】到底改了什么、什么没变

> 对照 `/home/samson/future_junjie/fut-alpha`（原始 C++ 仓 "SignalRepoV3"）和 `fut2cafe`（cafe 插件版）。**一句话：因子数学一行没动，变的全是「外壳」**——原仓是自带 `replay` 可执行程序、吃 CSV 吐 CSV 的独立库；cafe 版是被 `caf` 主程序 dlopen 的插件 `.so`、吃 mdb 吐 feather。

## X.1 两套系统并排

```
【原始 fut-alpha（SignalRepoV3）】                  【融入 cafe（fut2cafe）】
独立程序自己跑                                       插件，被 cafe 引擎驱动

CSV(一合约一文件,27列)                              mdb(caf 读)
   │ replay/main.cpp 自己解析                          │ caf 解析
   ▼                                                   ▼
market_data_type                                    CNE::FUT::cne_fut_md
   │ PredictorRegistry::create(repo,name)              │ SUPPORT_FACTORY_DECLARE 工厂
   ▼                                                   ▼
DynamicPredictorBase 子类                            FeatureCalc 子类
   onConfig → reset                                    init → post_init
   每 tick: onTradingData                              每 tick: onSnapshot
            getForecasterValue ──┐                              └─ setValue
            finishMarketDataUpdate│                     （一次完成）
   │ replay 自己 writeRow                               │ caf 的 output 段写
   ▼                                                   ▼
CSV(machine_time_stamp + 每因子一列)                 feather(col_selection 白名单列)
```

## X.2 逐维度对比

| 维度 | 原始 fut-alpha | 融入 cafe 后（fut2cafe） |
|---|---|---|
| **定位** | 独立 alpha 研究库（C++20，8 个 signalRepo） | cafe 框架的一个因子插件 |
| **运行单元** | **自带 `replay` 可执行程序**（tools/replay/main.cpp） | **无可执行程序**；编成 `.so` 被 caf `dlopen` |
| **输入** | CSV（一合约一文件，replay 自己解析 27 列） | mdb（caf 读，run.sh 按日期解析合约） |
| **输出** | CSV（replay 自己 `writeRow`） | feather（caf 的 `output` 段，libcafoutput.so 写） |
| **因子基类** | `DynamicPredictorBase` / `PredictorBase`（自带 `m_deque_snapshot_fixedNum` 窗口、`m_symbol`） | `FeatureCalc`（cafe 提供，无内置窗口，自己持 deque） |
| **生命周期** | **3-phase**：`onTradingData` → `getForecasterValue` → `finishMarketDataUpdate`（+`onConfig`/`reset`/`onAssistData`） | **一次性** `onSnapshot` 里算完 `setValue`（+`init`/`post_init`） |
| **数据类型** | `market_data_type`（`machine_time_stamp`、`ask_prices[5]`、`ask_size[5]`、`instrument_id`、`open_interst`(原仓拼写)、`type`/`source`） | `CNE::FUT::cne_fut_md`（`cur_time`、`AskPrice1..5`、`AskVolume1..5`…） |
| **注册** | `PredictorVTable`（**C-ABI 函数指针表**）+ `PredictorRegistry::create(repo, name)` | `SUPPORT_FACTORY_DECLARE` 宏**静态注册**到全局工厂，caf 按字符串 type 实例化 |
| **配置** | `configs/replay/srN_all.json`：`primary`/`assist`（CSV 路径+symbol）、`factors[]`（name/alias/enabled/params）、`output.path` | `signals.json`（signals[id/type/ukey/params] + col_selection + y/model/strat 脚手架）+ `caf.json`（引擎级） |
| **选合约** | config **写死 CSV 文件路径 + symbol**（如 `lh2605_20260302.csv`） | run.sh **逐日从 universe 解析 ukey**（自动换月） |
| **多标的** | **原生支持**：replay 同时读 primary+assist 两个 CSV、按 ts 归并、`symbolMatches` 分流，因子 `onTradingData`(主)/`onAssistData`(辅) | **引擎无原生支持** → 双实例 + `str_objs` 共享黑板手写（见 S4） |
| **时间** | `machine_time_stamp`（CSV `Time` 列经 `mktime` 解析成 ns） | `cur_time`（machine 接收时间，ns）——语义等同 machine_time_stamp |
| **构建** | conan **v1** + boost 1.85 + **future-def**(内网包) + zlib，C++20，每 repo 编 static+shared lib | 复用 cafe build 树（conan 缓存），只编插件，全合进**一个** `libfactors_v1.so` |

## X.3 同一份数学，两套外壳（RT 因子）

```cpp
// ── 原始 fut-alpha ──                          // ── 融入 cafe ──
class RtnPredictor : public PredictorBase {       class RT final : public FeatureCalc {
    EMA midEMA_{60e6};                                SUPPORT_FACTORY_DECLARE(RT, "RT")
    void onConfig(const cfg_t& cfg) {                 EMA m_midEMA{60e6};
        midEMA_ = EMA(cfg["decay"].get<double>());    void init(const json& p) {
    }                                                     m_midEMA = EMA(json_get<double>(p,"decay",60e6)); }
    void onTradingData(market_data_type* data) {      void post_init(...){ register SNAPSHOT→onSnapshot; }
        double bid = data->bid_prices[0];             void onSnapshot(sym,mds,const cne_fut_md& msg){
        double ask = data->ask_prices[0];                 double bid = msg.BidPrice1;
        ... if(bidSize<=0) bid=0; ...                      double ask = msg.AskPrice1;
        double mid = 0.5*(bid+ask);                       ... 原样照抄 ...
        midEMA_.update(mid, nsToUs(                       double mid = 0.5*(bid+ask);
            data->machine_time_stamp));                   m_midEMA.update(mid, msg.cur_time/1000.0);
        value_ = (midEMA_.getValue()-mid)/mid;            setValue((m_midEMA.getValue()-mid)/mid);
    }                                                 }
    double getForecasterValue(){ return value_; }  };
};
```
**中间那段数学逐行相同**，只换：基类名、`onConfig→init`、`cfg[]→json_get`、`onTradingData→onSnapshot`、字段名（`bid_prices[0]→BidPrice1`）、`machine_time_stamp→cur_time`、`value_=X→setValue(X)`。这正是 §5 的「6 条机械替换」和 gen.py（S2）自动化的内容。

## X.4 三个最值得注意的差异

1. **多标的：原生 vs 手写黑板**。原仓 replay **天然支持**双合约——它同时打开 `lh2605.csv` + `c2605.csv`，按时间戳归并成一条事件流，`onTradingData`(生猪)/`onAssistData`(玉米) 分别喂；`getSubscribedSymbols()` 返回 `{primary,assist}` 让 replay 知道把哪个 symbol 喂给哪个因子。cafe 引擎**做不到**（per-ukey 实例化、看不到别的合约），所以 S4 那套「双实例 + `str_objs` 共享 `shared_ptr<State>`」是**为补足 cafe 能力缺口而发明的**，不是 fut-alpha 本来的写法。

2. **3-phase vs 一次性，以及 reset/finish 的意义**。原仓把「算值」(`onTradingData`)、「读值」(`getForecasterValue`)、「刷新上一 tick 状态」(`finishMarketDataUpdate`) 分三步，`reset()` 在 session 起点预填容器。cafe 只有一个 `onSnapshot`，gen.py 把三段塞进三个 IIFE-lambda（S2.1）。**这个拆分正是 S6 里「reset() 预填」类坑的根源**——`reset()`/`finishMarketDataUpdate` 在 cafe 都得显式复刻，generator 早期翻成 noop 就出 bug（VolReverse）。

3. **配置即真值来源**。`configs/replay/sr0_all.json` 是**所有参数默认值和因子清单的源头**：里面能看到 `RT decay=60000000`、`BT/DBT/ET tick_size=5.0`、`ET point_value=16.0`、11 个 `AST_*`（`rel_decay=30000000/is_diff=false/is_sep=true`，与 S4 里 run.sh 注入的参数**逐字一致**）、19 个 `ls*`、37 个 `*_multi_*`、`VO/VO2/VO3/VO4`。fut2cafe 的 signals.json.template + run.sh 注入就是把这份 config 翻译成 cafe 格式。**查某因子的原始参数/原始名，看 `fut-alpha/configs/replay/srN_all.json` 最快。**

## X.5 cafe 版**全新**的（fut-alpha 里没有）

- **OFR 重建引擎 + 41 因子 + 9 探针**（S3）：来自**另一个** Python OFR 项目（`/mnt/nvme2/syin/OFR`），fut-alpha 里完全没有。
- **日期区间 + 自动换月 runner**（run.sh）：原仓 config 写死单个 CSV，没有「跑一段日期、逐日换主力」的概念。
- **generator 工具链**（gen.py/regen_all.sh）：迁移工程自造的翻译工具。
- **建模/回测栈**（S5）：stacking、GPU 模型库、调参。

## X.6 **完全没变**的

- **因子数学公式**：逐行照搬（S6 证明 209/211 逐位一致或 <4%）。
- **参数默认值**：decay 60e6、tick_size 5.0、point_value 16.0、Assist rel_decay 30e6 等，与原仓 config 一致。
- **因子家族划分**：sr0/4/5/7/8/9/10/12 八个 repo 归属沿用。
- **时间语义**：都用 machine 接收时间（原仓 `machine_time_stamp` = cafe `cur_time`）。

> 收尾：**这次迁移是「换运行时、不换算法」**——把一个独立 CSV 研究库的因子，逐个套进 cafe 插件契约（FeatureCalc + 工厂注册 + onSnapshot + 两层 JSON），数学原封不动，再补上 cafe 缺的多标的能力（黑板）、加上 fut-alpha 没有的 OFR 和生产化 runner/建模。验证的全部意义就是证明「换了运行时之后，因子值还和原来逐位对得上」。

---
---

# 【写新因子】想加一个全新因子，怎么做

> 写一个**全新**因子（不是从 fut-alpha 迁移）。核心就是实现 cafe 因子契约（FeatureCalc 子类 + 工厂注册 + onSnapshot + setValue）+ 三处同步配置 + build/run/verify。全部在 `fut2cafe/`，编译/运行**必须在内网**（数据本地性，见 §6）。

## 写新因子 · 第 0 步：先选基类（按你的因子需要什么）

| 你的因子需要 | 继承 | 放哪个目录 | 参考 |
|---|---|---|---|
| 只用当前五档盘口 / 成交，自己持几个标量或 deque | `FeatureCalc` | `plugin/factors_v1/custom/`（新建即可） | 本节模板 |
| 时间窗滚动均值/方差/EWMA | `FeatureCalc` + 自持 deque 或 include `ofr/GACommon.hpp` 的 `RollingTime/EwmTime` | 同上 | S3.4 |
| OFR 重建的买卖量/cvd/逐档撤撤增 | `OFRFactorBase<Derived>` | `ofr/flow/` 或 `ofr/snapshot/` | S3.3 |
| 跨品种（读另一个合约） | `AssistBase<Derived,State>` | `sr0_handport/` | S4 |

> 大多数新想法是第一类（纯盘口/成交）。CMake `GLOB_RECURSE *.cpp` 会自动收编新 `.cpp`（build.sh 已 `touch` CMakeLists 强制 re-glob），**新建子目录、丢文件进去即可，不用改 CMake**。也不用碰 `create()` 入口（那是模块级的，已在 main.cpp，新因子只是往同一个 .so 里多加一个类）。

## 写新因子 · 第 1 步：因子类（纯盘口因子完整模板，可照抄）

```cpp
// plugin/factors_v1/custom/MyFactor.h
#pragma once
#include "../EMA.h"                 // 若要 EMA —— 必须在 namespace 之前 include（否则嵌成 factors_v1::factors_v1::EMA）
#include "featurebase/FeatureCalc.h"
#include "../utils.h"               // bid_price_at / ask_size_at 等 accessor

namespace factors_v1 {

class MyFactor final : public FeatureCalc {
    SUPPORT_FACTORY_DECLARE(MyFactor, "MyFactor")     // 第二参 = JSON 的 type 字段，必须逐字一致
public:
    MyFactor() = default;                              // 必须 default-constructible（注册期 ctor 不走初始化列表）
    ~MyFactor() final = default;
    void init(const nlohmann::json& params) final;
    void post_init(const SigMap& all_features) final;
    void onSnapshot(const MDSymbol& sym, MDServices* mds, const CNE::FUT::cne_fut_md& msg);
    bool static_trigger() const final { return true; }
private:
    double m_tick_size{1.0};                           // 所有成员都给默认值
    EMA    m_ema{60e6};
};

} // namespace factors_v1
```

```cpp
// plugin/factors_v1/custom/MyFactor.cpp
#include "MyFactor.h"
#include <featurebase/AllCalc.h>

namespace factors_v1 {
SUPPORT_FACTORY_IMPLEMENT(MyFactor)

void MyFactor::init(const nlohmann::json& params) {
    m_tick_size = json_get<double>(params, "tick_size", 1.0);
    m_ema = EMA(json_get<double>(params, "decay", 60e6));
}
void MyFactor::post_init(const SigMap&) {
    m_ac->m_event_store->register_callback(                    // 一次性模板：订阅快照
        this, EVENT_TYPE_SNAPSHOT,
        make_callback<EB_SNAPSHOT_CB_t>(this, &MyFactor::onSnapshot));
}
void MyFactor::onSnapshot(const MDSymbol&, MDServices*, const CNE::FUT::cne_fut_md& msg) {
    double bid = msg.BidPrice1, ask = msg.AskPrice1;
    double bidSz = static_cast<double>(msg.BidVolume1), askSz = static_cast<double>(msg.AskVolume1);
    if (bid <= 0 || ask <= 0 || bid >= ask) { setValue(0.0); return; }   // 守卫：空盘口/穿价
    double mid = 0.5 * (bid + ask);
    // ↓↓↓ 你的因子数学（这里举例：盘口失衡 × tick/mid，再叠一个 EMA 平滑）
    double imb = (bidSz - askSz) / (bidSz + askSz);
    m_ema.update(imb, msg.cur_time / 1000.0);                  // EMA 用微秒（cur_time 是 ns）
    setValue(m_ema.getValue() * m_tick_size / mid);
}
} // namespace factors_v1
```

## 写新因子 · 第 2 步：三处同步配置（漏一个就出问题）

编辑 `config/signals.json.template`：
1. **`col_selection[]` 加列名**（漏 = init 了但不写进 feather）：`"MyFactor"`。
2. **`signals[]` 加一条**（用占位符，run.sh 会逐日填）：
   ```json
   { "id": "MyFactor", "type": "MyFactor", "ukey": __UKEY__, "output": true,
     "tick_size": __TICK__, "decay": 60000000 }
   ```
3. **注册名 == JSON `type`**：上面 `SUPPORT_FACTORY_DECLARE(MyFactor, "MyFactor")` 的 `"MyFactor"` 必须等于这里的 `"type": "MyFactor"`（不一致 → 工厂返回 null → segfault）。

## 写新因子 · 第 3 步：build → run → verify（内网）

```bash
cd fut2cafe && bash scripts/build.sh                                   # GLOB 自动收新 .cpp
nm -D --defined-only $CAFE_BUILD/install/lib/libfactors_v1.so | grep MyFactor   # 看注册符号在不在
FORCE=1 bash scripts/run.sh 222102 20260518 20260518                  # 单日单 ukey 先跑通
python3 -c "import pyarrow.feather as f; t=f.read_table('<feather路径>'); print('MyFactor' in t.column_names, t.column('MyFactor')[:5])"
```
看到 `MyFactor` 列存在、值合理（量级对、不全 0、不 NaN）即成功。

## 写新因子 · 第 4 步：避坑 checklist（全是前人踩过的）

- [ ] **所有成员 default-constructible**：给默认值或默认 ctor（`SUPPORT_FACTORY_DECLARE` 注入的注册 ctor 不走初始化列表，BarGenerator 类要加 `=default`）。
- [ ] **注册名 == JSON type**（否则 segfault）。
- [ ] **三处同步**：signals[] + col_selection[] + 注册名。
- [ ] **EMA.h / 含 namespace 的头在 `namespace factors_v1 {` 之前 include**。
- [ ] **`static_trigger() const final { return true; }`** 别漏（纯虚，不实现编不过）。
- [ ] **时间单位**：`cur_time` 是 ns，EMA/时间窗多用微秒 → `cur_time/1000.0`；时间区间采样用 ns。
- [ ] **size 字段是 uint64**：参与浮点运算先 `static_cast<double>(msg.BidVolume1)`。
- [ ] **改了源码必须重跑 `build.sh`**（且只能内网编）；只改 signals.json（加/删因子、改参数）**不用重编**，run.sh 下次自动用新配置。
- [ ] **绝不 `-ffast-math`**（破坏取整/NaN，OFR 对齐铁律）。

## 写新因子 · 进阶三种

- **要滚动窗口**：`#include "../ofr/GACommon.hpp"`，持一个 `RollingTime`（O(1) sum/mean/std）或 `EwmTime` 成员，onSnapshot 里 `push(msg.cur_time, x)` 再读 `.mean()/.stddev()`；或简单情况自持 `std::deque` + 手动维护。
- **要 OFR 重建量**（买卖量/cvd/逐档撤撤增）：继承 `OFRFactorBase<MyOfrFactor>`，提供 `static constexpr char kName[]` / `onInit` / `double onTick(const cne_fut_md& msg, OFRRecon& eng)`，在 `onTick` 里读 `eng.buyVolume()/cvd()/marketOfi()/askCancel(k)...`，文件放 `ofr/flow/`，**并在 `ofr/OFRFactory.cpp` 加一行 `SUPPORT_FACTORY_IMPLEMENT(MyOfrFactor)`**（OFR 因子是显式注册，不像普通因子靠 .cpp 里的宏）。共享引擎每 tick 只重建一次，免费复用（S3.3）。
- **要跨品种**（读另一个合约）：继承 `AssistBase<MyAst, MyAstState>`（S4.1），提供 `kName` / `onAssistTick`（喂合约更新共享 State）/ `onTradingTick`（交易合约读 State 出信号），把因子名加进 `run.sh` 的 `ASSIST_FACTS`，用 `ASSIST_PRODUCT=<品种>` 跑。

> 想验证新因子数值对不对？没有 fut-alpha 原版可比（它是全新的），就走 S6 第①轮的自检思路：跑一段、看 IC/分布/稀疏度是否合理、跨合约符号是否一致（`tools/factor_viz/`）。若是某个已有 Python/research 实现的在线化（像 OFR），就按 S6.2 写「读同一份输入、逐 tick dump、和真值逐列比」的校验器。
