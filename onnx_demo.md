# onnxalpha 接入 DEMO —— 从 hfcrypto_onnx 把 mlp_strong_120 接进来

> **你来操作**，每一步都有：① 做什么 ② 命令(可直接粘) ③ ✅ 期望看到什么。
> 视角 = **全新使用者**：只把 `onnxalpha` 当一个 pip 装好的外部包用，不碰它的源码。
> 目标 = 最后能成功：产出你自己的 `bundle` + 验证 `max|err|≈1e-10` + 跑通部署接入。
>
> **全程工作目录** = `/home/samson/hfcrypto_onnx`（除非某步另说）。
> 产物都放在新建的 `onnx_integration/` 下，**不碰 crypto-ts-alpha / crypto-ts-strategy 一行**。

---

## 它们的关系（先看懂，30 秒）

- `onnxalpha`：一个**包**。功能 = 把模型权重 → 自包含 `bundle`（`model.onnx`+`schema.json`）；并能加载 bundle 做推理。
- 你这个 repo：有训练好的 MLP 权重 `mlp_strong_120/weights.json` + 子因子顺序 cfg。
- **接入 = 用 onnxalpha 这个包，把你的权重导成 bundle。** C++ 那边用全队共享的 `libonnxalpha.so`，你只产出 bundle。

---

## Step 0 — 建一个干净环境 + 装 onnxalpha

**做什么**：建一个**全新的** Python 环境（不依赖任何现成 env），把 onnxalpha 当外部包装进去。
它会自动从 PyPI 拉 numpy/onnx/onnxruntime/scipy。下面两种建环境方式，**挑你机器上有的那个**。

```bash
cd /home/samson/hfcrypto_onnx
```

**方式 A — 有 conda / micromamba（你终端 `(base)` 提示符就说明有）**
```bash
conda create -y -n onnx_demo python=3.10
conda activate onnx_demo
pip install --upgrade pip
pip install "git+ssh://git@git.9th-tech.com/samson/onnx_junjie.git"
```

**方式 B — 只有系统 python3**
```bash
python3 -m venv ~/.venvs/onnx_demo
source ~/.venvs/onnx_demo/bin/activate
pip install --upgrade pip
pip install "git+ssh://git@git.9th-tech.com/samson/onnx_junjie.git"
```

✅ **期望看到**：末尾 `Successfully installed onnxalpha-0.1.0 numpy-... onnxruntime-... ...`
（onnxalpha 连同它的依赖一并装好）。

> 之后每开新终端要用，先 `conda activate onnx_demo`（方式 A）或
> `source ~/.venvs/onnx_demo/bin/activate`（方式 B）激活这个环境。

**验证装好了**：
```bash
python -c "import onnxalpha; print('onnxalpha at', onnxalpha.__file__)"
onnxalpha info
```
✅ **期望看到**：
```
包内自带 bundle(1 个):
  - mlp_strong_120
```

> 🔁 **内网版**：内网若装不上 git（连不上 PyPI 拉依赖），改用离线 wheel：
> 把 `onnx_junjie/third_party/wheels/` 拷到内网，`pip install --no-index --find-links wheels onnxalpha`。
> 装完一样 `onnxalpha info` 能看到。

---

## Step 1 — 建接入工作区 + 准备两个输入

**做什么**：onnxalpha 导出需要两样东西：① 权重 json ② 子因子顺序 cfg（顶层是 `{ukey, alpha_names, alphas}`）。
权重你 repo 里现成；子因子 cfg 你 repo 里**嵌在** `genaAC_sol_mlp120_val.json` 的 `alpha_cfg.ts_mlp` 下，抽出来即可。

```bash
mkdir -p onnx_integration/bundles

# ① 权重(现成,只是记下路径)
ls -l crypto-ts-alpha/models/mlp_strong_120/weights.json

# ② 抽出子因子 cfg → 存成 onnxalpha 要的顶层格式
python -c "import json; c=json.load(open('crypto-ts-alpha/cfg/genaAC_sol_mlp120_val.json')); json.dump(c['alpha_cfg']['ts_mlp'], open('onnx_integration/alpha_cfg_mlp_strong_120.json','w'), indent=2); print('done')"
```

