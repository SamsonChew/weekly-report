# onnx_junjie ONNX 统一推理 package —— 项目概览与 FAQ

> 本块用一页讲清**为什么做、优化什么、难点、常见问题**。
> 所有结论已对真实代码/工具/数据做过 file:line 级验证（见 §8.0）。
> 技术细节往下看：§0–§6 现状基线、§7 可行性调研、§8 可执行实施计划。
>
> **总结**：把"我训练的深度模型"做成同事 `import` 就能用的统一产物，**融入增强** senior
> 的 `crypto-ts-alpha`/`crypto-ts-strategy` ，让任意模型结构都能零改
> C++ 进实盘。

## 一、项目的意义 / ONNX 的优势 / 为什么需要它

**现状痛点（为什么需要）**：
- 每种组合模型都在 C++ 里**手写一遍 forward**（已为此养了 `lgbm`/`mlp`/`cls_reg_mix` 三套），
  换个结构就得重写一套。
- Python 训练端与 C++ 推理端必须**逐行对齐**（特征顺序、预处理、数学），错位还**不报错、静默失真**。
- 别人想复用我的模型，门槛很高。

**ONNX 的优势**：
| 优势 | 解决的痛点 |
|---|---|
| **架构无关**：任意 PyTorch 结构导出一个 `.onnx`，C++ 零改代码加载 | 加新模型不再手写 forward |
| **跨语言**：Python 与 C++ **加载同一个文件**推理 | 训练端=推理端，根除"两套实现对不齐" |
| **自包含**：预处理(NaN 填充+标准化)+解码可烤进图 | 杜绝"漏做预处理/口径不一" |
| **业界标准**：`torch.onnx` 原生导出，工具成熟、不绑框架 | 长期可维护，易上手 |

**例子**：模型从"一段必须自己写的 C++ 代码"升级为"一个可分发、自校验、跨语言的产物"；
团队任何人都能训练 → 导出 → 直接进实盘，且**不影响目前 senior 们实盘测试框架**。

## 二、对比现状：优化了什么 · 提效在哪 · 格式如何

**流程对比**：
| 环节 | 现状 | ONNX 后 |
|---|---|---|
| 训练（Python） | 不变 | 不变 |
| 导出 | 手写 `export_mlp_weights.py`，只存权重 | `export()` 一键导出**自包含 bundle** |
| C++ 推理 | 手写 forward（`MLPAlpha.h`，每种结构一套） | **通用 `ts_onnx` alpha，零改代码** |
| 预处理 | C++ 手写 scaler+NaN，易与训练不一致 | **烤进图**，单一实现 |
| 特征对齐 | cfg 手维护 + `gen_lgbm_cfg.py` 从列名反解 | **`schema.json` 单一事实来源 + 自动校验** |
| 换新结构 | 重复全套（重写 forward+对齐+逐值校验） | **只换一个 `.onnx` 文件** |

**提效核心**：① 加新模型/新结构，C++ 从"重写一套 forward+对齐"降到**零代码**（最大提效）；
② 协作：同事 `pip install` → 训练 → `export()` → 发 bundle，全程不碰 C++；
③ 正确性：预处理与特征顺序从"两端手维护"变成"产物自带 + 启动自动校验"，消除最常见的静默错位。

**格式（bundle = 版本化产物，两个文件）**：
- `model.onnx`：计算图 = 预处理(NaN→median + 标准化) + 网络 + softmax + center 解码；
  **输入 = 原始特征向量，输出 = 单个标量 alpha**。
- `schema.json`：**有序**子因子清单（每项 `name`+`params`+`shape`）+ `input_dim` + 输出单位 +
  版本/训练 commit —— 特征对齐契约本体。示意：
```json
{ "model_id":"mlp_strong_120", "input_dim":120, "output":{"unit":"return"},
  "sub_alphas":[
    {"name":"CDiffDensity","params":{"level":50},"shape":1,"col_start":0,"col_end":1},
    "... 共 115 项, 顺序即组装顺序 ...",
    {"name":"magnitude","params":{},"shape":6,"col_start":114,"col_end":120}
  ] }
```

## 三、难点在哪 · 特征对齐怎么解决

**难点（均已定位/验证）**：
1. **精度对齐**：现状 C++ 全 `double`，ONNX 默认 `float32`。已实测漂移仅 **~1.4e-8**（相对 ~3e-5），
   可接受；需逐 bit 兼容可导 f64 图。另有 **centers 尺度坑**：字段名叫 `centers_bp` 实为 return 尺度
   （差 **1e4 倍**），导出务必对齐生产 cfg 实喂那套。
2. **NaN 语义（最易踩）**：ONNX `IsNaN` **不捕 ±inf**，而 C++ 用 `!isfinite` 把 inf 也当缺失 →
   图里必须 `IsNaN OR IsInf` 才一致。
3. **依赖接入**：C++ 新增 onnxruntime（已确认 conancenter 有，`conanfile.txt` 加一行、CMake 零改；
   体积 +~10MB 可裁剪到 2–4MB）。
4. **特征对齐（头号风险）** → 见下。

**特征对齐怎么解决**：
- 病根：特征向量 = "按固定顺序把 115 个子因子输出拼成 120 维"，顺序/参数/多输出展开任一处两端不一致，
  预测就静默失真。现状靠 cfg 手维护 + 从列名反解（多输出如 `magnitude` 会丢 shape 信息）。
