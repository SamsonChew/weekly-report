# HF Crypto — SOL 回测落地 / 复现 / 开发 Pipeline 总纲

> 文档目的:把"两个仓库怎么联动 → 之前的基线做到哪 → 我们怎么先复现 → 再怎么超越"一次讲清楚。
> 配套速览见 [[hfcrypto_alpha_code]](hfcrypto_alpha_code.md) / [[hfcrypto_strategy_code]](hfcrypto_strategy_code.md);本文是它们之上的"任务作战图"。
> 日期:2026-06-03 · 标的:**SOLUSDT (ukey 110200132)** · 目标:让 SOL 回测稳定、上实盘,且**比 0528 报告做得更好**。

---

## 0. 一句话背景

大目标:**让 Solana 高频策略回测稳定、上实盘**。
crypto 的 **1 秒 alpha 目前已在实盘测试中**;之前的基线优化过 SOL 的组合 model(见 `SOL Edge Return 0528.pdf`),我接手继续优化——主要方向是**改 loss / 改建模口径,让"扣完手续费后的真实表现"更好**。

为什么 SOL 难(全篇的核心矛盾):
- **SOL 每秒真实波动极小**:`y_1s` std = **1.313 bp**,mean ≈ 0。1 秒能预测,10 秒就很难(IC 从 0.3 掉到 0.18,见下表)。
- **SOL 吃单成本高**:每笔吃单名义额 ≈ **$90–100**(小单);更关键是 SOL 的**相对价差/tick ≈ 万1(0.8bp)**,而 BTC ≈ **万0.1 或更低**——SOL 主动吃单跨价差的成本是 BTC 的约 **10 倍**(详见 §0.5 概念入门 + §3.5)。
  > ⚠️ 纠正:此前把"万1"当成 taker 手续费是错的。手续费按 VIP 等级定、同账户对所有币种相同;**万1/万0.1 指的是 tick 相对价格的占比(=最小价格颗粒度/价差成本)**,这才是币种特有、且 SOL≈10×BTC 的那个量。
- 结论:edge 必须 > 来回手续费才有 PnL。BTC/ETH 的 q99 单位成交量收益约 **+1.3~1.4 bp**,SOL 更差 → **SOL 目标也是把这个 edge 顶到一个能覆盖成本的维度**。
- **⭐ 方向定调:我们就是要在 taker(吃单 / HFTaking)里赚钱,靠"模型上的完美超越"做到——不是退回 maker 做市。** 即:把模型的尾部 net edge 顶过 SOL 的来回 taker 成本,让 HFTaking 在 SOL 上由亏转稳定盈利。**不走"SOL 改用 HFMaking 规避成本"这条路。**

### 之前的 SOL 基线是怎么做的 & 预测收益点在哪

**之前的基线（0528 报告）做了什么**
- 用 `/share/crypto_hf_alpha` 的 sr4/5/8/9 **115 个微结构因子**（+ 6 个 magnitude 特征 = 121 维）训练 LGBM 模型，预测 `y_1s`（1 秒 forward mid return）。
- 核心改进路线：**reg → clf7（7 分类）+ center decode + tail-weighting（样本按 |y| 加权）+ 深树（d11）+ 大棵（n500）+ 集成**。
- 最终 gross edge0.5% 从 +1.147bp（纯 reg 基线）提升到 **+1.751bp（ENS_AVG_Z 集成）**，+35%。
- 但 C++ run_sim 验证：HFTaking 只有在 α > 1.5bp（触发率 0.58%，~1504 笔/天）时才 net 为正，**net PnL 仅 +$0.99/day**——几乎不赚。

**预测收益点在哪（我们要超越的具体缺口）**

| 层次 | 0528 现状 | 病根 | 我们的目标 |
|---|---|---|---|
| 信号质量（gross） | edge0.5% = +1.75bp | 模型只预测方向，不预测幅度（oracle 重叠率仅 **1.4%**） | edge0.5% ≥ 1.9bp；oracle 重叠率**显著提升** |
| 变现（net） | HFTaking 多档为负，α>1.5bp 才转正，net ≈ +$1/day | SOL 来回 taker 成本（spread ~1.18bp + fee ~1.20bp = **~2.38bp/RT**）吃光 1.75bp gross | **taker 主力档 net > 0**；q99 单位成交量收益 ≥ 1.3bp |
| 覆盖量 | 每天仅 ~1504 笔有效 fills | 有效 alpha 区间极窄（只有极尾部才过成本线） | 有效 fills 做大一个量级，PnL 可持续 |

**预测收益的两个抓手**：
1. **提升幅度预测**（oracle 重叠 1.4% → 目标 5%+）：改 loss / 直接优化 tail signed edge，让模型真正挑到大波动样本，而不只是猜对方向。
2. **扩大有效覆盖**：把"alpha > 成本线"的样本从极尾部（top0.1%）推到 top1%，PnL 才有规模。

---

## 0.5 概念速查

| 术语 | 定义 | 本项目数值 |
|---|---|---|
| **bp（基点）** | 1 bp = 0.01% = 0.0001 | SOL y_1s std = 1.313 bp |
| **mid** | (best_bid + best_ask) / 2，定义"真实价格"和 return | — |
| **spread** | ask − bid，永远 > 0 | SOL ≈ 1 tick ≈ 0.8–1 bp |
| **tick** | 价格最小变动单位 | SOL tick=0.01 → **0.8 bp**；BTC ≈ 0.1 bp |
| **maker** | 挂单等成交，不跨价差，可拿 rebate，但不保证成交 | — |
| **taker** | 主动吃单，100% 成交，但付 spread + taker 手续费 | **本项目 HFTaking = taker** |
| **half-spread** | taker 进场即付的成本 = spread/2 | SOL ≈ 0.4–0.5 bp/单边 |
| **来回 taker 成本** | spread + fee×2（一买一卖） | SOL ≈ **~2.4 bp/RT**（含手续费） |
| **edge0.5%** | `mean(sign(α)·y_TRUE)` 在 \|α\| top 0.5% 子集 | 基线 1.75 bp，目标 ≥ 1.9 bp |
| **IC（信息系数）** | `corr(alpha, y_TRUE)`，看预测与真实的相关性 | 看尾部 IC，不看全局（全局被大量 y=0 主导） |

**核心矛盾一句话**：SOL 每秒可预测 edge ≈ 1.3 bp，来回 taker 成本 ≈ 1 bp（spread）+ 手续费，几乎打平 → 必须靠**模型把尾部 edge 顶过成本线**才能 net 为正。

---

## 1. 两个仓库到底怎么联动(alpha 生成 ↔ 回测)

两个 C++20 仓库,都在 `/home/samson/mlf-qyas-junjie/hf_crypto/` 下,都靠 conan 拉私有包编译。

```
crypto-ts-alpha    →  算 160+ 因子 + 提供 LGBM 组合器(产出 .so 动态库)
crypto-ts-strategy →  写策略 + 跑回测撮合(run_sim),运行时动态加载上面的 .so
```

### 1.1 关键桥梁:strategy 运行时如何拿到一个标量 alpha

不是"strategy 自己读因子 CSV",而是**运行时动态加载 alpha 仓的 .so 现场重算因子 + 现场跑 LGBM**。链路:

```
run_sim.cc (strategy 仓)
  └─ Factory::create("HFTaking") → HFTaking::on_start()
       └─ context_->get_alpha_manager()->load_ts(repo="crypto_ts_alpha", name="ult_lgbm", config)
            │   (alpha-manager 靠 cfg["alpha-manager"]["repo_path"] 找到 libcrypto_ts_alpha.so)
            └─ TSUltimateLGBM (UltimateAlphaLGBM.cc)
                 ├─ 读 config["alpha_names"](100+ 个因子名)→ 逐个 load 成子 alpha
                 ├─ ncols = 因子个数;booster = config["model"](= 训练好的 booster.txt)
                 └─ load_ts("crypto_ts_alpha","lgbm", …) → MyLgbmCombineAlpha (lgbm_combine_alpha.h)
                      ├─ LGBM_BoosterCreateFromModelfile(booster.txt)  # 载入树模型
                      └─ 每个 1s bar:把所有子因子当前值塞进特征向量
                                      → LGBM_BoosterPredictForMatSingleRowFast → value_ (标量)
```

策略侧每次 `do_once()`:
```cpp
alpha = alpha_holder_->get_value()[0];           // ← 上面那个标量预测
my_mp = md_mp*diff_ema*(1-pos_lean*logic_pos)*(1+alpha_lean*alpha);  // alpha 抬/压目标价
// my_mp 与对手盘 trade.ap/bp 比 take_thres → 决定是否吃单 → place_order
```

### 1.2 三类"alpha 产物"别混淆

