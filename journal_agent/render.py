"""Daily HTML page and the archive index."""

from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from journal_agent.common import OUTPUT_DIR, Article

logger = logging.getLogger("journal_agent")

JOURNAL_ORDER = (
    "Nature",
    "Nature Genetics",
    "Nature Plants",
    "Cell",
    "Science",
)

STYLES = """
body {
  margin:0;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;
  background:linear-gradient(180deg,#e5f6e8 0%,#f0f7f2 240px,#eef5ef 100%);
  color:#1b3a1f;
}
header {
  background:linear-gradient(120deg,#14532d,#1f7a3a);
  color:#fff;
  padding:16px 24px;
  display:flex;
  align-items:flex-start;
  gap:16px;
  box-shadow:0 4px 18px rgba(20,83,45,.25);
}
.back-home {
  flex:none;
  display:inline-flex;
  align-items:center;
  padding:8px 14px;
  margin-top:2px;
  background:rgba(255,255,255,.16);
  border:1px solid rgba(255,255,255,.35);
  border-radius:8px;
  color:#fff;
  text-decoration:none;
  font-size:14px;
  font-weight:550;
  white-space:nowrap;
  transition:background .15s ease;
}
.back-home:hover { background:rgba(255,255,255,.28); color:#fff; }
.header-main { flex:1; min-width:0; }
header h1 { margin:0 0 6px; font-size:22px; letter-spacing:.02em; }
header .stats { margin:0; font-size:13px; opacity:.92; line-height:1.45; }
.hero {
  max-width:1200px;
  margin:16px auto 0;
  padding:0 18px;
}
.hero-inner {
  background:linear-gradient(135deg,rgba(34,197,94,.16),rgba(255,255,255,.85));
  border:1px solid rgba(22,163,74,.2);
  border-radius:16px;
  padding:14px 18px;
  display:flex;
  align-items:center;
  gap:18px;
  box-shadow:0 2px 12px rgba(31,122,58,.08);
}
.hero img {
  display:block;
  width:auto;
  max-width:320px;
  height:auto;
  max-height:140px;
  border-radius:12px;
  object-fit:contain;
  object-position:center;
  flex-shrink:0;
  box-shadow:0 4px 14px rgba(0,0,0,.12);
}
.hero-text-title { font-size:17px; font-weight:650; color:#064e3b; margin-bottom:6px; }
.hero-text-sub { font-size:13px; color:#166534; line-height:1.55; max-width:720px; }
.container {
  display:flex;
  gap:18px;
  padding:18px;
  max-width:1200px;
  margin:0 auto 32px;
  align-items:flex-start;
}
nav.sidebar {
  width:220px;
  flex:none;
  position:sticky;
  top:16px;
  max-height:calc(100vh - 32px);
  overflow-y:auto;
  background:#ecfdf3;
  border:1px solid rgba(22,163,74,.18);
  border-radius:14px;
  padding:12px;
  box-shadow:0 2px 10px rgba(31,122,58,.06);
}
.nav-title { font-size:13px; font-weight:650; color:#065f46; margin-bottom:8px; }
nav.sidebar a {
  display:block;
  margin-bottom:4px;
  padding:7px 10px;
  border-radius:8px;
  color:#065f46;
  text-decoration:none;
  font-size:13px;
}
nav.sidebar a:hover { background:rgba(22,163,74,.12); }
nav.sidebar a.active {
  background:#16a34a;
  color:#ecfdf3;
  font-weight:650;
  box-shadow:0 2px 8px rgba(22,163,74,.25);
}
main { flex:1; min-width:0; }
.search-wrap { margin-bottom:14px; }
input#q {
  width:100%;
  padding:10px 14px;
  border:1px solid #cfe3d3;
  border-radius:999px;
  font-size:14px;
  background:#fff;
  box-sizing:border-box;
}
input#q:focus {
  outline:none;
  border-color:#16a34a;
  box-shadow:0 0 0 3px rgba(22,163,74,.15);
}
.journal {
  background:#fff;
  border-radius:14px;
  padding:18px 20px;
  margin-bottom:18px;
  border:1px solid rgba(22,163,74,.1);
  box-shadow:0 2px 12px rgba(31,122,58,.06);
  scroll-margin-top:18px;
}
.journal h2 {
  margin:0 0 10px;
  font-size:20px;
  color:#064e3b;
  border-bottom:2px solid rgba(22,163,74,.15);
  padding-bottom:8px;
}
.trends {
  background:#f3fbf4;
  border-left:4px solid #16a34a;
  padding:10px 14px;
  white-space:pre-wrap;
  line-height:1.55;
  font-size:13px;
  color:#166534;
  border-radius:0 10px 10px 0;
  margin-bottom:14px;
}
.card.article-panel {
  background:linear-gradient(180deg,#fcfffd,#f7fbf8);
  border:1px solid #dcefe3;
  border-radius:12px;
  padding:14px 16px 16px;
  margin-bottom:12px;
  box-shadow:0 1px 6px rgba(31,122,58,.05);
}
.card-top {
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  margin-bottom:10px;
}
.journal-badge {
  display:inline-block;
  padding:4px 10px;
  border-radius:999px;
  background:#14532d;
  color:#ecfdf3;
  font-size:12px;
  font-weight:650;
  letter-spacing:.02em;
}
.card-date { font-size:12px; color:#5d7262; }
.title { font-weight:650; font-size:17px; line-height:1.4; color:#14291a; margin-bottom:6px; }
.authors {
  font-size:12px;
  color:#4b5563;
  line-height:1.55;
  margin-bottom:8px;
}
.authors-label {
  font-weight:650;
  color:#065f46;
  margin-right:4px;
}
.card { border-top:none; padding:0; }
.meta {
  color:#5d7262;
  font-size:12px;
  margin:8px 0 10px;
  line-height:1.5;
}
.summary {
  white-space:pre-wrap;
  line-height:1.6;
  font-size:14px;
  color:#374151;
  background:#fafdfb;
  border-radius:10px;
  padding:12px 14px;
  border:1px solid #e8f3ea;
}
.link-row { margin-top:12px; }
.link-row a {
  display:inline-block;
  padding:6px 14px;
  border-radius:999px;
  background:#ecfdf3;
  border:1px solid #a7d7b5;
  color:#0b6b32;
  text-decoration:none;
  font-size:13px;
  font-weight:550;
}
.link-row a:hover { background:#d1fae5; }
.footer {
  text-align:center;
  color:#5d7262;
  padding:8px 18px 28px;
  font-size:13px;
}
@media (max-width:900px) {
  .container { flex-direction:column; }
  nav.sidebar { position:static; width:auto; max-height:none; }
  .hero-inner { flex-direction:column; text-align:center; }
  .hero img { max-width:100%; width:auto; height:auto; max-height:200px; object-fit:contain; }
}
""".strip()