- 解法：**`schema.json` 做单一事实来源**，显式记录**有序**子因子（name+params+shape）。
  C++ 通用 `OnnxAlpha` 读 schema 装配、按 shape 展开，**逐位复刻**现有 `MLPAlpha` 的组装循环；并设
  **四道自动校验**：① 顺序=训练顺序 ② 每项 `shape`==运行时 `get_shape()` ③ `Σshape`==`input_dim`==onnx
  入口维 ④ 组装末尾必须正好填满。任一不符**直接 throw** —— 错位从"静默失真"变成"启动即报错"。

## 四、大家可能关心的问题（FAQ）

| 问题 | 结论 |
|---|---|
| 会不会替换/动 senior 现有的东西？ | **不会，纯加法**。现有 `mlp`/`lgbm`/`cls_reg_mix` 与所有 cfg/脚本一行不动；strategy 只是 JSON 里多一个可选名字 `ts_onnx`，框架/`.so` 加载/消费路径全不变。 |
| 实盘会变慢吗？ | **不会**。小模型单行推理**微秒级**，对 1s bar 占比 <0.01%；session 启动开销只在进程启动一次。 |
| 要重新训练模型吗？ | **不用**。现有 `weights.json`（与部署端逐字节相同）直接导出，第一个模型不重训。 |
| 精度会变吗？影响历史回测吗？ | f32 漂移 ~1e-8（远小于 alpha 波动），可接受；需逐 bit 一致可用 f64 图。切 ONNX 后报告基准建议重锚到 f32 口径。 |
| LGBM 也要走 ONNX 吗？ | **不**。LGBM 已原生链 `c_api`（精确），LGBM→ONNX 有 float32 阈值精度差——只深度模型走 ONNX。 |
| 二进制体积涨多少？ | onnxruntime 静态链约 +10MB，可 minimal build 压到 2–4MB，或独立 `.so`。 |
| 大家具体怎么用？ | `pip install hf-model` → 训练任意 torch 模型 → `export(model, schema)` 得 bundle → 发出 → 实盘丢给 `ts_onnx`，C++ 零改代码。 |


> **我目前想要如何去做**：落地步骤见 §8「可执行实施计划」（P0–P5，file-level，每阶段带验收 gate）。
> 最快路径 = 先做 P0–P2 的 Python 闭环验证可行，再推 C++ 接入。

---

# hf_crypto 模型推理现状（LGBM / MLP 输入输出与 feature 定义）

> 调研日期：2026-06-10。本文记录 SOL alpha 模型当前 Python 训练端 ↔ C++ 推理端的输入/输出定义、
> feature 如何定义、以及做 feature 实验的方式。作为后续（含 ONNX 化）工作的基线现状。

---

## 0. 一句话总结

模型输入 = 一个**长度固定（SOL=115）的 `double` 向量**，每个位置是一个子因子（sub-alpha）的输出，
**顺序写死**；输出 = 单个 `double`（预测的 forward mid 收益，bp）。Python 训练端与 C++ 推理端
**必须逐位对齐**，靠 `gen_lgbm_cfg.py` 从训练结果自动生成 C++ 配置来保证不错位。

---

## 1. 整体架构：两个并行、必须对齐的世界

| | Python 训练端 (`sol_alpha/`) | C++ 推理端 (`crypto-ts-alpha/`) |
|---|---|---|
| 作用 | 读因子 CSV → 拼特征矩阵 → 训练 → 存模型 | 实盘/回测逐秒算因子 → 喂模型 → 出 alpha |
| 输入 | `X = np.ndarray (n_rows, 115)` float64 | `std::vector<double> values_`，长度 115 |
| 模型产物 | `booster.txt`(LGBM) / `weights.json`(MLP) | 运行时加载上述产物 |
| 入口 | `sol_alpha/train.py` | `crypto-ts-alpha` 的 `genaAC` + cfg json |

关键 key：因子 CSV 列名形如 `Sr8Alpha4_6_a10_b10_0` = `因子名_参数_输出索引`，这是连接两端的纽带。

---

## 2. 输入（input）定义

### C++ 端 —— 扁平 `vector<double>`
`src/lgbm_combine_alpha.h` 的 `calculate_value()`（每个 1s bar 触发）：

```cpp
uint32_t iw = 0;
for (const auto& alpha : alphas_) {          // 按 config 里 alpha_names 顺序
    for (uint32_t i = 0; i < alpha->get_shape()[0]; ++i, ++iw)
        values_[iw] = alpha->get_value()[i]; // 拼进 values_
}
LGBM_BoosterPredictForMatSingleRowFast(handler, values_.data(), &len, &value_);
```

- 数据结构：`std::vector<double> values_`，长度 = `ncols`（SOL=115）。
- 每个 feature = 一个子因子的 `get_value()`。多数因子 `get_shape()={1}`；少数多输出：
  `MagnitudeAlpha={6}`、`PriceBase={7}`、`BarOHLCV={7}`、`Price={3}`，占连续多个位置。
- **顺序 = config 里 `alpha_names` 数组顺序**；`ncols` 必须 == 所有子因子 `get_shape()[0]` 之和，
  否则 MLP / ClsRegMix 在 `on_start` 直接 throw。

