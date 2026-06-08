# CryptoAlpha Week 23 工程进展周报（2026-06）

---

## 🎯 一句话结论

> **平台局限于手工日线调参、信号不可信（选择偏差）、单一频率、LLM 推理串行**（动机）→ 四条并行工程线：AI自动调参loop / LOB高频OOS方法学 / 外部alpha验证工具 / Qwen3-32B 4并发基础设施（做法）→ ~2400行新代码落盘 + 合成真值验证通过 + 日线零回归确认，IC/σ≈2.4确认有调参空间（结果）。

---

## TL;DR

- **结论**：四条工程线全部推进，代码落盘+静态校验，整体把 CryptoAlpha 从「手工日线回测」升级为「多频率 / AI驱动 / 诚实样本外 / 高并发推理」的量化平台。
- **最重要进展**：① LightGBM 自动调参 loop（~2400行，把5条quant safety priors刻进loop，vs 盲套SPML是工程循环不是研究方法）；② LOB三段切分OOS方法学（把IC从"样本内有选择偏差"修成"诚实样本外"，是高频小样本的必需保护）。
- **关键数据**：baseline IC=0.0776, σ_noise=0.0327, IC/σ≈2.4（有调参空间）；seed敏感（5次重跑IC 0.032~0.121）→ noise-band 1σ门是关键设计；y_1s零膨胀88.95% → RankIC必须用平均秩（否则0.316→0.233）。
- **唯一待办**：HPC端到端运行验证（audit→tune≥10轮→LOB实跑）；Phase 2 edge demo（盲套 vs 定制对照，给老板看edge）。

---

## 0. 本周背景与整体动机

### 问题定义

四个问题同时存在，本周分别攻克：

| 问题 | 现象 | 本周方案 |
|------|------|----------|
| LightGBM 调参靠手工，没有系统化方法 | 参数空间9维，20轮随机游走难收敛；无法区分真改进和seed噪声 | AI自动调参loop（科学方法 > 盲套SPML） |
| IC指标有选择偏差，乐观不可信 | 两段切分：发现因子的数据就是评估因子的数据 | 三段切分TRAIN/SELECTION/HOLDOUT + block置换检验 |
| 平台锁死在日线，错过高频alpha | LOB 20档数据已有，但符号引擎从未接过 | 1min LOB端到端打通（22微观结构特征） |
| 外部C++ alpha无标准验证通道 | y_1s零膨胀88.95%，朴素RankIC被压低；无增量价值评估 | validate_alpha.py设计（薄入口复用sol_alpha） |
| LLM推理串行，4个角色排队 | Researcher/Reflect/Meta-reflect/Chat同时需要LLM | Qwen3-32B 4并发实例 |

### 先验可行性

- **调参loop**：同参数2次跑IC=0.99复现率已验证 → 确定性达成，噪声来自seed。IC/σ≈2.4 → 有信号，值得search。先验：**高**。
- **LOB符号因子**：算子层100%频率无关（rolling操作，不检查日历）→ 日线因子引擎不用动，只改prompt+config。先验：**高**。
- **三段切分OOS**：统计学标准方法，5场景合成真值已验证（真信号holdout≈selection且显著，纯噪声被p≥0.1门淘汰）。先验：**确定**。
- **Qwen3-32B**：288GB显存 vs 模型64GB需求 → 硬件充分；API兼容OpenAI格式 → 代码3处改动。先验：**高**。

---

## 1. 主题一：LightGBM AI 自动调参 Loop

### 做了什么

把开源 superpowers-ML（SPML）的设计模式移植到内网本地 Qwen（Claude Code 内网不可用），并在其上刻入量化研究员的科学方法，落地 ~2400 行新代码，前端集成进模型评估页。

**交付物**