| 产物 | 在哪 | 谁用 | 用途 |
|---|---|---|---|
| **因子 CSV**(逐秒因子值) | `/share/crypto_hf_alpha/{sr4,sr5,sr8,sr9}/` | python(离线) | **训练 booster.txt** 的特征矩阵 |
| **booster.txt**(树模型) | jiayi 的 `mlf-qyas/output/lgbm_*/booster.txt` | C++ ult_lgbm | 把因子→标量 alpha |
| **标量 alpha**(预测值) | run_sim 运行时内存 | HFTaking/HFMaking | 驱动下单 |

> 即:**离线用因子 CSV 训 booster(python) → 回测/实盘时 C++ 现场重算同一批因子 + 跑 booster → 标量 alpha → 下单**。
> 注意 HFTaking.json 里默认 `model` 指向 **BTC(110200172)** 的 booster,做 SOL 必须换成 SOL 的 booster 和 `ukey=110200132`。

### 1.3 ⚠️ 关键落地缺口(影响整个开发路线,务必先确认)

`lgbm_combine_alpha.h` 第 120–122 行:
```cpp
LGBM_BoosterPredictForMatSingleRowFast(lgbm_fast_handler, values_.data(), &len, &value_)
```
`&value_` 只接收**一个 double**。也就是说当前 C++ 部署链路**只能正确部署"单输出回归 booster"**。

而 0528 报告里**最强的模型全是 `lgbm_clf7`(7 分类)+ `center` decode**——多分类 booster 会输出 7 个概率,需要再做 `Σ P(k)·center[k]` 才得到标量。这一步 decode **目前 C++ 侧没有**。

> **要不要适配,一句话判定:**
> - 上**回归 booster(单输出)→ 不用改**,`&value_` 接 1 个 double 正好;
> - 上 **clf7(多分类)→ 必须改**(否则只拿到第 0 类概率或 buffer 越界)。
> 所以先做 B3.1:**确认现网实盘跑的是 reg 还是 clf**,再决定动不动 C++。

**含义:之前的基线的 +1.75bp 结果是 python sim 里的,要原样搬到 run_sim / 实盘,二选一:**
- (A) 训练一个**回归 booster**(单输出),把"分类+center decode"的效果用回归目标(如 edge 加权/tail 加权回归)逼近;**或**
- (B) **改 `lgbm_combine_alpha.h`**:`ncols`/输出按 num_class 分配,在 C++ 里做 center decode(`Σ P(k)·centers[k]`),把 centers 作为 cfg 传入。

这是我们 pipeline 的**第一个技术决策点**(见 §5)。

---

## 2. 数据确认(对应你的问题 2)

### 2.1 预算好的因子 CSV(`/share/crypto_hf_alpha`)— ✅ 可读,但有日期边界
- 目录:`sr4 / sr5 / sr8 / sr9`(就是 0528 报告用的 115 个微结构因子来源)。
- 三个 ukey 全有:`110200089=ETH`、`110200132=SOL`、`110200172=BTC`。
- **SOL 实际覆盖范围:`20260101 ~ 20260426`(共 116 天)**,分布:1月31 + 2月28 + 3月31 + 4月26。
- **⚠️ 没有 202605 的预算 CSV**。所以"202601–202605 都能测"这句话**对预算好的 CSV 不成立**——CSV 只到 4/26。

### 2.2 原始行情(`/share/data/binance_ts_data`)— ✅ 含 202605,可自己重算
- 目录 `20260501 ~ 20260531` 全在(31 天),SOL 的 book_ticker/depth_update/snapshot/trade/type_257~261 齐全。
- 整体范围 **20250601 ~ 20260602**。

### 2.3 结论:怎么"确认是不是这样测"
- **训练/评估 booster(python,纯因子)**:直接用 `/share/crypto_hf_alpha` 的 SOL CSV,可测 **202601–202604(到 4/26)**。这跟 0528 报告口径一致(训练 1/1–2/14,OOS 2/15–2/17,sim 3/22–4/26)。
- **要测 202605**:必须先用 crypto-ts-alpha 的 `genaAC` + dumper 配置,对着原始行情**自己 dump 出 SOL 的 sr4/5/8/9 因子 CSV**(原始数据有,补 5 月很直接),再训练/评估。→ 这是复现后第一个补数据动作。
- **回测 PnL(run_sim)**:不依赖预算 CSV,直接吃原始行情,因子现场重算,所以 **202601–202605 任意区间都能跑**(只要原始数据在)。

---

## 3. 复现:先把之前的基线(0528 报告)的结论整理清楚

### 3.1 实验设定(报告口径)
- 目标 `y_1s = mid.shift(-1)/mid - 1`(1 秒 forward mid return)。
- 特征:sr4/5/8/9 共 **115 个因子** + 6 个 magnitude 特征(vol_30s/120s, abs_ret_30s, vov_60s, trend_zscore_30s, sr5vol_diff)= 用到时 **121 维**。
- 训练 45 天(20260101–0214, ~3.9M 样本);OOS 3 天(0215–0217, ~259k)。
- **核心评估指标 `edge0.5%` = `mean(sign(α)·y_TRUE)` 在 |α| 排名 top 0.5% 子集上**(单位 bp)。即"我最有把握的那 0.5% 信号,平均每单位能抓到多少 bp 的真实方向收益"。

### 3.2 SOL 真实分布(为什么盯尾部)
| 分位 | 阈值 |y| | mean|y| | +side | −side |
|---|---|---|---|---|---|
| top 1% | 4.78 bp | 6.92 | +5.68 | −5.73 |
| top 0.5% | 5.97 bp | 8.31 | +6.85 | −6.98 |
| top 0.1% | 9.44 bp | 12.52 | +10.25 | −10.80 |
> 钱在尾部:整体 std 才 1.3bp,但 top0.5% 真实 |y| 有 8.3bp。所以"更关注 IC 尾部"= 把建模重心压到大波动样本上(tail-weighting)。

### 3.3 实验设计 → Baseline → 最优

**6 大类实验（共约 50+ 模型）**
1. **Baseline 扫描**（16 个）：LGBM/XGB/CatBoost × clf3/5/7/9/reg，默认超参
2. **超参调整**（16 个）：树深 d9/d11、棵数 n500/800、各种权重（tw/twq/step/rank）、clf15/21
3. **两阶段 magnitude×direction**（4 个）：二分类 magnitude 探测器 × 方向 clf7
4. **Tail 变体**（4–8 个）：dart booster、clf31、multi-seed bagging
5. **最优配方组合**（6 个）：d11+n500+twq+mag / clf15+d11_n500 / clf11_tail 等
6. **集成**（3 个）：avg_rank、avg_z、meta_lgbm

**Baseline 递进**
| 模型 | edge0.5% |
|---|---|
| lgbm_reg（默认回归） | **+1.147**（最差，印证"reg 在 SOL 不行"） |
| lgbm_clf7 + ordinal | +1.299 |
| clf7 + features + tail_wt | +1.490 |
| **lgbm_clf7_d11_n500（单模型最强）** | **+1.719** |
| **ENS_AVG_Z（top-N z-score 平均集成，最高）** | **+1.751** |

把 top0.5% edge 从 **1.30 → 1.75 bp（+35%）**，整体 IC 几乎不变（−0.018）。

**完整 Leaderboard Top 10**
| Rank | 模型 ID | Decode | edge0.5% | IC0.5% | OvIC | edge0.1% | sign_acc | 说明 |
|---|---|---|---|---|---|---|---|---|
| 1 | ENS_AVG_Z | N/A | **+1.751** | +0.590 | — | — | — | top-N z-score 集成 |
| 2 | lgbm_clf7_d11_n500 | center | +1.719 | +0.588 | +0.282 | +2.62 | 75.5% | **单模最强**；深+大，无权重 |
| 3 | lgbm_clf7_d11_n500_twq_mag | center | +1.712 | +0.532 | +0.266 | +2.79 | 65.9% | 二次权重 + mag 特征 |
| 4 | lgbm_clf7_d9_n500 | center | +1.704 | +0.581 | +0.282 | +2.62 | 75.8% | 默认深度 + 大棵树 |
| 5 | lgbm_clf7_d11_n500_lr05 | center | +1.702 | +0.581 | +0.282 | +2.66 | 74.7% | 中间学习率 |
| 6 | lgbm_clf11_d9_n500_tail | center | +1.692 | +0.549 | +0.285 | +2.63 | 73.8% | 11 类 + 尾部加密分箱 [-5,-2,-1,...,1,2,5]bp |
| 7 | ENS_AVG_RANK | N/A | +1.690 | +0.570 | — | — | — | rank 百分位平均集成 |
| 8 | lgbm_clf7_d9_twq_mag | center | +1.680 | +0.531 | +0.265 | +2.55 | 66.1% | 二次权重 + mag 特征 |
| 9 | lgbm_clf15_d9 | center | +1.670 | +0.499 | +0.283 | +2.76 | 70.4% | 15 类更细分箱 |
| 10 | lgbm_clf7_d9_lr01_n300 | center | +1.657 | +0.559 | +0.279 | +2.67 | 72.9% | 快学习率 |

