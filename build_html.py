"""Build a single-file HTML viewer with tab switcher for the two week-1 reports.

Output: /home/samson/mlf-qyas-junjie/weekly_report/index.html

Run with: /home/samson/.local/share/mamba/envs/mlf-qyas/bin/python3 build_html.py
"""
from pathlib import Path
import base64
import html as html_lib
import mimetypes
import re

import markdown

HERE = Path(__file__).parent

REPORTS = [
    {
        "id": "deeplob",
        "title": "DeepLOB Week 1",
        "subtitle": "四条路径并行 → Bagging 融合 → 精度/召回双轴框架",
        "file": HERE / "week1_report.md",
    },
    {
        "id": "quantalpha",
        "title": "QuantaAlpha Week 1",
        "subtitle": "从 0 到「可演示」: 内网 LLM × 自动因子挖掘系统",
        "file": HERE / "week1_quantalpha.md",
    },
    {
        "id": "quantalpha-w23",
        "title": "QuantaAlpha Week 2,3",
        "subtitle": "AI自动调参Loop / LOB高频OOS / 外部alpha验证 / Qwen3-32B 4并发",
        "file": HERE / "cryptoalpha_week23.md",
    },
    {
        "id": "hfcrypto",
        "title": "HF Crypto — SOL",
        "subtitle": "SOL 回测落地 / 复现 / 开发 Pipeline 总纲",
        "file": HERE / "hfcrypto_result.md",
    },
    {
        "id": "hfcrypto-baseline",
        "title": "SOL 基线复现",
        "subtitle": "115 因子 · 71 天 OOS · 信号+PnL 双层评估完整体系",
        "file": HERE / "hfcrypto_result_baseline_summary.md",
    },
    {
        "id": "hfcrypto-experiment",
        "title": "SOL 实验记录",
        "subtitle": "组合模型实验 · 病根验证 · 改 loss 迭代",
        "file": HERE / "hfcrypto_experiment.md",
    },
    {
        "id": "bestresult",
        "title": "S&P 500 最优结果",
        "subtitle": "LambdaRank + i2i + Crash Filter · Sharpe 1.311 · $10k→$250k",
        "file": HERE / "best_result.md",
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

    nav_buttons = "\n".join(
        f'      <button class="tab-btn" data-target="{r["id"]}">{html_lib.escape(r["title"])}</button>'
        for r in rendered
    )

    panels = "\n".join(
        f'''  <section class="report" id="{r["id"]}">
    <header class="report-header">
      <h1>{html_lib.escape(r["title"])}</h1>
      <p class="subtitle">{html_lib.escape(r["subtitle"])}</p>
    </header>
    <article class="markdown-body">
{r["body"]}
    </article>
  </section>'''
        for r in rendered
    )

    css = """
      :root {
        --bg: #fafafa;
        --panel-bg: #ffffff;
        --text: #1f2328;
        --muted: #57606a;
        --border: #d0d7de;
        --link: #0969da;
        --code-bg: #f6f8fa;
        --tab-active: #0969da;
        --tab-hover: #eaeef2;
        --quote-border: #d0d7de;
        --table-stripe: #f6f8fa;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                     "Hiragino Sans GB", "Microsoft YaHei", Helvetica, Arial, sans-serif;
        font-size: 15px;
        line-height: 1.65;
        background: var(--bg);
        color: var(--text);
      }
      .topbar {
        position: sticky;
        top: 0;
        z-index: 10;
        background: var(--panel-bg);
        border-bottom: 1px solid var(--border);
        padding: 12px 24px;
        display: flex;
        align-items: center;
        gap: 16px;
        flex-wrap: wrap;
      }
      .topbar h2 {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
        color: var(--muted);
      }
      .tabs {
        display: flex;
        gap: 4px;
        margin-left: auto;
      }
      .tab-btn {
        background: transparent;
        border: 1px solid var(--border);
        padding: 8px 16px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        border-radius: 6px;
        color: var(--muted);
        transition: all 0.15s ease;
      }
      .tab-btn:hover { background: var(--tab-hover); color: var(--text); }
      .tab-btn.active {
        background: var(--tab-active);
        color: white;
        border-color: var(--tab-active);
      }
      .report {
        display: none;
        max-width: 980px;
        margin: 0 auto;
        padding: 32px 48px 80px;
        background: var(--panel-bg);
        min-height: calc(100vh - 60px);
      }
      .report.active { display: block; }
      .report-header {
        border-bottom: 2px solid var(--border);
        padding-bottom: 16px;
        margin-bottom: 32px;
      }
      .report-header h1 { margin: 0 0 6px; font-size: 28px; }
      .report-header .subtitle { margin: 0; color: var(--muted); font-size: 15px; }

      .markdown-body h1 {
        font-size: 26px;
        margin-top: 48px;
        margin-bottom: 16px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--border);
      }
      .markdown-body h2 {
        font-size: 22px;
        margin-top: 36px;
        margin-bottom: 14px;
        padding-bottom: 6px;
        border-bottom: 1px solid var(--border);
      }
      .markdown-body h3 { font-size: 18px; margin-top: 28px; margin-bottom: 12px; }
      .markdown-body h4 { font-size: 16px; margin-top: 22px; margin-bottom: 10px; color: #24292f; }
      .markdown-body h5 { font-size: 14px; margin-top: 18px; margin-bottom: 8px; color: #57606a; }
      .markdown-body p { margin: 0 0 14px; }
      .markdown-body a { color: var(--link); text-decoration: none; }
      .markdown-body a:hover { text-decoration: underline; }
      .markdown-body img {
        max-width: 100%;
        height: auto;
        display: block;
        margin: 16px auto;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: #fff;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
      }
      .markdown-body code {
        font-family: "SF Mono", Consolas, "Liberation Mono", Menlo, monospace;
        background: var(--code-bg);
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.88em;
      }
      .markdown-body pre {
        background: var(--code-bg);
        padding: 14px 18px;
        border-radius: 6px;
        overflow-x: auto;
        font-size: 13px;
        line-height: 1.55;
        border: 1px solid var(--border);
      }
      .markdown-body pre code {
        background: transparent;
        padding: 0;
        border-radius: 0;
        font-size: 13px;
      }
      .markdown-body blockquote {
        margin: 0 0 16px;
        padding: 8px 18px;
        color: var(--muted);
        border-left: 4px solid var(--quote-border);
        background: #f6f8fa;
        border-radius: 0 4px 4px 0;
      }
      .markdown-body blockquote p { margin: 6px 0; }
      .markdown-body ul, .markdown-body ol { padding-left: 28px; margin: 0 0 14px; }
      .markdown-body li { margin: 4px 0; }
      .markdown-body table {
        border-collapse: collapse;
        margin: 16px 0;
        font-size: 13.5px;
        display: block;
        overflow-x: auto;
        max-width: 100%;
      }
      .markdown-body table th, .markdown-body table td {
        border: 1px solid var(--border);
        padding: 8px 12px;
        text-align: left;
        vertical-align: top;
      }
      .markdown-body table th {
        background: var(--code-bg);
        font-weight: 600;
      }
      .markdown-body table tr:nth-child(even) td { background: var(--table-stripe); }
      .markdown-body hr {
        border: none;
        border-top: 1px solid var(--border);
        margin: 28px 0;
      }
      .markdown-body em { color: #57606a; }
      .markdown-body strong { color: #1f2328; }

      @media (max-width: 760px) {
        .report { padding: 24px 18px 60px; }
        .topbar { padding: 10px 14px; }
        .tabs { width: 100%; margin-left: 0; }
        .tab-btn { flex: 1; }
      }
    """

    js = """
      const buttons = document.querySelectorAll('.tab-btn');
      const reports = document.querySelectorAll('.report');

      function activate(id) {
        buttons.forEach(b => b.classList.toggle('active', b.dataset.target === id));
        reports.forEach(r => r.classList.toggle('active', r.id === id));
        window.scrollTo({ top: 0, behavior: 'instant' });
        if (history.replaceState) history.replaceState(null, '', '#' + id);
      }
      buttons.forEach(b => b.addEventListener('click', () => activate(b.dataset.target)));
      const initial = (location.hash || '').replace('#', '') || buttons[0].dataset.target;
      activate(document.getElementById(initial) ? initial : buttons[0].dataset.target);

      // ── Section keyboard navigation ──────────────────────────────────
      const TOPBAR_H = 64;

      function activeHeadings() {
        const panel = document.querySelector('.report.active');
        if (!panel) return [];
        return Array.from(panel.querySelectorAll('h1, h2, h3'));
      }

      function currentHeadingIdx(headings) {
        const mid = window.scrollY + TOPBAR_H + 4;
        let idx = -1;
        for (let i = 0; i < headings.length; i++) {
          if (headings[i].getBoundingClientRect().top + window.scrollY <= mid) idx = i;
          else break;
        }
        return idx;
      }

      function jumpToHeading(h) {
        const top = h.getBoundingClientRect().top + window.scrollY - TOPBAR_H - 8;
        window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
        showToast(h.textContent.trim());
      }

      // Toast
      const toast = document.createElement('div');
      toast.id = 'kbd-toast';
      Object.assign(toast.style, {
        position:'fixed', bottom:'28px', left:'50%', transform:'translateX(-50%) translateY(12px)',
        background:'rgba(31,35,40,0.88)', color:'#fff', padding:'8px 18px',
        borderRadius:'8px', fontSize:'13px', fontFamily:'inherit',
        pointerEvents:'none', opacity:'0', transition:'opacity .18s, transform .18s',
        maxWidth:'70vw', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis',
        zIndex:'999'
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

      // Help overlay
      const helpOverlay = document.createElement('div');
      helpOverlay.id = 'kbd-help';
      helpOverlay.innerHTML = `
        <div style="background:#fff;border-radius:10px;padding:28px 32px;max-width:380px;width:90vw;box-shadow:0 8px 40px rgba(0,0,0,.18);">
          <div style="font-weight:700;font-size:16px;margin-bottom:16px;color:#1f2328">⌨️ 键盘快捷键</div>
          <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr><td style="padding:6px 12px 6px 0;color:#57606a">]</td><td>下一个标题</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a">[</td><td>上一个标题</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a">1 – ${buttons.length}</td><td>切换到对应 Tab</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a">g g</td><td>回到顶部</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a">G</td><td>跳到底部</td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#57606a">?</td><td>显示 / 关闭此面板</td></tr>
          </table>
          <div style="margin-top:18px;text-align:right">
            <button onclick="document.getElementById('kbd-help').style.display='none'"
              style="border:1px solid #d0d7de;background:#f6f8fa;padding:5px 14px;border-radius:6px;cursor:pointer;font-size:13px">关闭</button>
          </div>
        </div>`;
      Object.assign(helpOverlay.style, {
        display:'none', position:'fixed', inset:'0',
        background:'rgba(0,0,0,.35)', zIndex:'1000',
        alignItems:'center', justifyContent:'center'
      });
      helpOverlay.addEventListener('click', e => { if (e.target === helpOverlay) helpOverlay.style.display='none'; });
      document.body.appendChild(helpOverlay);

      // Key handler
      let lastKey = '', lastKeyTime = 0;
      document.addEventListener('keydown', e => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
        const key = e.key;

        // Tab switching: 1-9
        if (/^[1-9]$/.test(key) && !e.metaKey && !e.ctrlKey) {
          const idx = parseInt(key) - 1;
          if (idx < buttons.length) { e.preventDefault(); buttons[idx].click(); return; }
        }

        // ] next heading
        if (key === ']') {
          e.preventDefault();
          const hs = activeHeadings();
          if (!hs.length) return;
          const cur = currentHeadingIdx(hs);
          const next = hs[Math.min(cur + 1, hs.length - 1)];
          jumpToHeading(next);
          return;
        }

        // [ prev heading
        if (key === '[') {
          e.preventDefault();
          const hs = activeHeadings();
          if (!hs.length) return;
          const cur = currentHeadingIdx(hs);
          const prev = hs[Math.max(cur - 1, 0)];
          jumpToHeading(prev);
          return;
        }

        // g g → top
        const now = Date.now();
        if (key === 'g' && !e.shiftKey) {
          if (lastKey === 'g' && now - lastKeyTime < 500) {
            e.preventDefault();
            window.scrollTo({ top: 0, behavior: 'smooth' });
            showToast('⬆ 回到顶部');
          }
          lastKey = 'g'; lastKeyTime = now;
          return;
        }

        // G → bottom
        if (key === 'G') {
          e.preventDefault();
          window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
          showToast('⬇ 跳到底部');
          return;
        }

        // ? → help
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
  <title>mlf-qyas-junjie · Week 1 周报</title>
  <style>{css}</style>
</head>
<body>
  <nav class="topbar">
    <h2>mlf-qyas-junjie · Week 1</h2>
    <div class="tabs">
{nav_buttons}
    </div>
  </nav>

{panels}

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
