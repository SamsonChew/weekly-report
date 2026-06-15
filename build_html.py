"""Build a single-file HTML viewer with grouped sidebar navigation for weekly reports."""
from pathlib import Path
import base64
import html as html_lib
import mimetypes
import re

import markdown

HERE = Path(__file__).parent

HOME_LINKS = [
    {"title": "Samson Week 2 & 3 Summary",
     "url": "https://njp9rhghllrb.jp.larksuite.com/wiki/GeUswyjYLiqgEYkMZK1jiktfpQb?from=from_copylink"},
    {"title": "Samson Week 4 Summary",
     "url": "https://njp9rhghllrb.jp.larksuite.com/wiki/K2nswkremi8VcskqmddjwOcFpGc?from=from_copylink"},
    {"title": "Samson 模型思考",
     "url": "https://njp9rhghllrb.jp.larksuite.com/wiki/U5cXw5fQPi4mJikkyc3jPHYSp49?from=from_copylink"},
    {"title": "Crypto 高频 Milestone",
     "url": "https://njp9rhghllrb.jp.larksuite.com/wiki/FpgswPrwiiAqY8krF1ljaOhApqf?from=from_copylink"},
    {"title": "AutoResearch + Brainstorm",
     "url": "https://njp9rhghllrb.jp.larksuite.com/wiki/ZCs7wmAAKi8JHKkPbeJjgHzwpUf?from=from_copylink"},
    {"title": "Q2 Model Research Summary",
     "url": "https://njp9rhghllrb.jp.larksuite.com/wiki/DC8iwVLHuiJWfBk9q3cjt1khp5c?from=from_copylink"},
    {"title": "Q1 Model Research Summary",
     "url": "https://njp9rhghllrb.jp.larksuite.com/wiki/WQCDwjxJ1ibyCgkMcBvjlcfQpPc?from=from_copylink"},
]

GROUPS = [
    {"id": "hfcrypto-sol", "label": "HF Crypto · SOL",   "color": "#0550ae"},
    {"id": "deeplob",      "label": "DeepLOB / S&P 500", "color": "#6e40c9"},
    {"id": "quantaalpha",  "label": "QuantaAlpha",         "color": "#b5690e"},
    {"id": "alphabank",    "label": "AlphaBank",           "color": "#116329"},
    {"id": "futures",      "label": "期货",                 "color": "#9a3412"},
]

REPORTS = [
    # ── HF Crypto SOL ─────────────────────────────────────────────────
    {
        "id": "hfcrypto",
        "group": "hfcrypto-sol",
        "title": "design review",
        "subtitle": "SOL 回测落地 / 复现 / 开发 Pipeline 总纲",
        "file": HERE / "hfcrypto_result.md",
    },
    {
        "id": "hfcrypto-baseline",
        "group": "hfcrypto-sol",
        "title": "基线复现",
        "subtitle": "115 因子 · 71 天 OOS · 信号+PnL 双层评估完整体系",
        "file": HERE / "hfcrypto_result_baseline_summary.md",
    },
    {
        "id": "hfcrypto-experiment",
        "group": "hfcrypto-sol",
        "title": "实验记录",
        "subtitle": "组合模型实验 · 病根验证 · 改 loss 迭代",
        "file": HERE / "hfcrypto_experiment.md",
    },
    {
        "id": "hfcrypto-w4",
        "group": "hfcrypto-sol",
        "title": "Week 4",
        "subtitle": "信号→C++→因子修复→run_sim 四阶段 · 单120MLP · 缺口在穿价",
        "file": HERE / "hfcrypto_week4.md",
    },
    {
        "id": "hfcrypto-onnx",
        "group": "hfcrypto-sol",
        "title": "onnx design review",
        "subtitle": "onnx_junjie 统一推理 package · 项目概览 · 可行性调研 · 实施计划",
        "file": HERE / "hfcrypto_onnx.md",
    },
    {
        "id": "hfcrypto-0614",
        "group": "hfcrypto-sol",
        "title": "实盘 dry run 排查",
        "subtitle": "0614 实盘 dry run 问题排查记录",
        "file": HERE / "hfcrypto_0614.md",
    },
    # ── DeepLOB / S&P 500 ─────────────────────────────────────────────
    {
        "id": "deeplob",
        "group": "deeplob",
        "title": "Week 1",
        "subtitle": "四条路径并行 → Bagging 融合 → 精度/召回双轴框架",
        "file": HERE / "week1_report.md",
    },
    {
        "id": "model-summary-w23",
        "group": "deeplob",
        "title": "Week 23 模型",
        "subtitle": "新数据接入范式 + Regime-Adaptive 动态形态 · bar/FiLM/Hypernet γ_t",
        "file": HERE / "model_summary_week23.md",
    },
    {
        "id": "bestresult",
        "group": "deeplob",
        "title": "S&P 500 最优结果",
        "subtitle": "LambdaRank + i2i + Crash Filter · Sharpe 1.311 · $10k→$250k",
        "file": HERE / "best_result.md",
    },
    # ── QuantaAlpha ───────────────────────────────────────────────────
    {
        "id": "quantalpha",
        "group": "quantaalpha",
        "title": "Week 1",
        "subtitle": "从 0 到「可演示」: 内网 LLM × 自动因子挖掘系统",
        "file": HERE / "week1_quantalpha.md",
    },
    {
        "id": "quantalpha-w23",
        "group": "quantaalpha",
        "title": "Week 2,3",
        "subtitle": "AI自动调参Loop / LOB高频OOS / 外部alpha验证 / Qwen3-32B 4并发",
        "file": HERE / "cryptoalpha_week23.md",
    },
    # ── AlphaBank ─────────────────────────────────────────────────────
    {
        "id": "alphabank-w23",
        "group": "alphabank",
        "title": "Week 23",
        "subtitle": "BTC 1s HFT · Return口径/Bar因子/IC Sweep/Return结构分析",
        "file": HERE / "alphabank_week23.md",
    },
    # ── 期货 ──────────────────────────────────────────────────────────
    {
        "id": "futures-code",
        "group": "futures",
        "title": "design review",
        "subtitle": "cafe_syin + fut2cafe 因子迁移工程全记录",
        "file": HERE / "futures_code.md",
    },
]

