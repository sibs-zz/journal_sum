"""Daily HTML page and the archive index."""

from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from journal_agent.common import OUTPUT_DIR, Article

logger = logging.getLogger("journal_agent")

STYLES = """
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif; background:#e5f6e8; color:#1b3a1f; }
header { background:#1f7a3a; color:#fff; padding:18px 24px; display:flex; align-items:flex-start; gap:16px; }
.back-home { flex:none; display:inline-flex; align-items:center; padding:8px 14px; margin-top:2px; background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.35); border-radius:8px; color:#fff; text-decoration:none; font-size:14px; font-weight:550; white-space:nowrap; transition:background .15s ease; }
.back-home:hover { background:rgba(255,255,255,.28); color:#fff; }
.header-main { flex:1; min-width:0; }
h1 { margin:0 0 6px; font-size:26px; }
.container { display:flex; gap:18px; padding:18px; max-width:1200px; margin:0 auto; }
nav { width:220px; flex:none; }
nav a { display:block; background:#fff; margin-bottom:8px; padding:8px 10px; border-radius:8px; color:#1f7a3a; text-decoration:none; }
main { flex:1; min-width:0; }
.journal { background:#fff; border-radius:12px; padding:16px 18px; margin-bottom:16px; }
.trends { background:#f3fbf4; border-left:4px solid #1f7a3a; padding:8px 12px; white-space:pre-wrap; }
.card { border-top:1px solid #e3efe4; padding:12px 0; }
.title { font-weight:650; font-size:18px; }
.meta { color:#5d7262; font-size:13px; margin:4px 0 8px; }
.summary { white-space:pre-wrap; line-height:1.55; }
a { color:#0b6b32; }
.footer { text-align:center; color:#5d7262; padding:18px; }
input { width:100%; padding:8px 10px; border:1px solid #cfe3d3; border-radius:8px; }
""".strip()

SCRIPT = """
<script>
function filterCards() {
  const q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('.card').forEach(card => {
    card.style.display = card.innerText.toLowerCase().includes(q) ? '' : 'none';
  });
}
</script>
""".strip()