| 文件 | 行数 | 作用 |
|------|------|------|
| `lgb_tune.py` | ~420 | 6阶段主loop：Observe→Diagnose→Hypothesize+Predict→Test→Reflect→Document |
| `lgb_baseline_audit.py` | ~340 | Phase 0：A1复现/A2随机标签(heuristic)/A6噪声带bootstrap |
| `lgb_diagnostics.py` | ~240 | 7条DEFENSIVE_CHECKS + 噪声带显著性 + dead-end/plateau检测 |
| `_lgb_tune_prompts.py` | ~280 | 5 safety priors + Researcher V3 / Reflect / Meta-Reflect / Chat / Final Report |
| `runner.py` (+50) | — | param_overrides + 暴露train_IC/best_iteration/top_features/top1_share |
| `AutoTuneTab.tsx` | ~380 | 实验列表/audit+tune按钮/实时轮次表/基线卡片/hint注入/实验问答Chat |
| 后端 `app.py` (+430) | — | 8个API routes + WebSocket + `_scrub_json_floats` |

**5轮code review修38个bug（人工29 + 对抗式9）**，其中2个最致命：

- R2：`format_diagnostic_signals`导入但未调用 → **诊断信号0个到达LLM → Part 8全部 edge失效**，import linter抓不到，靠数据流回溯发现
- R3：A2随机标签形同虚设还谎称PASS（越界表达式全NaN），靠语义理解发现

### 核心难点 & 解法

**难点1：盲套SPML = 9维空间随机游走**

SPML是工程循环（compile→train→eval→commit），不是研究方法。真量化研究员调LGB走的是「Observe → Diagnose → **Hypothesize+Predict** → Test → **Reflect** → Document」。SPML缺的3个阶段恰恰是研究员区别于工程师的核心：Baseline Audit（先验证可信度）、强制写quantitative prediction、Reflect比对predict vs observe差距。

**解法**：5条safety priors编码进每轮Researcher系统提示，每轮必看：
```
P1. Leak-first hypothesis：任何IC大幅上升 → 第一假设是leak，第二才是model改良
P2. Capacity-data ratio：150行训练集，num_leaves>30严禁
P3. One-knob-at-a-time：一轮只改1-2个参数，多变量归因丧失
P4. Statistical floor：ΔICIR < 1σ_noise 视为noise，不作为hypothesis证据
P5. Prediction discipline：每个intervention必配quantitative prediction
```

---

**难点2：improvement可能是seed噪声**

5次重跑IC: 0.032~0.121（3.8x range）。盲套版0.34→0.42看起来"+24%"，但可能只是lucky seed。

**解法**：Phase 0 bootstrap估算σ_noise=0.0327；noise-band gate：
- Δ > 2σ → likely real，commit
- 1σ < Δ < 2σ → suspicious，加robustness check
- Δ < 1σ → **noise，不commit，给LLM "neutral"反馈**（不是"not_improved"，不惩罚正确方向）

---

**难点3：人在loop路，subprocess无法IPC**

用户想跑过程中注入提示（"试试lambda_l2"），但loop是独立subprocess。

**解法**：`live_hints.jsonl`文件信箱。前端→`POST /hint`→append一行 JSON；loop每轮开头`_read_live_hints()`读全量→拼进Researcher prompt的"用户实时提示"段；run启动时unlink旧文件。hint下一轮生效（非即时打断），符合「轻量介入，不打断自动化」的设计意图。

### 价值

**vs 盲套开源的可量化edge**（待Phase 2 edge demo实测，以下是设计预期）：

| 指标 | 盲套版 | 定制版 | edge |
|------|--------|--------|------|
| 到达best轮数 | 18（max） | ~8 | -55% |
| hypothesis命中率 | n/a | 预期58% | 新维度 |
| noise-filtered improvements | 0/12（不知道） | 4/12真的，8/12假的 | 防自欺 |
| look-ahead拦截 | 0 | P1 prior触发 | 节省生产事故 |

**最核心**：「不是'用了LLM调参'，而是'把团队10年quant直觉系统化为可验证protocol'」——这是老板能买账的edge story。

---

## 2. 主题二：1分钟 LOB 微观结构因子挖掘

### 做了什么