> 共同规律：全是 d9/d11 + n500；一半用 tw/twq；全部 center decode。集成增益有限（1.719→1.751，仅 +0.032），根因：top15 模型互相关 = **0.966**，多样性极低。

**ENS_AVG_Z 完整分位分布（OOS 259k 样本）**
| topX% | n | IC | edge(bp) | mean\|y\|(bp) | sign_acc |
|---|---|---|---|---|---|
| 50% | 129,599 | +0.338 | +0.445 | 0.798 | 33.0% |
| 10% | 25,920 | +0.449 | +0.861 | 1.261 | 52.8% |
| 5% | 12,960 | +0.478 | +1.030 | 1.464 | 59.9% |
| 1% | 2,592 | +0.564 | +1.450 | 1.915 | 72.2% |
| **0.5%** | 1,296 | +0.588 | **+1.719** | 2.195 | **75.5%** |
| 0.1% | 260 | +0.611 | +2.623 | 3.190 | 80.8% |
| 0.05% | 130 | +0.605 | +3.002 | 3.585 | 80.8% |

> q99（1%）对应 edge ≈ 1.45bp，接近 BTC/ETH 的 1.3–1.4 目标，但覆盖仅 1%。模型 top0.5% 与 oracle top0.5% **重叠率仅 1.4%**——模型挑到的和真正大波动的样本几乎是两批人。

### 3.3.1 ⭐ 之前的基线"最好结果"要分两个口径看(别被 1.75 误导)

> 参照系:**同一套 alpha 在 BTC/ETH 能做到 1.x bp(q99 单位成交量 taker 收益 1.3–1.4),SOL 也必须做到这个效果。** 那"之前的基线到底做到多少"必须拆成两个口径,否则会误判。

| 口径 | 之前的基线最好 | 说明 |
|---|---|---|
| **① 模型 gross edge0.5%**(python 评估,纯信号质量) | **+1.751 bp(集成)** / **+1.719 bp(单模 clf7_d11_n500)** | 这个数字**已经够到 BTC/ETH 的 1.3–1.4 量级**,所以"模型本身"看起来不差 |
| **② taker 实测变现**(C++ HFTaking sim,真能不能赚) | **gross 1.344 bp/RT,net 仅 +$0.99/day**(HFTaking2,只放 α>1.5bp,每天 ~1504 单) | 放松到 top1%/0.5% 直接转负(edge_bp −0.98 / −0.63)→ 几乎不赚 |

**核心判断:之前的基线真实瓶颈不是 gross edge 不够(它做到 1.75),而是这个 edge 只在 α>1.5bp 的极尾部成立——样本一放大就被 SOL 来回 taker 成本(万1×2 + 半 spread)吃光,net 归零。** 根因即 §3.5 的"模型只预测方向不预测幅度"(与 oracle top0.5% 重叠率仅 1.4%)。

**我们要超越的不是把 1.75 再堆高,而是:**
- 让 **1.3+ bp 的 net edge 在更大、可持续的成交量上成立**(把"α>成本线"的有效 fills 从 ~1504/期 做大一个量级),
- 即 SOL taker 的 **q99/gross bp-per-RT 稳定 ≥ 1.3 且 net 明显为正**,与 BTC/ETH 平价。
- 抓手:模型把**幅度预测 / 尾部命中率**做对(提升 oracle top0.5% 重叠率)。

### 3.4 ✅ 有效 / ❌ 无效(直接拿来当我们的先验)
**✅ 有效**
- LGBM **clf7 最优**(top10 里 5 个是 clf7 变种);分类 > 回归。
- **深度增加有效**(d9/d11);大棵树 n=500。
- 分类映射用 **`center`**(深树上 > ordinal)；`ordinal` 在浅树上略好。
- **Tail-weighting** 稳定 +5–10%，精确定义：
  - `_tw`（linear）：`sample_weight = |y| × 1e4 + 0.5`
  - `_twq`（quadratic）：`sample_weight = (|y| × 1e4)² + 0.5`（更激进）
  - `_step`：`|y| > 1bp` 权重 5×，否则 1×
  - `_step15`：`|y| > 1.5bp` 权重 5×
  - `_rank`：按 `|y|` 百分位 rank 给权重（更平滑）
- decode 方式（K 类概率→标量 alpha）：
  - `center`：`α = Σ_k P(k) × centers[k]`（标准 expected-value）
  - `ordinal`：`α = Σ_k P(k) × (k − mid) / mid`（保留有序信息，归一化 [−1,1]）
  - `p_up_down`：`α = Σ_{k>mid} P(k) − Σ_{k<mid} P(k)`（上下侧概率差）
- magnitude 特征边际 +0.05–0.1 bp。
- 集成略好于单模(top15 模型 corr=0.966,都 >0.9 → 多样性其实很低)。
- ENS_AVG_Z_compact 具体成员：M1(lgbm_clf7_d11_n500) + M6(lgbm_clf7_d9_twq_mag) + M8(lgbm_clf7_d9_lr01_n300)——分别代表 baseline / loss 变形 / 优化变形。

**❌ 无效**
- **两阶段(magnitude×direction)**：magnitude detector 训练时 top1% pick lift **4–28×**（非常惊艳），但 OOS combined 信号只追平单 stage clf7。magnitude 的 OOS 稳定性不够。
- `argmax` decode：退化（只有 K 个离散值，无法做分位排序）。
- **mlp(PyTorch)本项目未跑成功**。
- `_huber`（Huber loss 替代 MSE）、`_q95`（分位回归 95%）：报告中列为选项，无明显突破的结论记录。

### 3.5 ⚠️ 报告暴露的真问题(我们超越的切入点)
1. **模型只预测方向、几乎不预测幅度**:模型 top0.5% 与 oracle top0.5% **重叠率仅 1.4%**。→ 信号 sign 对(0.5% 子集 sign_acc 75.5%),但没挑到真正的大波动样本。
2. **集成多样性低**(corr>0.9)→ 集成增益有限(单模 1.719 → 三模集成 1.745,只 +0.024)。
3. **最致命:扣完手续费后基本不赚钱。** 报告 python sim(20260322–0426):

| Gate | HFTaking edge_bp | HFTaking PnL/day | HFMaking edge_bp | HFMaking PnL/day |
|---|---|---|---|---|
| top 10% | −1.70 | −$129 | 0.56 | +$21 |
| top 1% | −0.98 | −$7.4 | 1.04 | +$4.0 |
| top 0.5% | −0.63 | −$2.4 | 1.29 | +$2.4 |
| top 0.1% | +1.1 | +$0.8 | 2.54 | +$1.0 |
| top 0.05% | +2.23 | +$0.9 | 3.41 | +$0.7 |

> **HFTaking 在 SOL 上几乎全程亏(只有 top0.1% 以上才转正,但量极小)**;HFMaking 微赚。C++ sim(报告末页)也印证:HFTaking 只有把阈值卡到 α>1.5bp(每天才 ~1504 fills)才 net 正(gross 1.344 bp/RT, net +$0.99)。
> **核心病根:gross edge ≈ 1.3–1.75bp,而 SOL 来回 taker 成本(万1×2 + 半个 spread)就吃掉大半 → 我们的路线是把 edge / 尾部命中顶上去(模型超越),让 taker 在更大样本上 net 为正,而不是转 maker 规避。**

**Python sim 的具体假设（20260322–0426）**

| 参数 | HFTaking_bybit | HFMaking_bybit | 说明 |
|---|---|---|---|
| spread_rt | +1.18bp | −1.18bp | taker 跨完整 spread；maker 赚完整 spread |
| fee_rt | +1.20bp | −0.40bp | taker 付费；maker 拿 rebate |
| adverse_sel | 0.0 | +1.50bp | taker 主动选时机无逆选择；maker 每笔被打吃 1.5bp |
| fill_rate | 1.0（100%） | 0.5（50%） | taker 必然成交；maker 挂单 50% 成交率 |
| edge_realization | 1.0 | 0.7 | taker 抓住 100% mid 移动；maker 只抓 70% |

> 注意：这是 **Python sim 的简化假设**，并非 C++ run_sim 的真实撮合。C++ sim 用实际行情撮合，结果更保守（α>1.5bp 才转正，gross 1.344bp/RT，net +$0.99/day）。两者均印证同一结论：HFTaking 在 SOL 上没有足够 margin。