### Python 端 —— `(n, 115)` 矩阵
`sol_alpha/data/features.py`：
- 从 `/share/crypto_hf_alpha/{sr4,sr5,sr8,sr9}/<ukey>_<日期>.csv` 读各目录因子，按 `timestamp`
  inner-join 成宽表（`load_factor_panel`）。
- `feature_columns()`：除 `timestamp` 和原始价格列 `Price_0/1/2` 外的所有列 → 正好 115 个。
- `to_matrix()` → `X = df[cols].to_numpy(float64)`。
- `sanitize()`：`inf→NaN`，NaN 当缺失值喂 LGBM（不丢行）。
- `mid = Price_1 = (bid+ask)/2`（已确认，OOS std=1.313bp 与报告吻合）；`Price_0`=末笔成交、
  `Price_2`=microprice，原始价格水平列不作特征。

---

## 3. 输出（output）定义

### C++ 端：统一接口，组合模型都输出 1 个 double
每个 alpha 实现 `get_shape()` / `get_value()` / `get_timestamp()`。三种组合模型：

| 模型 (Factory 名) | 文件 | `value_` 含义 |
|---|---|---|
| **LGBM** (`lgbm`) | `lgbm_combine_alpha.h` | booster 直接回归预测（bp） |
| **MLP** (`mlp`) | `MLPAlpha.h` | 3 层 BN+GELU → 7 类 softmax → `probs · centers_bp`（期望解码 bp） |
| **ClsRegMix** (`cls_reg_mix`) | `ClsRegMixAlpha.h` | 两段全期望 `Σ_k P(k\|X)·reg_k(X)`，跳过 flat 类 |

> **关键差异**：MLP 推理前多一步 StandardScaler 标准化 + NaN→训练中位数填充
> （`MLPAlpha.h` 中，scaler 参数存于 `weights.json`）。LGBM 树模型原生吃 NaN、不需要标准化。
> 换模型时勿把 LGBM 的原始 NaN 直接喂进 MLP。

### Python 端：训练目标 y
`train.py`：`y_bp = T.to_bp(T.forward_mid_return(mid))` —— 未来 mid 收益（bp），用 `Price_1` 算。

---

## 4. Factory 已注册的组合模型（`src/Factory.cc`）

`demo, PriceBase, BarOHLCV, lgbm, lgbm_clf, ts_lgbm_clf, magnitude, cls_reg_mix, ts_cls_reg_mix,
mlp, ts_mlp, ts_ens3, ult_lgbm, ...` + 160+ 个单因子（CDiff*, Sr4*, Sr5*, Sr8*, Sr10*, Sr12* 等）。
`ts_*` 前缀 = 时序版（`BaseTSAlpha`），非 `ts_` = `BaseAlpha`。

---

## 5. 做 feature 实验的三种方式

### A. 从现有 115 个增删/筛选（最常用，改配置即可）
- Python：config yaml 里 `exclude_features: [...]` 丢列；或改 `sr_dirs` 控制读哪些目录。
- C++：改 cfg json 的 `alpha_names` 数组 + `alphas` 参数字典，同步改 `ncols`。
- ⚠️ 两端顺序必须完全一致 → **不要手改**，用 `crypto-ts-alpha/cfg/gen_lgbm_cfg.py`：
  读训练产出的 `results.json` 的 `feature_names`，解析 `Sr8Alpha4_6_a10_b10_0 → (key,{a:10,b:10})`
  自动生成对齐的 C++ json。错位不会报错，但预测会全乱。

### B. 调因子参数（窗口等）
- 两端 config 改对应因子的参数字典（如 `"Sr5Atr": {"n": 300}` → `{"n": 600}`）。
- 同一因子类不同参数 = 不同 feature 列（列名 `_a10_b10` 会变），需重新生成训练 CSV。

### C. 加全新因子（最重，必须双端实现并对齐）
1. C++：仿 `DemoAlpha.h/.cc` 写 `BaseAlpha` 子类（`on(各事件)` + `get_shape/get_value/get_timestamp`），
   在 `Factory.cc` 注册、`AllFactor.h` include。
2. Python：让其成为训练 CSV 一列；派生因子可直接在 `features.py` 加（如 `add_magnitude_features`）。
3. 验证对齐：跑 `validate_*_cpp.py`（`validate_magnitude_cpp.py` / `validate_mlp_cpp.py` /
   `validate_crm_cpp.py` / `validate_clf7_cpp.py`），逐值比对两端，必须一致。

> 双端派生因子最佳模板：`features.py::add_magnitude_features`（Python）↔ `MagnitudeAlpha.h`（C++），
> 注释逐行标注如何对齐 pandas 的 rolling / min_periods / fillna。

---

## 6. 关键风险点 / 注意事项

- **两端对齐是头号风险**：feature 顺序/参数/NaN 处理任一不一致，预测就失真且不报错。改 feature 后
  务必跑 `validate_*_cpp.py`。
- **MLP vs LGBM 的预处理差异**：MLP 需要 StandardScaler + 中位数填充，LGBM 不需要。
- **NaN 语义**：LGBM 把 NaN 当缺失值（保留行）；MLP 用训练中位数填充；某些因子（如
  `Sr5EmaTrade_a10_b10`）在某些日期整列 NaN。
- **C++ 推理是逐 1s bar 单行预测**（`PredictForMatSingleRowFast`），不是批量。

---

## 7. 统一推理 package（ONNX 化）可行性调研（2026-06-14）