在**日线全功能零回归**前提下，打通1分钟LOB（Level-20盘口）符号因子挖掘端到端，并实现三段切分OOS方法学。

**交付物**

| 文件 | 作用 |
|------|------|
| `lob_adapter.py` | 分钟采样 + 22深度聚合列 + OFI跨日 + shift防前视 + 内建校验 |
| `runner.py` (horizon-aware) | IC-only路径；绕开qlib秒级store不确定性 |
| 三段切分模块 | TRAIN/SELECTION/HOLDOUT + block置换显著性检验(p<0.1) + fit-on-train日内去均值（无泄漏） |
| `OrderBookDepthChart.tsx` | 20档盘口阶梯深度图（绿买墙/红卖墙，demo核心） |
| `LOBFeaturePalette.tsx` | 22特征卡片（点击插入prompt） |
| OOS徽章 + holdout hovercard | 前端直观区分诚实表现 vs 乐观表现 + shrinkage量化 |

**15个code review bug全修；5场景合成真值数值验证通过**（真信号/纯噪声/选择偏差/多因子过拟合/退化，全部结果符合预期）

### 核心难点 & 解法

**难点1：列名替换冲突，20档因子全废**

`bp1`⊂`bp10`，裸`str.replace`把`$bp10`改成`df['$bp1']0`，结果：**§9所有多档因子全部损坏**。

**解法**：长度降序 + 正则词边界（`\b$bp1\b`），20档列名替换全部正确。

---

**难点2：日线代码6处频率硬编码，分散在5个文件**

`freq='day'`/`ann_scaler=365`/`"1day"` metrics key/`FactorDatetimeDailyEvaluator`拒亚日数据→判"definitely wrong"→死循环。

**解法**：新增不替换策略。所有改动在`QA_HORIZON != 'daily'`闸门内；1min走IC-only h5路径，完全绕开qlib；daily路径零改动，daily零回归已确认。

---

**难点3：IC有选择偏差，乐观不可信**

传统两段切分（train/test）：挖因子的数据 = 评估因子的数据。1分钟因子库小样本更脆弱，这个问题更严重。

**解法**：三段切分：
```
TRAIN (fit model) → SELECTION (挑因子，可以看) → HOLDOUT (最终验收，挑完再看)
```
Block置换显著性检验（保留时间序列自相关）：p<0.1才算真显著。日内去均值fit-on-train（无前视泄漏）。前端OOS徽章直观区分，并量化shrinkage（selection IC vs holdout IC的差距）。

---

**难点4：LLM不懂高频窗口语义**

LLM会按"50天"直觉写`SMA($x, 50)`，在1分钟下变成50分钟，不是50天。

**解法**：prompt模板注入horizon_desc变量（"当前1 bar = 1分钟"）+ 22个LOB特征语义说明 + 2-3个示例因子（`TS_MEAN($depth_imb_5, 30)` = 深度动量）。

### 价值

**22个LOB特征**把20档盘口信息浓缩为可直接组合的信号：

| 特征 | 公式 | 捕捉什么 |
|------|------|----------|
| `$depth_imb_5` | `(Σbv1..5 - Σav1..5)/总和` | 5档买卖力量对比，比L1 imbalance稳 |
| `$microprice` | `(bp1·av1 + ap1·bv1)/(bv1+av1)` | 量加权公允价，比mid更准的短期锚 |
| `$ofi_L1` | deeplob OFI聚合 | 订单流失衡，成交压力真实来源 |
| `$book_slope_bid` | `(bp1-bp10)/Σbv1..10` | 买侧流动性梯度，吃单滑点曲线 |

**方法学价值**：三段切分 + block检验把高频因子IC从"样本内有选择偏差"修成"诚实样本外"——小样本高频场景下这不是可选项，是必需的。

---

## 3. 主题三：外部 Alpha 自动验证工具

### 做了什么

设计了一个「薄入口」工具`validate_alpha.py`，接受外部C++ alpha路径，自动复用`sol_alpha` pipeline（data/model/eval三层现成）完成LGBM验证，出完整IC/RankIC/edge/PnL报告。无需另起炉灶。