### 3.6 本地建模工程（sol_alpha/）

> 现状:0528 报告的模型(clf7/reg/tail_wt/ensemble…)**本地都没有代码**,booster 在 jiayi 那边。方案:**不依赖 jiayi**,在 `hf_crypto/` 下新建一个 python 研究工程,把 `mlf-qyas-junjie/model_zoo/` 的代码**拷贝过来调整**,做成 **spec 驱动、可快速迭代**的建模区——这样后期改 loss / 加模型只动 config,不改框架。

**关键调整点(`model_zoo` 现状 → 我们要补的)**:
- `model_zoo/lgbm.py` 是 sklearn 风格 `BaseModel`,支持 objective / `sample_weight` / save-load —— 但**只支持二分类**。0528 用 **7 分类 clf7**,所以必须**扩展 multiclass**(clf7/clf15)。
- 0528 的 **decode**(`center`/`ordinal`/`argmax`/`p_up_down`:K 类概率→标量 alpha)`model_zoo` 没有 → 新写 `decode.py`。
- 0528 的 **label 加权**(`_tw`/`_twq`/`_step`/`_rank`/`_huber`/`_q95`)→ 新写 `weights.py`(产出 `sample_weight`,喂现成接口)。
- **集成**(ENS_AVG_Z / AVG_RANK / META)→ 新写 `ensemble.py`。

**目录结构(新增 `hf_crypto/sol_alpha/`)**:
```
hf_crypto/sol_alpha/
├── README.md
├── config/                     # ★ spec 驱动:一个模型 = 一个 yaml(可迭代)
│   └── baseline_clf7_d11_n500.yaml
├── data/
│   ├── features.py             # 读 /share/crypto_hf_alpha sr4/5/8/9 → 特征矩阵 (+6 magnitude)
│   ├── target.py               # y_1s = mid.shift(-1)/mid-1 + tick-move 分类分箱
│   └── splits.py               # train/OOS 日期切分(对齐 0528:1/1–2/14 训, 2/15–2/17 OOS)
├── models/                     # 从 model_zoo 拷贝 + 调整
│   ├── lgbm_multi.py           # 扩展 model_zoo/lgbm.py → 支持 multiclass
│   ├── weights.py              # _tw/_twq/_step/_rank … 样本权重
│   ├── decode.py               # center/ordinal/argmax/p_up_down
│   └── ensemble.py             # ENS_AVG_Z / AVG_RANK / META
├── train.py                    # spec → 训练 → 存 output/<model>/booster.txt
├── predict.py                  # booster + OOS → output/<model>/eval_<model>.csv (ts,alpha,y_1s)
├── eval/                       # = §4.5 评估(cost/eval_report/pnl_report/figures/leaderboard)
└── output/<model_id>/          # 所有产物:booster.txt + eval csv + metrics json + pnl csv + 白底图
```
- **复用 vs 拷贝**:**models 从 model_zoo 拷贝+改**(保证本地自洽可改);**评估侧 import mlf-qyas-junjie 的 `utils/metrics.py` / `visualization.py`**(已有强基建,不重造)。
- **可迭代性**:新模型/新 loss = 加一个 `config/*.yaml`(模型类型、深度、权重方案、decode),`train.py`/`predict.py`/`eval/` 全通用 → 一条命令出 booster + eval + pnl + 图,自动进 leaderboard。

---

## 3.9 📊 复现 Baseline 数据分析（展示用）

> **一句话**:用 `/share/crypto_hf_alpha` 的 **115 个 sr4/5/8/9 因子**,在 71 天 OOS（20260218–0426,N≈5.9M)上训练 + 评估 4 个模型（clf7 / clf5 / clf3 / reg），**完整复现了 0525「2. SOL model」表**——Pearson IC、Spearman IC、decile、模型排序全部对齐。
> 评估口径:Spearman 用 `scipy.rankdata` 平均秩（SOL `y_1s` 有 75.7% 为 0,必须平均秩,否则被压低）。所有图白底/DPI150。

### 3.9.1 模型横向对比（4 单模 + 集成；⚠️ 这里全是 **gross / 扣费前** 信号指标,不是 PnL;扣费后的 net PnL 见 §3.9.4）

> **`edge0.5%` 这列是 gross(扣费前)** —— 例如 clf7=1.697bp。它 ≠ §3.9.4 python sim 的 net(−0.736bp):**net = 这个 gross(同窗口约 1.664) − 2.4bp taker 成本**。gross 1.7 < 成本 2.4 → 扣完转负,这正是基线不赚钱的核心。

| 模型 | Pearson IC | **Spearman IC** | decile bp | **edge0.5%(gross)** | **尾部 IC q95/q99/q99.5** | **oracle 重叠 q99 / q995** | turnover | 0525 Spearman |
|---|---|---|---|---|---|---|---|---|
| **clf7**（单模最强） | 0.297 | **0.314** | 1.187 | **1.697** | 0.453 / 0.497 / 0.507 | 0.086 / 0.074 | 1.140 | 0.3119 ✓ |
| **reg**（可直接进 sim） | 0.293 | 0.310 | 1.167 | 1.664 | 0.454 / 0.487 / 0.485 | **0.095 / 0.090** | 1.134 | 0.308 ✓ |
| **clf5** | 0.294 | 0.314 | 1.184 | 1.642 | 0.468 / 0.520 / 0.526 | 0.067 / 0.054 | 1.136 | 0.312 ✓ |
| **clf3** | 0.288 | 0.315 | 1.164 | 1.443 | 0.492 / 0.538 / 0.533 | 0.036 / 0.026 | 1.117 | 0.313 ✓ |
| **ENS_AVG_Z**(4模型z-score平均) | 0.297 | 0.315 | 1.188 | **1.703** | 0.475 / 0.533 / 0.544 | 0.070 / 0.059 | 1.129 | 0.3123(rankblend) ✓ |
| *0525 参考* | *0.279* | *0.31* | *1.11* | — | — | — | — | — |

> ⚠️ **尾部 IC(子集内 corr)≠ oracle 重叠(有没有挑中尾部)**:clf3 的尾部 IC 反而最高(0.492/0.538/0.533),但 oracle 重叠最低(2.6%)、edge0.5% 最低(1.443)——它在**自己挑出的那批样本里**相关性不差,问题是**挑错了人**(没挑中真正的大波动)。判断能不能赚钱看 oracle 重叠 + edge,不能只看尾部 IC。

**三个展示要点:**
1. **整体信号质量(Pearson/Spearman/decile)各模型几乎打平** —— 与 0525 结论一致,clf3≈clf5≈clf7>reg,集成也没拉开。
2. **真正分化在尾部**:edge0.5% 和 oracle 重叠上 **clf7/reg 远胜 clf3**(clf3 尾部命中仅 2.6%)。→ 整体 IC 是假象,尾部才决定能不能赚钱。
3. **reg 兼具「可直接进 C++ sim(单输出)」+「oracle 重叠最高」** → Layer-2 首选。

**⭐ ensemble 复现(ENS_AVG_Z,复现 0528 的 ensemble 思路)**:4 模型 z-score 标准化后平均。
- **成员平均相关 = 0.962**(≈ 0528 的 0.966)→ 高度同质。
- **edge0.5% = 1.703,仅比最强单模 clf7(1.697)+0.006**(0528 是 +0.032)—— 我们增益更小,因为 4 个成员(clf3/5/7/reg,全在同 115 因子+同目标)比 0528 的 15 个 clf7 变种更同质。
- **结论(复现 0528)**:**同质模型集成几乎没用**,集成要有意义必须用**低相关异质成员** → 直接论证 Phase 2 该做不同 loss/objective/horizon 的多样化模型,而非堆同family模型。

![四模型 leaderboard](../../../mlf-qyas-junjie/hf_crypto/sol_alpha/output/fig_leaderboard.png)
*图 0(5 模型,含 ENS_AVG_Z):左=edge_q99 条形(叠 BTC/ETH 1.35bp 目标线);右=oracle 重叠率 top1%/top0.5%(叠 0528 病根 0.014 参照线)。reg/clf7 尾部命中最高,clf3 垫底,集成≈clf7 不拉开。*

### 3.9.2 各模型信号面板（每张 4 子图:① edge vs gate ② IC_tail ③ alpha–y 散点 ④ oracle capture）

代表两档:**clf7**（单模最强,edge0.5%=1.697）、**reg**（oracle 重叠最高,Layer-2 首选）;clf5/clf3 图见 `output/<model>/`。

![clf7 signal](../../../mlf-qyas-junjie/hf_crypto/sol_alpha/output/baseline_clf7_d11_n500/fig_signal_baseline_clf7_d11_n500.png)
![reg signal](../../../mlf-qyas-junjie/hf_crypto/sol_alpha/output/reg_d11_n500/fig_signal_reg_d11_n500.png)