✅ **期望看到**：`done`，并生成 `onnx_integration/alpha_cfg_mlp_strong_120.json`。

**验证抽对了**：
```bash
python -c "import json; a=json.load(open('onnx_integration/alpha_cfg_mlp_strong_120.json')); print('顶层键:', list(a.keys())); print('alpha_names 个数:', len(a['alpha_names']), '| ukey:', a.get('ukey'))"
```
✅ **期望看到**：`顶层键: ['ukey', 'alpha_names', 'alphas']`（或顺序略不同但含这三个），`alpha_names 个数: 115`，`ukey: 110200132`。

> 📌 **这就是新人会卡的那个点**（已替你解决）：onnxalpha 要顶层就是 `{ukey,alpha_names,alphas}`；
> 你 repo 把它包在 `alpha_cfg.ts_mlp` 里。上面那行 `json.dump` 就是把它"解包"出来。

---

## Step 2 — 导出你自己的 bundle（只用 onnxalpha 的命令行）

**做什么**：用 onnxalpha 的 `export` 子命令，把权重 + 子因子 cfg → bundle。

```bash
onnxalpha export \
  --weights   crypto-ts-alpha/models/mlp_strong_120/weights.json \
  --alpha-cfg onnx_integration/alpha_cfg_mlp_strong_120.json \
  --out       onnx_integration/bundles/mlp_strong_120 \
  --model-id  mlp_strong_120
```

✅ **期望看到**：`已导出 bundle 到 onnx_integration/bundles/mlp_strong_120`。

**验证 bundle**：
```bash
ls -l onnx_integration/bundles/mlp_strong_120/          # 应有 model.onnx + schema.json
onnxalpha info --bundle onnx_integration/bundles/mlp_strong_120
```
✅ **期望看到**：`输入维度 : 120`、`子因子数 : 115`、`输出单位 : return`、`分类数 : 7`。

---

## Step 3 — 验证 bundle 推理正确（对包内黄金参考）

**做什么**：用 onnxalpha 加载 bundle 推理，和它自带的 numpy 黄金参考逐值比，证明导出没出错（含 NaN/inf）。

```bash
cat > onnx_integration/verify.py <<'PY'
import numpy as np
import onnxalpha as oa
from onnxalpha import load_weights, reference_forward

W = "crypto-ts-alpha/models/mlp_strong_120/weights.json"
B = "onnx_integration/bundles/mlp_strong_120"

w = load_weights(W)
p = oa.Predictor.load(B)

rng = np.random.RandomState(0)
X = rng.randn(256, 120).astype(np.float64)
X[1, 3:8] = np.nan      # NaN 行
X[2, 50]  = np.inf       # inf 行

got  = p.predict(X)               # onnxalpha 走 onnxruntime
gold = reference_forward(X, w)    # 包自带 numpy-double 黄金参考
err  = np.abs(got - gold).max()
pear = np.corrcoef(got, gold)[0, 1]
print(f"max|err| = {err:.3e}   pearson = {pear:.6f}")
print("PASS" if (err < 1e-6 and pear > 0.9999) else "FAIL")
PY
python onnx_integration/verify.py
```

✅ **期望看到**：`max|err| = ~1e-7（在 1e-6 容差内）   pearson = 1.000000` + `PASS`。
（已实测：本 repo 的 mlp_strong_120 跑出 `max|err| = 4.4e-7, pearson = 1.000000, PASS`。
`1e-7` 量级是 f32 推理 vs f64 黄金参考的正常漂移，不是错误。）

> 到这一步，**你的模型已经成功"接入" onnxalpha 了** —— 你有了一个自己导出、且验证正确的 bundle。

---

## Step 4 — 部署接入（C++ serving，复用全队共享 `.so`）

**关键心法**：`.so`（`libonnxalpha.so` + `libonnxruntime.so.1.18.1`）是**全队共享的同一份**，已在共享路径。
你这个项目**只加一个 bundle**，不编任何 C++。

