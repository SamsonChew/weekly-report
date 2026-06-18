# hf_crypto SOL 1s Taker Alpha —— 尝试过的所有模型形态(含效果)

标的 SOL,1s taker alpha。核心问题:零膨胀(68% y≈0)+ 大相对 tick(0.80bp)。
下表 edge0.5% 除注明外均为**研究层 gross**(71d);实盘上线线另列 net。口径不可跨层直接比。

---

## A. LGBM 分类(分箱)
| 模型 | 做法 | 效果 | 结论 |
|---|---|---|---|
| clf7 | 7类 tick 分箱 + center-decode | edge **1.697** / IC 0.314 / oracle 7.4% | 基线 |
| clf7_mag | clf7 + 6 regime 特征(无新数据) | edge **1.706** / sign 0.703 | 单模最高 |
| clf5 | 5类分箱 | edge 1.642 / oracle 5.4% | 守恒内 |
| clf3 | 3类分箱 | edge 1.443 / oracle 2.6% | sign↑ oracle 最低 |
| clf11_tick | 11类 tick 分箱 | edge 1.675 | 守恒内 |
| clf11_dynq | 11类动态分位边界 | edge 1.647 | tick 优于分位 |
| clf15_tick | 15类细分箱 | edge 1.632 / oracle 10.5% / sign 0.662 | oracle↑ sign↓ |

## B. LGBM 回归
| 模型 | 做法 | 效果 | 结论 |
|---|---|---|---|
| reg | 单输出 MSE 回归 | edge 1.664 / oracle 9.0–9.5%(最高) | 保留幅度;尾部不如 MLP |

## C. LGBM 两阶段 / 混合
| 模型 | 做法 | 效果 | 结论 |
|---|---|---|---|
| C10b cls_reg_mix | clf7 判 P(k) × 各类内 MSE | edge 1.699 / **oracle 0.101(+36%)** | 唯一破"幅度↔方向守恒" |
| C10b_tw | C10b + 极端类尾权 | oracle 0.114 / sign 0.665 | 被异常值主导 |
| I0 解耦 | gate(reg)×dir(clf7) | edge 1.648 | 方向不可转移,失败 |
| C1 / C1b 方向器 | 干净 2/3 类方向器 | edge 1.25 / 1.43,sign≈0.678 | 收敛到方向天花板 |

## D. LGBM Loss / Objective 变体
| 模型 | 做法 | 效果 | 结论 |
|---|---|---|---|
| L2b hurdle | logistic 两段 + MSE | edge 1.663 / oracle +23% | 攻零膨胀仍打不过基线 |
| L1 quantile_dual | τ=0.9/0.1 分位 | edge 1.291 | 不如分箱 |
| L3 rank_signed | lambdarank 学秩 | edge 1.342 / 尾部 IC 0.172 | 尾部极低 |
| L2a magweight | 梯度按 \|y\| 放大 | edge 1.431 | 伤 sign |
| L2c focal | focal 近零降权 | edge 1.465 | 3d 假象,长窗退化 |
| L2e dir_aware | 方向感知梯度 | edge 1.044 | 零吸引子,sign 崩 |
| L2f hurdle+dir | 叠加 | edge 0.958 | 无法叠加,最差 |

## E. MLP / 神经网络
| 模型 | 做法 | 效果 | 结论 |
|---|---|---|---|
| 早期 MLP(mse/focal/dir) | 实现未修对,10ep | edge 0.80 / 0.54 / −0.02 | 全废 |
| mlp_strong | 256×3 + BN + GELU,7类 | edge 1.704 / sign 0.718 / corr 0.973 | 追平 LGBM 不超越 |
| mlp_clsreg_evt | encoder + log 训练 + expm1 解码 | edge 1.705 | 追平天花板 |
| mlp_hurdle_clf | gate × clf 方向头 | edge 1.686 / sign 0.730 / oracle 0.064 | 守恒反向 |
| mlp_cost | 成本原生 decode | edge 1.609 | 守恒 |
| mlp_big512x5 | 512×5 深网 | edge 1.676 | 加容量不破天花板 |
| **mlp_strong_120** | 115fix+6mag−Sr8MACD=120维 | **gross@mid 2.102 / net +1.101bp / +66% vs reg / corr 0.973** | ✅ 实盘上线,尾部最优 |

## F. 表示学习 / 线性
| 模型 | 做法 | 效果 | 结论 |
|---|---|---|---|
| SupCon | 自监督表示(confidence+同向正样本) | edge 0.316 | embedding 坍缩,废 |
| linear_ridge | 线性基准 | edge 1.231 / IC 0.301 | IC≈LGBM → 信号本质线性 |

## G. 集成(Ensemble)
| 模型 | 做法 | 效果 | 结论 |
|---|---|---|---|
| ENS_bigmag | mlp_big + clf7_mag 等权 z | edge **1.781** | 研究层最高,跨家族去相关 |
| ENS_EQW4 | clf7_mag+C10b+mlp+clf7 | edge 1.776 / PnL 最优 | sign 0.706→0.720 |
| STACK_ridge4 | ridge 学权重 | edge 1.773 | 权重≈等权,无增益 |
| ENS_AVG_Z | clf3/5/7/reg 等权 z | edge 1.703 / corr 0.962 | 同质,仅 +0.006 |
| ENS3 | clf7_mag+C10b+mlp_strong | net +0.378bp | 后被单 MLP 超越,弃用 |

## H. 特征消融形态(C12)
| 模型 | 做法 | 效果 | 结论 |
|---|---|---|---|
| clf7_clean(109) | 砍 6 zero-gain | edge 1.579 | 掉 0.12bp |
| clf7_sr9sr5(55) | 仅 sr9+sr5 | edge 1.480 | sr4+sr8 贡献 +0.10bp |
| clf7_top16(16) | 仅 top16 gain | edge 1.460 | 保 86% edge,工程权衡 |

---

## 实盘上线线(120 因子 MLP 版本演进,net 口径)
| 版本 | 做法 | 效果 | 状态 |
|---|---|---|---|
| 原版 MLP120(2月训) | /share CSV,训 1/1–2/14 | IC 0.312(2–4月)→ live 6月衰到 0.238 | ⚠️ 陈旧 |
| 折中版 MLP120(4月重训) | 自产面板 0101–0420 | IC 0.3125 / C++↔Py corr 0.9998 | ✅ 可用 |
| Robust MLP118(删 Sr12 b60 对) | 删长暖机重复因子 | 冷接 IC 0.339 / net +0.467 转正 / 冷 corr 0.997 | ✅ 交接 ready |
| 替身版 MLP120(b20) | Sr12 b60→b20 短窗替身 | 冷 corr 仅 0.949 | ❌ 弃用 |
| **mlp_strong_120** | 115fix+6mag−Sr8MACD | net +1.101bp / 热 corr 0.973 | ✅ **定案上线** |

真实撮合提醒:mlp_strong_120 gross@mid 2.102bp 是理想上界 → run_sim 带硬门只兑现 +0.382bp、自然触发 top0.5% 反亏 −0.47(穿价成本墙 1.61bp)。

---

> 来源:hfcrypto_result / experiment / baseline_summary / trading / migrate / simulation / 0614 / alpha_robust / us_open_ic。