> 怎么看:**①** edge_bp 随 gate 收紧单调上升(叠成本线+目标线,看尾部能否过线);**②** 尾部 IC;**③** alpha–真实 y 散点(尾部高亮);**④** model vs oracle 的 |y| capture(差距越小越能挑中大波动)。图源 `fig_signal_<model>.png`,`eval_report.py` 一键产出。

### 3.9.3 复现质量结论(信号层)
- ✅ **Pearson + Spearman + decile + 模型排序全部对齐 0525**(±0.005)→ 115 因子复现成立。
- ✅ edge0.5%(clf7)=**1.697**,对齐 0528 的 1.719(71天 OOS vs 3天,差异在窗口)。
- ⚠️ 仅 IC_IR(我们 ~7 vs 0525 ~11)有差,系分桶大小定义不同,不影响结论。

### 3.9.4 📊 PnL —— python sim(全模型,报告 p10 格式)+ reg C++ sim 交叉验证

> **两种 PnL 见 §4.5。** 下面是 **python sim**(信号层 PnL 代理,不过 C++,所有模型都能算,偏乐观),窗口对齐 0528 = **20260322–0426(36天)**,fee=**2bp**+半价差0.4=cost 2.4bp,每笔 $90。脚本 `sol_alpha/eval/python_sim.py` 一键产出。

**统一矩阵(5 模型并列,ensemble 平等一行):net edge_bp(扣 2.4bp 成本)/ PnL-day$**

| 模型 | top10%(8640/d) | top5%(4320/d) | top1%(864/d) | top0.5%(432/d) |
|---|---|---|---|---|
| clf7 | −1.724 / −$134 | −1.546 / −$60 | −1.035 / −$8.1 | −0.736 / −$2.9 |
| reg | −1.741 / −$135 | −1.566 / −$61 | −1.063 / −$8.3 | −0.736 / −$2.9 |
| clf5 | −1.726 / −$134 | −1.551 / −$60 | −1.058 / −$8.2 | −0.783 / −$3.0 |
| clf3 | −1.743 / −$136 | −1.587 / −$62 | −1.182 / −$9.2 | −0.965 / −$3.8 |
| **ENS_AVG_Z** | −1.724 / −$134 | −1.545 / −$60 | −1.033 / −$8.0 | **−0.724 / −$2.8** |

> 完整含 gross_bp/PnL-trade 的 20 行见 `output/python_sim_summary.csv`;每格 = `net edge_bp / PnL-day$`(net = gross − 2.4bp,fee 2bp+半价差0.4)。
> **5 模型(含集成)形态完全一致**:top10%/5% 全亏(成本吃光),收紧到 top0.5% 亏损收窄但量小(432 笔/天)。**全部 gate net 都 <0 —— 这就是要超越的基线。**
> **ENS_AVG_Z 并不比最强单模好**:top0.5% −$2.8 vs clf7 −$2.9(改善 ~$0.05/day 可忽略)→ **PnL 层确认 §3.9.1 的结论:同质集成(成员相关 0.962)无用,集成要有效必须造低相关异质成员(Phase 2)。**

![python sim 全模型](../../../mlf-qyas-junjie/hf_crypto/sol_alpha/output/fig_python_sim.png)
*图:左=net edge_bp vs gate(>0 才扣费后赚,全模型在所有 gate 都 <0);右=PnL/day vs gate。*

**✅ python sim 也数值复现 0528**(报告 p10 HFTaking python sim):

| | 我们 clf7 top10% | 0528 HFTaking top10% |
|---|---|---|
| edge_bp | −1.724 | −1.70 ✓ |
| PnL/trade | −$0.0155 | −$0.015 ✓ |
| PnL/day | −$134 | −$129 ✓ |

**reg 的 C++ run_sim 交叉验证**(真实撮合,20260501,1天,fee 2bp):gross 随 gate 收紧升到 3.96bp,只有 top0.5%(3笔/天)net 转正 +1.96bp —— 与 python sim 同一形态(edge 被成本吃光、只极尾部转正)。**说明 python sim 代理可信,且 C++ 真实更保守。**

> ⭐ **复现标准 = 趋势/形态一致即可,不要求 bit-exact(共识,2026-06-04)。** 原因:我们用自己 115 因子 pipeline 训的 booster,不是 jiayi 的同一个(他自己不同次跑也未必同一个);只要结论方向一致就证明 pipeline 与口径正确。**实测趋势完全一致**:① gross edge 随 gate 收紧上升 ② ~2.4bp 成本吃光、宽 gate 全亏 ③ 只极尾部 net 转正且量小 ④ clf>reg 在尾部、clf3 垫底 ⑤ 数量级对得上(−$134 vs −$129)。信号层 **Spearman IC 0.31 甚至精确对齐**。

> ⚠️ clf3/5/7 暂只有 python sim(多分类过不了 C++ 单输出);要它们的 C++ 真实 sim,需 opt-in 改 `lgbm_combine_alpha`(§4.5 / B3,纯加法不影响回溯)。

---

## 4. 回测 PnL 怎么算

```
./run_sim <cfg> HFTaking binance
  → order_<ukey>.csv   # 每笔订单（price/qty/side/filled/commission）
  → stats_<ukey>.csv   # 每次决策快照（bbo/alpha/diff_ema）
```

PnL = `成交方向 × 量 × 后续 mid 变动 − commission`，由 `pnl_report.py` 读 order CSV 自算。  
费率：cfg `taker_commission_rate=0.0002`（默认，**SOL 实盘费率需核对**）；maker rebate = −0.00002。  
纯 SOL 单所回测：`md_ukey=trade_ukey=110200132`。参考分析脚本：`tests/summary_hf.ipynb`。

---

## 4.5 ⭐ 统一评估规范(每个模型都跑这一套,简洁 systematic,取代 0528 的零散呈现)

> 设计原则:**每个模型 = 两层评估 + 一张固定表 + 一组固定 file**,口径对齐 mlf-qyas-junjie `utils/metrics.py`,任何模型横向可比。
> 核心新增(0528 缺的):① **尾部信号 IC**(q95/q97/q99/q995)② **每单位成交量收益 bp**(gross + net)③ **标准化 PnL 输出与验证**。

### 为什么必须有 sim(确认:有必要)
信号层指标(IC/edge)全是 **gross**——没扣价差、没扣手续费、没考虑成交时机/逆选择/不一定成交。**sim 才告诉你扣完这些后到底赚不赚。**
铁证就在 0528:gross edge0.5% = 1.75bp 看着很好,但 sim net PnL ≈ +$0.99/day(几乎 0)。**所以 sim 不是可选项,是判定"模型有没有用"的终审。** 但 sim 慢,所以分两层:信号层快速筛 → sim 只验证 top-K。

### ⭐ 两种 PnL:python sim vs C++ sim(必须分清,报告也是两套)

PnL 有**两种算法**,0528/0525 报告本来就两套都给,我们一一对应:

| | **python sim(信号层 PnL 代理)** | **C++ run_sim(真实 taker PnL)** |
|---|---|---|
| 怎么算 | 直接从 eval CSV:每笔 `sign(α)·y_1s − 成本(fee+半价差)` | 真实撮合:实际成交价、IOC、HFTaking 下单逻辑、真 commission |
| 过 C++? | **不用**(纯 python 读 eval CSV) | 要(`run_sim` + `pnl_report`) |
| 多分类 clf 能算? | ✅ **所有模型都能**(python 端 decode) | ❌ clf 要先改 C++(单输出接口,见 §1.3 / B3) |
| 速度 | 秒级 | 慢(每模型一个区间 ~小时级) |
| 真实度 | **偏乐观**(假设按 mid 成交、100% 成交、抓满 1s mid 移动) | **真实/保守**(过价差→成交价更差、可能打不中、只在过 take_thres 时下单) |
| 对应报告 | 0528 p10–11 的 `dict(spread_rt,fee_rt,fill_rate,edge_realization)` + 0525 分位表 | 0528 p12 HFTaking1/2(Fills/Gross/Fee/Net)+ 0525 "Reg Sim −$647/7天" |
| 我们的产物 | `metrics_<model>.json` 的 `edge_bp/net_edge_bp`(+ 跨模型 net PnL 表) | `pnl_<model>.csv`(读 `order/stats`) |