MD_EXTS = [
    "tables",
    "fenced_code",
    "codehilite",
    "toc",
    "attr_list",
    "md_in_html",
    "sane_lists",
]

_IMG_TAG_RE = re.compile(r'<img\b([^>]*?)\bsrc="([^"]+)"([^>]*)>')


def _embed_image(match: re.Match) -> str:
    before, src, after = match.group(1), match.group(2), match.group(3)
    if src.startswith(("http://", "https://", "data:")):
        return match.group(0)
    img_path = (HERE / src).resolve()
    if not img_path.is_file():
        print(f"  warn: missing image {src}")
        return match.group(0)
    mime, _ = mimetypes.guess_type(str(img_path))
    if not mime:
        mime = "application/octet-stream"
    encoded = base64.b64encode(img_path.read_bytes()).decode("ascii")
    return f'<img{before}src="data:{mime};base64,{encoded}"{after}>'


def render_md(path: Path) -> str:
    md_text = path.read_text(encoding="utf-8")
    md = markdown.Markdown(extensions=MD_EXTS, extension_configs={
        "codehilite": {"guess_lang": False, "noclasses": True, "pygments_style": "default"},
        "toc": {"permalink": False},
    })
    html_body = md.convert(md_text)
    return _IMG_TAG_RE.sub(_embed_image, html_body)