SCRIPT = """
<script>
function filterCards() {
  const q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('.card.article-panel').forEach(card => {
    card.style.display = card.innerText.toLowerCase().includes(q) ? '' : 'none';
  });
}
(function initJournalNavSpy() {
  const navLinks = [...document.querySelectorAll('nav.sidebar a.nav-journal')];
  const sections = [...document.querySelectorAll('section.journal')];
  if (!navLinks.length || !sections.length) return;
  function setActive(sectionId) {
    navLinks.forEach(link => {
      link.classList.toggle('active', link.dataset.section === sectionId);
    });
  }
  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter(entry => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
    if (visible.length) {
      setActive(visible[0].target.id);
    }
  }, { root: null, rootMargin: '-25% 0px -60% 0px', threshold: [0, 0.08, 0.2, 0.4] });
  sections.forEach(section => observer.observe(section));
  setActive(sections[0].id);
})();
</script>
""".strip()


def _journal_sort_key(journal: str) -> tuple[int, str]:
    try:
        return (JOURNAL_ORDER.index(journal), journal)
    except ValueError:
        return (len(JOURNAL_ORDER), journal)


def _journal_anchor(journal: str) -> str:
    return journal.replace(" ", "_")


def write_report(articles: list[Article], trends: dict[str, str], stats: dict[str, int]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_tag = datetime.now().strftime("%Y-%m-%d")
    grouped: dict[str, list[Article]] = {}
    for article in articles:
        grouped.setdefault(article.journal, []).append(article)
    order = sorted(grouped.keys(), key=_journal_sort_key)
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
        f"<p class='stats'>日期 {date_tag} · 生成 {generated} · "
        f"新抓取 {stats.get('fetched', 0)} · 缓存跳过 {stats.get('cached', 0)} · "
        f"重复跳过 {stats.get('duplicate', 0)} · 页面 {len(articles)} 篇</p>",
        "</div></header>",
        "<div class='hero'><div class='hero-inner'>",
        "<img src='soybean.jpg' alt='大豆' onerror=\"this.style.display='none'\">",
        "<div>",
        "<div class='hero-text-title'>面向育种与作物改良的每日文献雷达</div>",
        "<div class='hero-text-sub'>Nature / Nature Genetics / Nature Plants / Cell / Science · "
        "近 15 天窗口 · 大模型从作物视角筛选与中文总结</div>",
        "</div></div></div>",
        "<div class='container'>",
        "<nav class='sidebar'>",
        "<div class='nav-title'>期刊导航</div>",
    ]
    for journal in order:
        anchor = html.escape(_journal_anchor(journal))
        parts.append(
            f"<a class='nav-journal' href='#{anchor}' data-section='{anchor}'>"
            f"{html.escape(journal)}（{len(grouped[journal])}）</a>"
        )
    parts.append("</nav><main>")
    parts.append(
        "<div class='search-wrap'><input id='q' placeholder='搜索标题或总结…' oninput='filterCards()'></div>"
    )
    if not articles:
        parts.append("<div class='journal'>本次窗口内没有待展示的文章。</div>")
    for journal in order:
        anchor = html.escape(_journal_anchor(journal))
        parts.append(f"<section class='journal' id='{anchor}'><h2>{html.escape(journal)}</h2>")
        if trends.get(journal):
            parts.append(f"<div class='trends'>{html.escape(trends[journal])}</div>")
        for article in sorted(grouped[journal], key=lambda item: item.pub_date, reverse=True):
            authors = (article.authors or "").strip() or "见原文链接"
            parts.append('<div class="card article-panel">')
            parts.append('<div class="card-top">')
            parts.append(f'<span class="journal-badge">{html.escape(article.journal)}</span>')
            parts.append(f'<span class="card-date">{html.escape(article.pub_date)}</span>')
            parts.append("</div>")
            parts.append(f'<div class="title">{html.escape(article.title)}</div>')
            parts.append(
                f'<div class="authors"><span class="authors-label">作者</span>{html.escape(authors)}</div>'
            )
            meta = article.content_source or article.source
            if article.score:
                meta += f" · 相关度 {article.score:g}"
            if article.reason:
                meta += f" · {article.reason}"
            parts.append(f'<div class="meta">{html.escape(meta)}</div>')
            if article.summary:
                parts.append(f"<div class='summary'>{html.escape(article.summary)}</div>")
            if article.url:
                parts.append(
                    f"<div class='link-row'><a href='{html.escape(article.url)}' "
                    f"target='_blank' rel='noopener'>阅读原文</a></div>"
                )
            parts.append("</div>")
        parts.append("</section>")
    parts.append("</main></div>")
    parts.append("<div class='footer'>本地脚本生成 · 摘要依据抓到的题录与摘要，请以原文为准</div>")
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