**工作流(和报告一致)**:**python sim 先把全部模型(clf3/5/7/reg/集成)快速横比**(因为 python 能 decode 任何模型,不卡 C++ 多分类接口)→ **C++ sim 只对挑出的 top-K(如 reg)做"真能不能赚"终审**(更保守)。
> ⚠️ 关键认知:**python sim net 通常 > C++ sim net**(乐观 vs 真实)。给 mentor 横比用 python sim(全模型可比、同报告口径);判定上实盘用 C++ sim。
> ⚠️ clf 没有 C++ sim、只有 python sim,是因为多分类过不了 C++ 单输出接口——报告当年也是这么分工的(python 比全模型、C++ 验证少数)。要让 clf 也进 C++ sim,需对 `lgbm_combine_alpha` 做 **opt-in 多分类 center-decode 改动**(纯加法,不影响原框架/回溯;见 B3)。

### 两层评估

**Layer 1 — 信号层(python,纯 alpha vs `y_1s`,快,排序所有模型)**
在 OOS 上对每个模型算一张**尾部表**(gate = 按 |alpha| 取 top X%):

| gate | top% | n / coverage | thr·|α| | **edge_bp(单位成交量 gross 收益)** | IC_tail | mean·|y| | sign_acc | +side / −side |
|---|---|---|---|---|---|---|---|---|
| q50 | 50% | … | | | | | | |
| q90 | 10% | | | | | | | |
| q95 | 5% | | | | | | | |
| q97 | 3% | | | | | | | |
| q99 | 1% | | | **← "q99 单位成交量收益",目标 ≥1.3bp** | | | | |
| q995 | 0.5% | | | **edge0.5%(对齐 0528)** | | | | |

- **`edge_bp` = `mean(sign(alpha)·y_TRUE)` 在该尾部子集上(单位 bp)= 每单位成交量带来多少 bp 的(方向)收益**。这就是 mlf-qyas-junjie 的 `calc_tail_threshold_metrics` 的 `long_short`,也就是"每单位成交量 bp"。
- **`IC_tail` = `corr(alpha, y_TRUE)` 在该子集上** = mlf-qyas-junjie 的 `ic_abs_pred_q95/q99/q995`。衡量在真正交易的尾部里,alpha 大小是否还和真实幅度相关(0528 暴露的"只猜方向不猜幅度"就看这个)。
- 全局补:overall IC、hit_rate、pred 分布(q01/q50/q99)、与 **oracle 尾部重叠率**(0528 仅 1.4%,关键改进指标)。

**Layer 2 — 变现层(C++ run_sim HFTaking,只对 Layer1 的 top-K 模型跑,终审)**
把 booster 接 run_sim → `order/stats` CSV → 我们的 PnL 脚本算每个 gate(=`take_thres`):

| gate | fills/day | avg clip($) | gross_bp/RT | fee_bp | half_spread_bp | **net_bp/RT(单位成交量净收益)** | **net PnL/day** | maxDD |
|---|---|---|---|---|---|---|---|---|

- **`net_bp/RT` = gross_bp/RT − fee_bp − 半价差**= 扣完一切后每来回单位成交量真实净收益。**这是与 BTC/ETH 的 1.3–1.4bp 直接可比的那个数,也是上不上实盘的硬门槛(必须 >0 且稳定)。**
- `net PnL/day` = net_bp/RT × notional/day。0528 只算到这层的零散点,我们要给完整 gate 曲线 + 跨日稳定性。

### ⭐ 集成(ensemble)评估 —— 标准一环,但**价值由成员相关性决定**

跑完单模型后,把多个模型组合(`ensemble.py`:`ENS_AVG_Z` z-score 平均 / `ENS_AVG_RANK` rank 平均),当成一个新"模型"过同一套 Layer1/python-sim 评估。**但集成有没有用,取决于成员的相关性,不是堆数量:**

- **必做:先算成员相关矩阵 + 平均成对相关**(`ensemble.py::corr_matrix`)。这是判断集成是否值得的前提。
- **铁律(0528 + 我们都验证)**:**成员高度相关(corr≈0.96)→ 集成增益≈0**。
  - 0528:15 个 clf7 变种 corr=0.966 → edge0.5% 1.719→1.751,仅 +0.032。
  - 我们:clf3/5/7/reg corr=0.962 → 1.697→1.703,仅 +0.006;PnL top0.5% −$2.86→−$2.81,可忽略。
- **推论(指导 Phase 2)**:**要让集成真正加分,必须造低相关异质成员** —— 不同 **loss/objective**(MSE / tail signed edge / quantile)、不同 **horizon**(1s/10s)、不同 **特征子集**(`feature_fraction`),而不是同 family 堆 clf3/5/7。"异质成员"和"改 loss 顶尾部 edge"是同一件事的两面。
- **评估口径**:集成模型(如 `ENS_AVG_Z`)和单模型走**完全相同**的 `eval_report` + `python_sim`(信号 + PnL),进同一张 leaderboard 横比。

### 标准化产出（每个模型固定）

**文件**
- `eval_<model>.csv` — 逐秒 `ts/alpha/y_1s`，Layer1 原料
- `metrics_<model>.json` — Layer1 全指标（IC/edge/oracle 重叠，尾部表 q50…q995）
- `python_sim_summary.csv` — **python sim PnL(全模型,报告 p10 格式:edge_bp/PnL-trade/PnL-day)**,`eval/python_sim.py` 产出
- `pnl_<model>.csv` — Layer2 **C++ sim** 按 gate 的 fills/gross/net bp/PnL/DD（`pnl_report.py`）
- `leaderboard.csv` / `pnl_summary.csv` — 横向选模汇总表
- 集成:`ENS_AVG_Z` 等当作一个 model,产出 `eval_/metrics_/python_sim` 同款文件 + 先报**成员相关矩阵**(判断集成是否值得)

**图（白底/DPI≥150，脚本一键产出）**
- `fig_signal_<model>.png` — edge vs gate（叠成本线+BTC/ETH参考线）、IC_tail、alpha散点、oracle capture 曲线
- `fig_pnl_<model>.png` — net_bp/RT vs gate（含成本分解）、累计 PnL + maxDD、fills/day
- `fig_leaderboard.png` — 所有模型 edge_q99 / net_bp/RT 条形对比 + 相关性热图

---

## 5. 开发 Pipeline 总览

两条战线并行：**(A) 把 edge 顶上去（模型）** + **(B) 让 PnL 真正为正（执行+部署）**。

| Phase | 重点 |
|---|---|
| 0 — 打通复现 | 编译两仓、搭评估框架、复现 edge0.5%≈1.72 + sim net≈+$1/day |
| 1 — 数据+评估升级 | dump 202605 CSV；评估指标升级为 net edge（扣成本） |
| 2 — 模型迭代 | 改 loss / 提升幅度预测 / 低相关集成（目标 oracle overlap 1.4%→5%+） |
| 3 — 执行侧 | take_thres/alpha_lean 扫参；全周期 run_sim；坚持 taker |
| 4 — 上实盘前 | C++ vs python decode 数值对齐；费率/tick 核对；多日稳定性 |

**KPI（超越 0528 的判定标准）**
| 维度 | 0528 现状 | 目标 |
|---|---|---|
| edge0.5%（gross） | +1.75 bp | ≥ 1.9 bp（OOS/5月不掉） |
| net PnL/day（HFTaking） | 多档为负 | **taker 主力档稳定为正** |
| q99 单位成交量收益 | < 1.3 bp | ≥ 1.3 bp |
| oracle top0.5% 重叠率 | 1.4% | 显著提升 |
| 部署一致性 | clf 只在 python | C++ 链路可跑 clf+center |

---

---

## 附: crypto-ts-strategy 环境配置

### ✅ 专用环境 `hfcrypto`(已搭好,2026-06-03)

**strategy 仓(及 alpha 仓)统一用 `hfcrypto` 环境**:
```bash
micromamba activate hfcrypto
```

env 内容(已验证):
| 组件 | 版本 | 用途 |
|------|------|------|
| **conan** | **1.61.0** | C++ 依赖管理(已配好私有仓+只读账号+profile) |
| cmake | >= 3.15 | C++ 构建 |
| gcc/g++ | 11.4.0 | C++20 编译 |
| **系统库**(外 env) | — | make 4.3, 标准开发工具 |

**conan 已完成的一次性配置**(无需重做):
- remote `conan` → `http://18.179.181.15:8081/artifactory/api/conan/conan-local` ✅
- 只读账号 `readonly` 已登录 ✅
- profile `default`:gcc 11 / **`compiler.libcxx=libstdc++11`**(关键!)
- 私有仓 **6 个** 依赖包确认有货:
  - `crypto-def/[~1]@qwer/release` (交易所、合约定义)
  - `data-provider/[~1]@qwer/release` (历史行情回放)
  - `alpha-utils/[~1]@qwer/release` (Alpha 工具)
  - `simulation/[~1]@qwer/release` (回测框架)
  - `crypto_ts_alpha/[~1]@qwer/release` (Alpha 动态库)
  - `rapidjson/cci.20220822` (JSON 解析)