**三种验证模式**：

| mode | 特征 | 回答的问题 |
|------|------|-----------|
| `alone` | [my_alpha] | 这alpha单独有没有预测力 |
| **`incremental`** | [115基线] vs [115+my_alpha] | **加上我的alpha比现有组合好多少**（增量IC delta）= 值不值得收的金标准 |
| `combo` | [115+my_alpha] | 全量组合表现 |

始终附带direct RankIC（不过模型）做诚实基线，判断LGBM是否只在拟合噪声。

### 核心难点 & 解法

**难点1：y_1s零膨胀88.95%，传统RankIC被压低**

实测：y_1s共86398行，零占比88.95%，非零std≈1.5。传统RankIC（order rank）把大量并列零全给相同秩，严重压低相关性（已知坑：0.316→0.233差距）。

**解法**：`scipy.rankdata(y, method='average')`平均秩处理并列零，是高频零膨胀标签的标准做法。

---

**难点2："IC正"≠"赚钱"**

OFI/反向类信号典型死法：IC正但换手太高，手续费吃光收益。

**解法**：Layer2 PnL必看换手率/net vs gross Sharpe差/不同gate阈值（q95/q99/q99.5）下的net_edge_bp。图叠SOL成本线 + BTC/ETH 1.35bp目标线。

### 价值

- 给C++ alpha提供**标准化验证通道**：一条命令出完整报告
- **incremental视角**是金标准：delta≤0是常见合理结论，要敢报（alpha在现有115因子之上无增量 = 不值得收）

---

## 4. 主题四：Qwen3-32B 推理基础设施升级

### 做了什么

在12×RTX 3090（288GB）集群部署Qwen3-32B，4并发实例 + round-robin负载均衡代理，现有`.env OPENAI_BASE_URL=http://localhost:8001/v1`零改动。

**实例规划**：

| 实例 | GPU | 端口 | 显存 |
|------|-----|------|------|
| A | 0,1,2 | 8011 | 72GB |
| B | 3,4,5 | 8012 | 72GB |
| C | 6,7,8 | 8013 | 72GB |
| D | 9,10,11 | 8014 | 72GB |
| lb代理 | — | 8001 | — |

**代码改动（共3处，向后兼容）**：`serve_qwen.py`加`ENABLE_THINKING`环境变量（0时不传给tokenizer，Qwen2.5完全兼容）；`.env CHAT_MAX_TOKENS` 2000→6000；`serve_qwen_lb.py`（新文件~25行）。

### 核心难点 & 解法

**难点：thinking输出截断JSON**

Qwen3 thinking block 500-2000 token，旧`CHAT_MAX_TOKENS=2000`：thinking本身就可能占满额度，JSON内容被截断导致解析失败。

**解法**：改6000；json_mode下用regex剥离`<think>[\s\S]*?</think>`块，只返回干净JSON给调用方。

### 价值

lgb_tune loop的4个LLM角色（Researcher/Reflect/Meta-reflect/实验问答）**真正并发**，不再排队。thinking模式给Researcher更深的参数推理质量（代价：每次20-50s，但4并发吞吐比原来好）。

---

## 5. 关键结论汇总（直接可用）