def write_report(articles: list[Article], trends: dict[str, str], stats: dict[str, int]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_tag = datetime.now().strftime("%Y-%m-%d")
    grouped: dict[str, list[Article]] = {}
    for article in articles:
        grouped.setdefault(article.journal, []).append(article)
    order = list(dict.fromkeys(article.journal for article in articles))
    parts = [
        "<!DOCTYPE html>",
        "<html lang='zh-CN'><head><meta charset='UTF-8'>",
        f"<title>期刊每日摘要 · {date_tag}</title>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<style>{STYLES}</style></head><body>",
        "<header>",
        "<a class='back-home' href='index.html' title='返回日期目录'>← 目录首页</a>",
        "<div class='header-main'>",
        "<h1>期刊自动摘要 · 作物视角</h1>",
        f"<p>日期 {date_tag} · 生成 {generated} · "
        f"新抓取 {stats.get('fetched', 0)} · 缓存跳过 {stats.get('cached', 0)} · "
        f"重复跳过 {stats.get('duplicate', 0)} · 本次保留 {len(articles)}</p>",
        "</div></header>",
        "<div class='container'><nav>",
    ]
    for journal in order:
        anchor = html.escape(journal.replace(" ", "_"))
        parts.append(f"<a href='#{anchor}'>{html.escape(journal)}（{len(grouped[journal])}）</a>")
    parts.append("</nav><main>")
    parts.append("<p><input id='q' placeholder='搜索标题或总结' oninput='filterCards()'></p>")
    if not articles:
        parts.append("<div class='journal'>本次窗口内没有新的、且尚未整理过的文章。</div>")
    for journal in order:
        anchor = html.escape(journal.replace(" ", "_"))
        parts.append(f"<section class='journal' id='{anchor}'><h2>{html.escape(journal)}</h2>")
        if trends.get(journal):
            parts.append(f"<div class='trends'>{html.escape(trends[journal])}</div>")
        for article in sorted(grouped[journal], key=lambda item: item.pub_date, reverse=True):
            parts.append("<div class='card'>")
            parts.append(f"<div class='title'>{html.escape(article.title)}</div>")
            meta = f"{article.pub_date} · {article.content_source or article.source}"
            if article.score:
                meta += f" · 相关度 {article.score:g}"
            if article.reason:
                meta += f" · {article.reason}"
            parts.append(f"<div class='meta'>{html.escape(meta)}</div>")
            if article.summary:
                parts.append(f"<div class='summary'>{html.escape(article.summary)}</div>")
            if article.url:
                parts.append(
                    f"<p><a href='{html.escape(article.url)}' target='_blank' rel='noopener'>原文</a></p>"
                )
            parts.append("</div>")
        parts.append("</section>")
    parts.append("</main></div>")
    parts.append("<div class='footer'>页面由本地脚本生成。摘要只依据抓到的标题和摘要，请以原文为准。</div>")
    parts.append(SCRIPT)
    parts.append("</body></html>")
    path = OUTPUT_DIR / f"index_{date_tag}.html"
    path.write_text("\n".join(parts), encoding="utf-8")
    _write_index(generated, date_tag)
    logger.info("已写入 %s", path)
    return path


def _write_index(generated: str, latest_date: str) -> None:
    pages = sorted(OUTPUT_DIR.glob("index_*.html"), reverse=True)
    cards = []
    for page in pages:
        label = page.name.replace("index_", "").replace(".html", "")
        is_latest = label == latest_date
        cls = "day-card latest" if is_latest else "day-card"
        star = " ★" if is_latest else ""
        cards.append(
            f"<a class='{cls}' href='{html.escape(page.name)}'>"
            f"<span class='day-date{' latest-text' if is_latest else ''}'>{html.escape(label)}{star}</span>"
            f"<span class='day-hint'>{'最新' if is_latest else '查看摘要'}</span>"
            f"</a>"
        )
    body = "\n".join(cards) or "<p class='empty'>暂无历史摘要页</p>"
    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>期刊摘要索引 · 作物视角</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
{INDEX_STYLES}
</style></head><body>
<div class="wrap">
  <header class="hero">
    <h1>期刊摘要索引</h1>
    <p class="sub">作物 / 育种 / 功能基因组 · 选择日期进入当日摘要</p>
    <p class="meta">更新于 {html.escape(generated)} · 最新 <span class="latest-text">{html.escape(latest_date)} ★</span></p>
  </header>
  <main class="grid">{body}</main>
  <footer class="foot">本地脚本生成 · 摘要请以原文为准</footer>
</div>
</body></html>"""
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")


def rebuild_index(latest_date: Optional[str] = None) -> Path:
    """Regenerate site/index.html from existing index_*.html pages (no redirect)."""
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    pages = sorted(OUTPUT_DIR.glob("index_*.html"), reverse=True)
    if not latest_date and pages:
        latest_date = pages[0].name.replace("index_", "").replace(".html", "")
    latest_date = latest_date or datetime.now().strftime("%Y-%m-%d")
    _write_index(generated, latest_date)
    path = OUTPUT_DIR / "index.html"
    logger.info("已刷新索引页 %s", path)
    return path


INDEX_STYLES = """
body {
  margin:0;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;
  background:linear-gradient(165deg,#e8f5ea 0%,#f7fbf8 45%,#e3f0e6 100%);
  color:#1b3a1f;
  min-height:100vh;
}
.wrap { max-width:920px; margin:0 auto; padding:28px 18px 40px; }
.hero {
  background:linear-gradient(120deg,#1f7a3a,#2d9a52);
  color:#fff;
  border-radius:16px;
  padding:28px 26px;
  box-shadow:0 10px 30px rgba(31,122,58,.25);
}
.hero h1 { margin:0 0 8px; font-size:28px; letter-spacing:.02em; }
.sub { margin:0; opacity:.92; font-size:15px; }
.meta { margin:14px 0 0; font-size:13px; opacity:.88; }
.latest-text { color:#ff6b6b; font-weight:700; }
.grid {
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(240px,1fr));
  gap:14px;
  margin-top:22px;
}
.day-card {
  display:flex; flex-direction:column; gap:6px;
  background:#fff;
  border:1px solid #cfe3d3;
  border-radius:12px;
  padding:16px 18px;
  text-decoration:none;
  color:inherit;
  transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}
.day-card:hover {
  transform:translateY(-2px);
  box-shadow:0 8px 20px rgba(31,122,58,.12);
  border-color:#8ecfaa;
}
.day-card.latest {
  border-color:#e57373;
  background:linear-gradient(180deg,#fff5f5,#ffffff);
  box-shadow:0 6px 18px rgba(229,115,115,.18);
}
.day-date { font-size:18px; font-weight:650; color:#1f5f32; }
.day-card.latest .day-date { color:#c62828; }
.day-hint { font-size:13px; color:#5d7262; }
.foot { text-align:center; color:#5d7262; font-size:13px; margin-top:28px; }
.empty { color:#5d7262; padding:12px 4px; }
""".strip()