> ⚠️ 若换机器/重建 env,务必设 libcxx=libstdc++11:
> ```bash
> conan profile update settings.compiler.libcxx=libstdc++11 default
> ```

### 编译步骤

```bash
cd /home/samson/mlf-qyas-junjie/hf_crypto/crypto-ts-strategy
mkdir -p build && cd build

# 1. 拉依赖
conan install ../conanfile.txt -r conan -u

# 2. 生成构建系统(含回测可执行文件)
cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=ON

# 3. 编译
make -j$(nproc)
```

**产物**:
- `build/libcrypto_ts_strategy.so` — 策略动态库(实盘用)
- `build/tests/run_sim` — 回测程序 ★

### 快速验证

```bash
cd build/tests

# Test 策略(验证环境)
./run_sim ../../cfg/runner_cfg/Test.json Test binance

# 成功标志:日志输出到 ../../log/Test_binance/*/
ls ../../log/Test_binance/*/
```

---

## 7. 每日进展

### 2026-06-03
- 通读 0528 报告 + 两仓源码，搞清 **alpha↔strategy 联动链路**（run_sim → ult_lgbm → lgbm_combine_alpha → 标量 alpha → HFTaking 下单）。
- 发现**关键部署缺口**：`lgbm_combine_alpha` 只取单输出，clf7+center 无法原样上线（§1.3）。
- 确认数据边界：预算因子 CSV（SOL）只到 **20260426**，202605 需自己 dump（原始数据齐）。
- 整理基线结论：edge0.5% 1.30→1.75（+35%），clf7+深树+tail_wt 有效；真问题 = **只预测方向不预测幅度（oracle 重叠 1.4%）+ 扣费后 HFTaking 亏**。
- 定下开发 pipeline（Phase 0–4 + KPI）+ crypto-ts-strategy 环境配置（6 个 conan 依赖+编译步骤）。
- 定下 **§4.5 统一评估规范**（两层+固定 file+固定 2 张白底图+leaderboard，脚本一键产出）。
- 定下 **§3.7 本地建模工程**（sol_alpha/，从 model_zoo 拷贝+扩展，spec 驱动，不依赖 jiayi）。
- 定下 **§3.8 跑基线全 TODO（B0–B7）**，明确 lgbm_combine_alpha 适配判定（reg 不改/clf 必须改）。
- 下午：搭好 `sol_alpha/` 21 个文件工程，`test_synthetic` **8 项合成验证全绿**（B1.1 + B4.1/4.2/4.3）。

### 2026-06-04
- **B1.2/B1.3/B2/B5**：确认 mid 列为 `Price_1`，训练 clf7_d11_n500 基线 booster（~25min，booster.txt 12.8MB）。
  - ⚠️ 踩坑：`num_leaves=255` 在 3.9M 行极慢（69min 未完），改回默认 **31** 正常；0528 "default" = num_leaves 31 + d11 控深度。
  - 3天 OOS 结果：edge0.5% = **+1.528bp**（vs 0528 的 1.719，复现度 89%）；oracle_overlap = **5.3%**（优于 0528 的 1.4%）；gap 主因是 bin edges/center 未公开。
- **评估器升级**：新增 Spearman IC、IC_IR（50min 分桶）、decile spread；splits 加 71天长 OOS（20260218–0426）对齐 0525 口径。
  - ⚠️ 两份报告 OOS 不同：0528 = 3天（N≈259k）；0525 = 71天 rolling（N≈6.1M）——不可直接对比，需用 `oos_full` 重评。
- **0525 报告参考值整理**（信号层）：clf3/5/7 Spearman IC 基本打平（0.312–0.313），clf7 在 Pearson/IC_IR 略优；Reg Sim baseline = **−$647/7天**（默认阈值太松，铁证 edge 不足）。
- **take-size alpha 的 latency cliff 分析**：SOL 书薄导致 alpha 大，但同一个"薄"使执行延迟直接跳档（1bp/档），alpha-positive 变 alpha-negative 没有缓冲。alpha 层解法：① anticipatory 信号（book pressure 预判）② 选更长 horizon（ret_10/50+）③ 组合 decay 加权 ④ take-size 作条件变量。
- **Loss 优化方向分析**：MSE reg 天然失败（zero-inflated）；clf7 是间接改进；根本解法为直接优化 tail signed edge（custom LGBM obj）或 quantile regression，预期 edge0.5% 可从 1.72 → **1.85–1.95bp**，oracle overlap 从 1.4% → 3–6%。
- **全文解读 0528.pdf**，补完整 leaderboard Top10 / ENS_AVG_Z 完整分位表 / 权重数学定义 / decode 公式 / ENS 成员 / Python sim 假设参数，合成进 §3.3–§3.5。

### 2026-06-04（晚）— 4 模型 71 天 OOS 对比完成（对齐 0525「2. SOL model」）+ B0.3 编译
- **训练 + 71天 OOS 评估 clf3/clf5/reg（clf7 已训），统一 leaderboard：**

  | 模型 | Pearson(分桶) | Spearman(分桶) | IC_IR(s) | decile | **edge0.5%** | **oracle q99/q995** | turnover | flip | 0525 Spearman |
  |---|---|---|---|---|---|---|---|---|---|
  | clf7 | 0.297 | **0.314** | 7.03 | 1.187 | **1.697** | 0.086/0.074 | 1.140 | 31% | 0.3119 ✓ |
  | reg | 0.293 | **0.310** | 6.92 | 1.167 | 1.664 | **0.095/0.090** | 1.134 | 32% | 0.308 ✓ |
  | clf5 | 0.294 | **0.314** | 7.03 | 1.184 | 1.642 | 0.067/0.054 | 1.136 | 31% | 0.312 ✓ |
  | clf3 | 0.288 | **0.315** | 7.02 | 1.164 | 1.443 | 0.036/0.026 | 1.117 | 31% | 0.313 ✓ |
  | *0525* | *0.279* | *0.31* | *11.1* | *1.11* | — | — | — | — | — |

- **结论①(完整复现)** Pearson **+ Spearman** + decile + **模型排序** 全部对齐 0525:Spearman 0.310–0.315 vs 0525 0.308–0.313(±0.005),且 clf3≈clf5≈clf7>reg 的排序一模一样。**115 因子完整复现 0525「2. SOL model」表。**
- **结论②(Spearman 踩坑→修正)** ⚠️ **曾一度以为 Spearman 低(0.22)是因子集差异,错了 —— 是我们 Spearman 实现的 bug。** SOL `y_1s` 有 **75.7% 恰好=0**,旧实现 `argsort(argsort())` 不做并列平均秩,把这 75.7% 的 0 按时间序强排成不同秩→注入噪声→Spearman 被压到 0.233。改用 `scipy.stats.rankdata`(平均秩)后 = **0.316,完美对上 0525 的 0.312**。
  > ⭐ **教训:对 SOL 这种 ~76% 为 0 的零膨胀目标,任何 rank 类指标(Spearman/rank-IC)必须用平均秩,否则全是假的低值。**
  > fut2cafe 扩展因子集(216+OFR+assist)是**另一个项目,不纳入**;但它**不是** Spearman gap 的原因(根本没 gap)。我们锁定 115 因子,提升靠改 loss / tail edge,不堆因子。
  > IC_IR 仍 7 vs 0525 的 11 —— 分桶大小定义不同(IC_IR=均值/标准差,对桶大小极敏感),不影响结论。
- **结论③(对优化最重要)** 4 模型 **Spearman/Pearson/decile 几乎分不开**(整体信号质量打平),但 **edge0.5% 和 oracle 重叠强烈分化**:edge0.5% clf7≈reg>clf5>>clf3;oracle 重叠 **reg 最高(9.0–9.5%)** >clf7>clf5>>clf3(2.6%)。**clf3 整体 IC 打平却尾部命中最差** → 印证「整体 IC 是假象,尾部见真章」,oracle 重叠当优化中间指标成立。
- **结论④（对 Layer 2）** **reg 既单输出可直接进 C++ sim，oracle 重叠又最高** → Layer-2 首跑用 reg 是最优解,非妥协。
- **评估器**:加 turnover（mean\|Δα\|/mean\|α\|≈1.13，autocorr≈0.23，sign_flip≈31%，**模型间几乎不变** → turnover 是 1s 信号固有属性,要降得从特征/horizon 入手）;分桶 Spearman/IC_IR、oracle 重叠 4 gate 进 leaderboard。
- **B0.3 ✅** `crypto-ts-strategy` 编译跑通,`run_sim` OK（需先 export conan `LD_LIBRARY_PATH`);alpha .so = conan `crypto_ts_alpha/1.0.0`;暴露 Layer-2 命门 = **B3.2 特征对齐**（CSV 列名 ↔ C++ alpha_names）。
- **下一步**:B3.2 特征对齐 → reg booster 进 run_sim → 第一个 SOL sim 真实 PnL;并行问 B3.1 现网 reg/clf。(fut2cafe 扩展因子集已确认不纳入,提升靠改 loss / tail edge,不堆因子。)