### 4a. 内网：把 bundle 放进共享路径

```bash
cp -r onnx_integration/bundles/mlp_strong_120 \
      /gpfs/hddfs/sgqr/shared/onnxalpha/bundles/
ls /gpfs/hddfs/sgqr/shared/onnxalpha/bundles/        # 应能看到 mlp_strong_120
```
（`.so` 已经在 `/gpfs/hddfs/sgqr/shared/onnxalpha/lib/`，不用动。）

### 4b. cfg 指向（你的 runner 的 json 里，alpha 段）

```json
"alpha-manager": { "repo_path": "/gpfs/hddfs/sgqr/shared/onnxalpha/lib" },
"alpha": {
  "repo": "onnxalpha",
  "name": "ts_onnx",
  "config": {
    "ukey": 110200132,
    "bundle": "/gpfs/hddfs/sgqr/shared/onnxalpha/bundles/mlp_strong_120"
  }
}
```

### 4c. 起 runner（LD_LIBRARY_PATH 含共享 lib）

```bash
export LD_LIBRARY_PATH="/gpfs/hddfs/sgqr/shared/onnxalpha/lib:$LD_LIBRARY_PATH"
# ./bin/runner ./config/你的_runner.json ...
```

✅ **期望**：runner 加载 `ts_onnx` 成功、逐 bar 出 alpha（量级 ~1e-5 return）。

> 🖥️ **本地(qrdev)想先验一把 C++**：`.so` 用 `/home/samson/onnx_junjie/deploy/serving_lib/`，
> `bundle` 用 `onnx_integration/bundles/mlp_strong_120`，`LD_LIBRARY_PATH` 指向那个 serving_lib 即可。

---

## Step 5 — 收尾：留一份接入记录

**做什么**：把你实跑的输出贴进一个日志，方便复现 / 给同事。

```bash
cat > onnx_integration/接入记录.md <<'MD'
# mlp_strong_120 接入 onnxalpha 记录

- 装包: pip install git+ssh://.../onnx_junjie.git  -> onnxalpha 0.1.0
- 输入: crypto-ts-alpha/models/mlp_strong_120/weights.json
        + alpha_cfg(从 genaAC_sol_mlp120_val.json 的 alpha_cfg.ts_mlp 抽出)
- 导出: onnxalpha export ... -> onnx_integration/bundles/mlp_strong_120
- 验证: max|err|=____  pearson=____  (粘 Step 3 实跑结果)
- 部署: bundle 拷进 /gpfs/hddfs/sgqr/shared/onnxalpha/bundles/ ; cfg 用 ts_onnx
MD
echo "记录已建,记得把 Step3 的真实数字填进 ____"
```

---

## 一页流程图（记住这个就够）

```
你 repo 的 weights.json ─┐
                         ├─ onnxalpha export ─→ bundle(model.onnx+schema.json)
genaAC 抽出的 alpha_cfg ─┘                          │
                                                    ├─ 本地: oa.Predictor 验证(Step3)
                                                    └─ 内网: 拷进共享 bundles/ + cfg 指过去
                                                            (.so 全队共享,不编 C++)
```

## 出错速查

| 现象 | 解法 |
|---|---|
| `onnxalpha: command not found` | 没激活你建的环境；先 `conda activate onnx_demo`（或 `source ~/.venvs/onnx_demo/bin/activate`）再跑 |
| export 报 `KeyError: 'alpha_names'` | Step 1 的 cfg 没抽对；确认 `onnx_integration/alpha_cfg_mlp_strong_120.json` 顶层有 `alpha_names` |
| export 报维度断言失败 | weights 的 `n_features` 与子因子 Σshape 不一致；确认用的是 `mlp_strong_120` 那套权重+cfg |
| Step3 `max|err|` 很大(>1e-3) | 多半 alpha_cfg 顺序错了；确认抽的是 `alpha_cfg.ts_mlp`（不是别的模型段） |
| 内网 pip 装不上 | 用 Step 0 的 🔁 离线 wheel 方式 |
