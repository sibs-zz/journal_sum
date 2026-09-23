"""Daily HTML page and the archive index."""

from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path

from journal_agent.common import OUTPUT_DIR, Article

logger = logging.getLogger("journal_agent")

STYLES = """
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif; background:#e5f6e8; color:#1b3a1f; }
header { background:#1f7a3a; color:#fff; padding:20px 28px; }
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
        "<header><h1>期刊自动摘要 · 作物视角</h1>",
        f"<p>日期 {date_tag} · 生成 {generated} · "
        f"新抓取 {stats.get('fetched', 0)} · 缓存跳过 {stats.get('cached', 0)} · "
        f"重复跳过 {stats.get('duplicate', 0)} · 本次保留 {len(articles)}</p></header>",
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
    _write_index(generated)
    logger.info("已写入 %s", path)
    return path


def _write_index(generated: str) -> None:
    pages = sorted(OUTPUT_DIR.glob("index_*.html"), reverse=True)
    items = []
    for page in pages:
        label = page.name.replace("index_", "").replace(".html", "")
        items.append(f"<li><a href='{html.escape(page.name)}'>{html.escape(label)}</a></li>")
    body = "\n".join(items) or "<li>暂无页面</li>"
    html_text = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>期刊摘要索引</title>
<style>{STYLES}</style></head><body>
<header><h1>期刊摘要索引</h1><p>更新于 {html.escape(generated)}</p></header>
<main style="max-width:800px;margin:20px auto;"><ol>{body}</ol></main>
</body></html>"""
    (OUTPUT_DIR / "index.html").write_text(html_text, encoding="utf-8")