### 2026-06-04（夜）— ⭐ Layer-2 全链路打通 + 第一个真实 SOL PnL
- **B3.2 特征对齐 = 免费**:115 因子顺序/命名 100% 对齐(C++ alpha_name = 我们列名去 `srN__` 前缀 + `_参数_idx` 后缀),全单输出 → 直接复用 `HFTaking_bn.json` 的 alpha_names+alphas 块。
- **run_sim 跨所打通**(binance SOL 算 alpha + bybit SOL 130200256 执行,跑 `exchange=bybit`):
  - 踩坑1:`md_ukey==trade_ukey`(单所)→ HFTaking 的 `trade.ready` 永远 false → do_once 全 early-return、不下单。**HFTaking 本质跨所策略**,必须 md≠trade。
  - 踩坑2(单位 bug):reg booster 训练目标是 `y_bp`(×1e4)→ 输出 alpha 大 1e4 倍 → `1+alpha_lean*alpha` 爆炸 → 74793 笔/天 garbage。**修:`train.py` 加 `target.unit=raw`,训 `reg_deploy` booster 输出原始 return** → alpha std=2.1e-5(正确)、550 笔/天(合理)。
  - ✅ booster 加载(lgbm4.6 训 / conan C++ 4.2 读,兼容)、115 因子现场计算、alpha 非零、86400 bar、干净退出。
- **第一个真实 PnL(reg_deploy,20260501,1天,fee=2bp 默认):**

  | gate | fills/day | gross_bp | net_bp(−2bp费) | PnL/day |
  |---|---|---|---|---|
  | q50 | 275 | −0.005 | −2.005 | −$0.46 |
  | q95 | 28 | +1.316 | −0.684 | −$0.02 |
  | q99 | 6 | +1.833 | −0.167 | −$0.00 |
  | q99.5 | 3 | +3.964 | **+1.964** | +$0.00 |

  > **完美复刻 0528 病根**:gross edge 真实(随 gate 收紧升到 3.96bp),但 ~2bp taker 费吃光,只有极尾部 net 转正、量极小。**这就是我们要超越的 net 基线。**
- **caveat**:① fee=2bp 是默认值,**SOL 真实 taker 费率待 B3.1 确认**(若更低则 net 整体上移);② 仅1天远OOS(训1/1-2/14);③ pnl_report 用 binance mid 标记(应 bybit,diff≈1 近似 OK)。
- **配置产物**:`crypto-ts-strategy/cfg/runner_cfg/HFTaking_sol_x.json`(跨所 SOL,指 reg_deploy booster)。
- **下一步**:① 问 B3.1 现网 reg/clf + SOL 真实费率;② 进 Phase 2 改 loss / 顶尾部 net edge(目标:让更宽的 gate net 转正,而非只有 top0.5%);③ 跑多天/全 sim 区间看 net PnL 稳定性。

---

## 8. TODO Checklist

### 复现 Baseline（B0–B7）

依赖链：B0 → (B1→B2→B5 信号线) + (B3→B6 变现线)，B4 并行；B7 收口。

**B0 环境 & 编译**
- [x] B0.1 ✅ conan/cmake/g++ 正常
- [ ] B0.2 编译 `crypto-ts-alpha` → `libcrypto_ts_alpha.so` + `genaAC`（strategy 已经 conan 拉到预编译 `crypto_ts_alpha/1.0.0`,仅 dump 因子才需本仓自编）
- [x] B0.3 ✅(2026-06-04)编译 `crypto-ts-strategy` 成功,`run_sim` 报 usage。⚠️ 运行前必须 export conan 库路径:
  `export LD_LIBRARY_PATH="$(find ~/.conan/data -path '*/package/*/lib' -type d | tr '\n' ':')$LD_LIBRARY_PATH"`
  alpha .so(repo_path 指向):`~/.conan/data/crypto_ts_alpha/1.0.0/qwer/release/package/4fba6feb7a0356786454def4a45500198552a449/lib/`;conan lightgbm=4.2.0(训练用 4.6.0,需 B3.2 核对)
- [ ] B0.4 跑通 Test 策略,`log/Test_binance/<date>/` 有输出

> ⚠️ **Layer-2 真正命门(B3.2 特征对齐):** `HFTaking.json` 的 `alpha.config.alpha_names` 是 C++ 现场算因子、按该顺序拼特征喂 booster 的列表(用**因子注册名**);我们 Python 训练用 dump CSV 的**列名**(`sr4__<因子>_<参数>_<idx>`,115列)。两套命名不同,**必须建映射 + 保证顺序一致**,否则 booster 在 sim 里吃错位特征→预测全错。比编译难。另:HFTaking.json 现指向 jiayi 的 repo_path/model(无权限),做 SOL 要全换成自己路径 + `ukey=110200132` + 单输出 **reg booster**(clf7 多输出过不了 C++ 单 double 接口)。

**B1 建模工程 + 基线 booster**
- [x] B1.1 ✅ `sol_alpha/` 骨架 + 合成验证全绿
- [x] B1.2 ✅ `Price_1`=mid 确认，115 特征，OOS std≈1.313bp
- [x] B1.3 ✅ 训练 clf7_d11_n500 booster（~25min，12.8MB）

**B2 评估原料**
- [x] B2.1 ✅ `predict.py` → `eval_clf7_d11_n500.csv`（OOS 259k 行）

**B3 部署缺口（clf7 → run_sim）**
- [ ] B3.1 确认现网是 reg 还是 clf → 决定方案 A（回归逼近）还是 B（改 C++ clf+center decode）
- [ ] B3.2 落地方案；验证 C++ alpha 与 python 逐 bar 一致（corr>0.999）

**B4 评估框架**
- [x] B4.1 ✅ `eval/cost.py`（SOL 成本模型，tick_bp=0.803）
- [x] B4.2 ✅ `eval/eval_report.py` + `figures.py`（白底/DPI 150）
- [x] B4.3 ✅ `eval/pnl_report.py`（Layer2，手算对齐）

**B5 信号层复现**
- [ ] B5.1 `eval_report.py` 跑 OOS → `edge_q995≈+1.72`，oracle overlap≈1.4%

**B6 变现层复现（run_sim）**
- [ ] B6.1 配 SOL HFTaking cfg（ukey=110200132，核对 SOL 真实 taker 费率）
- [ ] B6.2 `run_sim` 跑 20260322–0426 → `order/stats_110200132.csv`
- [ ] B6.3 `pnl_report.py` → 验证 α>1.5bp 档 `net_bp/RT≈1.34`，net≈+$1/day

**B7 收口**
- [ ] B7.1 `leaderboard.py` → `leaderboard.csv` + `fig_leaderboard.png`
- [ ] B7.2 复现判定：B5 edge0.5%≈1.72 **且** B6 net≈+$1/day → 进 Phase2

---

### Phase 1 — 数据扩展 + 评估升级
- [ ] dump SOL **202605** 因子 CSV（原始行情已有）
- [ ] 评估指标升级为 net edge（直接扣 taker 成本）
- [ ] 加 oracle 重叠率为硬指标（当前 1.4%）

### Phase 2 — 模型迭代
- [ ] 自定义 loss：直接优化 tail signed edge（custom LGBM obj）
- [ ] 分位回归（quantile reg）作为幅度预测对照
- [ ] magnitude 模型作**特征**喂方向模型（非两阶段相乘）
- [ ] 低相关集成：_ff05 / 不同标的 / 不同 horizon

### Phase 3 — 执行侧
- [ ] `take_thres / alpha_lean / gap_ms / base_qty` 扫参
- [ ] `run_sim` 202601–202605 全周期回测 HFTaking
- [ ] （对照）HFMaking 仅作参照

### Phase 4 — 上实盘前
- [ ] C++ vs python decode 逐 bar 数值对齐（corr>0.999）
- [ ] 核对 SOL 真实费率/tick(0.01)/最小下单量
- [ ] 多日 OOS 不同行情段稳定性验证

---

### 待确认（需问相关同事）
- [ ] SOL 实盘 taker 真实费率（现 cfg 默认 0.0002=2bp，偏高，需核对）
- [ ] §1.3：clf7 怎么上线的？现网跑 reg 还是 clf？（决定走方案 A/B）
- [ ] SOL booster.txt 最新版路径（HFTaking.json 现挂 BTC 的 booster）