def build_page() -> str:
    rendered = []
    for r in REPORTS:
        body_html = render_md(r["file"])
        rendered.append({**r, "body": body_html})

    group_map = {g["id"]: g for g in GROUPS}
    reports_by_group = {g["id"]: [] for g in GROUPS}
    for r in rendered:
        gid = r.get("group", "")
        if gid in reports_by_group:
            reports_by_group[gid].append(r)

    # ── Home panel ────────────────────────────────────────────────────
    home_cards = "\n".join(
        f'      <a href="{l["url"]}" target="_blank" rel="noopener" class="home-card">'
        f'<span class="home-card-num">{i}</span>'
        f'<span class="home-card-title">{html_lib.escape(l["title"])}</span>'
        f'<span class="home-card-arrow">↗</span></a>'
        for i, l in enumerate(HOME_LINKS, 1)
    )
    home_panel = f'''  <section class="report" id="home">
    <header class="report-header">
      <h1 style="margin-top:0">文档索引</h1>
      <p class="subtitle">Lark 文档快速入口</p>
    </header>
    <div class="home-links">
{home_cards}
    </div>
  </section>'''

    # ── Sidebar ────────────────────────────────────────────────────────
    sidebar_parts = ['    <button class="nav-item nav-home" data-target="home">首页</button>\n    <div class="nav-divider"></div>']
    for g in GROUPS:
        items = reports_by_group[g["id"]]
        if not items:
            continue
        items_html = "\n".join(
            f'      <button class="nav-item" data-target="{r["id"]}">{html_lib.escape(r["title"])}</button>'
            for r in items
        )
        sidebar_parts.append(
            f'    <div class="nav-group" style="--gc:{g["color"]}">\n'
            f'      <div class="nav-group-label">{html_lib.escape(g["label"])}</div>\n'
            f'{items_html}\n'
            f'    </div>'
        )
    sidebar_html = "\n".join(sidebar_parts)

    # ── Panels ────────────────────────────────────────────────────────
    report_panels = "\n".join(
        f'''  <section class="report" id="{r["id"]}">
    <header class="report-header">
      <div class="report-group-tag" style="color:{group_map[r["group"]]["color"]}">{html_lib.escape(group_map[r["group"]]["label"])}</div>
      <h1>{html_lib.escape(r["title"])}</h1>
      <p class="subtitle">{html_lib.escape(r["subtitle"])}</p>
    </header>
    <article class="markdown-body">
{r["body"]}
    </article>
  </section>'''
        for r in rendered
    )
    panels = home_panel + "\n" + report_panels

    css = """
      :root {
        --bg: #f6f8fa;
        --sidebar-bg: #f6f8fa;
        --panel-bg: #ffffff;
        --text: #1f2328;
        --muted: #57606a;
        --border: #d0d7de;
        --link: #0969da;
        --code-bg: #f6f8fa;
        --hover-bg: #eaeef2;
        --topbar-h: 52px;
        --sidebar-w: 210px;
      }
      *, *::before, *::after { box-sizing: border-box; }
      html, body { height: 100%; overflow: hidden; margin: 0; padding: 0; }
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                     "Hiragino Sans GB", "Microsoft YaHei", Helvetica, Arial, sans-serif;
        font-size: 15px;
        line-height: 1.65;
        background: var(--bg);
        color: var(--text);
      }

      /* ── Topbar ── */
      .topbar {
        height: var(--topbar-h);
        background: var(--panel-bg);
        border-bottom: 1px solid var(--border);
        padding: 0 20px;
        display: flex;
        align-items: center;
        gap: 10px;
        position: relative;
        z-index: 10;
      }
      .topbar-logo {
        font-size: 15px;
        font-weight: 700;
        color: var(--text);
        letter-spacing: -0.01em;
      }
      .topbar-logo span { color: var(--muted); font-weight: 400; }
      .topbar-hint {
        margin-left: auto;
        font-size: 12px;
        color: var(--muted);
        cursor: pointer;
        padding: 3px 10px;
        border: 1px solid var(--border);
        border-radius: 5px;
        background: var(--bg);
        user-select: none;
        transition: background 0.1s;
      }
      .topbar-hint:hover { background: var(--hover-bg); color: var(--text); }

      /* ── Layout ── */
      .layout {
        display: flex;
        height: calc(100vh - var(--topbar-h));
        overflow: hidden;
      }

      /* ── Sidebar ── */
      .sidebar {
        width: var(--sidebar-w);
        flex-shrink: 0;
        background: var(--sidebar-bg);
        border-right: 1px solid var(--border);
        overflow-y: auto;
        padding: 10px 0 32px;
      }
      .nav-group { margin-bottom: 4px; }
      .nav-group-label {
        font-size: 10.5px;
        font-weight: 700;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        padding: 14px 14px 5px;
        color: var(--gc, var(--muted));
        opacity: 0.75;
      }
      .nav-item {
        display: block;
        width: 100%;
        text-align: left;
        background: transparent;
        border: none;
        border-left: 3px solid transparent;
        padding: 6px 14px 6px 11px;
        font-size: 13.5px;
        font-weight: 500;
        color: #444c56;
        cursor: pointer;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        transition: background 0.1s, color 0.1s, border-color 0.1s;
        line-height: 1.4;
        font-family: inherit;
      }
      .nav-item:hover { background: var(--hover-bg); color: var(--text); }
      .nav-item.active {
        border-left-color: var(--gc, #0969da);
        background: rgba(0,0,0,0.04);
        color: var(--gc, #0969da);
        font-weight: 600;
      }
      .nav-home {
        margin: 8px 8px 0;
        width: calc(100% - 16px);
        border-radius: 6px;
        border-left: none !important;
        font-weight: 600;
        font-size: 13.5px;
        padding: 7px 12px;
        background: var(--hover-bg);
        color: var(--text);
      }
      .nav-home:hover { background: #dde3ea; }
      .nav-home.active { background: #1f2328 !important; color: #fff !important; }
      .nav-divider { height: 1px; background: var(--border); margin: 10px 0 2px; }

      /* ── Home page ── */
      .home-links { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
      .home-card {
        display: flex; align-items: center; gap: 14px;
        padding: 14px 18px;
        border: 1px solid var(--border); border-radius: 8px;
        text-decoration: none; color: var(--text);
        background: var(--panel-bg);
        transition: border-color 0.15s, box-shadow 0.15s, background 0.1s;
      }
      .home-card:hover {
        border-color: #0969da;
        box-shadow: 0 2px 10px rgba(9,105,218,0.10);
        text-decoration: none;
        background: #f0f6ff;
      }
      .home-card-num {
        width: 24px; height: 24px; border-radius: 50%;
        background: var(--border); color: var(--muted);
        font-size: 12px; font-weight: 700;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
      }
      .home-card-title { flex: 1; font-weight: 500; font-size: 15px; }
      .home-card-arrow { color: var(--muted); font-size: 16px; flex-shrink: 0; }

      /* ── Main area ── */
      .main-area {
        flex: 1;
        overflow-y: auto;
        background: var(--bg);
      }
      .report {
        display: none;
        max-width: 900px;
        margin: 0 auto;
        padding: 36px 52px 100px;
        background: var(--panel-bg);
        min-height: 100%;
      }
      .report.active { display: block; }

      .report-group-tag {
        font-size: 11.5px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 6px;
        opacity: 0.8;
      }
      .report-header {
        border-bottom: 2px solid var(--border);
        padding-bottom: 18px;
        margin-bottom: 32px;
      }
      .report-header h1 { margin: 4px 0 6px; font-size: 26px; }
      .report-header .subtitle { margin: 0; color: var(--muted); font-size: 14.5px; }

      /* ── Markdown body ── */
      .markdown-body h1 {
        font-size: 24px; margin-top: 48px; margin-bottom: 14px;
        padding-bottom: 8px; border-bottom: 1px solid var(--border);
      }
      .markdown-body h2 {
        font-size: 20px; margin-top: 36px; margin-bottom: 12px;
        padding-bottom: 6px; border-bottom: 1px solid var(--border);
      }
      .markdown-body h3 { font-size: 17px; margin-top: 28px; margin-bottom: 10px; }
      .markdown-body h4 { font-size: 15px; margin-top: 22px; margin-bottom: 8px; color: #24292f; }
      .markdown-body h5 { font-size: 13.5px; margin-top: 18px; margin-bottom: 6px; color: var(--muted); }
      .markdown-body p { margin: 0 0 14px; }
      .markdown-body a { color: var(--link); text-decoration: none; }
      .markdown-body a:hover { text-decoration: underline; }
      .markdown-body img {
        max-width: 100%; height: auto; display: block; margin: 16px auto;
        border: 1px solid var(--border); border-radius: 6px;
        background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
      }
      .markdown-body code {
        font-family: "SF Mono", Consolas, "Liberation Mono", Menlo, monospace;
        background: var(--code-bg); padding: 2px 6px; border-radius: 4px; font-size: 0.87em;
      }
      .markdown-body pre {
        background: var(--code-bg); padding: 14px 18px; border-radius: 6px;
        overflow-x: auto; font-size: 13px; line-height: 1.55; border: 1px solid var(--border);
      }
      .markdown-body pre code { background: transparent; padding: 0; border-radius: 0; font-size: 13px; }
      .markdown-body blockquote {
        margin: 0 0 16px; padding: 8px 18px; color: var(--muted);
        border-left: 4px solid var(--border); background: #f6f8fa; border-radius: 0 4px 4px 0;
      }
      .markdown-body blockquote p { margin: 6px 0; }
      .markdown-body ul, .markdown-body ol { padding-left: 28px; margin: 0 0 14px; }
      .markdown-body li { margin: 4px 0; }
      .markdown-body table {
        border-collapse: collapse; margin: 16px 0; font-size: 13.5px;
        display: block; overflow-x: auto; max-width: 100%;
      }
      .markdown-body table th, .markdown-body table td {
        border: 1px solid var(--border); padding: 8px 12px; text-align: left; vertical-align: top;
      }
      .markdown-body table th { background: var(--code-bg); font-weight: 600; }
      .markdown-body table tr:nth-child(even) td { background: #f6f8fa; }
      .markdown-body hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
      .markdown-body em { color: #57606a; }
      .markdown-body strong { color: #1f2328; }

      /* ── Mobile ── */
      @media (max-width: 700px) {
        html, body { height: auto; overflow: auto; }
        .layout { flex-direction: column; height: auto; overflow: visible; }
        .sidebar {
          width: 100%; border-right: none; border-bottom: 1px solid var(--border);
          padding: 8px; display: flex; flex-wrap: wrap; gap: 4px; overflow: visible;
        }
        .nav-group { display: contents; }
        .nav-group-label { display: none; }
        .nav-item {
          border-left: none; border-bottom: 2px solid transparent;
          padding: 5px 10px; border-radius: 5px; white-space: nowrap; flex-shrink: 0;
        }
        .nav-item.active {
          border-left: none; border-bottom-color: var(--gc, #0969da);
          background: rgba(0,0,0,0.04);
        }
        .main-area { overflow: visible; height: auto; }
        .report { padding: 24px 18px 60px; min-height: auto; }
      }
    """

    js = r"""
      const navItems = Array.from(document.querySelectorAll('.nav-item'));
      const reports  = document.querySelectorAll('.report');
      const mainArea = document.querySelector('.main-area');

      function scrollMainTo(px, behavior) {
        if (getComputedStyle(mainArea).overflowY !== 'visible') {
          mainArea.scrollTo({ top: px, behavior: behavior || 'smooth' });
        } else {
          window.scrollTo({ top: px, behavior: behavior || 'smooth' });
        }
      }

      function activate(id) {
        navItems.forEach(b => b.classList.toggle('active', b.dataset.target === id));
        reports.forEach(r => r.classList.toggle('active', r.id === id));
        scrollMainTo(0, 'instant');
        if (history.replaceState) history.replaceState(null, '', '#' + id);
      }

      navItems.forEach(b => b.addEventListener('click', () => activate(b.dataset.target)));
      const initial = (location.hash || '').replace('#', '') || navItems[0].dataset.target;
      activate(document.getElementById(initial) ? initial : navItems[0].dataset.target);

      // ── Section heading navigation ────────────────────────────────
      function activeHeadings() {
        const panel = document.querySelector('.report.active');
        return panel ? Array.from(panel.querySelectorAll('h1, h2, h3')) : [];
      }

      function getScrollTop() {
        return getComputedStyle(mainArea).overflowY !== 'visible' ? mainArea.scrollTop : window.scrollY;
      }

      function currentHeadingIdx(headings) {
        const areaTop = mainArea.getBoundingClientRect().top;
        const scrollTop = getScrollTop();
        let idx = -1;
        for (let i = 0; i < headings.length; i++) {
          const relTop = headings[i].getBoundingClientRect().top - areaTop + scrollTop;
          if (relTop <= scrollTop + 4) idx = i;
          else break;
        }
        return idx;
      }

      function jumpToHeading(h) {
        const areaTop = mainArea.getBoundingClientRect().top;
        const scrollTop = getScrollTop();
        const relTop = h.getBoundingClientRect().top - areaTop + scrollTop;
        scrollMainTo(Math.max(0, relTop - 8));
        showToast(h.textContent.trim());
      }

      // ── Toast ──────────────────────────────────────────────────────
      const toast = document.createElement('div');
      toast.id = 'kbd-toast';
      Object.assign(toast.style, {
        position:'fixed', bottom:'28px', left:'50%', transform:'translateX(-50%) translateY(12px)',
        background:'rgba(31,35,40,0.88)', color:'#fff', padding:'8px 18px',
        borderRadius:'8px', fontSize:'13px', fontFamily:'inherit',
        pointerEvents:'none', opacity:'0', transition:'opacity .18s, transform .18s',
        maxWidth:'70vw', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis', zIndex:'999'
      });
      document.body.appendChild(toast);
      let toastTimer;
      function showToast(msg) {
        clearTimeout(toastTimer);
        toast.textContent = msg;
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(-50%) translateY(0)';
        toastTimer = setTimeout(() => {
          toast.style.opacity = '0';
          toast.style.transform = 'translateX(-50%) translateY(12px)';
        }, 1800);
      }

      // ── Help overlay ───────────────────────────────────────────────
      const helpOverlay = document.createElement('div');
      helpOverlay.id = 'kbd-help';
      helpOverlay.innerHTML = `
        <div style="background:#fff;border-radius:10px;padding:28px 32px;max-width:380px;width:90vw;box-shadow:0 8px 40px rgba(0,0,0,.18);">
          <div style="font-weight:700;font-size:16px;margin-bottom:16px;color:#1f2328">⌨️ 键盘快捷键</div>
          <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr><td style="padding:6px 12px 6px 0;color:#57606a;font-family:monospace">]</td><td>下一个标题</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a;font-family:monospace">[</td><td>上一个标题</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a;font-family:monospace">1 – 9</td><td>切换到第 N 篇报告</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a;font-family:monospace">g g</td><td>回到顶部</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a;font-family:monospace">G</td><td>跳到底部</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a;font-family:monospace">?</td><td>显示 / 关闭此面板</td></tr>
          </table>
          <div style="margin-top:18px;text-align:right">
            <button onclick="document.getElementById('kbd-help').style.display='none'"
              style="border:1px solid #d0d7de;background:#f6f8fa;padding:5px 14px;border-radius:6px;cursor:pointer;font-size:13px">关闭</button>
          </div>
        </div>`;
      Object.assign(helpOverlay.style, {
        display:'none', position:'fixed', inset:'0',
        background:'rgba(0,0,0,.35)', zIndex:'1000', alignItems:'center', justifyContent:'center'
      });
      helpOverlay.addEventListener('click', e => { if (e.target === helpOverlay) helpOverlay.style.display='none'; });
      document.body.appendChild(helpOverlay);

      // ── Key handler ────────────────────────────────────────────────
      let lastKey = '', lastKeyTime = 0;
      document.addEventListener('keydown', e => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
        const key = e.key;

        if (/^[1-9]$/.test(key) && !e.metaKey && !e.ctrlKey) {
          const idx = parseInt(key) - 1;
          if (idx < navItems.length) { e.preventDefault(); activate(navItems[idx].dataset.target); return; }
        }

        if (key === ']') {
          e.preventDefault();
          const hs = activeHeadings(); if (!hs.length) return;
          jumpToHeading(hs[Math.min(currentHeadingIdx(hs) + 1, hs.length - 1)]);
          return;
        }

        if (key === '[') {
          e.preventDefault();
          const hs = activeHeadings(); if (!hs.length) return;
          jumpToHeading(hs[Math.max(currentHeadingIdx(hs) - 1, 0)]);
          return;
        }

        const now = Date.now();
        if (key === 'g' && !e.shiftKey) {
          if (lastKey === 'g' && now - lastKeyTime < 500) {
            e.preventDefault();
            scrollMainTo(0);
            showToast('⬆ 回到顶部');
          }
          lastKey = 'g'; lastKeyTime = now; return;
        }

        if (key === 'G') {
          e.preventDefault();
          scrollMainTo(mainArea.scrollHeight || document.body.scrollHeight);
          showToast('⬇ 跳到底部');
          return;
        }

        if (key === '?') {
          e.preventDefault();
          const h = helpOverlay;
          h.style.display = h.style.display === 'none' ? 'flex' : 'none';
          return;
        }

        lastKey = key; lastKeyTime = now;
      });
    """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>junjie · 周报</title>
  <style>{css}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-logo">junjie <span>· 周报</span></div>
    <button class="topbar-hint" onclick="document.getElementById('kbd-help').style.display='flex'">? 快捷键</button>
  </header>
  <div class="layout">
    <nav class="sidebar">
{sidebar_html}
    </nav>
    <main class="main-area">
{panels}
    </main>
  </div>
  <script>{js}</script>
</body>
</html>
"""


def main():
    html_text = build_page()
    out = HERE / "index.html"
    out.write_text(html_text, encoding="utf-8")
    print(f"wrote {out} ({len(html_text):,} chars)")


if __name__ == "__main__":
    main()