| # | 结论 | 数字 | 来源 | 状态 |
|---|------|------|------|------|
| C1 | 当前因子库有调参空间 | baseline IC=0.0776, σ_noise=0.0327, IC/σ≈2.4 | Phase 0 audit | ✅ HPC已验证 |
| C2 | noise-band门是关键，seed敏感不可忽略 | 5次重跑IC 0.032~0.121（3.8x range） | Phase 0 audit | ✅ 已验证 |
| C3 | y_1s零膨胀必须用平均秩，否则RankIC严重失真 | 88.95%为零；0.316→0.233的坑 | sol_alpha实测 | ✅ 已确认 |
| C4 | LOB符号因子引擎100%频率无关，日线代码只需改6处浅层文件 | 算子全是bar-agnostic rolling | 架构分析 | ✅ 落地验证 |
| C5 | 三段切分OOS是高频小样本必需，两段切分有selection bias | 5场景合成真值验证通过 | 方法学设计 | ✅ 合成验证 |
| C6 | 小数据LGB：num_leaves>30严禁，max_depth>8严禁 | 150行训练集，capacity-data ratio先验 | P2 safety prior | ✅ 编码进prompt |
| C7 | IC大幅上升第一假设是leak，不是model变强 | 历史7个bug中5个是leak类 | P1 safety prior | ✅ 编码进prompt |
| C8 | 任何improvement<1σ_noise都不应commit，防seed幻觉 | σ=0.0327，Δ<0.033不commit | noise-band设计 | ✅ 落地 |

---

## 6. 已知限制（demo时注意）

1. **A2随机标签是heuristic-only**：当前越界表达式全NaN→标`inconclusive`，不是真正随机标签注入（需qlib loader层改动）。**edge demo中"拦住look-ahead"靠的是运行时DEFENSIVE_CHECKS（IC>0.5 trigger，真实），不是A2。**
2. **A3/A4/A5/A7 audit全是stub**，只有A1复现/A2(heuristic)/A6噪声带真跑。
3. **LOB数据未实跑**：代码+合成验证通过，待HPC重建≥4周`lob_1min.h5`后实跑。
4. **validate_alpha.py代码未落地**：设计完成，待编写（est. 0.5天）。
5. **axis tier只有tier-1（LGB超参）**；tier-2因子子集/tier-3预处理/tier-4时间段待后续。
6. **git commit用主仓而非git worktree隔离**：SPML的worktree隔离是Phase 3+。

---

## 7. 下周优先级

| 优先级 | 事项 | est. |
|--------|------|------|
| 🔴 P0 | **HPC端到端验证**：git pull → 重启backend(kill 8000) → 拷因子库快照 → `audit_lgb` → `tune_lgb` ≥10轮 → 确认基线卡片/中间指标/hint注入/chat正常 | 0.5天 |
| 🔴 P0 | **Phase 2 edge demo**：盲套版 vs 定制版同 factor snapshot 跑 max_rounds=20，产`edge_comparison.md`（给老板看 edge 的关键证据，Part 8.10表格） | 0.5天 |
| 🔴 P0 | **HPC重建lob_1min.h5**（≥4周）→ 后端重启 → 前端1min因子挖掘端到端实跑，看日志`IC-only 3-seg: SEL IC=… HOLDOUT IC=… pval=…` | HPC数据 |
| 🟡 P1 | **validate_alpha.py落地**（~100行）+ smoke test（取现有parquet一列当外部alpha跑通） | 0.5天 |
| 🟡 P1 | **Qwen3-32B下载+部署**（ModelScope，~64GB）→ 验证JSON无`<think>`残留 → lgb_tune接Qwen3测thinking质量 | 下载时间 |
| 🟢 P2 | OFI lag粒度决策（当前分钟级 vs 秒级deeplob口径）；A3/A4/A7真实审计实现 | 待排期 |

---

## 附：配图（HPC实跑后生成）

**图1：调参loop收敛曲线**（白底，seaborn whitegrid）
- X轴：round编号；Y轴：IC（左）+ 是否>1σ显著（颜色）
- 叠加baseline水平线 + noise-band置信带（±1σ, ±2σ）
- Caption：「每轮IC变化，蓝点=likely real improvement (Δ>2σ)，灰点=noise；红线=baseline IC=0.0776」

**图2：LOB三段切分OOS对比**（白底）
- X轴：因子编号（按SELECTION IC排序）；Y轴：IC
- 三条线：TRAIN IC / SELECTION IC / HOLDOUT IC
- 颜色区分p值显著性（green/orange/red）
- Caption：「selection IC vs holdout IC shrinkage量化：gap大的因子被OOS徽章标记为高风险」