> 目标：开一个**新 repo**，写一个统一 package / 接口，让同事 `import` 就能复用我训练的
> MLP / 其它深度模型，**而不必每换一种结构就在 C++ 里手写一遍 forward**。
> 本节为该需求的可行性调研结论。
>
> **⚠️ 设计铁律（融入而非替换）**：本工具**必须基于、增强** senior 既有的 `crypto-ts-alpha` +
> `crypto-ts-strategy` 范式——**绝不替换/推翻** senior 的东西，而是融入使其更强，并让其他人能
> **适配她（senior）现有的 `BaseAlpha`/`Factory` 范式**。下文所有"通用 onnx alpha"都是**新增、
> 与现有 bespoke 实现并存**的家族新成员；现有 `mlp`/`lgbm`/`cls_reg_mix` 一律**保留照常工作**，
> crypto-ts-strategy 的消费路径（`.so`/`genaAC`/cfg）**不变**，新范式只是多一个可选 alpha 类型。

### 7.0 一句话结论

**能实现，ONNX 就是为这个场景设计的标准解法。** 训练端任意 PyTorch 架构 → 导出一个
`.onnx` → Python(`onnxruntime`) 与 C++(`onnxruntime` C++ API) 加载**同一个文件**推理；
**加新架构（CNN/LSTM/Transformer）时 C++ 端零改代码，只换一个 `.onnx` + schema**。
预处理（StandardScaler + NaN 填充）可烤进 ONNX 图，让产物完全自包含。

唯一 ONNX **不能**替你解决的是**特征向量组装顺序对齐**（第 2 节那个头号风险）——所以 package
必须把"特征 schema（名字+顺序）"作为元数据和模型绑在一起、并在加载时校验（见 7.5）。

### 7.1 为什么现状不可扩展（痛点精确定位）

当前 [MLPAlpha.h](../../hfcrypto_junjie/crypto-ts-alpha/src/MLPAlpha.h) 是**纯手写 C++ forward**：
`Linear → 融合 BN(`s*bn_scale+bn_shift`) → GELU(erf 版) → 输出层 → softmax → center 解码`
全是 `std::vector<double>` 手撸循环（`calculate_value()` lines 177-251）。其结构必须和 Python
训练端**逐行对齐**。后果：

- **每换一种模型结构，就要在 C++ 重写一遍 forward**——这正是"让同事用任意深度模型"的核心障碍。
  现在 repo 里已经为此并行养了三套 bespoke C++ 实现：`lgbm` / `mlp` / `cls_reg_mix`。
  （目标是**新增**一条通用 ONNX 路径**融入增强**这套框架，**不是删掉这三套**——它们照常保留工作。）
- 已确认**好消息**：`calculate_value()` 在"特征组装完之后"的数学核心，对 `BaseAlpha`/事件系统
  **零依赖**，抽出来很容易（耦合点只有 `on_start` 装子因子、`on(bar_t)` 触发、`get_value()` 取值）。

### 7.2 推荐架构：「模型 bundle + 双语言薄 runtime」

```
            训练端 (Python, 同事/我)
                    │  export()  ← 唯一需要"懂模型"的地方
                    ▼
        ┌─────────────────────────────┐
        │   模型 bundle (版本化产物)    │   ← 单一事实来源 (single source of truth)
        │   model.onnx  + schema.json │
        └─────────────────────────────┘
            │                       │
   import & predict            link & predict
            ▼                       ▼
   Python runtime (onnxruntime)   C++ runtime (onnxruntime C++ API)
   研究/回测                       新增一个"通用 onnx alpha"作为新成员,
                                   注册进 Factory, 与现有 mlp/cls_reg_mix 并存
```

三个组件：
1. **bundle**：版本化的模型产物（`.onnx` + `schema.json`），跨语言、自包含。
2. **薄 runtime**（两套，但都只是 onnxruntime 的封装）：Python 包 + C++ 库，**对外都是同一个
   `predict(features) -> double` 语义**。runtime 不懂模型结构，只负责喂张量、取结果、校验 schema。
3. **export 助手**（训练端）：`export(torch_model, feature_schema, scaler) -> bundle`，是
   **唯一**需要懂模型/框架的地方，把"标准化"这件事收口到一个函数。

这样"同事 import 就能用任意深度模型"成立：同事训练任意 torch 模型 → 调 `export()` → 发一个
bundle → 消费端代码一行不改。

### 7.3 bundle 里到底装什么

| 文件 | 内容 | 解决什么 |
|---|---|---|
| `model.onnx` | 计算图（**预处理烤进去**：NaN→median 填充 + StandardScaler + 网络 + softmax + center 解码） | 架构无关、跨语言 |
| `schema.json` | `feature_names`（**有序**）、`input_dim`、各子因子 `get_shape`、output 含义/单位(bp)、`model_id`、`version`、训练 commit | 特征对齐（单一事实来源，新范式下可选简化 `gen_lgbm_cfg.py` 双向手维护）、可追溯 |

关键设计：**特征顺序写进 bundle 的 schema，而不是散落在 C++ cfg 和 Python config 两处**。现有
[gen_lgbm_cfg.py](../../hfcrypto_junjie/crypto-ts-alpha/cfg/gen_lgbm_cfg.py) 做的"从 `results.json`
的 `feature_names` 反解出 C++ alpha 参数"这件事，未来可由通用 onnx alpha 直接读 bundle 的
`schema.feature_names` 完成——单一事实来源，错位无处藏身。（现有 `gen_lgbm_cfg.py` 路径**保留照常
工作**，新范式下只是**可选简化**，不强制删。）

### 7.4 三种消费场景 × 对应实现（按你拍板的"消费端语言"选）

| 场景 | Python runtime | C++ runtime | 工作量 |
|---|---|---|---|
| **两者都要**（默认假设：训练Python+实盘C++） | pip 包，`onnxruntime` 一层封装 | **新增**一个**通用 `onnx` alpha**（仿 `MLPAlpha` 的 `BaseAlpha` 适配壳、注册进 `Factory` 与现有并存，内部不再手写 forward，改成 `Ort::Session.Run`）+ onnxruntime C++ 依赖 | 中：两套薄 runtime，共享一个 bundle |
| 仅 Python | 同上 | — | 小：几乎只是 onnxruntime + schema 校验 |
| 仅 C++ | 仅 export 脚本 | 同上通用 onnx alpha | 中：重点在 C++ 集成 + parity |

C++ 单行推理范式（每个 1s bar）：进程启动时建一次 `Ort::Session`（复用），每 bar 组装
`1×N` 输入张量 → `session.Run` → 取标量输出。**1s bar 预算极其宽裕，onnxruntime 的 per-call
开销（微秒~数十微秒级）对你这里完全不是问题**（不是 sub-ms 的 taking 决策路径）。

### 7.5 ONNX 关键技术细节与坑

1. **精度对齐（头号坑，必须先定）**
   - 现状 C++ **全程 `double`**（[MLPAlpha.h:99-129](../../hfcrypto_junjie/crypto-ts-alpha/src/MLPAlpha.h#L99)）；
     而 PyTorch 训练几乎肯定是 **float32**，`torch.onnx.export` 默认导出 **float32 图**，onnxruntime
     默认按 float32 跑。
   - 推论：**现在的 double C++ 推理本来就和 float32 训练不完全一致**；改用 float32 ONNX 反而会让
     C++ 推理**更贴近训练真值**。但代价是：历史报告里那些用 double C++ 算出来的数会**轻微漂移**。
   - 两条路二选一：
     - **(a) float32 ONNX**（推荐）：与训练一致、更快、生态全。验证时基准选 **PyTorch float32 forward**，
       不是旧 double C++。
     - **(b) float64 ONNX**（把模型 cast double 再导）：与现有 double C++ 精确对齐、向后兼容历史数；
       代价是略慢、部分算子/EP 的 double 覆盖较少。
2. **预处理烤进图**：`NaN→median` 用 `Where(IsNaN(x), median, x)`（opset≥9），再
   `(x-mean)/scale`（`Sub`/`Div`），都能进 ONNX 图。烤进去后 bundle 吃"原始特征"，消费端不可能漏做
   预处理——比现状（C++ 里手写 scaler、LGBM 又不需要 scaler，容易喂错，见第 6 节）更稳。
3. **center 解码也进图**：`softmax · centers_bp` 用 `Softmax`+`MatMul`/`ReduceSum` 表达，使 onnx
   输出直接就是 bp，runtime 真正零业务逻辑。
4. **特征对齐 ONNX 管不了**：见 7.3，靠 schema + 加载校验（`input_dim==Σget_shape` 不符就 throw，
   沿用现有 `on_start` throw 的思路）。
5. **多输出子因子**：`magnitude={6}`/`PriceBase={7}` 等占连续多位，schema 里要记每个子因子的
   `get_shape`，组装时按它展开（C++ 通用 alpha 复用现有 `for i in get_shape()[0]` 逻辑）。

### 7.6 LGBM 要不要也走 ONNX（诚实取舍）

- 技术上**可以**：`onnxmltools.convert_lightgbm` 能转。
- 但 **LightGBM→ONNX 的树集成在 onnxruntime 里用 float32 阈值，和原生 LGBM 的 double 预测有
  已知的小幅不一致**；而本 repo **已经原生链 `LightGBM/c_api.h`**（conan 里已有 `lightgbm` 包），
  这条路是精确的。
- 结论（做对的事优先）：**深度模型走 ONNX（手写 forward 的痛点在这），LGBM 维持原生 c_api**。
  统一接口可以在"runtime 外壳"层做到（对外都是 `predict`），但底层 LGBM 不必硬塞进 ONNX 换来一个
  需要反复验证的精度差。若坚持全统一，须把 LGBM→ONNX 的 parity 误差当独立验收项。

### 7.7 备选方案对比与取舍

| 方案 | 架构无关? | 跨语言? | 依赖重量 | 取舍 |
|---|---|---|---|---|
| **A. ONNX bundle + 薄 runtime** ✅推荐 | ✅ | ✅ Py+C++ | onnxruntime（中） | 命中全部诉求；需新增 onnxruntime 依赖 + 精度对齐 |
| B. 抽成 header-only `MLPInferenceEngine`（把现有手写 forward 抽包） | ❌ 仍要手写新结构 | C++为主 | 零新依赖 | 最省事，但**不解决核心痛点**；仅当同事永远只用这一种 MLP 形状才够 |
| C. TorchScript / libtorch | ✅ | Py+C++ | libtorch（**很重**，数百 MB） | 也能架构无关，但部署进 HFT C++ binary 太重，比 onnxruntime 笨 |
| D. gRPC/REST 推理微服务 | ✅ | 任意语言 | 服务化 | 多一跳网络+运维，**不适合实盘内联**；研究/批量可接受 |
| E. 纯 Python 包 | ✅ | ❌ 仅Py | onnxruntime/torch | 同事全是 Python 才够；本 repo 实盘是 C++,不满足 |

### 7.8 新 repo 目录结构建议（archetype）

```
hf-model/                      # 新 repo (建议放 git.9th-tech.com 同内网)
  pyproject.toml               # pip 可装
  hfmodel/                     # Python runtime + export
    __init__.py
    bundle.py                  # 读写 bundle (model.onnx + schema.json), 版本/校验
    export.py                  # export(torch_model, schema, scaler) -> bundle (烤预处理进图)
    predict.py                 # Predictor: load(bundle) -> predict(features)->bp  (onnxruntime)
    schema.py                  # FeatureSchema: 有序 feature_names + get_shape + 校验
  cpp/                         # C++ runtime (header + 薄 .cc, 封装 onnxruntime C++ API)
    include/hfmodel/predictor.h  # OnnxPredictor::load(bundle); run(span<double>)->double
    src/predictor.cc
    CMakeLists.txt / conanfile  # 依赖 onnxruntime (conan center 有, 或 vendored)
  adapters/                    # 把 runtime 融入现有 crypto-ts-alpha 框架(增强,不改框架)
    OnnxAlpha.h                # 通用 BaseAlpha 适配壳(新增,注册进 Factory,与 MLPAlpha/ClsRegMix 并存)
  tests/
    test_parity.py             # ONNX 输出 vs PyTorch float32 forward, 逐值
    test_cpp_parity/           # C++ runtime 输出 vs Python, 逐值 (沿用 validate_*_cpp.py 思路)
  examples/
    train_and_export_mlp.py    # 同事照抄的最小例子
```

注：现 repo 用 conan（本机缓存已有 `eigen`/`lightgbm`/`rapidjson`/`fmt`/`spdlog` 等），新 repo
沿用 conan 接 onnxruntime 最顺；onnxruntime 在 conancenter 有 recipe，或用官方预编译包 vendored。

### 7.9 分阶段落地路线 + parity 验证（不可省）

1. **P0 训练侧（现成，不用还原 —— 已更正）**：训练/导出代码完整存在于
   `/home/samson/mlf-qyas-junjie/hf_crypto/sol_alpha/`（`mlp_strong_120.py`/`export_mlp_weights_120.py`），
   其 `output/mlp_strong_120/weights.json` 与 C++ 部署端 [weights.json](../../hfcrypto_junjie/crypto-ts-alpha/models/mlp_strong_120/weights.json)
   **逐字节相同**。故 P0 只是"加一个 onnx 导出脚本"，非从零重建。模型：120→256×3→7，融合BN，
   GELU erf，centers 是**收益尺度 ~1e-4 非 bp**，勿被名字骗。详见 §8 实施计划。
2. **P1 Python 闭环**：`export()` 把该模型（含 scaler/median/center 解码）导成烤好预处理的 onnx；
   `test_parity.py` 验 ONNX 输出 == PyTorch float32 forward（定 7.5 的精度基准）。
3. **P2 C++ runtime**：**新增**通用 `OnnxAlpha`（`BaseAlpha` 壳 + `Ort::Session`，注册进 `Factory`
   与现有并存），逐值比对 Python runtime；再和现有 double `MLPAlpha` 比对，量化 float32 漂移（决定是否需 float64 图）。
4. **P3 收口对齐**：通用 alpha 直接读 bundle 的 `schema.feature_names` 组装特征（`gen_lgbm_cfg.py`
   现状保留，新范式下可选简化双向手维护）；跑现有 `validate_*_cpp.py` 等价回归。
5. **P4 推广**：同事按 `examples/` 训练任意结构 → `export()` → 发 bundle → 实盘换 onnx 文件即用。

### 7.10 需要你拍板的决策点（权限流断了没问成，列在此）

- **D1 消费端语言**：Python研究+C++实盘两者都要（默认假设）/ 仅Python / 仅C++ —— 决定做几套 runtime。
- **D2 核心目标层级**：架构无关（默认，止于深度模型）/ 连 LGBM 也统一进同一 predict（须接受 LGBM→ONNX
  精度验收）/ 只把现状 MLP 标准化打包（先用 B 方案）。
- **D3 精度策略**：float32 ONNX（推荐，贴训练，历史数会微漂）/ float64 ONNX（精确兼容旧 double C++）。
- **D4 新 repo 落点**：内网 `git.9th-tech.com`（与现 repo 同源，方便同事拉）还是别处。

### 7.11 风险点清单

- **协作铁律（融入而非替换）**：必须基于、增强 senior 的 `crypto-ts-alpha`/`crypto-ts-strategy`；
  新 onnx 路径与现有 bespoke **并存**、不破坏 strategy 消费路径（`.so`/`genaAC`/cfg 不变）——违背即方案作废。
- **特征对齐仍是头号风险**：ONNX 只解决模型可移植，顺序/参数错位照样静默失真 → schema 单一事实来源 +
  加载校验 + parity 测试，缺一不可。
- **精度漂移**：见 D3；切 ONNX 后历史报告基准要重锚到 PyTorch float32，别和旧 double C++ 直接比数。
- **新增 onnxruntime 依赖**：进 HFT C++ binary 需评估体积/EP；用 CPU EP、关多余 EP 以控体积与启动开销。
- **LGBM 精度差**：若 D2 选"全统一"，LGBM→ONNX 的 float32 阈值误差须单列验收，否则维持原生 c_api。
- **训练侧现成（已更正）**：完整 sol_alpha 在 `/home/samson/mlf-qyas-junjie/hf_crypto/sol_alpha/`，
  weights.json 与部署端逐字节相同，P0 不需重建——详见 §8 实施计划。

---

## 8. 可执行实施计划（file-level，基于 2026-06-14 五路深挖实证）

> 第 7 节是可行性背景；本节是落地用的 file-level 计划。五个原本"拍脑袋"的假设已逐一对真实
> 代码/工具/数据验证（带 file:line），故**整体可行、低风险**。

### 8.0 为什么"通"——五路实证

| # | 原假设 | 实证结论 | 证据 |
|---|---|---|---|
| 1 | C++ 接入要动框架 | **零改框架**：strategy 只把 JSON 里 `ts_mlp→ts_onnx`；Factory 加 2 个 `if`；机制 `load_ts(repo,name,cfg)→dlopen lib*.so→factory->create` | `HFTaking.cc:33-39`、`alpha_manager.h:23/102-109`、`Factory.cc:29-32` |
| 2 | 模型能否精确还原未知 | **能，已实测**：PyTorch 复刻 vs 纯 double 参考，f64 max_abs=**2.9e-17**、f32=**1.4e-8** | 2000 样本含 5% NaN |
| 3 | onnxruntime C++ 能否接入未知 | **能且轻**：conancenter 有 `onnxruntime/1.18.1`（默认 CPU 静态），`conanfile.txt` 加一行、CMake 零改；单行推理微秒级 | `conan search onnxruntime`、`CMakeLists.txt:10/26` |
| 4 | 训练侧缺失要从零还原（**上一版最大误判**） | **不用还原**：完整 `sol_alpha` 在 `/home/samson/mlf-qyas-junjie/hf_crypto/sol_alpha/`，`weights.json` 与部署端**逐字节相同** | `mlp_strong_120.py`、`export_mlp_weights_120.py` |
| 5 | 特征对齐契约不清 | **已固化**：真实 115 子因子→120 列，唯一多输出 `magnitude={6}` 占 [114..119]，schema 就绪 | `genaAC_sol_mlp120_val.json`、`MLPAlpha.h:66-67/181-196` |

### 8.1 架构落点（三个位置，全部加法）

| 位置 | 新增内容 | 动他人代码? |
|---|---|---|
| **新 repo `hf-model/`**（同事 import 入口） | Python `hfmodel`：`export()`/`Predictor`/`schema`+`bundle`；C++ ORT 薄封装；examples/文档 | 全新，零触碰 |
| **`crypto-ts-alpha/`**（融入点，纯新增） | `src/OnnxAlpha.h`+`src/TSOnnxAlpha.h`（新文件）；`Factory.cc` 加 2 个 `if`；`AllFactor.h` 加 2 个 include；`conanfile.txt` 加 `onnxruntime` | 仅追加，旧 entry/链接不动 |
| **`sol_alpha/`**（训练侧，纯新增） | `export_onnx_120.py`（torch→onnx+schema）；`validate_onnx_parity.py` | 现有脚本不动 |

### 8.2 file-level 阶段（P0–P5，每阶段带验收 gate）

- **P0 环境与基线锁定（~0.5d）**：隔离 venv 装 `onnx onnxruntime`（dry-run 已验证可装；torch/sklearn 现成；**不需** skl2onnx/onnxmltools）；复核两端 weights.json 一致、`centers_unit="return"`。**Gate**：`import onnxruntime` 成功。
- **P1 训练端导出（~0.5d）**：新增 `sol_alpha/export_onnx_120.py`，用精确复刻的 `MLPAlphaNet`（BN 用预融合 scale/shift 逐元素 affine，**非 nn.BatchNorm**；GELU erf；`W` 是 `[out,in]` 直接赋值不转置），把**预处理+解码全烤进图**：`Where(IsNaN(x) OR IsInf(x), median, x)→(x-mean)/scale→网络→Softmax→·centers`，`opset_version=17`。**centers 尺度必须对齐生产 cfg 实际喂的那套（名义 bp vs return 差 1e4 倍）**。**Gate**：导出 `.onnx`+`schema.json`，核对输入名/维=120、输出标量。
- **P2 Python parity（~1d）**：新增 `validate_onnx_parity.py`，复用 `validate_mlp_cpp.py` 的 numpy-forward 作锚点；**同一矩阵喂各端**（不靠时间戳 join）三方比 `onnxruntime` vs `torch f32` vs `numpy-double(=C++ 语义)`；输入含真实 OOS 切片 + **NaN 覆盖批**（全有限/单 NaN/整列 NaN/inf）。容差：onnx↔torch `atol=1e-6`；onnx/torch↔double `atol≈1e-7~1e-6`+`Pearson>0.9999`，按 NaN 桶分别报。**Gate**：onnx 对齐 double 不差于 torch-f32；NaN 桶 max|err| 与有限桶同量级。
- **P3 C++ 接入（~1.5d）**：`conanfile.txt` 加 `onnxruntime/1.18.1`（经典 generator 下 CMake 零改；内网无包则 vendored 微软预编译兜底）；新增 `OnnxAlpha.h`（照抄 `MLPAlpha` 的 11 虚方法/子因子 load `:60-69`/iw 组装 `:181-196`，**仅**把手写 forward `:213-251` 换成 `Ort::Session.Run`，输入 float32 `{1,120}`，预处理已烤图故 C++ 零预处理）+ `TSOnnxAlpha.h`（同 `TSMLPAlpha`，`name "mlp"→"onnx"`、`weights→onnx_path`）；`AllFactor.h`/`Factory.cc` 各加 2 行（不碰旧 entry）：
  ```cpp
  if (name=="onnx")    return std::make_unique<OnnxAlpha>();
  if (name=="ts_onnx") return std::make_unique<TSOnnxAlpha>();
  ```
  **Gate**：`.so` 构建通过；`genaAC` 用 `ts_onnx` cfg 跑出 alpha。
- **P4 端到端 parity + strategy 联调（~1.5d）**：加 C++ test harness 直接 `set values_` 再 `calculate_value`，对 P2 同一矩阵逐值比 `OnnxAlpha` vs `MLPAlpha`；复制 `HFTaking_sol_mlp120_return.json` 把 `name ts_mlp→ts_onnx`、`weights→onnx_path` 跑 strategy。**Gate**：与现状 `ts_mlp` 逐值对齐达标、strategy 零代码改动跑通。
- **P5 抽 hf-model 通用 package + 推广（~2-3d）**：把"懂模型/会 ORT"部分收口成 `hf-model`（Python `export()/Predictor/schema`；C++ session 封装抽出，`crypto-ts-alpha` 只留薄壳继承注册）；`examples/train_and_export.py`。**Gate**：换个玩具结构走 `export()→bundle→ts_onnx`，C++ **零改代码** 跑通（证明架构无关）。

### 8.3 parity 验证策略（头号风险）

- **黄金基准 = 实盘在跑的 double C++ `MLPAlpha`**。三方：`onnx`(f32)↔`torch`(f32) 近 bit 级；f32↔double 差异来自 256 项累加，属预期。
- **NaN 语义坑（最易踩）**：ONNX `IsNaN` **不捕 ±inf**，而 C++ 用 `!isfinite` 把 inf 也当缺失 → 图里须 `IsNaN(x) OR IsInf(x)`。必造"整列 NaN/inf"输入断言。
- 喂法：同一矩阵喂各端（C++ 加直喂 harness），逐值 abs 比，不用时间戳 join。

### 8.4 关键决策

**已定**：P0 不重建训练侧；精度默认 **f32**（需逐 bit 兼容旧 double 时先 f64 图离线锚定再切 f32）；**预处理烤进图**；C++ 输入 **float32**；onnxruntime 走 **conancenter**（内网不通则 vendored）；**LGBM 维持原生 c_api**。
**待你拍（不阻塞 P0-P4）**：D1 消费端语言（默认 Py+C++）/ D2 抽象层级（默认止于深度模型）/ D4 `hf-model` 落点（默认内网）/ **centers 用名义 bp 还是 return**（须确认生产 cfg 实喂哪套，差 1e4 倍）。

### 8.5 风险与回退

| 风险 | 回退 |
|---|---|
| onnxruntime 内网 remote 无 | vendored 微软官方预编译 `.so`+头文件 |
| f32 漂移改历史报告数 | 基准重锚 torch-f32；或 f64 图逐 bit 兼容 |
| `.so` 体积 +~10MB | `shared=True` 独立 .so，或 minimal build 压 2-4MB |
| 多输出子因子错位 | schema 四道校验（顺序/shape/Σ=input_dim/iw 填满）+ parity NaN 桶 |
| centers 尺度搞错 | 输出整体差 1e4 倍，parity 立即暴露 |

### 8.6 里程碑

- **P0-P2（Python 闭环）≈ 2d** → 即可演示"onnx 与现状逐值对齐"，**最小可验证"通不通"**。
- **P3-P4（C++ 接入+端到端 parity）≈ 3d**（含 conan 首次构建、harness）。
- **P5（抽通用 package+文档）≈ 2-3d**。合计约 **7-8 工作日** 到可推广。

### 8.7 关键文件索引

- C++ 接口/Factory：`crypto-def …/crypto/components/{alpha,interface,context,base}.h`；`crypto-ts-alpha/src/{Factory.cc,Factory.h,AllFactor.h}`
- 范本 alpha：`crypto-ts-alpha/src/{MLPAlpha.h,TSMLPAlpha.h,MagnitudeAlpha.h}`
- strategy 消费：`crypto-ts-strategy/src/{HFTaking.cc:33-39,SignalExecution.cc:74,HFMaking.cc:30}`；cfg `crypto-ts-strategy/cfg/runner_cfg/HFTaking_sol_mlp120_return.json`
- 构建：`crypto-ts-alpha/{CMakeLists.txt,conanfile.txt}`
- **训练侧（关键新发现）**：`/home/samson/mlf-qyas-junjie/hf_crypto/sol_alpha/{mlp_strong_120.py,export_mlp_weights_120.py,validate_mlp_cpp.py,compare_cpp_py_120.py,data/features.py,output/mlp_strong_120/weights.json}`
- 真实特征契约：`crypto-ts-alpha/cfg/genaAC_sol_mlp120_val.json`（115 子因子→120 列）
